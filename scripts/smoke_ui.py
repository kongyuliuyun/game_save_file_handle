"""界面运行期冒烟测试（离屏，不弹窗）。

覆盖交接文档 5.1 / 5.2 的关键检查点：

1. 主窗口能创建、显示、三页可切换；
2. 备份页表格不会被压扁，空状态与数据态切换正常；
3. 底部固定操作栏始终在可视区域底部，日志展开后不遮挡按钮；
4. 设置页底部存在「保存设置」按钮；
5. 深浅色主题切换不报错，按钮图标随主题重新着色；
6. 设置页的「添加目录」能写入白名单且不会重复。

用法::

    python scripts/smoke_ui.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parent.parent
for _path in (str(ROOT), str(ROOT.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QFileDialog, QWidget  # noqa: E402

from game_save_file_handle.app.bootstrap import ThemeManager, create_application  # noqa: E402
from game_save_file_handle.core.models import GameEntry, GameStatus, SaveFile  # noqa: E402
from game_save_file_handle.ui.main_window import MainWindow  # noqa: E402

OUT_DIR = ROOT / "docs" / "preview" / "smoke"

_failures: list[str] = []


def check(condition: bool, message: str) -> None:
    """断言并记录结果，失败不中断后续检查。"""
    if condition:
        print(f"  [通过] {message}")
    else:
        print(f"  [失败] {message}")
        _failures.append(message)


def _load_system_fonts() -> None:
    if os.name != "nt":
        return
    for name in ("msyh.ttc", "simhei.ttf", "Deng.ttf", "simsun.ttc"):
        candidate = Path(r"C:\Windows\Fonts") / name
        if candidate.is_file():
            QFontDatabase.addApplicationFont(str(candidate))
            return


def _demo_games() -> list[GameEntry]:
    games: list[GameEntry] = []
    for index, (name, status, count, size) in enumerate(
        [
            ("艾尔登法环", GameStatus.READY, 12, 2_411_520),
            ("博德之门3", GameStatus.READY, 8, 8_912_640),
            ("星露谷物语", GameStatus.READY, 4, 512_000),
            ("只狼：影逝二度", GameStatus.NO_SAVES, 0, 0),
            ("荒野大镖客2", GameStatus.SKIPPED, 0, 0),
        ]
    ):
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


def _overlaps(a: QRect, b: QRect) -> bool:
    return a.intersects(b)


def _wait_until(app, predicate, timeout: float) -> bool:
    """驱动事件循环，直到条件成立或超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


def _render(window: MainWindow, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(OUT_DIR / name))


