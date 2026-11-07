"""界面主题：调色板与全局样式表。

旧版界面用的是 Windows 原生 ttk 主题，控件灰扑扑、层次扁平，是「老旧感」
的主要来源。这里用一套自定义配色 + QSS 重建视觉语言：

* 中性灰蓝底色，卡片纯白浮起，12px 圆角；
* 主色统一走蓝，状态色（成功/警告/危险）只用于语义；
* 深色主题与浅色主题共用同一套结构，只换色值。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Palette", "LIGHT", "DARK", "build_qss", "FONT_FAMILY"]


FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif'
MONO_FAMILY = '"Cascadia Mono", "Consolas", "Courier New", monospace'


@dataclass(frozen=True, slots=True)
class Palette:
    """一套完整配色。"""

    name: str
    bg: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str
    text: str
    text_soft: str
    muted: str
    primary: str
    primary_hover: str
    primary_pressed: str
    primary_soft: str
    on_primary: str
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    shadow: str
    log_bg: str
    log_text: str
    sidebar: str
    sidebar_active: str
    sidebar_text: str
    sidebar_text_active: str


LIGHT = Palette(
    name="light",
    bg="#F4F6FB",
    surface="#FFFFFF",
    surface_alt="#F7F9FD",
    surface_hover="#EEF2FA",
    border="#E4E9F2",
    border_strong="#CBD5E1",
    text="#111C33",
    text_soft="#334155",
    muted="#7A8AA3",
    primary="#2F6BFF",
    primary_hover="#1F57E6",
    primary_pressed="#1A49C4",
    primary_soft="#EAF0FF",
    on_primary="#FFFFFF",
    success="#12A06F",
    success_soft="#E6F7F0",
    warning="#D97706",
    warning_soft="#FEF3E2",
    danger="#E11D48",
    danger_soft="#FEECF0",
    shadow="#0B1B3A14",
    log_bg="#0E1729",
    log_text="#C7D3E8",
    sidebar="#FFFFFF",
    sidebar_active="#EAF0FF",
    sidebar_text="#5A6B85",
    sidebar_text_active="#2F6BFF",
)

DARK = Palette(
    name="dark",
    bg="#0B1220",
    surface="#131C2E",
    surface_alt="#18233A",
    surface_hover="#1E2B45",
    border="#243149",
    border_strong="#33425E",
    text="#E8EEF9",
    text_soft="#C3CEE0",
    muted="#8496B0",
    primary="#4C86FF",
    primary_hover="#6296FF",
    primary_pressed="#3B74EC",
    primary_soft="#1B2A4A",
    on_primary="#FFFFFF",
    success="#2ED3A0",
    success_soft="#12312A",
    warning="#F2B44A",
    warning_soft="#33260F",
    danger="#FF6B87",
    danger_soft="#361A22",
    shadow="#00000040",
    log_bg="#080E19",
    log_text="#AEC0DA",
    sidebar="#0F1829",
    sidebar_active="#1B2A4A",
    sidebar_text="#8496B0",
    sidebar_text_active="#6FA0FF",
)


def build_qss(p: Palette) -> str:
    """生成整套 QSS。"""
    return f"""
/* ---------- 基础 ---------- */
QWidget {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {p.text};
}}
QMainWindow, #Root {{
    background: {p.bg};
}}
QToolTip {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 6px 8px;
}}

/* ---------- 顶栏与侧边栏 ---------- */
#TopBar {{
    background: {p.surface};
    border-bottom: 1px solid {p.border};
}}
#AppTitle {{
    font-size: 16px;
    font-weight: 700;
    color: {p.text};
}}
#AppSubtitle {{
    font-size: 12px;
    color: {p.muted};
}}
#Sidebar {{
    background: {p.sidebar};
    border-right: 1px solid {p.border};
}}
#VersionLabel {{
    color: {p.muted};
    font-size: 11px;
}}

/* ---------- 卡片 ---------- */
#Card {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 14px;
}}
#BottomBar {{
    background: {p.surface};
    border-top: 1px solid {p.border};
}}
#PageContent {{
    background: {p.bg};
}}
#CardTitle {{
    font-size: 14px;
    font-weight: 700;
    color: {p.text};
}}
#CardHint {{
    font-size: 12px;
    color: {p.muted};
}}
#StepBadge {{
    background: {p.primary_soft};
    color: {p.primary};
    border-radius: 9px;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 8px;
}}

