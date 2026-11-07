"""主窗口：侧边导航 + 顶栏 + 页面堆栈。"""

from __future__ import annotations

from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..app.bootstrap import APP_NAME, APP_VERSION, ThemeManager
from ..core.config import AppConfig, load_config
from ..core.errors import AppError
from .pages.auth_page import AuthPage
from .pages.backup_page import BackupPage
from .pages.settings_page import SettingsPage
from .widgets.icons import icon
from .widgets.nav import Sidebar
from .widgets.toast import Toast

__all__ = ["MainWindow"]

_PAGE_META = (
    (0, "备份游戏存档", "扫描存档、压缩打包并上传到百度网盘"),
    (1, "百度云授权", "管理百度账号的登录状态"),
    (2, "设置", "扩展名、默认路径与外观"),
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        try:
            self.config: AppConfig = load_config()
        except AppError:
            self.config = AppConfig().normalized()

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icon("shield", ThemeManager.instance().palette.primary, 32))
        self.resize(1160, 780)
        self.setMinimumSize(980, 660)

        self._settings = QSettings("GameSaveBackup", "GameSaveBackup")
        self._authorized = False
        self._build_ui()
        self._connect()
        self._apply_theme(self.config.theme, persist=False)
        self._restore_geometry()

    # ==================================================================
    # 构建
    # ==================================================================

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        layout.addWidget(self.sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        layout.addLayout(right, 1)

        self.setCentralWidget(root)

        # 页面
        self.backup_page = BackupPage(self.config)
        self.auth_page = AuthPage()
        self.settings_page = SettingsPage(self.config)
        for page in (self.backup_page, self.auth_page, self.settings_page):
            self.stack.addWidget(page)

        for title, icon_name in (
            ("备份", "upload"),
            ("授权", "key"),
            ("设置", "settings"),
        ):
            self.sidebar.add_page(title, icon_name)
        self.sidebar.set_current(0)

        self.toast = Toast(root)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(72)

        row = QHBoxLayout(bar)
        row.setContentsMargins(24, 0, 22, 0)
        row.setSpacing(12)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.page_title = QLabel(_PAGE_META[0][1])
        self.page_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        texts.addWidget(self.page_title)
        self.page_subtitle = QLabel(_PAGE_META[0][2])
        self.page_subtitle.setObjectName("Muted")
        texts.addWidget(self.page_subtitle)
        row.addLayout(texts)
        row.addStretch(1)

        self.auth_chip = QLabel("未授权")
        self.auth_chip.setObjectName("Muted")
        row.addWidget(self.auth_chip)

        self.theme_button = QPushButton()
        self.theme_button.setObjectName("IconButton")
        self.theme_button.setToolTip("切换深浅色主题")
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.setFixedSize(38, 38)
        self.theme_button.setIconSize(QSize(18, 18))
        self.theme_button.clicked.connect(self._toggle_theme)
        row.addWidget(self.theme_button)

        return bar

    # ==================================================================
    # 信号
    # ==================================================================

    def _connect(self) -> None:
        self.sidebar.current_changed.connect(self._switch_page)

        self.backup_page.status_message.connect(self._show_toast)
        self.backup_page.auth_requested.connect(lambda: self._switch_page(1))

        self.auth_page.status_message.connect(self._show_toast)
        self.auth_page.auth_changed.connect(self._on_auth_changed)

        self.settings_page.status_message.connect(self._show_toast)
        self.settings_page.saved.connect(self._on_settings_saved)

        ThemeManager.instance().changed.connect(self._on_theme_applied)

    # ==================================================================
    # 页面切换
    # ==================================================================

    def _switch_page(self, index: int) -> None:
        if not (0 <= index < self.stack.count()):
            return
        self.stack.setCurrentIndex(index)
        for position, title, subtitle in _PAGE_META:
            if position == index:
                self.page_title.setText(title)
                self.page_subtitle.setText(subtitle)
                break
        if index == 1:
            self.auth_page.refresh_status(probe=True)

    # ==================================================================
    # 主题
    # ==================================================================

    def _apply_theme(self, name: str, *, persist: bool) -> None:
        ThemeManager.instance().set_theme(name)
        if persist:
            self.config.theme = ThemeManager.instance().palette.name
            try:
                self.config.save()
            except AppError:
                pass
        self._refresh_theme_button()

    def _toggle_theme(self) -> None:
        target = ThemeManager.instance().toggle()
        self._apply_theme(target, persist=True)
        self._show_toast(f"已切换到{'深色' if target == 'dark' else '浅色'}主题", "info", 1500)

    def _on_theme_applied(self, _palette) -> None:
        self._refresh_theme_button()
        # 顶部授权状态是内联样式，需要跟随主题重绘
        self._update_auth_chip(self._authorized)

    def _refresh_theme_button(self) -> None:
        palette = ThemeManager.instance().palette
        name = "sun" if palette.name == "dark" else "moon"
        self.theme_button.setIcon(icon(name, palette.text_soft, 18))

    # ==================================================================
    # 其他回调
    # ==================================================================

    def _show_toast(self, text: str, kind: str = "info", duration: int = 2600) -> None:
        self.toast.show_message(text, kind, duration)

    def _on_auth_changed(self, authorized: bool) -> None:
        self._update_auth_chip(authorized)

    def _update_auth_chip(self, authorized: bool) -> None:
        self._authorized = authorized
        palette = ThemeManager.instance().palette
        if authorized:
            self.auth_chip.setText("● 已连接百度云")
            self.auth_chip.setStyleSheet(f"color: {palette.success}; font-size: 12px;")
        else:
            self.auth_chip.setText("● 未授权")
            self.auth_chip.setStyleSheet(f"color: {palette.muted}; font-size: 12px;")

    def _on_settings_saved(self, config: AppConfig) -> None:
        self.config = config
        self.backup_page.config = config
        self.backup_page.refresh_from_config()
        self._apply_theme(config.theme, persist=False)

    # ==================================================================
    # 窗口生命周期
    # ==================================================================

    def _restore_geometry(self) -> None:
        geometry = self._settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt 命名
        if self.backup_page.is_busy():
            reply = QMessageBox.question(
                self,
                "任务进行中",
                "当前还有任务在执行，确定要退出吗？\n未完成的临时文件会被清理。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.backup_page.stop_all()

        self.auth_page.shutdown()
        self._settings.setValue("geometry", self.saveGeometry())
        try:
            self.backup_page.apply_to_config()
            self.config.save()
        except AppError:
            pass
        event.accept()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        self._update_auth_chip(self.auth_page.has_token())
