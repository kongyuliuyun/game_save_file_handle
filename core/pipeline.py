"""备份流水线编排：扫描结果 → 复制 → 压缩 → 上传 → 清理。

设计要点
--------
* **临时目录隔离**：旧版会把用户配置的备份目录整个删掉（``shutil.rmtree``），
  一旦用户误填成桌面或游戏目录，存档直接没了。新版每次任务在
  ``<工作目录>/run-<时间戳>/`` 下工作，结束时只删除这个子目录。
* **失败不连锁**：单个游戏复制失败、单个压缩包上传失败都只记录到报告里，
  不影响其余项目。
* **取消可回收**：无论成功、失败还是取消，``finally`` 都会清理临时文件。
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol

from .backup import GameArtifact, copy_saves, remove_tree
from .config import AppConfig, resolve_path
from .errors import AppError, AuthError, TaskCancelled
from .models import GameEntry, TaskReport
from .packager import ZipArtifact, pack_artifacts, verify_zip
from .progress import Stage, TaskContext
from ..utils.fmt import human_size

__all__ = ["BackupPipeline", "PipelineResult"]


class _CloudClient(Protocol):
    def upload(self, local_path: Path, remote_dir: str, ctx: TaskContext, *,
               on_progress=None) -> object: ...


@dataclass(slots=True)
class PipelineResult:
    """流水线的完整输出，界面用它来渲染完成页。"""

    report: TaskReport
    artifacts: list[GameArtifact] = field(default_factory=list)
    zips: list[ZipArtifact] = field(default_factory=list)
    work_dir: Path | None = None
    kept_dir: Path | None = None
    warnings: list[str] = field(default_factory=list)


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


class BackupPipeline:
    """把一次备份任务拆成可观测、可取消的四个阶段。"""

    def __init__(
        self,
        config: AppConfig,
        ctx: TaskContext,
        client: _CloudClient | None = None,
    ) -> None:
        self.config = config
        self.ctx = ctx
        self.client = client
        self.result = PipelineResult(report=TaskReport())

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def run(self, selected: Iterable[GameEntry]) -> PipelineResult:
        games = [g for g in selected if g.selected and g.save_files]
        if not games:
            raise AppError("没有可备份的游戏，请先扫描并勾选")

        report = self.result.report
        report.games_total = len(games)
        report.files_total = sum(g.save_count for g in games)
        report.bytes_total = sum(g.total_bytes for g in games)

        started = time.monotonic()
        work_dir = self._create_work_dir()
        self.result.work_dir = work_dir

        try:
            artifacts = copy_saves(games, work_dir / "saves", self.ctx)
            self.result.artifacts = artifacts
            report.games_backed_up = len(artifacts)
            for artifact in artifacts:
                report.errors.extend(
                    f"{artifact.game.name}: {msg}" for msg in artifact.errors
                )

            zips = pack_artifacts(artifacts, work_dir / "zips", self.ctx)
            self.result.zips = zips
            report.zips = [item.path for item in zips]
            for item in zips:
                report.errors.extend(f"{item.name}: {msg}" for msg in item.errors)

            self._maybe_verify(zips)

            # 先把压缩包落到用户指定的保留目录，再上传：
            # 即使上传失败，本地备份也已经保住。
            if self.config.keep_local_backup:
                self._keep_local(zips)

            if self.client is not None:
                self._upload(zips, report)

        except TaskCancelled:
            report.cancelled = True
            raise
        finally:
            report.elapsed = time.monotonic() - started
            self._cleanup(work_dir)

        self.ctx.report(
            Stage.DONE,
            1,
            1,
            unit="task",
            message="全部完成",
            detail=(
                f"{report.games_backed_up} 个游戏 · {human_size(report.bytes_total)}"
                f" · 上传 {len(report.uploaded)} 个压缩包"
            ),
        )
        return self.result

    # ------------------------------------------------------------------
    # 各阶段
    # ------------------------------------------------------------------

    def _create_work_dir(self) -> Path:
        """在工作目录下创建本次任务专属的子目录。"""
        configured = (self.config.backup_root or "").strip()
        if configured:
            base, warning = resolve_path(configured)
            if warning:
                self.result.warnings.append(warning)
        else:
            base = Path(tempfile.gettempdir()) / "GameSaveBackup"

        try:
            base.mkdir(parents=True, exist_ok=True)
            # mkdtemp 保证并发/连续任务不会撞名
            work_dir = Path(tempfile.mkdtemp(prefix=f"run-{_timestamp()}-", dir=str(base)))
        except OSError:
            # 配置的目录不可写时退回系统临时目录，保证任务能继续
            fallback = Path(tempfile.mkdtemp(prefix="GameSaveBackup-"))
            self.result.warnings.append(
                f"工作目录 {base} 不可用，已改用系统临时目录 {fallback}"
            )
            return fallback

        return work_dir

    def _maybe_verify(self, zips: list[ZipArtifact]) -> None:
        if not self.config.verify_upload:
            return
        for item in zips:
            self.ctx.check()
            ok, message = verify_zip(item.path)
            if not ok:
                self.result.report.errors.append(f"{item.name}: 压缩包校验失败 {message}")

    def _upload(self, zips: list[ZipArtifact], report: TaskReport) -> None:
        total = sum(item.size for item in zips)
        if total <= 0:
            raise AppError("压缩包为空，无法上传")

        self.ctx.meter.reset()
        requested = int(getattr(self.config, "upload_threads", 1) or 1)
        threads = max(1, min(requested, len(zips)))
        if threads <= 1:
            self._upload_serial(zips, report, total)
        else:
            self._upload_parallel(zips, report, total, threads)

    def _upload_serial(
        self, zips: list[ZipArtifact], report: TaskReport, total: int
    ) -> None:
        uploaded_bytes = 0
        for index, item in enumerate(zips, start=1):
            self.ctx.check()
            base = uploaded_bytes

            def _on_progress(sent: int, *, _base=base, _item=item, _index=index) -> None:
                overall = _base + sent
                speed = self.ctx.meter.update(overall)
                detail = (
                    f"{_item.name} · {_index}/{len(zips)} · "
                    f"{human_size(sent)}/{human_size(_item.size)}"
                )
                if speed > 0:
                    detail += f" · {human_size(speed)}/s"
                self.ctx.report(
                    Stage.UPLOAD,
                    overall,
                    total,
                    unit="bytes",
                    message=f"正在上传（{_index}/{len(zips)}）",
                    detail=detail,
                )

            self.ctx.activity(Stage.UPLOAD, f"准备上传：{item.name}", "")
            try:
                assert self.client is not None
                self.client.upload(item.path, self.config.remote_dir, self.ctx,
                                   on_progress=_on_progress)
                report.uploaded.append(f"{self.config.remote_dir.rstrip('/')}/{item.name}")
            except TaskCancelled:
                raise
            except AuthError:
                # 授权问题后续文件必然也失败，直接中止
                raise
            except AppError as exc:
                report.errors.append(f"{item.name}: {exc.message}")

            uploaded_bytes += item.size
            self.ctx.report(
                Stage.UPLOAD,
                uploaded_bytes,
                total,
                unit="bytes",
                message=f"已上传 {index}/{len(zips)}",
                detail=item.name,
            )

    def _upload_parallel(
        self,
        zips: list[ZipArtifact],
        report: TaskReport,
        total: int,
        threads: int,
    ) -> None:
        """并发上传多个压缩包。

        每个工作线程通过 ``client.clone()`` 使用独立的 HTTP 会话；
        进度按所有文件已发送字节之和汇总，因此仍然单调且最终等于总大小。
        任一文件授权失败时通知其余线程尽快停止，避免继续做无效上传。
        """
        client = self.client
        if client is None:
            raise AppError("上传客户端未初始化")

        lock = threading.Lock()
        sent = [0] * len(zips)
        abort = threading.Event()
        auth_errors: list[AuthError] = []
        cancelled = False

        def worker(index: int, item: ZipArtifact) -> None:
            nonlocal cancelled
            cloned = getattr(client, "clone", None)
            local_client = cloned() if callable(cloned) else client

            def on_progress(value: int, _index=index, _item=item) -> None:
                if abort.is_set():
                    raise TaskCancelled()
                # 计算与上报放在同一把锁内，保证事件顺序与进度值顺序一致
                with lock:
                    sent[_index] = min(value, _item.size)
                    overall = sum(sent)
                    speed = self.ctx.meter.update(overall)
                    detail = (
                        f"{_item.name} · {_index + 1}/{len(zips)} · "
                        f"{human_size(value)}/{human_size(_item.size)}"
                    )
                    if speed > 0:
                        detail += f" · {human_size(speed)}/s"
                    self.ctx.report(
                        Stage.UPLOAD,
                        overall,
                        total,
                        unit="bytes",
                        message=f"正在上传（{threads} 并发）",
                        detail=detail,
                    )

            self.ctx.activity(Stage.UPLOAD, f"准备上传：{item.name}", "")
            try:
                local_client.upload(
                    item.path, self.config.remote_dir, self.ctx, on_progress=on_progress
                )
                with lock:
                    sent[index] = item.size
                    report.uploaded.append(
                        f"{self.config.remote_dir.rstrip('/')}/{item.name}"
                    )
            except TaskCancelled:
                # 由授权失败触发的停止不算用户取消
                if not abort.is_set():
                    cancelled = True
                raise
            except AuthError as exc:
                abort.set()
                with lock:
                    auth_errors.append(exc)
                raise
            except AppError as exc:
                with lock:
                    report.errors.append(f"{item.name}: {exc.message}")
            finally:
                if local_client is not client:
                    local_client.close()

        with ThreadPoolExecutor(max_workers=threads, thread_name_prefix="upload") as pool:
            futures = [
                pool.submit(worker, index, item) for index, item in enumerate(zips)
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except (TaskCancelled, AuthError):
                    pass
                except Exception as exc:  # 兜底，避免单个线程异常吞掉整个任务
                    with lock:
                        report.errors.append(f"上传异常: {exc}")

        if auth_errors:
            raise auth_errors[0]
        if cancelled or self.ctx.cancelled:
            raise TaskCancelled()

        self.ctx.report(
            Stage.UPLOAD,
            total,
            total,
            unit="bytes",
            message=f"已上传 {len(report.uploaded)}/{len(zips)} 个压缩包",
            detail="",
        )

    def _keep_local(self, zips: list[ZipArtifact]) -> None:
        target, warning = resolve_path(self.config.zip_root)
        if warning:
            self.result.warnings.append(warning)
        try:
            target.mkdir(parents=True, exist_ok=True)
            for item in zips:
                shutil.copy2(item.path, target / item.name)
            self.result.kept_dir = target
        except OSError as exc:
            self.result.warnings.append(f"本地备份保存失败: {exc}")

    def _cleanup(self, work_dir: Path) -> None:
        """只删除本次任务的子目录，绝不动用户配置的父目录。"""
        try:
            self.ctx.activity(Stage.CLEANUP, "正在清理临时文件…", "")
            removed = remove_tree(work_dir)
            self.ctx.report(
                Stage.CLEANUP,
                1,
                1,
                unit="files",
                message="临时文件已清理",
                detail=f"删除 {removed} 个文件",
            )
        except TaskCancelled:
            # 清理阶段即使已取消也必须执行完，因此这里吞掉取消信号
            pass
        except OSError:
            pass
