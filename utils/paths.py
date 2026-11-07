"""路径解析工具：统一处理开发环境与 PyInstaller 打包环境的差异。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "is_frozen",
    "app_root",
    "resource_path",
    "user_config_path",
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


def user_config_path() -> Path:
    """用户级配置文件路径（exe 目录不可写时的回退位置）。

    - Windows：``%APPDATA%/GameSaveBackup/config.yaml``
    - 其他平台：``$XDG_CONFIG_HOME/GameSaveBackup/config.yaml``
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or os.path.expanduser("~"))
    else:
        base = Path(
            os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
        )
    return base / "GameSaveBackup" / "config.yaml"


def config_path() -> Path:
    """配置文件的读写路径。

    查找顺序：

    1. exe / 项目根目录下的 ``config.yaml``（便携模式，用户可直接编辑）；
    2. 开发环境：项目内的 ``config/config.yaml``（可读写）；
    3. 用户配置目录中的 ``config.yaml``（打包后 exe 目录不可写时的回退）；
    4. 都不存在时返回 exe 旁的 ``config.yaml``，作为首次保存位置。

    **绝不能**把用户配置写进 PyInstaller 的 ``sys._MEIPASS`` 临时目录：
    那里每次启动都会重新解压，退出后即丢弃，设置会「看似保存、重启丢失」。
    """
    external = app_root() / "config.yaml"
    if external.is_file():
        return external

    if not is_frozen():
        bundled = app_root() / "config" / "config.yaml"
        if bundled.is_file():
            return bundled

    user = user_config_path()
    if user.is_file():
        return user
    return external


def work_dir() -> Path:
    """默认工作目录（备份产出、日志）。"""
    return app_root()


def token_file() -> Path:
    """百度网盘授权令牌缓存位置，与 bypy 保持同一路径以便互换。"""
    return Path(os.path.expanduser("~")) / ".bypy" / "bypy.json"
