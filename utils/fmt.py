"""数值格式化：体积、速率、时长、路径缩写。"""

from __future__ import annotations

__all__ = ["human_size", "human_speed", "human_duration", "shorten_path"]

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def human_size(num: float | int | None) -> str:
    """把字节数格式化为人类可读字符串，例如 ``1.42 GB``。"""
    if num is None:
        return "—"
    value = float(num)
    if value < 0:
        return "—"
    index = 0
    while value >= 1024 and index < len(_UNITS) - 1:
        value /= 1024.0
        index += 1
    if index == 0:
        return f"{int(value)} B"
    return f"{value:.2f} {_UNITS[index]}"


def human_speed(bytes_per_second: float | None) -> str:
    """格式化传输速率，例如 ``12.3 MB/s``。"""
    if not bytes_per_second or bytes_per_second <= 0:
        return "—"
    return f"{human_size(bytes_per_second)}/s"


def human_duration(seconds: float | None) -> str:
    """格式化剩余时间，例如 ``1 分 23 秒``。"""
    if seconds is None or seconds < 0 or seconds != seconds:  # NaN 检查
        return "—"
    total = int(seconds)
    if total < 1:
        return "不到 1 秒"
    if total < 60:
        return f"{total} 秒"
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} 分 {sec} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 时 {minutes} 分"


def shorten_path(path: str, max_chars: int = 52) -> str:
    """从中间截断过长路径，保留盘符与末尾目录名。"""
    if not path or len(path) <= max_chars:
        return path
    head_len = max(6, max_chars // 3)
    tail_len = max_chars - head_len - 1
    return f"{path[:head_len]}…{path[-tail_len:]}"
