"""轻量浮层提示（Toast）。"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from .icons import icon
from ...app.bootstrap import ThemeManager

__all__ = ["Toast"]

_KIND_STYLE = {
    "info": ("primary", "primary_soft", "cloud"),
    "success": ("success", "success_soft", "check"),
    "warning": ("warning", "warning_soft", "alert"),
    "error": ("danger", "danger_soft", "alert"),
}


class Toast(QFrame):
    """在父窗口顶部居中弹出的短提示，2.5 秒后自动淡出。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 16, 10)
        layout.setSpacing(9)

        self._icon = QLabel()
        self._icon.setFixedSize(18, 18)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)

        self._text = QLabel()
        self._text.setWordWrap(False)
        layout.addWidget(self._text)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)

    # ------------------------------------------------------------------

    def show_message(self, text: str, kind: str = "info", duration: int = 2600) -> None:
        palette = ThemeManager.instance().palette
        fg_key, bg_key, icon_name = _KIND_STYLE.get(kind, _KIND_STYLE["info"])
        fg = getattr(palette, fg_key)
        bg = getattr(palette, bg_key)

        self._icon.setPixmap(icon(icon_name, fg, 16).pixmap(16, 16))
        self._text.setText(text)
        self._text.setStyleSheet(f"color: {fg}; font-weight: 600; font-size: 13px;")
        self.setStyleSheet(
            f"Toast {{ background: {bg}; border: 1px solid {fg}; border-radius: 10px; }}"
        )

        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()

        self._animation.stop()
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(1.0)
        self._animation.start()
        self._timer.start(duration)

    def _fade_out(self) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(0.0)
        self._animation.start()
        QTimer.singleShot(220, self.hide)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        rect = parent.rect()
        x = max(12, (rect.width() - self.width()) // 2)
        self.move(QPoint(x, 20))
