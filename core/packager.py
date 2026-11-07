"""ZIP 打包。

旧版 ``dir_packager`` 只在**每个文件写完**时更新一次进度，而进度条的分母
是「总文件数」，遇到几个超大文件时进度条会长时间不动，看起来像卡死；
另外打包失败没有任何错误处理。

新版按**已压缩的原始字节数**推进，分母来自扫描结果，进度线性可信；
并用 ``ZipInfo`` 手动分块写入，使大文件也能持续上报。
"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .backup import GameArtifact, safe_filename
from .errors import PackError, TaskCancelled
from .progress import Stage, TaskContext

__all__ = ["ZipArtifact", "pack_artifacts"]

_WRITE_CHUNK = 1024 * 1024


@dataclass(slots=True)
class ZipArtifact:
    """一个打包完成的压缩包。"""

    name: str
    path: Path
    size: int
    files: int = 0
    errors: list[str] = field(default_factory=list)


def _iter_sources(directory: Path):
    """产出 ``(源文件, 归档内相对路径)``。"""
    for root, _dirs, files in os.walk(directory):
        for name in files:
            source = Path(root) / name
            relative = source.relative_to(directory)
            arcname = relative.as_posix()
            yield source, arcname


def _pack_one(
    artifact: GameArtifact,
    zip_dir: Path,
    base_done: int,
    total: int,
    ctx: TaskContext,
) -> ZipArtifact:
    zip_name = f"{safe_filename(artifact.game.name)}.zip"
    zip_path = zip_dir / zip_name
    written_total = base_done
    packed_files = 0

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for source, arcname in _iter_sources(artifact.directory):
                ctx.check()
                try:
                    info = zipfile.ZipInfo.from_file(source, arcname)
                except OSError as exc:
                    artifact.errors.append(f"{source.name}: {exc}")
                    continue
                info.compress_type = zipfile.ZIP_DEFLATED
                # 以 DEFLATE 流写入，逐块累计已读字节作为进度
                try:
                    with archive.open(info, "w") as target, open(source, "rb") as stream:
                        while True:
                            ctx.check()
                            chunk = stream.read(_WRITE_CHUNK)
                            if not chunk:
                                break
                            target.write(chunk)
                            written_total += len(chunk)
                            ctx.report(
                                Stage.PACK,
                                written_total,
                                total,
                                unit="bytes",
                                message=f"正在压缩：{artifact.game.name}",
                                detail=f"{packed_files + 1} 个文件 · {arcname}",
                            )
                    packed_files += 1
                except TaskCancelled:
                    raise
                except OSError as exc:
                    artifact.errors.append(f"{arcname}: {exc}")
                    continue
    except TaskCancelled:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    if packed_files == 0:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise PackError(f"{artifact.game.name} 没有可压缩的文件")

    return ZipArtifact(
        name=zip_name,
        path=zip_path,
        size=zip_path.stat().st_size if zip_path.exists() else 0,
        files=packed_files,
        errors=list(artifact.errors),
    )


def pack_artifacts(
    artifacts: Iterable[GameArtifact],
    zip_dir: Path,
    ctx: TaskContext,
) -> list[ZipArtifact]:
    """把每个游戏目录压成一个 ZIP。

    进度分母是**所有待压缩文件的原始字节数**，与实际读取量一致。
    """
    items = [item for item in artifacts if item.files > 0]
    if not items:
        raise PackError("没有可打包的内容")

    total = sum(item.bytes for item in items)
    zip_dir.mkdir(parents=True, exist_ok=True)

    results: list[ZipArtifact] = []
    done = 0
    for index, artifact in enumerate(items, start=1):
        ctx.check()
        ctx.report(
            Stage.PACK,
            done,
            total,
            unit="bytes",
            message=f"压缩 {index}/{len(items)}：{artifact.game.name}",
        )
        try:
            result = _pack_one(artifact, zip_dir, done, total, ctx)
        except PackError as exc:
            artifact.errors.append(exc.message)
            continue
        done += artifact.bytes
        results.append(result)
        ctx.report(
            Stage.PACK,
            done,
            total,
            unit="bytes",
            message=f"已完成 {index}/{len(items)} 个压缩包",
            detail=result.name,
        )

    if not results:
        raise PackError("所有压缩包均创建失败")
    return results


def verify_zip(path: Path) -> tuple[bool, str]:
    """快速校验压缩包完整性，供上传前自检。"""
    try:
        with zipfile.ZipFile(path, "r") as archive:
            bad = archive.testzip()
            if bad is not None:
                return False, f"压缩包内文件损坏: {bad}"
    except (OSError, zipfile.BadZipFile) as exc:
        return False, str(exc)
    return True, ""