/* ---------- 文本 ---------- */
QLabel#Muted {{ color: {p.muted}; }}
QLabel#Soft  {{ color: {p.text_soft}; }}
QLabel#SectionLabel {{
    color: {p.muted};
    font-size: 12px;
    font-weight: 600;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: transparent;
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 9px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {p.surface_hover}; }}
QPushButton:pressed {{ background: {p.surface_alt}; }}
QPushButton:disabled {{ color: {p.muted}; border-color: {p.border}; }}

QPushButton#Primary {{
    background: {p.primary};
    color: {p.on_primary};
    border: 1px solid {p.primary};
}}
QPushButton#Primary:hover {{ background: {p.primary_hover}; border-color: {p.primary_hover}; }}
QPushButton#Primary:pressed {{ background: {p.primary_pressed}; }}
QPushButton#Primary:disabled {{
    background: {p.surface_alt};
    color: {p.muted};
    border-color: {p.border};
}}

QPushButton#Ghost {{
    background: transparent;
    border: 1px solid {p.border};
    color: {p.text_soft};
}}
QPushButton#Ghost:hover {{ background: {p.surface_hover}; color: {p.text}; }}

QPushButton#Danger {{
    background: transparent;
    border: 1px solid {p.border};
    color: {p.danger};
}}
QPushButton#Danger:hover {{ background: {p.danger_soft}; border-color: {p.danger}; }}

QPushButton#Nav {{
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 10px 14px;
    text-align: left;
    color: {p.sidebar_text};
    font-weight: 600;
}}
QPushButton#Nav:hover {{ background: {p.surface_hover}; color: {p.text}; }}
QPushButton#Nav:checked {{
    background: {p.sidebar_active};
    color: {p.sidebar_text_active};
}}

QPushButton#IconButton {{
    background: transparent;
    border: 1px solid {p.border};
    border-radius: 9px;
    padding: 6px;
}}
QPushButton#IconButton:hover {{ background: {p.surface_hover}; }}

/* ---------- 输入控件 ---------- */
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 9px;
    padding: 8px 12px;
    selection-background-color: {p.primary};
    selection-color: {p.on_primary};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {p.primary};
    background: {p.surface};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {{ color: {p.muted}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    selection-background-color: {p.primary_soft};
    selection-color: {p.text};
    outline: none;
    padding: 4px;
}}

/* ---------- 表格 ---------- */
QTableWidget, QTableView {{
    background: {p.surface};
    border: none;
    gridline-color: transparent;
    selection-background-color: {p.primary_soft};
    selection-color: {p.text};
    alternate-background-color: {p.surface_alt};
    outline: none;
}}
QTableWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid {p.border};
}}
QTableWidget::item:selected {{
    background: {p.primary_soft};
    color: {p.text};
}}
QHeaderView::section {{
    background: {p.surface_alt};
    color: {p.muted};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 9px 10px;
    font-size: 12px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background: {p.surface_alt}; border: none; }}

/* ---------- 复选 / 单选 ---------- */
QCheckBox, QRadioButton {{ spacing: 8px; color: {p.text_soft}; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1.5px solid {p.border_strong};
    border-radius: 5px;
    background: {p.surface};
}}
QCheckBox::indicator:hover {{ border-color: {p.primary}; }}
QCheckBox::indicator:checked {{
    background: {p.primary};
    border-color: {p.primary};
    image: none;
}}
QCheckBox::indicator:disabled {{ border-color: {p.border}; background: {p.surface_alt}; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {p.border_strong};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {p.border_strong};
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ---------- 日志 ---------- */
QPlainTextEdit#LogView {{
    background: {p.log_bg};
    color: {p.log_text};
    border: 1px solid {p.border};
    border-radius: 10px;
    font-family: {MONO_FAMILY};
    font-size: 12px;
    padding: 10px;
    selection-background-color: {p.primary};
}}

/* ---------- 其他 ---------- */
QFrame#Divider {{
    background: {p.border};
    max-height: 1px;
    border: none;
}}
QProgressBar {{
    background: {p.surface_alt};
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {p.primary};
    border-radius: 5px;
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QMenu {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.primary_soft}; color: {p.text}; }}
"""
