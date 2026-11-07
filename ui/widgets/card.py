"""卡片容器与状态徽章。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...app.bootstrap import ThemeManager

__all__ = ["Card", "StatusBadge", "Divider", "set_pixmap_icon"]


class Card(QFrame):
    """白底圆角卡片，带「步骤序号 + 标题 + 说明」的头部。"""

    def __init__(
        self,
        title: str = "",
        hint: str = "",
        step: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 15, 18, 16)
        root.setSpacing(13)

        self._header = QHBoxLayout()
        self._header.setSpacing(10)
        self._header.setContentsMargins(0, 0, 0, 0)

        self._step_badge: QLabel | None = None
        if step is not None:
            self._step_badge = QLabel(str(step))
            self._step_badge.setObjectName("StepBadge")
            self._step_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._step_badge.setFixedHeight(22)
            self._step_badge.setMinimumWidth(22)
            self._header.addWidget(self._step_badge)

        self._title = QLabel(title)
        self._title.setObjectName("CardTitle")
        self._header.addWidget(self._title)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("CardHint")
            self._header.addWidget(hint_label)

        self._header.addStretch(1)

        if title or step is not None or hint:
            root.addLayout(self._header)

        self._body = QVBoxLayout()
        self._body.setSpacing(10)
        self._body.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self._body, 1)

    # ------------------------------------------------------------------

    def body(self) -> QVBoxLayout:
        return self._body

    def header(self) -> QHBoxLayout:
        return self._header

    def add_header_widget(self, widget: QWidget) -> None:
        """把控件放在标题右侧（例如统计信息、工具按钮）。"""
        self._header.addWidget(widget)

    def set_title(self, text: str) -> None:
        self._title.setText(text)


class StatusBadge(QLabel):
    """圆角状态标签：已就绪 / 无存档 / 已跳过 ……"""

    KINDS = {
        "neutral": ("muted", "surface_alt"),
        "primary": ("primary", "primary_soft"),
        "success": ("success", "success_soft"),
        "warning": ("warning", "warning_soft"),
        "danger": ("danger", "danger_soft"),
    }

    def __init__(self, text: str = "", kind: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._kind = kind
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(22)
        ThemeManager.instance().changed.connect(self._apply_style)
        self._apply_style()

    def set_status(self, text: str, kind: str = "neutral") -> None:
        self._kind = kind
        self.setText(text)
        self._apply_style()

    def _apply_style(self) -> None:
        palette = ThemeManager.instance().palette
        fg_key, bg_key = self.KINDS.get(self._kind, self.KINDS["neutral"])
        fg = getattr(palette, fg_key)
        bg = getattr(palette, bg_key)
        self.setStyleSheet(
            f"color: {fg}; background: {bg}; border-radius: 11px;"
            f" padding: 0 10px; font-size: 12px; font-weight: 600;"
        )


class Divider(QFrame):
    """1px 分隔线。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def set_pixmap_icon(widget, name: str, color: str, size: int = 18) -> None:
    """给 QLabel / QPushButton 设置 SVG 图标。"""
    from PySide6.QtGui import QIcon

    from .icons import pixmap

    image = pixmap(name, color, size)
    if image.isNull():
        return
    if isinstance(widget, QLabel):
        widget.setPixmap(image)
    else:
        widget.setIcon(QIcon(image))
