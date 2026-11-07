"""游戏目录发现与存档文件扫描。

相比旧版 ``game_scanner`` 的改动：

* 用 ``os.scandir`` 单次遍历完成「找文件 + 判扩展名」，比 ``os.walk`` 快，
  且不会像旧版那样在扫描阶段卡住界面。
* 扫描期分母未知，因此上报的是**不确定进度 + 已发现文件数**，
  而不是伪造一个百分比。
* 白名单真正生效：旧版在 GUI 里被 ``{root: ['all']}`` 覆盖成了死代码。
* 单个文件读取失败不会中断整个任务，只有目录级失败才标记为错误。
* 允许存档直接位于游戏根目录（旧版直接跳过，属于功能缺失）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Iterator

from .models import GameEntry, GameStatus, SaveFile, ScanSummary
from .progress import Stage, TaskContext

__all__ = [
    "discover_games",
    "is_game_directory",
    "scan_games",
    "whitelist_allows",
    "walk_files",
]

# 每扫描多少个文件检查一次取消信号、上报一次进度
_SCAN_TICK = 256


def is_game_directory(directory: Path) -> bool:
    """目录的第一层直接包含 ``.exe`` 时视为游戏目录。

    这只是「用户选中游戏本体而非父目录」时的启发式判断，失败也不影响备份，
    因为后续仍会按扩展名扫描存档。
    """
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".exe"):
                        return True
                except OSError:
                    continue
    except OSError:
        return False
    return False


def _safe_stat_size(entry: os.DirEntry[str]) -> int:
    try:
        stat = entry.stat(follow_symlinks=False)
        return int(stat.st_size)
    except OSError:
        return 0


def walk_files(root: Path) -> Iterator[tuple[Path, int]]:
    """深度遍历 ``root``，逐个产出 ``(文件路径, 字节数)``。

    跳过符号链接与重解析点，避免目录环导致死循环；无权访问的子目录
    直接跳过而不是让整个扫描失败。
    """
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            iterator = os.scandir(current)
        except OSError:
            continue
        with iterator:
            for entry in iterator:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        yield Path(entry.path), _safe_stat_size(entry)
                except OSError:
                    continue


def discover_games(root: Path) -> list[GameEntry]:
    """列出候选游戏目录。

    - ``root`` 自身就是游戏目录（第一层含 exe）→ 只返回它自己；
    - 否则返回其所有一级子目录（旧版行为，符合「游戏根目录」的使用习惯）。
    """
    if not root.exists() or not root.is_dir():
        return []

    if is_game_directory(root):
        return [GameEntry(path=root, name=root.name)]

    games: list[GameEntry] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                path = Path(entry.path)
                games.append(GameEntry(path=path, name=entry.name))
    except OSError:
        return []

    games.sort(key=lambda item: item.name.lower())
    return games


def _normalize_for_match(text: str) -> str:
    return os.path.normcase(os.path.normpath(text))


def whitelist_allows(game: GameEntry, whitelist: dict[str, list[str]] | None) -> bool:
    """判断游戏是否被白名单放行。

    规则（从宽松到严格）：

    1. 白名单为空 → 全部放行（默认行为，避免旧版「配置了 default 却全部拦掉」的坑）。
    2. 没有命中任何根目录条目 → 放行。
    3. 命中条目且包含 ``all`` → 放行。
    4. 否则仅当游戏目录名在名单内才放行（大小写不敏感）。
    """
    if not whitelist:
        return True

    root_key = str(game.path.parent)
    names: list[str] | None = None
    for key, value in whitelist.items():
        if _normalize_for_match(key) == _normalize_for_match(root_key):
            names = value
            break
    if names is None:
        names = whitelist.get("default")
    if names is None:
        return True

    lowered = {str(item).strip().lower() for item in names}
    if not lowered or "all" in lowered or "*" in lowered:
        return True
    return game.name.lower() in lowered


def _scan_one(
    game: GameEntry,
    extensions: set[str],
    ctx: TaskContext,
    counters: dict[str, int],
) -> None:
    """扫描单个游戏目录，原地更新 ``game``。"""
    if not game.path.exists():
        game.status = GameStatus.EMPTY
        game.error = "目录不存在"
        return
    if not game.path.is_dir():
        game.status = GameStatus.EMPTY
        game.error = "不是目录"
        return

    found: list[SaveFile] = []
    seen = 0
    try:
        for file_path, size in walk_files(game.path):
            counter = counters["total"] + seen
            seen += 1
            if counter % _SCAN_TICK == 0:
                ctx.check()
                ctx.activity(
                    Stage.SCAN,
                    f"正在扫描：{game.name}",
                    f"已检查 {counters['total'] + seen:,} 个文件，命中 {counters['hits'] + len(found):,} 个存档",
                )
            if file_path.suffix.lower() not in extensions:
                continue
            try:
                relative = file_path.relative_to(game.path)
            except ValueError:
                relative = Path(file_path.name)
            found.append(SaveFile(path=file_path, relative=relative, size=size))
    except PermissionError as exc:
        game.mark_error(f"无权访问: {exc}")
        counters["total"] += seen
        return
    except OSError as exc:
        game.mark_error(f"读取失败: {exc}")
        counters["total"] += seen
        return

    counters["total"] += seen
    counters["hits"] += len(found)

    game.save_files = sorted(found, key=lambda item: str(item.relative).lower())
    if game.save_files:
        game.status = GameStatus.READY
        game.error = ""
    else:
        game.status = GameStatus.NO_SAVES
        game.error = "未找到匹配扩展名的存档文件"


def scan_games(
    games: Iterable[GameEntry],
    extensions: set[str],
    ctx: TaskContext,
    whitelist: dict[str, list[str]] | None = None,
) -> ScanSummary:
    """扫描一组游戏目录并汇总结果。

    进度语义：``done`` 是**已完成扫描的游戏目录数**，``total`` 是待扫描目录数，
    因此百分比始终真实；当前目录内部的细节通过 ``detail`` 以文件计数呈现。
    """
    targets = list(games)
    total = len(targets)
    summary = ScanSummary(games=targets)
    counters = {"total": 0, "hits": 0}
    normalized = {ext.lower() if ext.startswith(".") else "." + ext.lower()
                  for ext in extensions}

    ctx.report(
        Stage.SCAN,
        0,
        total,
        unit="games",
        message=f"开始扫描 {total} 个游戏目录",
    )

    for index, game in enumerate(targets, start=1):
        ctx.check()

        if game.status is GameStatus.SKIPPED:
            ctx.report(Stage.SCAN, index, total, unit="games", message=f"跳过：{game.name}")
            continue

        if not whitelist_allows(game, whitelist):
            game.status = GameStatus.SKIPPED
            game.error = "白名单未通过"
            ctx.report(Stage.SCAN, index, total, unit="games", message=f"白名单跳过：{game.name}")
            continue

        ctx.activity(Stage.SCAN, f"正在扫描：{game.name}", "")
        _scan_one(game, normalized, ctx, counters)

        ctx.report(
            Stage.SCAN,
            index,
            total,
            unit="games",
            message=f"扫描：{game.name}",
            detail=f"找到 {game.save_count} 个存档"
            if game.save_count
            else (game.error or "无存档"),
        )

    summary.total_files = sum(game.save_count for game in targets)
    summary.total_bytes = sum(game.total_bytes for game in targets)
    return summary


def total_selected_bytes(games: Iterable[GameEntry]) -> tuple[int, int]:
    """返回 ``(文件数, 字节数)``，用于后续阶段的精确分母。"""
    files = 0
    size = 0
    for game in games:
        files += game.save_count
        size += game.total_bytes
    return files, size
