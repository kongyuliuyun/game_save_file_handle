"""百度云授权页。

流程拆成两步：先在浏览器完成 OAuth 拿到授权码，再粘贴回来换取令牌。
网络请求全部放在后台线程，界面不会假死。
"""

from __future__ import annotations

import webbrowser
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...cloud.auth import TokenStore, build_authorize_url, exchange_code
from ...cloud.baidu_pan import BaiduPanClient
from ...core.errors import AppError
from ...utils.fmt import human_duration
from ..widgets.card import Card, StatusBadge
from ..widgets.icons import icon
from ..widgets.themed import bind_themed_icon
from .common import build_scroll_area

__all__ = ["AuthPage"]


class _ExchangeWorker(QThread):
    """后台用授权码换取令牌。"""

    success = Signal(object)
    failed = Signal(str)

    def __init__(self, code: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._code = code

    def run(self) -> None:
        try:
            token = exchange_code(self._code)
            store = TokenStore()
            store.save(token)
            info: dict = {}
            try:
                with BaiduPanClient(store, timeout=(5.0, 10.0), retries=0) as client:
                    info = client.get_user_info()
            except AppError:
                info = {}
            except Exception:
                info = {}
        except AppError as exc:
            self.failed.emit(exc.message)
        except Exception as exc:
            self.failed.emit(f"授权失败：{exc}")
        else:
            self.success.emit(info)


class _InfoWorker(QThread):
    """后台刷新账号信息。"""

    success = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        try:
            store = TokenStore()
            with BaiduPanClient(store, timeout=(5.0, 10.0), retries=0) as client:
                info = client.get_user_info()
        except AppError as exc:
            self.failed.emit(exc.message)
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.success.emit(info)


class AuthPage(QWidget):
    status_message = Signal(str, str)
    auth_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = TokenStore()
        self._worker: QThread | None = None
        self._info_worker: QThread | None = None
        self._user_info: dict = {}

        self._build_ui()
        self.refresh_status(probe=False)

    # ==================================================================
    # 界面
    # ==================================================================

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll, layout = build_scroll_area()
        outer.addWidget(scroll, 1)

        layout.addWidget(self._build_status_card())
        layout.addWidget(self._build_code_card())
        layout.addWidget(self._build_help_card())
        layout.addStretch(1)

    def _build_status_card(self) -> Card:
        card = Card("百度云授权状态", "首次使用需要登录一次，令牌到期会自动续期", step=1)

        row = QHBoxLayout()
        row.setSpacing(12)

        self.status_badge = StatusBadge("未授权", "neutral")
        row.addWidget(self.status_badge)

        self.account_label = QLabel("尚未登录百度账号")
        self.account_label.setStyleSheet("font-weight: 600;")
        row.addWidget(self.account_label, 1)
        card.body().addLayout(row)

        self.expire_label = QLabel("")
        self.expire_label.setObjectName("Muted")
        card.body().addWidget(self.expire_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(9)

        self.open_button = QPushButton("  打开授权页面")
        self.open_button.setObjectName("Primary")
        self.open_button.setIcon(icon("external", "#FFFFFF", 15))
        self.open_button.setIconSize(QSize(15, 15))
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(self._open_authorize_page)
        buttons.addWidget(self.open_button)

        self.refresh_button = QPushButton("  刷新状态")
        self.refresh_button.setObjectName("Ghost")
        bind_themed_icon(self.refresh_button, "refresh", "text_soft", 15)
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(lambda: self.refresh_status(probe=True))
        buttons.addWidget(self.refresh_button)

        self.logout_button = QPushButton("  退出登录")
        self.logout_button.setObjectName("Danger")
        self.logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_button.clicked.connect(self._logout)
        buttons.addWidget(self.logout_button)

        buttons.addStretch(1)
        card.body().addLayout(buttons)
        return card

    def _build_code_card(self) -> Card:
        card = Card("粘贴授权码", "授权页面登录成功后会得到一串授权码，复制到下面即可", step=2)

        self.link_label = QLabel()
        self.link_label.setObjectName("Muted")
        self.link_label.setWordWrap(True)
        self.link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.link_label.setText("尚未生成授权链接，点击上方「打开授权页面」开始。")
        card.body().addWidget(self.link_label)

        row = QHBoxLayout()
        row.setSpacing(9)

        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("粘贴百度返回的授权码")
        self.code_edit.setClearButtonEnabled(True)
        self.code_edit.setEnabled(False)
        self.code_edit.returnPressed.connect(self._submit_code)
        row.addWidget(self.code_edit, 1)

        self.submit_button = QPushButton("  完成授权")
        self.submit_button.setObjectName("Primary")
        self.submit_button.setIcon(icon("check", "#FFFFFF", 15))
        self.submit_button.setIconSize(QSize(15, 15))
        self.submit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit_button.setEnabled(False)
        self.submit_button.clicked.connect(self._submit_code)
        row.addWidget(self.submit_button)

        card.body().addLayout(row)
        return card

    def _build_help_card(self) -> Card:
        card = Card("授权说明")
        text = QLabel(
            "1. 点击「打开授权页面」，浏览器会跳转到百度登录页；\n"
            "2. 登录并同意授权后，页面会显示一串授权码；\n"
            "3. 把授权码粘贴到上面的输入框，点击「完成授权」；\n"
            "4. 授权成功后即可回到「备份」页上传存档。\n\n"
            "令牌保存在 %USERPROFILE%\\.bypy\\bypy.json，与 bypy 工具通用，"
            "有效期约 30 天，过期会自动刷新，无需重复登录。"
        )
        text.setObjectName("Muted")
        text.setWordWrap(True)
        card.body().addWidget(text)
        return card

    # ==================================================================
    # 授权流程
    # ==================================================================

    def has_token(self) -> bool:
        """是否已保存有效令牌（供主窗口等外部模块查询）。"""
        return self._store.has_token()

    def _open_authorize_page(self) -> None:
        url = build_authorize_url()
        self.link_label.setText(f"如果浏览器没有自动打开，请手动访问：\n{url}")
        self.code_edit.setEnabled(True)
        self.submit_button.setEnabled(True)
        self.code_edit.setFocus()
        try:
            webbrowser.open(url)
        except Exception:
            self.status_message.emit("无法自动打开浏览器，请复制下方链接手动访问", "warning")
        else:
            self.status_message.emit("已在浏览器打开授权页面", "info")

    def _submit_code(self) -> None:
        if isinstance(self._worker, QThread) and self._worker.isRunning():
            return

        code = self.code_edit.text().strip()
        if len(code) < 8:
            self.status_message.emit("请输入有效的授权码", "warning")
            return

        self._set_busy(True, "正在换取授权令牌…")
        worker = _ExchangeWorker(code, self)
        worker.success.connect(self._on_exchange_success)
        worker.failed.connect(self._on_exchange_failed)
        self._worker = worker
        worker.start()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.submit_button.setEnabled(not busy)
        self.open_button.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.code_edit.setEnabled(not busy)
        if busy:
            self.submit_button.setText("  授权中…")
            self.status_badge.set_status(message or "处理中", "primary")
        else:
            self.submit_button.setText("  完成授权")

    def _on_exchange_success(self, info: dict) -> None:
        self._worker = None
        self._set_busy(False)
        self.code_edit.clear()
        self.code_edit.setEnabled(False)
        self.submit_button.setEnabled(False)
        self._user_info = info if isinstance(info, dict) else {}
        self.refresh_status(probe=False)
        self.status_message.emit("授权成功，现在可以上传存档了", "success")
        self.auth_changed.emit(True)

    def _on_exchange_failed(self, message: str) -> None:
        self._worker = None
        self._set_busy(False)
        self.status_badge.set_status("授权失败", "danger")
        self.status_message.emit(message, "error")

    def _logout(self) -> None:
        self._store.clear()
        self._user_info = {}
        self.refresh_status(probe=False)
        self.status_badge.set_status("未授权", "neutral")
        self.status_message.emit("已退出登录，本地令牌已删除", "info")
        self.auth_changed.emit(False)

    # ==================================================================
    # 状态刷新
    # ==================================================================

    def refresh_status(self, probe: bool = True) -> None:
        """读取本地令牌并更新界面；``probe`` 为真时异步拉取账号信息。"""
        state = self._store.describe()

        if not state.get("authorized"):
            self.status_badge.set_status("未授权", "neutral")
            self.account_label.setText("尚未登录百度账号")
            self.expire_label.setText("")
            self.logout_button.setEnabled(self._store.has_token())
            if probe and self._store.has_token():
                self._probe_info()
            return

        self.status_badge.set_status("已授权", "success")
        name = (
            self._user_info.get("netdisk_name")
            or self._user_info.get("baidu_name")
            or "百度账号"
        )
        self.account_label.setText(f"已登录：{name}")

        seconds = state.get("expires_in")
        if seconds:
            self.expire_label.setText(
                f"令牌有效期剩余约 {human_duration(seconds)}（过期后自动续期）"
            )
        else:
            self.expire_label.setText("令牌已保存")
        self.logout_button.setEnabled(True)

        if probe and not self._user_info:
            self._probe_info()

    def _probe_info(self) -> None:
        if isinstance(self._info_worker, QThread) and self._info_worker.isRunning():
            return
        worker = _InfoWorker(self)
        worker.success.connect(self._on_info)
        worker.failed.connect(lambda _msg: None)
        self._info_worker = worker
        worker.start()

    def _on_info(self, info: dict) -> None:
        self._info_worker = None
        if isinstance(info, dict):
            self._user_info = info
        name = (
            self._user_info.get("netdisk_name")
            or self._user_info.get("baidu_name")
            or "百度账号"
        )
        self.account_label.setText(f"已登录：{name}")

    # ==================================================================
    # 生命周期
    # ==================================================================

    def shutdown(self) -> None:
        """等待后台线程结束。

        网络请求本身无法从外部中断，因此先 ``wait`` 一段时间，
        仍未结束则 ``terminate`` 兜底——这比让 QThread 在运行中被析构
        导致进程崩溃要好。
        """
        for worker in (self._worker, self._info_worker):
            if not isinstance(worker, QThread) or not worker.isRunning():
                continue
            worker.requestInterruption()
            if not worker.wait(3000):
                worker.terminate()
                worker.wait(500)
        self._worker = None
        self._info_worker = None
