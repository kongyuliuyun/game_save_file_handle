"""把扫描到的存档复制到工作目录。

旧版 ``package_save_files`` 的问题：

* 存档位于游戏根目录时会把多个游戏的文件平铺到同一个目录，互相覆盖；
* 单个文件被占用会让整个任务抛异常并中断；
* 复制过程没有任何进度或取消检查。

新版统一放入 ``<工作目录>/<游戏名>/<相对路径>``，天然隔离，并对每个
文件做失败兜底。
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .errors import BackupError, TaskCancelled
from .models import GameEntry
from .progress import Stage, TaskContext

__all__ = ["GameArtifact", "copy_saves", "safe_filename", "remove_tree"]

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_COPY_CHUNK = 512 * 1024


def safe_filename(name: str, fallback: str = "unnamed") -> str:
    """把任意名称转成 Windows 合法文件名（同时去掉结尾的点和空格）。"""
    cleaned = _INVALID_CHARS.sub("_", name).strip().rstrip(".")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in _RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:120]


@dataclass(slots=True)
class GameArtifact:
    """一个游戏复制完成后的产物。"""

    game: GameEntry
    directory: Path
    files: int = 0
    bytes: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.directory.name


def _unique_dir(parent: Path, name: str, used: set[str]) -> Path:
    """处理不同根目录下同名游戏，避免互相覆盖。"""
    candidate = name
    index = 2
    while candidate.lower() in used:
        candidate = f"{name} ({index})"
        index += 1
    used.add(candidate.lower())
    return parent / candidate


def _safe_relative(relative: Path) -> Path:
    """剔除可能逃逸出目标目录的 ``..`` 片段。"""
    parts = [part for part in relative.parts if part not in ("..", "", ".")]
    return Path(*parts) if parts else Path(relative.name)


def _copy_file(source: Path, destination: Path, ctx: TaskContext, total: int, done: int) -> int:
    """分块复制，返回新增字节数。

    分块而非 ``shutil.copy2`` 是为了在两块之间插入取消检查与进度上报。
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with open(source, "rb") as src, open(destination, "wb") as dst:
            while True:
                ctx.check()
                chunk = src.read(_COPY_CHUNK)
                if not chunk:
                    break
                dst.write(chunk)
                written += len(chunk)
                ctx.report(
                    Stage.COPY,
                    done + written,
                    total,
                    unit="bytes",
                    message="正在复制存档",
                    detail=str(source.name),
                )
    except TaskCancelled:
        # 取消时清掉半截文件，避免污染工作目录
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    try:
        shutil.copystat(source, destination)
    except OSError:
        pass
    return written


def copy_saves(
    games: Iterable[GameEntry],
    destination_root: Path,
    ctx: TaskContext,
) -> list[GameArtifact]:
    """把选中游戏的存档复制到 ``destination_root`` 下，按游戏分目录。"""
    targets = [game for game in games if game.save_files]
    total_bytes = sum(game.total_bytes for game in targets)
    if total_bytes <= 0:
        raise BackupError("没有需要复制的存档文件")

    destination_root.mkdir(parents=True, exist_ok=True)
    artifacts: list[GameArtifact] = []
    used: set[str] = set()
    copied_bytes = 0

    total_games = len(targets)
    for index, game in enumerate(targets, start=1):
        ctx.check()
        folder = _unique_dir(destination_root, safe_filename(game.name), used)
        folder.mkdir(parents=True, exist_ok=True)
        artifact = GameArtifact(game=game, directory=folder)

        for save in game.save_files:
            ctx.check()
            target = folder / _safe_relative(save.relative)
            try:
                written = _copy_file(save.path, target, ctx, total_bytes, copied_bytes)
                copied_bytes += written
                artifact.files += 1
                artifact.bytes += written
            except TaskCancelled:
                raise
            except OSError as exc:
                artifact.errors.append(f"{save.path.name}: {exc}")
                continue

        if artifact.files:
            artifacts.append(artifact)
        else:
            # 一个都没复制成功，删掉空目录避免打包出空 zip
            try:
                folder.rmdir()
            except OSError:
                pass

        ctx.report(
            Stage.COPY,
            copied_bytes,
            total_bytes,
            unit="bytes",
            message=f"已复制 {index}/{total_games} 个游戏",
            detail=f"{game.name}：{artifact.files} 个文件",
        )

    if not artifacts:
        raise BackupError("所有存档文件均复制失败，请检查文件是否被占用")
    return artifacts


def remove_tree(path: Path) -> int:
    """删除目录树，返回删除的文件数。只读属性导致的失败会被忽略。"""
    removed = 0
    if not path.exists():
        return removed
    if path.is_file():
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
        return removed

    for root, _dirs, files in os.walk(path, topdown=False):
        for name in files:
            try:
                (Path(root) / name).unlink()
                removed += 1
            except OSError:
                continue
        try:
            Path(root).rmdir()
        except OSError:
            continue
    return removed
