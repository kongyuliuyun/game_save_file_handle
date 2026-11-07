"""应用统一异常体系。

所有可预期错误都应使用本模块的异常类型，便于界面层给出友好提示，
而不是把原始 traceback 直接抛给用户。
"""

from __future__ import annotations

__all__ = [
    "AppError",
    "ConfigError",
    "ScanError",
    "BackupError",
    "PackError",
    "TaskCancelled",
    "AuthError",
    "UploadError",
    "NetworkError",
    "QuotaExceeded",
]


class AppError(Exception):
    """所有业务异常的基类。``message`` 应可直接展示给用户。"""

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover - 简单转发
        return self.message


class ConfigError(AppError):
    """配置文件缺失、格式错误或字段非法。"""


class ScanError(AppError):
    """扫描目录时发生的错误。"""


class BackupError(AppError):
    """复制存档文件时发生的错误。"""


class PackError(AppError):
    """ZIP 打包失败。"""


class TaskCancelled(AppError):
    """用户主动取消了任务。这是控制流信号，不应作为错误提示。"""

    def __init__(self, message: str = "任务已取消") -> None:
        super().__init__(message)


class AuthError(AppError):
    """百度网盘授权缺失、失效或刷新失败。"""


class UploadError(AppError):
    """上传过程中服务端返回的、无法通过重试恢复的错误。"""


class NetworkError(AppError):
    """网络层错误（连接失败、超时、HTTP 5xx），通常可重试。"""


class QuotaExceeded(UploadError):
    """网盘空间不足。"""
