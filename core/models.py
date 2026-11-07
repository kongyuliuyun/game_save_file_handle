"""领域数据模型。

本模块不依赖任何 UI 或网络库，方便单元测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

__all__ = [
    "GameStatus",
    "SaveFile",
    "GameEntry",
    "ScanSummary",
    "TaskReport",
]


class GameStatus(str, Enum):
    """游戏目录在流水线中的状态。"""

    PENDING = "pending"      # 尚未扫描
    READY = "ready"          # 已找到存档，等待备份
    NO_SAVES = "no_saves"    # 未找到存档
    SKIPPED = "skipped"      # 被白名单过滤
    EMPTY = "empty"          # 目录不存在或为空
    ERROR = "error"          # 读取失败

    @property
    def label(self) -> str:
        return {
            GameStatus.PENDING: "待扫描",
            GameStatus.READY: "已就绪",
            GameStatus.NO_SAVES: "无存档",
            GameStatus.SKIPPED: "已跳过",
            GameStatus.EMPTY: "空目录",
            GameStatus.ERROR: "读取失败",
        }[self]


@dataclass(frozen=True, slots=True)
class SaveFile:
    """一个待备份的存档文件。"""

    path: Path
    relative: Path  # 相对游戏目录的路径，用于在备份包内还原目录结构
    size: int

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()


@dataclass(slots=True)
class GameEntry:
    """一个被识别为游戏（或候选游戏）的目录。"""

    path: Path
    name: str
    status: GameStatus = GameStatus.PENDING
    save_files: list[SaveFile] = field(default_factory=list)
    error: str = ""
    selected: bool = True

    @property
    def save_count(self) -> int:
        return len(self.save_files)

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.save_files)

    def mark_error(self, message: str) -> None:
        self.status = GameStatus.ERROR
        self.error = message
        self.save_files.clear()


@dataclass(slots=True)
class ScanSummary:
    """一次扫描的汇总统计。"""

    games: list[GameEntry] = field(default_factory=list)
    total_files: int = 0
    total_bytes: int = 0
    duration: float = 0.0

    @property
    def ready_games(self) -> list[GameEntry]:
        return [g for g in self.games if g.status is GameStatus.READY]

    @property
    def selected_games(self) -> list[GameEntry]:
        return [g for g in self.games if g.selected and g.status is GameStatus.READY]


@dataclass(slots=True)
class TaskReport:
    """一次完整备份任务的执行结果，用于界面收尾展示。"""

    games_total: int = 0
    games_backed_up: int = 0
    files_total: int = 0
    bytes_total: int = 0
    zips: list[Path] = field(default_factory=list)
    uploaded: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def success(self) -> bool:
        return not self.cancelled and not self.errors
