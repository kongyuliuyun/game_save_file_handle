"""页面公共布局工具。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

__all__ = ["build_scroll_area", "build_bottom_bar"]


def build_scroll_area(
    margins: tuple[int, int, int, int] = (22, 18, 22, 16),
    spacing: int = 13,
) -> tuple[QScrollArea, QVBoxLayout]:
    """创建可滚动的内容区。

    窗口较矮时出现滚动条，而不是把卡片压扁导致文字重叠。
    返回 ``(滚动区域, 内容布局)``。
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    content = QWidget()
    content.setObjectName("PageContent")
    layout = QVBoxLayout(content)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    scroll.setWidget(content)
    return scroll, layout


def build_bottom_bar() -> tuple[QWidget, QHBoxLayout]:
    """固定在页面底部的操作栏（有独立背景与顶部分隔线）。"""
    bar = QWidget()
    bar.setObjectName("BottomBar")
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(22, 10, 22, 12)
    layout.setSpacing(10)
    return bar, layout
