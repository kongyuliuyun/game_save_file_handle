"""应用启动装配：QApplication、主题管理、字体与图标。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication

from ..utils.paths import resource_path
from .theme import DARK, LIGHT, Palette, build_qss

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "ThemeManager",
    "apply_theme",
    "create_application",
    "app_icon",
    "run",
]

APP_NAME = "游戏存档备份工具"
APP_VERSION = "2.0.1"


class ThemeManager(QObject):
    """全局主题状态。自定义绘制的控件监听 ``changed`` 后重绘。"""

    changed = Signal(object)

    _instance: "ThemeManager | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._palette: Palette = LIGHT

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def palette(self) -> Palette:
        return self._palette

    @property
    def is_dark(self) -> bool:
        return self._palette.name == "dark"

    def set_theme(self, name: str) -> None:
        palette = DARK if name == "dark" else LIGHT
        if palette.name == self._palette.name:
            return
        self._palette = palette
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(build_qss(palette))
        self.changed.emit(palette)

    def toggle(self) -> str:
        target = "light" if self.is_dark else "dark"
        self.set_theme(target)
        return target


def app_icon() -> QIcon:
    """加载窗口/任务栏图标，缺失时返回空图标而不是报错。"""
    for candidate in (resource_path("img", "icon.ico"), resource_path("img", "icon.png")):
        if Path(candidate).is_file():
            icon = QIcon(str(candidate))
            if not icon.isNull():
                return icon
    return QIcon()


def _configure_font(app: QApplication) -> None:
    font = QFont("Microsoft YaHei UI", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)


def create_application(argv: list[str] | None = None) -> QApplication:
    """创建并配置 QApplication（高 DPI、字体、主题）。"""
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("GameSaveBackup")
    app.setStyle("Fusion")
    _configure_font(app)
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    app.setStyleSheet(build_qss(ThemeManager.instance().palette))
    return app


def apply_theme(app: QApplication, name: str) -> None:
    ThemeManager.instance().set_theme(name)


def run() -> int:
    """程序入口。"""
    app = create_application()

    # 延迟导入，避免在只做静态检查时拉起整个界面依赖
    from ..ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()