def _icon_bytes(button, size: int = 15) -> bytes:
    """把按钮图标渲染成 PNG 字节，用于比较主题切换前后的实际配色。"""
    image = button.icon().pixmap(size, size).toImage()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def main() -> int:
    app = create_application([])
    _load_system_fonts()

    print("== 1. 创建主窗口 ==")
    try:
        window = MainWindow()
        window.resize(1160, 780)
        window.show()
        app.processEvents()
    except Exception:
        traceback.print_exc()
        print("主窗口创建失败")
        return 1

    check(window.isVisible(), "主窗口可见")
    check(window.stack.count() == 3, "页面堆栈包含 3 个页面")

    print("== 2. 三页切换 ==")
    for index, name in enumerate(("备份", "授权", "设置")):
        try:
            window._switch_page(index)  # noqa: SLF001 - 冒烟脚本
            app.processEvents()
        except Exception:
            traceback.print_exc()
        check(window.stack.currentIndex() == index, f"切换到「{name}」页成功")
        check(
            window.page_title.text() == ("备份游戏存档", "百度云授权", "设置")[index],
            f"「{name}」页顶栏标题正确",
        )
        _render(window, f"page-{index}-{name}.png")

    print("== 3. 备份页布局 ==")
    window._switch_page(0)  # noqa: SLF001
    app.processEvents()
    page = window.backup_page

    check(page.table.minimumHeight() == 200, "表格设置了 200px 最小高度")
    check(
        page.table_stack.currentIndex() == 1,
        "无数据时显示空状态占位",
    )

    page.folder_edit.setText("D:/Games")
    page._games = _demo_games()  # noqa: SLF001 - 冒烟脚本
    page._populate_table()  # noqa: SLF001
    app.processEvents()

    check(page.table_stack.currentIndex() == 0, "有数据时切换回表格视图")
    check(page.table.rowCount() == 5, "表格行数与游戏数一致")
    check(page.table.height() >= 200, f"表格实际高度 {page.table.height()}px ≥ 200px")

    # 底部操作栏与滚动区不重叠
    bottom_bar = page.findChild(QWidget, "BottomBar")
    check(
        bottom_bar is not None and bottom_bar.height() > 0,
        "备份页底部操作栏存在且有高度",
    )
    if bottom_bar is not None:
        check(
            bottom_bar.geometry().top() >= 0
            and bottom_bar.geometry().bottom() <= page.height(),
            f"底部操作栏位于页面内（top={bottom_bar.geometry().top()}, "
            f"bottom={bottom_bar.geometry().bottom()}, 页面高={page.height()}）",
        )

    print("== 4. 日志展开不遮挡按钮 ==")
    page.log_button.setChecked(True)
    app.processEvents()
    check(page.log_view.isVisible(), "日志面板展开后可见")
    log_rect = page.log_view.mapTo(window, QPoint(0, 0))
    log_rect = QRect(log_rect, page.log_view.size())
    start_rect = page.start_button.mapTo(window, QPoint(0, 0))
    start_rect = QRect(start_rect, page.start_button.size())
    check(
        start_rect.height() > 0 and not _overlaps(log_rect, start_rect),
        "日志面板与「开始备份」按钮不重叠",
    )
    _render(window, "backup-with-log.png")
    page.log_button.setChecked(False)
    app.processEvents()

    print("== 5. 设置页底部保存按钮 ==")
    window._switch_page(2)  # noqa: SLF001
    app.processEvents()
    settings = window.settings_page
    check(hasattr(settings, "save_button"), "设置页存在 save_button 属性")
    check(settings.save_button.isVisible(), "设置页「保存设置」按钮可见")
    save_rect = settings.save_button.mapTo(window, QPoint(0, 0))
    save_rect = QRect(save_rect, settings.save_button.size())
    check(
        save_rect.bottom() <= window.height(),
        f"「保存设置」按钮在窗口内（bottom={save_rect.bottom()}, 窗口高={window.height()}）",
    )

    # 设置页保存流程（写临时目录，不碰用户真实配置）
    from game_save_file_handle.core.config import AppConfig, load_config

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "config.yaml"
        cfg = AppConfig().normalized()
        cfg.save(target)
        reloaded = load_config(target)
        check(
            reloaded.save_extensions == cfg.save_extensions,
            "配置保存后重新加载扩展名一致",
        )
        check(reloaded.remote_dir == cfg.remote_dir, "配置保存后远程目录一致")

    print("== 6. 主题切换与图标重新着色 ==")
    settings_icon_light = _icon_bytes(settings.reload_button)
    cancel_icon_light = _icon_bytes(page.cancel_button)

    # 模拟用户已编辑设置但尚未点「保存设置」
    settings.extensions_edit.setPlainText(".unsaved-ext")
    settings.whitelist_edit.setPlainText(r"D:\Games => all")

    for name in ("dark", "light"):
        try:
            ThemeManager.instance().set_theme(name)
            app.processEvents()
            ok = True
        except Exception:
            traceback.print_exc()
            ok = False
        check(ok, f"切换到{name}主题不报错")
        _render(window, f"settings-{name}.png")

    ThemeManager.instance().set_theme("dark")
    app.processEvents()
    check(
        _icon_bytes(settings.reload_button) != settings_icon_light,
        "深色主题下设置页图标重新着色",
    )
    check(
        _icon_bytes(page.cancel_button) != cancel_icon_light,
        "深色主题下取消按钮图标重新着色",
    )
    check(not page.cancel_button.icon().isNull(), "深色主题下取消按钮图标非空")
    check(
        settings.theme_combo.currentData() == "dark",
        "顶栏切换深色后设置页主题下拉框同步",
    )
    check(
        settings.extensions_edit.toPlainText() == ".unsaved-ext",
        "主题切换不覆盖未保存的扩展名",
    )
    check(
        settings.whitelist_edit.toPlainText() == r"D:\Games => all",
        "主题切换不覆盖未保存的白名单",
    )

    # 采样扩展名输入框背景，确认暗色主题下不再是系统白底
    image = window.grab().toImage()
    edit = settings.extensions_edit
    origin = edit.mapTo(window, QPoint(0, 0))
    sample = image.pixelColor(origin.x() + 30, origin.y() + edit.height() - 15)
    check(
        sample.lightness() < 120,
        f"深色主题下扩展名输入框为深色背景（{sample.name()}）",
    )

    ThemeManager.instance().set_theme("light")
    app.processEvents()
    check(
        _icon_bytes(settings.reload_button) == settings_icon_light,
        "切回浅色主题后设置页图标恢复原色",
    )
    check(
        settings.theme_combo.currentData() == "light",
        "切回浅色后设置页主题下拉框同步",
    )
    check(
        settings.extensions_edit.toPlainText() == ".unsaved-ext",
        "切回浅色后未保存的扩展名仍在",
    )

    print("== 7. 真实流程：扫描 → 备份（关闭上传） ==")
    with tempfile.TemporaryDirectory(prefix="gsb-smoke-") as tmp:
        base = Path(tmp)
        games_root = base / "games"
        for name, files in {
            "GameAlpha": {"saves/a.sav": 4096, "saves/b.sav": 2048},
            "GameBeta": {"data/profile.sav": 8192},
            "GameGamma": {"readme.txt": 128},
        }.items():
            for rel, size in files.items():
                target = games_root / name / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"x" * size)

        window._switch_page(0)  # noqa: SLF001
        app.processEvents()

        page.folder_edit.setText(str(games_root))
        page.scan_button.click()
        check(
            _wait_until(app, lambda: page._scan_worker is None, 20),  # noqa: SLF001
            "扫描线程在 20 秒内结束",
        )
        app.processEvents()

        check(page.table.rowCount() == 3, f"扫描得到 3 个目录（实际 {page.table.rowCount()}）")
        ready = [g for g in page._games if g.status is GameStatus.READY]
        check(len(ready) == 2, f"其中 2 个目录有存档（实际 {len(ready)}）")
        check(
            page.table_stack.currentIndex() == 0,
            "扫描后表格视图处于显示状态",
        )

        page._select_all()  # noqa: SLF001
        page.upload_check.setChecked(False)
        page.work_edit.setText(str(base / "work"))
        page.log_button.setChecked(True)
        page.start_button.click()

        check(
            _wait_until(app, lambda: page._backup_worker is None, 30),  # noqa: SLF001
            "备份线程在 30 秒内结束",
        )
        app.processEvents()

        check(page.percent_label.text() == "100%", f"进度显示 100%（实际 {page.percent_label.text()}）")
        check(page.stage_label.text() == "备份完成", f"阶段显示备份完成（实际 {page.stage_label.text()}）")

        log_text = page.log_view.toPlainText()
        check("开始备份" in log_text, "日志记录了任务开始")
        check("备份完成" in log_text or "✓" in log_text, "日志记录了任务完成")
        check("http" not in log_text.lower(), "关闭上传后日志中没有上传请求")

        work_dir = base / "work"
        leftovers = list(work_dir.glob("run-*")) if work_dir.is_dir() else []
        check(not leftovers, f"本次任务的临时目录已清理（残留 {len(leftovers)} 个）")
        _render(window, "backup-completed.png")

        print("== 8. 取消后按钮状态复位 ==")
        page._set_running(True)  # noqa: SLF001
        app.processEvents()
        check(
            not page.start_button.isEnabled() and page.cancel_button.isEnabled(),
            "运行中：开始按钮禁用、取消按钮可用",
        )
        page._on_backup_cancelled()  # noqa: SLF001
        app.processEvents()
        check(
            page.start_button.isEnabled() and not page.cancel_button.isEnabled(),
            "取消后：开始按钮恢复、取消按钮禁用",
        )
        check(page.stage_label.text() == "已取消", "取消后阶段显示已取消")

    print("== 9. 授权页交互（不真正打开浏览器） ==")
    import game_save_file_handle.ui.pages.auth_page as auth_module

    opened: list[str] = []
    original_open = auth_module.webbrowser.open
    auth_module.webbrowser.open = lambda url: opened.append(url) or True
    try:
        window._switch_page(1)  # noqa: SLF001
        app.processEvents()
        window.auth_page._open_authorize_page()  # noqa: SLF001
        app.processEvents()
        check(window.auth_page.code_edit.isEnabled(), "点击后授权码输入框已启用")
        check(window.auth_page.submit_button.isEnabled(), "点击后「完成授权」按钮已启用")
        check(
            bool(opened) and "openapi.baidu.com" in opened[0],
            f"生成了百度授权链接（{opened[0][:48] + '…' if opened else '无'}）",
        )
    finally:
        auth_module.webbrowser.open = original_open

    print("== 10. 设置页白名单目录插入 ==")
    from game_save_file_handle.core.config import parse_whitelist

    window._switch_page(2)  # noqa: SLF001
    app.processEvents()
    check(hasattr(settings, "add_whitelist_button"), "白名单卡片存在「添加目录」按钮")

    with tempfile.TemporaryDirectory(prefix="gsb-whitelist-") as tmp_dir:
        picked = str(Path(tmp_dir))
        original_picker = QFileDialog.getExistingDirectory
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: picked)
        try:
            settings.whitelist_edit.setPlainText("")
            settings.add_whitelist_button.click()
            app.processEvents()
            # 再点一次，验证不会写入重复行
            settings.add_whitelist_button.click()
            app.processEvents()
        finally:
            QFileDialog.getExistingDirectory = original_picker

        parsed = parse_whitelist(settings.whitelist_edit.toPlainText())
        check(picked in parsed, "「添加目录」已把所选目录写入白名单")
        check(parsed.get(picked) == ["all"], "插入的目录默认为全部放行")
        check(
            settings.whitelist_edit.toPlainText().count(picked) == 1,
            "重复添加同一目录不会写入两次",
        )

    # 不调用 close()，避免向用户真实配置/注册表写数据
    window.hide()
    window.deleteLater()
    app.processEvents()

    print()
    if _failures:
        print(f"冒烟测试失败 {len(_failures)} 项：")
        for item in _failures:
            print(f"  - {item}")
        return 1
    print("冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
