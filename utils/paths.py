"""路径解析工具：统一处理开发环境与 PyInstaller 打包环境的差异。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "is_frozen",
    "app_root",
    "resource_path",
    "config_path",
    "work_dir",
    "token_file",
]


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包出的可执行文件中。"""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """应用根目录。

    - 打包后：exe 所在目录（用户可在此放置 config.yaml）
    - 开发时：项目根目录（game_save_file_handle/）
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """只读资源路径（图标、内置默认配置）。

    打包后资源被解压到 sys._MEIPASS，因此不能和 :func:`app_root` 混用。
    """
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", app_root()))
    else:
        base = app_root()
    return base.joinpath(*parts)


def config_path() -> Path:
    """配置文件路径。

    优先使用 exe/项目根目录下的 ``config.yaml``（用户可直接编辑），
    其次退回打包内置的 ``config/config.yaml``。
    """
    external = app_root() / "config.yaml"
    if external.is_file():
        return external
    bundled = resource_path("config", "config.yaml")
    if bundled.is_file():
        return bundled
    return external


def work_dir() -> Path:
    """默认工作目录（备份产出、日志）。"""
    return app_root()


def token_file() -> Path:
    """百度网盘授权令牌缓存位置，与 bypy 保持同一路径以便互换。"""
    return Path(os.path.expanduser("~")) / ".bypy" / "bypy.json"
