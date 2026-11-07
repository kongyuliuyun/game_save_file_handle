"""核心业务逻辑测试：扫描、白名单、复制、压缩、流水线。

使用标准库 ``unittest``，无需安装额外依赖：

    python tests/test_core.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_PARENT = PROJECT_ROOT.parent
for _path in (str(PACKAGE_PARENT), str(PROJECT_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from game_save_file_handle.core import config as config_module
from game_save_file_handle.core.backup import copy_saves, safe_filename
from game_save_file_handle.core.config import (
    AppConfig,
    format_whitelist,
    load_config,
    parse_whitelist,
)
from game_save_file_handle.utils import paths
from game_save_file_handle.core.errors import AppError, TaskCancelled
from game_save_file_handle.core.models import GameStatus
from game_save_file_handle.core.packager import pack_artifacts
from game_save_file_handle.core.pipeline import BackupPipeline
from game_save_file_handle.core.progress import (
    CancellationToken,
    ProgressEvent,
    Stage,
    TaskContext,
)
from game_save_file_handle.core.scanner import (
    discover_games,
    scan_games,
    whitelist_allows,
)


def _write(path: Path, payload: bytes = b"data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


class BaseCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="gsb-test-"))
        self.root = self._tmp / "Games"
        self._build_games()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _build_games(self) -> None:
        root = self.root
        # 游戏 A：常见结构，子目录也有存档
        _write(root / "GameA" / "GameA.exe", b"MZ")
        _write(root / "GameA" / "saves" / "slot1.sav", b"1" * 100)
        _write(root / "GameA" / "saves" / "slot2.sav", b"2" * 200)
        _write(root / "GameA" / "saves" / "profile" / "extra.save", b"3" * 300)
        # 游戏 B：存档直接位于根目录（旧版会整体跳过）
        _write(root / "GameB" / "GameB.exe", b"MZ")
        _write(root / "GameB" / "root.sav", b"4" * 400)
        # 游戏 C：没有存档
        _write(root / "GameC" / "data.bin", b"5" * 50)

    def scanned(self) -> list:
        games = discover_games(self.root)
        scan_games(games, {".sav", ".save"}, TaskContext())
        return games


class DiscoverTests(BaseCase):
    def test_lists_subdirectories(self) -> None:
        self.assertEqual([g.name for g in discover_games(self.root)], ["GameA", "GameB", "GameC"])

    def test_single_game_directory_returns_self(self) -> None:
        games = discover_games(self.root / "GameA")
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].name, "GameA")


class ScanTests(BaseCase):
    def test_collects_saves_including_root_level(self) -> None:
        games = self.scanned()
        by_name = {g.name: g for g in games}

        self.assertIs(by_name["GameA"].status, GameStatus.READY)
        self.assertEqual(by_name["GameA"].save_count, 3)
        self.assertEqual(by_name["GameA"].total_bytes, 600)

        # 关键回归：根层存档不再被跳过
        self.assertIs(by_name["GameB"].status, GameStatus.READY)
        self.assertEqual(by_name["GameB"].save_count, 1)
        self.assertIs(by_name["GameC"].status, GameStatus.NO_SAVES)

    def test_progress_is_monotonic(self) -> None:
        events: list[ProgressEvent] = []
        games = discover_games(self.root)
        scan_games(games, {".sav", ".save"}, TaskContext(emit=events.append))

        fractions = [e.fraction for e in events if e.fraction is not None]
        self.assertTrue(fractions, "扫描应至少上报一次可计算的进度")
        self.assertEqual(fractions, sorted(fractions), "进度必须单调不减")
        self.assertEqual(fractions[-1], 1.0)


class WhitelistTests(BaseCase):
    def test_default_allows_everything(self) -> None:
        for game in discover_games(self.root):
            self.assertTrue(whitelist_allows(game, {}))
            self.assertTrue(whitelist_allows(game, None))

    def test_filters_by_name(self) -> None:
        by_name = {g.name: g for g in discover_games(self.root)}
        whitelist = {str(self.root): ["GameA"]}
        self.assertTrue(whitelist_allows(by_name["GameA"], whitelist))
        self.assertFalse(whitelist_allows(by_name["GameB"], whitelist))

    def test_all_keyword(self) -> None:
        whitelist = {str(self.root): ["all"]}
        for game in discover_games(self.root):
            self.assertTrue(whitelist_allows(game, whitelist))

    def test_parse_and_format_roundtrip(self) -> None:
        text = """
        # 注释行会被忽略
        D:\\Games => 游戏A, 游戏B
        default => all
        空名单 =
        """
        parsed = parse_whitelist(text)
        self.assertEqual(parsed["D:\\Games"], ["游戏A", "游戏B"])
        self.assertEqual(parsed["default"], ["all"])
        self.assertEqual(parsed["空名单"], [])

        # 空文本表示不做过滤
        self.assertEqual(parse_whitelist("   \n# 只有注释"), {})

        formatted = format_whitelist(parsed)
        self.assertIn("D:\\Games => 游戏A, 游戏B", formatted)
        self.assertIn("default => all", formatted)
        # 空名单在界面上显示为 all，语义都是「全部放行」
        self.assertIn("空名单 => all", formatted)

        reparsed = parse_whitelist(formatted)
        self.assertEqual(reparsed["D:\\Games"], ["游戏A", "游戏B"])
        self.assertEqual(reparsed["default"], ["all"])
        self.assertEqual(reparsed["空名单"], ["all"])


class CopyTests(BaseCase):
    def test_preserves_structure_and_isolates_games(self) -> None:
        games = self.scanned()
        destination = self._tmp / "backup"
        artifacts = copy_saves([g for g in games if g.save_files], destination, TaskContext())

        self.assertEqual({a.directory.name for a in artifacts}, {"GameA", "GameB"})
        self.assertTrue((destination / "GameA" / "saves" / "slot1.sav").is_file())
        self.assertTrue((destination / "GameA" / "saves" / "profile" / "extra.save").is_file())
        # 根层存档落在游戏自己的目录，不会和别的游戏混在一起
        self.assertTrue((destination / "GameB" / "root.sav").is_file())

    def test_progress_reaches_100_percent(self) -> None:
        games = self.scanned()
        events: list[ProgressEvent] = []
        copy_saves(
            [g for g in games if g.save_files],
            self._tmp / "backup",
            TaskContext(emit=events.append),
        )
        fractions = [e.fraction for e in events if e.fraction is not None]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions[-1], 1.0)


class PackTests(BaseCase):
    def test_creates_valid_zip_per_game(self) -> None:
        games = self.scanned()
        ctx = TaskContext()
        artifacts = copy_saves([g for g in games if g.save_files], self._tmp / "backup", ctx)
        zips = pack_artifacts(artifacts, self._tmp / "zips", TaskContext())

        self.assertEqual(len(zips), 2)
        for item in zips:
            self.assertTrue(item.path.is_file())
            with zipfile.ZipFile(item.path) as archive:
                self.assertTrue(archive.namelist())

        with zipfile.ZipFile(self._tmp / "zips" / "GameA.zip") as archive:
            names = set(archive.namelist())
        self.assertIn("saves/slot1.sav", names)
        self.assertIn("saves/profile/extra.save", names)


class PipelineTests(BaseCase):
    def test_end_to_end_without_upload(self) -> None:
        work = self._tmp / "work"
        config = AppConfig(backup_root=str(work))
        result = BackupPipeline(config, TaskContext(), client=None).run(self.scanned())

        self.assertEqual(result.report.games_backed_up, 2)
        self.assertEqual(result.report.files_total, 4)
        self.assertTrue(result.report.success)
        self.assertEqual(len(result.zips), 2)
        # 任务结束后临时目录必须被清理干净
        self.assertTrue(work.is_dir())
        self.assertEqual(list(work.iterdir()), [])

    def test_keeps_local_copy_when_requested(self) -> None:
        keep = self._tmp / "keep"
        config = AppConfig(
            backup_root=str(self._tmp / "work"),
            zip_root=str(keep),
            keep_local_backup=True,
        )
        result = BackupPipeline(config, TaskContext(), client=None).run(self.scanned())

        self.assertEqual(result.kept_dir, keep)
        self.assertEqual(sorted(p.name for p in keep.glob("*.zip")), ["GameA.zip", "GameB.zip"])

    def test_never_deletes_configured_parent(self) -> None:
        """回归：旧版会 rmtree 用户配置的整个备份目录。"""
        work = self._tmp / "work"
        work.mkdir()
        sentinel = work / "important.txt"
        sentinel.write_text("别删我", encoding="utf-8")

        BackupPipeline(AppConfig(backup_root=str(work)), TaskContext(), client=None).run(
            self.scanned()
        )
        self.assertTrue(sentinel.exists(), "父目录中的用户文件必须保留")

    def test_cancel_cleans_up(self) -> None:
        token = CancellationToken()
        ctx = TaskContext(token=token)

        def _cancel_on_copy(event: ProgressEvent) -> None:
            if event.stage is Stage.COPY:
                token.cancel()

        ctx.emit = _cancel_on_copy
        work = self._tmp / "work"
        with self.assertRaises(TaskCancelled):
            BackupPipeline(AppConfig(backup_root=str(work)), ctx, client=None).run(self.scanned())
        self.assertEqual(list(work.iterdir()), [], "取消后也必须清理临时文件")

    def test_requires_selection(self) -> None:
        with self.assertRaises(AppError):
            BackupPipeline(AppConfig(), TaskContext(), client=None).run([])

    def test_upload_progress_is_monotonic(self) -> None:
        """用一个假客户端验证上传阶段整体进度真实且单调。"""

        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[int] = []

            def upload(self, local_path, remote_dir, ctx, on_progress=None):
                size = local_path.stat().st_size
                for step in range(1, 6):
                    if on_progress:
                        on_progress(size * step // 5)
                self.calls.append(size)
                return f"{remote_dir}/{local_path.name}"

        events: list[ProgressEvent] = []
        # 显式使用串行模式，保持本用例对「单线程进度」的断言意图
        config = AppConfig(backup_root=str(self._tmp / "work"), upload_threads=1)
        client = FakeClient()
        BackupPipeline(config, TaskContext(emit=events.append), client=client).run(self.scanned())

        self.assertEqual(len(client.calls), 2)
        upload_events = [e for e in events if e.stage is Stage.UPLOAD]
        fractions = [e.fraction for e in upload_events if e.fraction is not None]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions[-1], 1.0)

    def test_upload_failure_does_not_abort_other_zips(self) -> None:
        class FlakyClient:
            def __init__(self) -> None:
                self.calls = 0

            def upload(self, local_path, remote_dir, ctx, on_progress=None):
                from game_save_file_handle.core.errors import UploadError

                self.calls += 1
                if self.calls == 1:
                    raise UploadError("模拟失败")
                return f"{remote_dir}/{local_path.name}"

        client = FlakyClient()
        config = AppConfig(backup_root=str(self._tmp / "work"), upload_threads=1)
        result = BackupPipeline(config, TaskContext(), client=client).run(self.scanned())

        self.assertEqual(client.calls, 2)
        self.assertTrue(result.report.errors)
        self.assertEqual(len(result.report.uploaded), 1)

    def test_parallel_upload_uses_multiple_threads(self) -> None:
        """并发上传：峰值并发 > 1，进度仍单调且最终到 100%。"""

        class ConcurrentClient:
            def __init__(self) -> None:
                self._lock = threading.Lock()
                self.active = 0
                self.peak = 0
                self.calls: list[str] = []

            def clone(self):
                return self

            def upload(self, local_path, remote_dir, ctx, on_progress=None):
                size = local_path.stat().st_size
                with self._lock:
                    self.active += 1
                    self.peak = max(self.peak, self.active)
                    self.calls.append(local_path.name)
                try:
                    for step in range(1, 6):
                        time.sleep(0.006)
                        if on_progress:
                            on_progress(size * step // 5)
                finally:
                    with self._lock:
                        self.active -= 1
                return f"{remote_dir}/{local_path.name}"

        events: list[ProgressEvent] = []
        client = ConcurrentClient()
        config = AppConfig(
            backup_root=str(self._tmp / "work"),
            upload_threads=2,
        )
        result = BackupPipeline(config, TaskContext(emit=events.append), client=client).run(
            self.scanned()
        )

        self.assertEqual(len(client.calls), 2)
        self.assertGreaterEqual(client.peak, 2, "两个压缩包应同时上传")
        self.assertEqual(len(result.report.uploaded), 2)

        upload_events = [e for e in events if e.stage is Stage.UPLOAD]
        fractions = [e.fraction for e in upload_events if e.fraction is not None]
        self.assertTrue(fractions)
        self.assertEqual(fractions, sorted(fractions), "并发进度必须单调不减")
        self.assertEqual(fractions[-1], 1.0)


class FilenameTests(unittest.TestCase):
    def test_strips_illegal_chars(self) -> None:
        self.assertEqual(safe_filename('a/b:c*d?'), "a_b_c_d_")
        self.assertEqual(safe_filename("CON"), "_CON")
        self.assertEqual(safe_filename("   "), "unnamed")


class ConfigPersistenceTests(unittest.TestCase):
    """回归：打包版保存设置后重启恢复默认。

    根因是旧逻辑把配置写进 PyInstaller 的 ``sys._MEIPASS`` 临时目录，
    退出即丢失；这里验证写入目标始终是持久化位置。
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="gsb-config-"))
        self.exe_dir = self._tmp / "app"
        self.exe_dir.mkdir()
        self.user_config = self._tmp / "roaming" / "GameSaveBackup" / "config.yaml"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _patch_frozen(self, *, frozen: bool = True):
        return (
            mock.patch.object(paths, "app_root", return_value=self.exe_dir),
            mock.patch.object(paths, "is_frozen", return_value=frozen),
            mock.patch.object(paths, "user_config_path", return_value=self.user_config),
        )

    def test_frozen_without_config_targets_exe_dir(self) -> None:
        """打包版首次保存应落在 exe 同目录，而不是 _MEIPASS。"""
        app_root_patch, frozen_patch, user_patch = self._patch_frozen()
        with app_root_patch, frozen_patch, user_patch:
            self.assertEqual(paths.config_path(), self.exe_dir / "config.yaml")

    def test_frozen_uses_existing_user_config(self) -> None:
        """exe 目录没有配置时，读取已存在的用户级配置。"""
        self.user_config.parent.mkdir(parents=True)
        self.user_config.write_text("theme: dark\n", encoding="utf-8")
        app_root_patch, frozen_patch, user_patch = self._patch_frozen()
        with app_root_patch, frozen_patch, user_patch:
            self.assertEqual(paths.config_path(), self.user_config)

    def test_dev_prefers_writable_project_config(self) -> None:
        """开发环境仍使用项目内可读写的 config/config.yaml。"""
        project = self._tmp / "project"
        bundled = project / "config" / "config.yaml"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("theme: light\n", encoding="utf-8")
        with mock.patch.object(paths, "app_root", return_value=project), \
                mock.patch.object(paths, "is_frozen", return_value=False), \
                mock.patch.object(paths, "user_config_path", return_value=self.user_config):
            self.assertEqual(paths.config_path(), bundled)

    def test_frozen_save_and_reload_roundtrip(self) -> None:
        """打包版保存后重新加载，主题与扩展名必须保留。"""
        target = self.exe_dir / "config.yaml"
        bundled = self._tmp / "_MEIPASS" / "config" / "config.yaml"
        with mock.patch.object(config_module, "config_path", return_value=target), \
                mock.patch.object(config_module, "is_frozen", return_value=True), \
                mock.patch.object(config_module, "resource_path", return_value=bundled), \
                mock.patch.object(config_module, "user_config_path", return_value=self.user_config), \
                mock.patch.object(config_module, "app_root", return_value=self.exe_dir):
            config = AppConfig(theme="dark", save_extensions={".sav", ".custom"})
            saved = config.save()
            self.assertEqual(saved, target)
            self.assertTrue(target.is_file())

            reloaded = load_config()
            self.assertEqual(reloaded.theme, "dark")
            self.assertIn(".custom", reloaded.extensions())

    def test_save_falls_back_when_exe_dir_unwritable(self) -> None:
        """exe 目录不可写时回退到用户配置目录，而不是报错或丢失。"""
        blocked = self.exe_dir / "config.yaml"
        original_write = AppConfig._write

        def fake_write(target: Path, text: str) -> None:
            if target == blocked:
                raise PermissionError("拒绝访问")
            original_write(target, text)

        with mock.patch.object(config_module, "user_config_path", return_value=self.user_config), \
                mock.patch.object(AppConfig, "_write", side_effect=fake_write):
            saved = AppConfig(theme="dark").save(blocked)

        self.assertEqual(saved, self.user_config)
        self.assertTrue(self.user_config.is_file())
        self.assertEqual(load_config(self.user_config).theme, "dark")


if __name__ == "__main__":
    unittest.main(verbosity=2)
