"""左侧导航栏。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...app.bootstrap import APP_NAME, APP_VERSION, ThemeManager
from .icons import icon

__all__ = ["Sidebar", "NavButton"]


class NavButton(QPushButton):
    """带图标的导航按钮，选中时换主色。"""

    def __init__(self, text: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._icon_name = icon_name
        self.setObjectName("Nav")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(42)
        self.setIconSize(QSize(18, 18))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        ThemeManager.instance().changed.connect(self._refresh_icon)
        self.toggled.connect(self._refresh_icon)
        self._refresh_icon()

    def _refresh_icon(self, *_args) -> None:
        palette = ThemeManager.instance().palette
        color = palette.sidebar_text_active if self.isChecked() else palette.sidebar_text
        self.setIcon(icon(self._icon_name, color, 18))


class Sidebar(QWidget):
    """导航容器：品牌区 + 按钮组 + 底部版本号。"""

    current_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(208)
        self._logo: QLabel | None = None

        ThemeManager.instance().changed.connect(self._refresh_brand)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(6)

        layout.addLayout(self._build_brand())
        layout.addSpacing(14)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[NavButton] = []

        self._group.idClicked.connect(self.current_changed.emit)

        layout.addStretch(1)
        layout.addWidget(self._build_footer())

    def _build_brand(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(6, 0, 0, 0)
        row.setSpacing(10)

        self._logo = QLabel()
        self._logo.setFixedSize(34, 34)
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh_brand()
        row.addWidget(self._logo)

        texts = QVBoxLayout()
        texts.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        subtitle = QLabel("安全地把存档送上云")
        subtitle.setObjectName("AppSubtitle")
        texts.addWidget(title)
        texts.addWidget(subtitle)
        row.addLayout(texts)
        row.addStretch(1)
        return row

    def _refresh_brand(self, *_args) -> None:
        """主题切换后重绘 logo 的背景色与图标颜色。"""
        if self._logo is None:
            return
        palette = ThemeManager.instance().palette
        self._logo.setPixmap(icon("shield", palette.primary, 26).pixmap(26, 26))
        self._logo.setStyleSheet(
            f"background: {palette.primary_soft}; border-radius: 10px;"
        )

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        row = QVBoxLayout(footer)
        row.setContentsMargins(8, 0, 0, 0)
        row.setSpacing(2)
        label = QLabel(f"版本 {APP_VERSION}")
        label.setObjectName("VersionLabel")
        row.addWidget(label)
        return footer

    def add_page(self, text: str, icon_name: str) -> int:
        button = NavButton(text, icon_name, self)
        index = len(self._buttons)
        self._group.addButton(button, index)
        self._buttons.append(button)
        # 插在 stretch 之前
        layout = self.layout()
        assert layout is not None
        layout.insertWidget(layout.count() - 2, button)
        return index

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)
