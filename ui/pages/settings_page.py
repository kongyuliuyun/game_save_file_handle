"""设置页：扩展名、默认路径、外观与配置文件维护。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...app.bootstrap import ThemeManager
from ...core.config import (
    AppConfig,
    format_whitelist,
    load_config,
    parse_whitelist,
)
from ...core.errors import AppError
from ...utils.paths import config_path
from ..widgets.card import Card
from ..widgets.icons import icon
from ..widgets.themed import bind_themed_icon
from .common import build_bottom_bar, build_scroll_area

__all__ = ["SettingsPage"]


class SettingsPage(QWidget):
    status_message = Signal(str, str)
    saved = Signal(object)

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._build_ui()
        self._sync_from_config()

    # ==================================================================
    # 界面
    # ==================================================================

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll, layout = build_scroll_area()
        outer.addWidget(scroll, 1)

        layout.addWidget(self._build_extensions_card())
        layout.addWidget(self._build_whitelist_card())
        layout.addWidget(self._build_defaults_card())
        layout.addWidget(self._build_appearance_card())
        layout.addWidget(self._build_config_card())
        layout.addStretch(1)

        bar, bar_layout = build_bottom_bar()
        self._build_actions(bar_layout)
        outer.addWidget(bar)

    def _build_extensions_card(self) -> Card:
        card = Card("存档文件扩展名", "扫描时按扩展名识别存档，多个用逗号或换行分隔")
        self.extensions_edit = QPlainTextEdit()
        self.extensions_edit.setFixedHeight(76)
        self.extensions_edit.setPlaceholderText(".sav, .save, .rpgsave")
        card.body().addWidget(self.extensions_edit)

        note = QLabel(
            "提示：不确定扩展名时可先扫描一次，日志会列出命中的文件；"
            "把它们的后缀补进来即可。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        card.body().addWidget(note)
        return card

    def _build_whitelist_card(self) -> Card:
        card = Card("扫描白名单", "按目录限制允许备份的游戏；留空表示全部放行")
        self.whitelist_edit = QPlainTextEdit()
        self.whitelist_edit.setFixedHeight(76)
        self.whitelist_edit.setPlaceholderText(
            "D:\\Games => 游戏A, 游戏B\n"
            "default => all"
        )
        card.body().addWidget(self.whitelist_edit)

        row = QHBoxLayout()
        row.setSpacing(9)

        self.add_whitelist_button = QPushButton("  添加目录…")
        self.add_whitelist_button.setObjectName("Ghost")
        bind_themed_icon(self.add_whitelist_button, "folder", "text_soft", 15)
        self.add_whitelist_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_whitelist_button.setToolTip("选择一个目录，插入为「目录 => all」")
        self.add_whitelist_button.clicked.connect(self._insert_whitelist_dir)
        row.addWidget(self.add_whitelist_button)
        row.addStretch(1)
        card.body().addLayout(row)

        note = QLabel(
            "每行格式：目录 => 游戏名1, 游戏名2；目录写 default 表示兜底规则；"
            "游戏名写 all 表示该目录全部放行。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        card.body().addWidget(note)
        return card

    def _build_defaults_card(self) -> Card:
        card = Card("默认路径", "新建任务时会自动填入这些目录")
        grid = QHBoxLayout()
        grid.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(self._label("临时工作目录"))
        self.work_edit = QLineEdit()
        self.work_edit.setPlaceholderText("留空使用系统临时目录")
        left.addWidget(self.work_edit)

        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(self._label("百度云目标目录"))
        self.remote_edit = QLineEdit()
        self.remote_edit.setPlaceholderText("/apps/bypy/game-save-backup")
        right.addWidget(self.remote_edit)

        grid.addLayout(left, 1)
        grid.addLayout(right, 1)
        card.body().addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(10)
        left2 = QVBoxLayout()
        left2.setSpacing(6)
        left2.addWidget(self._label("本地保留目录"))
        self.keep_edit = QLineEdit()
        self.keep_edit.setPlaceholderText("勾选备份页「保留一份本地压缩包」后生效")
        left2.addWidget(self.keep_edit)
        row.addLayout(left2, 1)
        row.addStretch(1)
        card.body().addLayout(row)

        return card

    def _build_appearance_card(self) -> Card:
        card = Card("外观与行为")

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self._label("主题"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.setFixedWidth(140)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        row.addWidget(self.theme_combo)

        row.addSpacing(20)
        row.addWidget(self._label("并发上传"))
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 8)
        self.threads_spin.setFixedWidth(80)
        self.threads_spin.setToolTip("同时上传的压缩包数量，网络较慢时建议 1-2")
        row.addWidget(self.threads_spin)
        row.addStretch(1)
        card.body().addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addWidget(self._label("行为"))
        self.verify_check = QCheckBox("上传前校验压缩包完整性")
        row2.addWidget(self.verify_check)
        self.upload_check = QCheckBox("默认上传到百度云")
        row2.addWidget(self.upload_check)
        row2.addStretch(1)
        card.body().addLayout(row2)

        return card

    def _build_config_card(self) -> Card:
        card = Card("配置文件")
        self.path_label = QLabel(str(config_path()))
        self.path_label.setObjectName("Muted")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        card.body().addWidget(self.path_label)

        row = QHBoxLayout()
        row.setSpacing(9)

        self.open_config_button = QPushButton("  打开配置文件")
        self.open_config_button.setObjectName("Ghost")
        bind_themed_icon(self.open_config_button, "external", "text_soft", 15)
        self.open_config_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_config_button.clicked.connect(self._open_config_file)
        row.addWidget(self.open_config_button)

        self.open_config_dir_button = QPushButton("  打开所在目录")
        self.open_config_dir_button.setObjectName("Ghost")
        bind_themed_icon(self.open_config_dir_button, "folder", "text_soft", 15)
        self.open_config_dir_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_config_dir_button.clicked.connect(self._open_config_dir)
        row.addWidget(self.open_config_dir_button)

        self.reload_button = QPushButton("  重新加载")
        self.reload_button.setObjectName("Ghost")
        bind_themed_icon(self.reload_button, "refresh", "text_soft", 15)
        self.reload_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reload_button.clicked.connect(self._reload)
        row.addWidget(self.reload_button)

        reset_button = QPushButton("  恢复默认")
        reset_button.setObjectName("Danger")
        reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_button.clicked.connect(self._reset)
        row.addWidget(reset_button)

        row.addStretch(1)
        card.body().addLayout(row)
        return card

    def _build_actions(self, row: QHBoxLayout) -> None:
        row.setSpacing(10)
        self.hint = QLabel("修改后点「保存设置」写入配置文件")
        self.hint.setObjectName("Muted")
        row.addWidget(self.hint, 1)

        self.save_button = QPushButton("  保存设置")
        self.save_button.setObjectName("Primary")
        self.save_button.setIcon(icon("check", "#FFFFFF", 15))
        self.save_button.setIconSize(QSize(15, 15))
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.setMinimumWidth(130)
        self.save_button.clicked.connect(self._save)
        row.addWidget(self.save_button)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionLabel")
        label.setMinimumWidth(96)
        return label

    # ==================================================================
    # 数据同步
    # ==================================================================

    def _sync_from_config(self) -> None:
        self.extensions_edit.setPlainText(", ".join(sorted(self.config.extensions())))
        self.whitelist_edit.setPlainText(format_whitelist(self.config.whitelist))
        self.work_edit.setText(self.config.backup_root)
        self.remote_edit.setText(self.config.remote_dir)
        self.keep_edit.setText(self.config.zip_root)
        self.verify_check.setChecked(self.config.verify_upload)
        self.upload_check.setChecked(self.config.upload_enabled)
        self.threads_spin.setValue(self.config.upload_threads)

        index = self.theme_combo.findData(self.config.theme)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(0, index))
        self.theme_combo.blockSignals(False)

        self.path_label.setText(str(config_path()))

    def _collect(self) -> AppConfig:
        raw = self.extensions_edit.toPlainText()
        parts = [item.strip() for item in raw.replace("\n", ",").replace(";", ",").split(",")]
        extensions = {
            (item if item.startswith(".") else "." + item).lower()
            for item in parts
            if item
        }

        self.config.save_extensions = extensions or self.config.extensions()
        self.config.whitelist = parse_whitelist(self.whitelist_edit.toPlainText())
        self.config.backup_root = self.work_edit.text().strip()
        self.config.remote_dir = self.remote_edit.text().strip() or self.config.remote_dir
        self.config.zip_root = self.keep_edit.text().strip() or self.config.zip_root
        self.config.verify_upload = self.verify_check.isChecked()
        self.config.upload_enabled = self.upload_check.isChecked()
        self.config.upload_threads = self.threads_spin.value()
        self.config.theme = self.theme_combo.currentData() or "light"
        return self.config.normalized()

    def _insert_whitelist_dir(self) -> None:
        """选择目录并插入一行白名单，默认该目录全部放行。"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择要加入白名单的游戏目录", self.work_edit.text().strip()
        )
        if not folder:
            return

        folder = str(Path(folder))
        if folder in parse_whitelist(self.whitelist_edit.toPlainText()):
            self.status_message.emit(f"该目录已在白名单中：{folder}", "info")
            return

        text = self.whitelist_edit.toPlainText().rstrip()
        line = f"{folder} => all"
        self.whitelist_edit.setPlainText(f"{text}\n{line}" if text else line)
        self.status_message.emit(f"已添加白名单目录：{folder}", "success")

    # ==================================================================
    # 事件
    # ==================================================================

    def _on_theme_changed(self) -> None:
        name = self.theme_combo.currentData() or "light"
        ThemeManager.instance().set_theme(name)

    def _save(self) -> None:
        config = self._collect()
        self.config = config
        try:
            target = config.save()
        except AppError as exc:
            self.status_message.emit(exc.message, "error")
            return
        self.hint.setText(f"已保存到 {target}")
        # 若因权限回退到用户配置目录，同步刷新显示的实际路径
        self.path_label.setText(str(target))
        self.status_message.emit("设置已保存", "success")
        self.saved.emit(config)

    def _reload(self) -> None:
        try:
            fresh = load_config()
        except AppError as exc:
            self.status_message.emit(exc.message, "error")
            return
        self.config = fresh
        self._sync_from_config()
        ThemeManager.instance().set_theme(fresh.theme)
        self.status_message.emit("已重新加载配置文件", "info")
        self.saved.emit(fresh)

    def _reset(self) -> None:
        self.config = AppConfig()
        self._sync_from_config()
        ThemeManager.instance().set_theme(self.config.theme)
        self.status_message.emit("已恢复默认值，记得点「保存设置」", "warning")

    def _open_config_file(self) -> None:
        path = config_path()
        if not path.is_file():
            self.status_message.emit("配置文件还不存在，先点「保存设置」创建", "warning")
            return
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError as exc:
            self.status_message.emit(f"无法打开配置文件：{exc}", "error")

    def _open_config_dir(self) -> None:
        path = config_path().parent
        if not path.is_dir():
            self.status_message.emit("配置目录不存在", "warning")
            return
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            self.status_message.emit(f"无法打开目录：{exc}", "error")
