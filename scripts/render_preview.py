"""离屏渲染界面预览图，用于验收视觉效果。

用法::

    python scripts/render_preview.py            # 空状态
    python scripts/render_preview.py --demo     # 带示例数据的满状态

生成文件位于 ``docs/preview/``。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# offscreen 平台不会自动读取系统字体目录，导致中文渲染成方框
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parent.parent
for _path in (str(ROOT), str(ROOT.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402

from game_save_file_handle.app.bootstrap import ThemeManager, create_application  # noqa: E402
from game_save_file_handle.core.models import GameEntry, GameStatus, SaveFile  # noqa: E402
from game_save_file_handle.ui.main_window import MainWindow  # noqa: E402

OUT_DIR = ROOT / "docs" / "preview"


def _load_system_fonts() -> None:
    """离屏渲染时手动注入中文字体，保证截图与真实运行一致。"""
    if os.name != "nt":
        return
    for name in ("simhei.ttf", "Deng.ttf", "simsun.ttc", "msyh.ttc"):
        candidate = Path(r"C:\Windows\Fonts") / name
        if not candidate.is_file():
            continue
        family = QFontDatabase.applicationFontFamilies(
            QFontDatabase.addApplicationFont(str(candidate))
        )
        if family:
            print(f"font loaded: {name} -> {family}")
            return


def _demo_games() -> list[GameEntry]:
    samples = [
        ("艾尔登法环", GameStatus.READY, 12, 2_411_520),
        ("博德之门3", GameStatus.READY, 8, 8_912_640),
        ("赛博朋克2077", GameStatus.READY, 23, 1_258_291),
        ("星露谷物语", GameStatus.READY, 4, 512_000),
        ("只狼：影逝二度", GameStatus.NO_SAVES, 0, 0),
        ("荒野大镖客2", GameStatus.SKIPPED, 0, 0),
        ("巫师3：狂猎", GameStatus.READY, 6, 786_432),
        ("黑神话：悟空", GameStatus.READY, 3, 4_194_304),
    ]
    games: list[GameEntry] = []
    for index, (name, status, count, size) in enumerate(samples):
        path = Path("D:/Games") / f"Game{index}"
        game = GameEntry(path=path, name=name, status=status)
        if status is GameStatus.SKIPPED:
            game.error = "白名单未通过"
        elif status is GameStatus.NO_SAVES:
            game.error = "未找到匹配扩展名的存档文件"
        if count:
            per = size // count
            game.save_files = [
                SaveFile(
                    path=path / "saves" / f"slot{i}.sav",
                    relative=Path("saves") / f"slot{i}.sav",
                    size=per,
                )
                for i in range(count)
            ]
        games.append(game)
    return games


def _render(window: MainWindow, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    window.grab().save(str(path))
    print(f"saved: {path}")
    return path


def _populate(page) -> None:
    from PySide6.QtCore import Qt as QtCore

    page.folder_edit.setText("D:/Games")
    page._games = _demo_games()  # noqa: SLF001 - 预览脚本
    page._populate_table()  # noqa: SLF001
    page.stage_label.setText("正在上传（1/2）")
    page.percent_label.setText("62%")
    page.detail_label.setText("博德之门3.zip · 1/2 · 5.4 MB/8.5 MB · 6.2 MB/s")
    page.speed_label.setText("6.2 MB/s")
    page.eta_label.setText("剩余 不到 1 秒")
    page.progress_bar.set_fraction(0.62)
    page.log_view.setVisible(True)
    page.log_button.setChecked(True)
    page.log_button.setText("隐藏日志")
    for line in (
        "[扫描] 扫描：艾尔登法环 — 找到 12 个存档",
        "[复制] 已复制 6/8 个游戏 — 黑神话：悟空：3 个文件",
        "[压缩] 正在压缩：博德之门3 — 8 个文件 · saves/profile/extra.save",
        "[上传] 正在上传（1/2）— 博德之门3.zip · 1/2 · 5.4 MB/8.5 MB · 6.2 MB/s",
    ):
        page._append_log(line)  # noqa: SLF001


def main() -> int:
    demo = "--demo" in sys.argv
    app = create_application([])
    _load_system_fonts()
    window = MainWindow()
    window.resize(1180, 800)

    if demo:
        _populate(window.backup_page)

    for index, suffix in ((0, "backup"), (1, "auth"), (2, "settings")):
        window._switch_page(index)  # noqa: SLF001 - 预览脚本
        app.processEvents()
        _render(window, f"{suffix}-{'demo' if demo else 'empty'}-light.png")

    ThemeManager.instance().set_theme("dark")
    app.processEvents()
    for index, suffix in ((0, "backup"), (1, "auth"), (2, "settings")):
        window._switch_page(index)  # noqa: SLF001
        app.processEvents()
        _render(window, f"{suffix}-{'demo' if demo else 'empty'}-dark.png")

    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
