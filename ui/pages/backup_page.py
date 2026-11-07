"""备份任务页：选择目录 → 扫描 → 勾选 → 备份上传。

界面结构对应真实操作流程（三步卡片 + 一块进度），所有进度都来自
:mod:`core.progress` 的真实采样，不存在假进度。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...app.bootstrap import ThemeManager
from ...core.config import AppConfig, resolve_path
from ...core.errors import AppError, TaskCancelled
from ...core.models import GameEntry, GameStatus, ScanSummary
from ...core.pipeline import BackupPipeline, PipelineResult
from ...core.progress import (
    CancellationToken,
    ProgressEvent,
    SpeedMeter,
    Stage,
    TaskContext,
    throttled,
)
from ...core.scanner import discover_games, scan_games
from ...utils.fmt import human_duration, human_size, shorten_path
from ..widgets.card import Card, StatusBadge
from ..widgets.icons import icon
from ..widgets.progress import ProgressBar
from ..widgets.themed import bind_themed_icon
from .common import build_bottom_bar, build_scroll_area

__all__ = ["BackupPage"]

_STATUS_STYLE = {
    GameStatus.READY: ("已就绪", "success"),
    GameStatus.NO_SAVES: ("无存档", "neutral"),
    GameStatus.SKIPPED: ("已跳过", "warning"),
    GameStatus.ERROR: ("读取失败", "danger"),
    GameStatus.EMPTY: ("空目录", "neutral"),
    GameStatus.PENDING: ("待扫描", "primary"),
}

_COL_CHECK, _COL_NAME, _COL_FILES, _COL_SIZE, _COL_STATUS, _COL_NOTE = range(6)


class _ScanWorker(QThread):
    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        games: list[GameEntry],
        extensions: set[str],
        whitelist: dict[str, list[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._games = games
        self._extensions = extensions
        self._whitelist = whitelist
        self._token = CancellationToken()
        self._ctx = TaskContext(self._token, throttled(self.progress.emit, 0.05))

    def cancel(self) -> None:
        self._token.cancel()

    def run(self) -> None:
        try:
            summary: ScanSummary = scan_games(
                self._games, self._extensions, self._ctx, self._whitelist
            )
        except TaskCancelled:
            self.cancelled.emit()
        except Exception as exc:  # 兜底，避免线程内异常导致进程退出
            self.failed.emit(f"扫描失败：{exc}")
        else:
            self.completed.emit(summary)


class _BackupWorker(QThread):
    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        config: AppConfig,
        games: list[GameEntry],
        with_upload: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._games = games
        self._with_upload = with_upload
        self._token = CancellationToken()
        self._ctx = TaskContext(self._token, throttled(self.progress.emit, 0.05))

    def cancel(self) -> None:
        self._token.cancel()

    def run(self) -> None:
        client = None
        try:
            if self._with_upload:
                from ...cloud.baidu_pan import BaiduPanClient

                client = BaiduPanClient()
            pipeline = BackupPipeline(self._config, self._ctx, client)
            result: PipelineResult = pipeline.run(self._games)
        except TaskCancelled:
            self.cancelled.emit()
        except AppError as exc:
            self.failed.emit(exc.message)
        except Exception as exc:
            self.failed.emit(f"未预期的错误：{exc}")
        else:
            self.completed.emit(result)
        finally:
            if client is not None:
                client.close()


class BackupPage(QWidget):
    """备份主页。"""

    status_message = Signal(str, str)  # (文本, 类型)
    auth_requested = Signal()

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._games: list[GameEntry] = []
        self._root_path: Path | None = None
        self._scan_worker: _ScanWorker | None = None
        self._backup_worker: _BackupWorker | None = None
        self._updating_table = False
        self._meter = SpeedMeter()
        self._last_stage: Stage | None = None
        self._last_log = ""
        self._last_result: PipelineResult | None = None

        self._build_ui()
        self._sync_from_config()
        ThemeManager.instance().changed.connect(self._refresh_table_colors)

    # ==================================================================
    # 界面构建
    # ==================================================================

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll, layout = build_scroll_area()
        outer.addWidget(scroll, 1)

        layout.addWidget(self._build_source_card())
        layout.addWidget(self._build_games_card(), 1)
        layout.addWidget(self._build_options_card())
        layout.addWidget(self._build_progress_card())
        layout.addStretch(0)

        bar, bar_layout = build_bottom_bar()
        self._build_actions(bar_layout)
        outer.addWidget(bar)

    # ---------- 步骤 1 ----------

    def _build_source_card(self) -> Card:
        card = Card("选择游戏目录", "支持选中游戏本体，也支持包含多个游戏的上级目录", step=1)

        row = QHBoxLayout()
        row.setSpacing(9)

        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("例如 D:\\Games，或某个游戏自己的安装目录")
        self.folder_edit.setClearButtonEnabled(True)
        self.folder_edit.returnPressed.connect(self._on_scan)
        row.addWidget(self.folder_edit, 1)

        self.browse_button = QPushButton("  浏览")
        self.browse_button.setObjectName("Ghost")
        bind_themed_icon(self.browse_button, "folder", "text_soft", 16)
        self.browse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_button.clicked.connect(self._choose_folder)
        row.addWidget(self.browse_button)

        self.scan_button = QPushButton("  扫描存档")
        self.scan_button.setObjectName("Primary")
        self.scan_button.setIcon(icon("search", "#FFFFFF", 16))
        self.scan_button.setIconSize(QSize(16, 16))
        self.scan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_button.clicked.connect(self._on_scan)
        row.addWidget(self.scan_button)

        card.body().addLayout(row)
        return card

    # ---------- 步骤 2 ----------

    def _build_games_card(self) -> Card:
        card = Card("选择要备份的游戏", "只勾选需要备份的目录", step=2)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        for text, slot in (
            ("全选", self._select_all),
            ("反选", self._invert_selection),
            ("仅已就绪", self._select_ready),
        ):
            button = QPushButton(text)
            button.setObjectName("Ghost")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            toolbar.addWidget(button)

        toolbar.addStretch(1)

        self.stats_label = QLabel("尚未扫描")
        self.stats_label.setObjectName("Muted")
        toolbar.addWidget(self.stats_label)

        card.body().addLayout(toolbar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", "游戏名称", "存档", "大小", "状态", "说明"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setMinimumHeight(200)

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(_COL_CHECK, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_FILES, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_SIZE, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_NOTE, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(_COL_CHECK, 42)
        self.table.setColumnWidth(_COL_FILES, 70)
        self.table.setColumnWidth(_COL_SIZE, 90)
        self.table.setColumnWidth(_COL_STATUS, 90)

        self.table.itemChanged.connect(self._on_item_changed)

        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.table)
        self.table_stack.addWidget(self._build_empty_state())
        card.body().addWidget(self.table_stack, 1)
        self._update_empty_state()
        return card

    def _build_empty_state(self) -> QWidget:
        """表格为空时的占位提示，避免大片空白显得简陋。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        self._empty_icon = QLabel()
        self._empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_icon)

        self._empty_title = QLabel("还没有扫描结果")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_title)

        subtitle = QLabel("先选择一个游戏目录，再点击「扫描存档」")
        subtitle.setObjectName("Muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        ThemeManager.instance().changed.connect(self._refresh_empty_state)
        self._refresh_empty_state()
        return container

    def _refresh_empty_state(self, *_args) -> None:
        """主题切换后重绘空状态图标与标题颜色。"""
        from ..widgets.icons import pixmap

        palette = ThemeManager.instance().palette
        self._empty_icon.setPixmap(pixmap("folder", palette.border_strong, 44))
        self._empty_title.setStyleSheet(
            f"color: {palette.text_soft}; font-weight: 600;"
        )

    def _update_empty_state(self) -> None:
        has_rows = self.table.rowCount() > 0
        self.table_stack.setCurrentIndex(0 if has_rows else 1)

    # ---------- 步骤 3 ----------

    def _build_options_card(self) -> Card:
        card = Card("备份与上传设置", "路径可随时修改，任务结束只清理本次产生的临时文件", step=3)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(9)

        grid.addWidget(self._label("临时工作目录"), 0, 0)
        self.work_edit = QLineEdit()
        self.work_edit.setPlaceholderText("留空则使用系统临时目录")
        grid.addWidget(self.work_edit, 0, 1)
        work_browse = QPushButton("浏览")
        work_browse.setObjectName("Ghost")
        work_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        work_browse.clicked.connect(lambda: self._browse_dir(self.work_edit))
        grid.addWidget(work_browse, 0, 2)

        grid.addWidget(self._label("百度云目录"), 1, 0)
        self.remote_edit = QLineEdit()
        self.remote_edit.setPlaceholderText("/apps/bypy/game-save-backup")
        grid.addWidget(self.remote_edit, 1, 1)

        self.upload_check = QCheckBox("上传到百度云")
        self.upload_check.setCursor(Qt.CursorShape.PointingHandCursor)
        grid.addWidget(self.upload_check, 1, 2)

        grid.addWidget(self._label("本地保留目录"), 2, 0)
        self.keep_edit = QLineEdit()
        self.keep_edit.setPlaceholderText("勾选下方选项后生效")
        grid.addWidget(self.keep_edit, 2, 1)
        keep_browse = QPushButton("浏览")
        keep_browse.setObjectName("Ghost")
        keep_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        keep_browse.clicked.connect(lambda: self._browse_dir(self.keep_edit))
        grid.addWidget(keep_browse, 2, 2)

        self.keep_check = QCheckBox("保留一份本地压缩包")
        self.keep_check.setCursor(Qt.CursorShape.PointingHandCursor)
        grid.addWidget(self.keep_check, 3, 1, 1, 2)

        grid.setColumnStretch(1, 1)
        card.body().addLayout(grid)

        self.keep_check.toggled.connect(self._update_keep_enabled)
        return card

    # ---------- 进度 ----------

    def _build_progress_card(self) -> Card:
        card = Card("任务进度")
        body = card.body()

        header = QHBoxLayout()
        header.setSpacing(12)

        self.percent_label = QLabel("0%")
        percent_font = QFont()
        percent_font.setPointSize(22)
        percent_font.setWeight(QFont.Weight.Bold)
        self.percent_label.setFont(percent_font)
        self.percent_label.setFixedWidth(78)
        header.addWidget(self.percent_label)

        info = QVBoxLayout()
        info.setSpacing(2)
        self.stage_label = QLabel("准备就绪")
        self.stage_label.setStyleSheet("font-weight: 700;")
        info.addWidget(self.stage_label)
        self.detail_label = QLabel("选择目录并扫描后即可开始备份")
        self.detail_label.setObjectName("Muted")
        self.detail_label.setMaximumHeight(20)
        info.addWidget(self.detail_label)
        header.addLayout(info, 1)

        meta = QVBoxLayout()
        meta.setSpacing(2)
        self.speed_label = QLabel("")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.speed_label.setObjectName("Muted")
        meta.addWidget(self.speed_label)
        self.eta_label = QLabel("")
        self.eta_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.eta_label.setObjectName("Muted")
        meta.addWidget(self.eta_label)
        header.addLayout(meta)

        body.addLayout(header)

        self.progress_bar = ProgressBar(thickness=10)
        body.addWidget(self.progress_bar)

        log_header = QHBoxLayout()
        log_header.setSpacing(8)
        log_header.addStretch(1)
        self.log_button = QPushButton("显示日志")
        self.log_button.setObjectName("Ghost")
        self.log_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_button.setCheckable(True)
        self.log_button.toggled.connect(self._toggle_log)
        log_header.addWidget(self.log_button)
        body.addLayout(log_header)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(112)
        self.log_view.setVisible(False)
        self.log_view.setMaximumBlockCount(3000)
        body.addWidget(self.log_view)

        return card

    # ---------- 底部操作 ----------

    def _build_actions(self, row: QHBoxLayout) -> None:
        row.setSpacing(10)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("Muted")
        row.addWidget(self.hint_label, 1)

        self.cancel_button = QPushButton("  取消")
        self.cancel_button.setObjectName("Danger")
        bind_themed_icon(self.cancel_button, "stop", "danger", 15)
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        row.addWidget(self.cancel_button)

        self.start_button = QPushButton("  开始备份")
        self.start_button.setObjectName("Primary")
        self.start_button.setIcon(icon("play", "#FFFFFF", 15))
        self.start_button.setIconSize(QSize(15, 15))
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.setMinimumWidth(140)
        self.start_button.clicked.connect(self._on_start)
        row.addWidget(self.start_button)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionLabel")
        label.setMinimumWidth(96)
        return label

    # ==================================================================
    # 配置同步
    # ==================================================================

    def _sync_from_config(self) -> None:
        work, warning = resolve_path(self.config.backup_root) if self.config.backup_root else (
            Path(),
            "",
        )
        self.work_edit.setText(self.config.backup_root or "")
        self.remote_edit.setText(self.config.remote_dir)
        self.keep_edit.setText(self.config.zip_root or "")
        self.keep_check.setChecked(self.config.keep_local_backup)
        self.upload_check.setChecked(self.config.upload_enabled)
        self._update_keep_enabled()
        if warning:
            self.status_message.emit(warning, "warning")

    def refresh_from_config(self) -> None:
        """配置在别处更新后，刷新界面上的回显值。"""
        self._sync_from_config()

    def apply_to_config(self) -> AppConfig:
        """把界面上的设置写回配置对象。"""
        self.config.backup_root = self.work_edit.text().strip()
        self.config.zip_root = self.keep_edit.text().strip() or self.config.zip_root
        self.config.remote_dir = self.remote_edit.text().strip() or self.config.remote_dir
        self.config.keep_local_backup = self.keep_check.isChecked()
        self.config.upload_enabled = self.upload_check.isChecked()
        return self.config

    def _update_keep_enabled(self) -> None:
        enabled = self.keep_check.isChecked()
        self.keep_edit.setEnabled(enabled)

    # ==================================================================
    # 扫描
    # ==================================================================

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择游戏目录", self.folder_edit.text())
        if not folder:
            return
        self.folder_edit.setText(folder)
        self._on_scan()

    def _on_scan(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return

        text = self.folder_edit.text().strip()
        if not text:
            self.status_message.emit("请先选择游戏目录", "warning")
            return

        root = Path(text)
        if not root.is_dir():
            self.status_message.emit("目录不存在或无法访问", "error")
            return

        games = discover_games(root)
        if not games:
            self.status_message.emit("该目录下没有可扫描的子目录", "warning")
            return

        self._root_path = root
        self._games = games
        self._populate_table()
        self._set_scanning(True)
        self._reset_progress()
        self._append_log(f"开始扫描：{root}（{len(games)} 个目录）")

        worker = _ScanWorker(games, self.config.extensions(), self.config.whitelist, self)
        worker.progress.connect(self._on_progress)
        worker.completed.connect(self._on_scan_completed)
        worker.failed.connect(self._on_scan_failed)
        worker.cancelled.connect(self._on_scan_cancelled)
        self._scan_worker = worker
        worker.start()

    def _set_scanning(self, scanning: bool) -> None:
        self.scan_button.setEnabled(not scanning)
        self.scan_button.setText("  扫描中…" if scanning else "  扫描存档")
        self.cancel_button.setEnabled(scanning)
        self.start_button.setEnabled(not scanning)

    def _on_scan_completed(self, summary: ScanSummary) -> None:
        self._set_scanning(False)
        self._scan_worker = None

        ready = len(summary.ready_games)
        self._populate_table()
        self._refresh_stats()
        self._append_log(
            f"扫描完成：{ready}/{len(summary.games)} 个目录找到存档，"
            f"共 {summary.total_files} 个文件 / {human_size(summary.total_bytes)}"
        )
        self.stage_label.setText("扫描完成")
        self.detail_label.setText(
            f"找到 {summary.total_files} 个存档文件，共 {human_size(summary.total_bytes)}"
        )
        self.progress_bar.set_fraction(1.0)
        self.percent_label.setText("100%")

        if ready == 0:
            self.status_message.emit("没有找到任何存档文件，请检查扩展名配置", "warning")
        else:
            self.status_message.emit(f"扫描完成，{ready} 个游戏可备份", "success")

    def _on_scan_failed(self, message: str) -> None:
        self._set_scanning(False)
        self._scan_worker = None
        self.stage_label.setText("扫描失败")
        self.progress_bar.set_fraction(0.0)
        self.percent_label.setText("—")
        self.status_message.emit(message, "error")
        self._append_log(message)

    def _on_scan_cancelled(self) -> None:
        self._set_scanning(False)
        self._scan_worker = None
        self.stage_label.setText("已取消")
        self.progress_bar.set_fraction(0.0)
        self.percent_label.setText("—")
        self.status_message.emit("扫描已取消", "warning")

    # ==================================================================
    # 表格
    # ==================================================================

    def _populate_table(self) -> None:
        self._updating_table = True
        try:
            self.table.setRowCount(len(self._games))
            for row, game in enumerate(self._games):
                check = QTableWidgetItem()
                check.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                check.setCheckState(
                    Qt.CheckState.Checked if game.selected else Qt.CheckState.Unchecked
                )
                self.table.setItem(row, _COL_CHECK, check)

                name = QTableWidgetItem(game.name)
                name.setToolTip(str(game.path))
                name.setData(Qt.ItemDataRole.UserRole, row)
                self.table.setItem(row, _COL_NAME, name)

                files = QTableWidgetItem(str(game.save_count) if game.save_count else "—")
                files.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, _COL_FILES, files)

                size_text = human_size(game.total_bytes) if game.total_bytes else "—"
                size = QTableWidgetItem(size_text)
                size.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, _COL_SIZE, size)

                label, kind = _STATUS_STYLE.get(game.status, ("—", "neutral"))
                badge = StatusBadge(label, kind)
                badge.setFixedHeight(20)
                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(0, 0, 0, 0)
                cell_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignCenter)
                self.table.setCellWidget(row, _COL_STATUS, cell)

                note = QTableWidgetItem(game.error or "")
                note.setToolTip(game.error or str(game.path))
                note.setForeground(QColor(ThemeManager.instance().palette.muted))
                self.table.setItem(row, _COL_NOTE, note)
        finally:
            self._updating_table = False
        self._update_empty_state()
        self._refresh_stats()

    def _refresh_table_colors(self, *_args) -> None:
        """主题切换后更新表格中固定颜色的文字（状态徽章会自行刷新）。"""
        palette = ThemeManager.instance().palette
        for row in range(min(len(self._games), self.table.rowCount())):
            note = self.table.item(row, _COL_NOTE)
            if note is not None:
                note.setForeground(QColor(palette.muted))

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.column() != _COL_CHECK:
            return
        row = item.row()
        if not (0 <= row < len(self._games)):
            return
        self._games[row].selected = item.checkState() == Qt.CheckState.Checked
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        total = len(self._games)
        if not total:
            self.stats_label.setText("尚未扫描")
            return
        selected = [g for g in self._games if g.selected and g.status is GameStatus.READY]
        files = sum(g.save_count for g in selected)
        size = sum(g.total_bytes for g in selected)
        self.stats_label.setText(
            f"共 {total} 个目录 · 已选 {len(selected)} 个 · "
            f"{files} 个存档 · {human_size(size)}"
        )
        self.hint_label.setText(
            f"已选择 {len(selected)} 个游戏，共 {files} 个存档文件"
            if selected
            else "请勾选至少一个游戏"
        )

    def _set_all(self, predicate) -> None:
        self._updating_table = True
        try:
            for row, game in enumerate(self._games):
                game.selected = bool(predicate(game))
                item = self.table.item(row, _COL_CHECK)
                if item is not None:
                    item.setCheckState(
                        Qt.CheckState.Checked if game.selected else Qt.CheckState.Unchecked
                    )
        finally:
            self._updating_table = False
        self._refresh_stats()

    def _select_all(self) -> None:
        self._set_all(lambda game: game.status is GameStatus.READY)

    def _invert_selection(self) -> None:
        self._set_all(lambda game: not game.selected)

    def _select_ready(self) -> None:
        self._set_all(lambda game: game.status is GameStatus.READY)

    # ==================================================================
    # 备份任务
    # ==================================================================

    def _on_start(self) -> None:
        if self._backup_worker is not None and self._backup_worker.isRunning():
            return

        selected = [g for g in self._games if g.selected and g.save_files]
        if not selected:
            self.status_message.emit("请先扫描并勾选至少一个游戏", "warning")
            return

        self.apply_to_config()
        with_upload = self.config.upload_enabled
        if with_upload:
            from ...cloud.auth import TokenStore

            if not TokenStore().has_token():
                self.status_message.emit("尚未授权百度云，请先前往「授权」页面", "warning")
                self.auth_requested.emit()
                return

        self._last_result = None
        self._reset_progress()
        self._set_running(True)
        self._append_log("═" * 48)
        self._append_log(f"开始备份 {len(selected)} 个游戏")

        worker = _BackupWorker(self.config, selected, with_upload, self)
        worker.progress.connect(self._on_progress)
        worker.completed.connect(self._on_backup_completed)
        worker.failed.connect(self._on_backup_failed)
        worker.cancelled.connect(self._on_backup_cancelled)
        self._backup_worker = worker
        worker.start()

    def _on_cancel(self) -> None:
        if self._backup_worker is not None and self._backup_worker.isRunning():
            self._backup_worker.cancel()
            self.cancel_button.setEnabled(False)
            self.stage_label.setText("正在取消…")
            self.status_message.emit("正在取消，请稍候…", "warning")
        elif self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.cancel()

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.start_button.setText("  备份中…" if running else "  开始备份")
        self.cancel_button.setEnabled(running)
        self.scan_button.setEnabled(not running)

    def _on_backup_completed(self, result: PipelineResult) -> None:
        self._set_running(False)
        self._backup_worker = None
        self._last_result = result
        report = result.report

        self.progress_bar.set_fraction(1.0)
        self.percent_label.setText("100%")
        self.stage_label.setText("备份完成")
        self.speed_label.setText("")
        self.eta_label.setText("")

        summary = (
            f"{report.games_backed_up} 个游戏 · {report.files_total} 个文件 · "
            f"{human_size(report.bytes_total)} · 用时 {human_duration(report.elapsed)}"
        )
        self.detail_label.setText(summary)
        self._append_log(f"✓ {summary}")

        if report.uploaded:
            self._append_log(f"已上传 {len(report.uploaded)} 个压缩包到 {self.config.remote_dir}")
        for warning in result.warnings:
            self._append_log(f"提示：{warning}")
        for error in report.errors[:20]:
            self._append_log(f"警告：{error}")

        if report.success:
            self.status_message.emit("备份完成", "success")
        else:
            self.status_message.emit(
                f"备份完成，但有 {len(report.errors)} 处问题，详见日志", "warning"
            )

    def _on_backup_failed(self, message: str) -> None:
        self._set_running(False)
        self._backup_worker = None
        self.stage_label.setText("备份失败")
        self.percent_label.setText("—")
        self.progress_bar.set_fraction(0.0)
        self.speed_label.setText("")
        self.eta_label.setText("")
        self.detail_label.setText(message)
        self._append_log(f"✗ {message}")
        self.status_message.emit(message, "error")

        if "授权" in message:
            self.auth_requested.emit()

    def _on_backup_cancelled(self) -> None:
        self._set_running(False)
        self._backup_worker = None
        self.stage_label.setText("已取消")
        self.percent_label.setText("—")
        self.progress_bar.set_fraction(0.0)
        self.speed_label.setText("")
        self.eta_label.setText("")
        self._append_log("任务已取消，临时文件已清理")
        self.status_message.emit("任务已取消", "warning")

    # ==================================================================
    # 进度渲染
    # ==================================================================

    def _reset_progress(self) -> None:
        self.progress_bar.reset()
        self.percent_label.setText("0%")
        self.stage_label.setText("准备中…")
        self.detail_label.setText("")
        self.speed_label.setText("")
        self.eta_label.setText("")
        self._meter.reset()
        self._last_stage = None

    def _on_progress(self, event: ProgressEvent) -> None:
        if event.stage is not self._last_stage:
            self._meter.reset()
            self._last_stage = event.stage

        fraction = event.fraction
        self.progress_bar.set_fraction(fraction)
        self.percent_label.setText("—" if fraction is None else f"{fraction * 100:.0f}%")

        self.stage_label.setText(event.stage.label)
        detail = event.detail or event.message
        self.detail_label.setText(shorten_path(detail, 96) if detail else "")

        if fraction is None:
            self.speed_label.setText("")
            self.eta_label.setText("")
        else:
            speed = self._meter.update(event.done)
            if event.unit == "bytes":
                self.speed_label.setText(f"{human_size(speed)}/s" if speed > 0 else "")
                eta = SpeedMeter.eta(event.total, event.done, speed)
                self.eta_label.setText(f"剩余 {human_duration(eta)}" if eta else "")
            else:
                self.speed_label.setText("")
                eta = SpeedMeter.eta(event.total, event.done, speed)
                self.eta_label.setText(f"预计 {human_duration(eta)}" if eta else "")

        self._log_event(event)

    def _log_event(self, event: ProgressEvent) -> None:
        message = event.message
        if not message or message == self._last_log:
            return
        self._last_log = message
        prefix = {
            Stage.SCAN: "扫描",
            Stage.COPY: "复制",
            Stage.PACK: "压缩",
            Stage.UPLOAD: "上传",
            Stage.CLEANUP: "清理",
            Stage.DONE: "完成",
        }.get(event.stage, "")
        line = f"[{prefix}] {message}"
        if event.detail and event.detail not in message:
            line += f" — {event.detail}"
        self._append_log(line)

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _toggle_log(self, visible: bool) -> None:
        self.log_view.setVisible(visible)
        self.log_button.setText("隐藏日志" if visible else "显示日志")

    # ==================================================================
    # 工具
    # ==================================================================

    def _browse_dir(self, target: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择目录", target.text())
        if folder:
            target.setText(folder)

    def focus_scan(self) -> None:
        self.folder_edit.setFocus()

    # ==================================================================
    # 生命周期
    # ==================================================================

    def is_busy(self) -> bool:
        """是否有扫描或备份任务在运行。"""
        return any(
            worker is not None and worker.isRunning()
            for worker in (self._scan_worker, self._backup_worker)
        )

    def stop_all(self) -> None:
        """请求取消所有任务并等待线程收尾（用于退出程序前）。"""
        for worker in (self._scan_worker, self._backup_worker):
            if worker is not None and worker.isRunning():
                worker.cancel()
        for worker in (self._scan_worker, self._backup_worker):
            if worker is not None:
                worker.wait(3000)
