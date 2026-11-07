"""跟随主题自动换色的控件辅助函数。

线性图标是用 SVG 动态渲染出来的，颜色在渲染时就被固定进 pixmap。
如果只在创建控件时取一次 ``palette``，切换深浅色主题后图标颜色不会变化，
深色主题下会出现对比度过低的问题。

:func:`bind_themed_icon` 把「按调色板角色取色 → 重新渲染图标」的过程
绑定到 :class:`ThemeManager.changed` 信号上，调用一次即可长期生效。
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QPushButton

from ...app.bootstrap import ThemeManager
from .icons import icon

__all__ = ["bind_themed_icon"]


def bind_themed_icon(
    button: QPushButton,
    name: str,
    color_role: str = "text_soft",
    size: int = 15,
) -> None:
    """让按钮图标跟随主题切换自动重新着色。

    Parameters
    ----------
    button:
        目标按钮。
    name:
        :mod:`ui.widgets.icons` 中的图标名。
    color_role:
        :class:`app.theme.Palette` 的字段名，例如 ``text_soft``（次要文字）、
        ``danger``（危险操作）、``on_primary``（主色按钮上的前景色）。
    size:
        图标边长（逻辑像素）。
    """

    def _refresh(*_args: object) -> None:
        try:
            palette = ThemeManager.instance().palette
            # 角色名写错时回退到次要文字色，避免图标直接消失
            color = getattr(palette, color_role, palette.text_soft)
            button.setIcon(icon(name, color, size))
        except RuntimeError:
            # 按钮已随窗口销毁，忽略迟到的主题信号
            pass

    button.setIconSize(QSize(size, size))
    ThemeManager.instance().changed.connect(_refresh)
    _refresh()
