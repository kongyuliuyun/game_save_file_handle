"""上传客户端测试：用本地 HTTP 服务器模拟百度 PCS 接口。

验证目标（对应「进度条虚假」的修复）：

1. 服务端实际收到的文件内容与原文件逐字节一致；
2. 进度回调单调不减，且最终值等于文件大小；
3. 上传中途取消能立刻中断，不会把整个文件发完。

运行：``python tests/test_upload.py``
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_PARENT = PROJECT_ROOT.parent
for _path in (str(PACKAGE_PARENT), str(PROJECT_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from game_save_file_handle.cloud import baidu_pan
from game_save_file_handle.cloud.auth import Token
from game_save_file_handle.core.errors import TaskCancelled
from game_save_file_handle.core.progress import CancellationToken, TaskContext


class _FakeStore:
    def require(self, auto_refresh: bool = True) -> Token:
        return Token(access_token="fake-token", refresh_token="fake-refresh")

    def force_refresh(self) -> Token:
        return self.require()


class _Recorder:
    """记录服务端收到的请求与已创建的目录。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.dirs: set[str] = {"/"}
        self.lock = threading.Lock()

    def add(self, item: dict) -> None:
        with self.lock:
            self.requests.append(item)


class _Handler(BaseHTTPRequestHandler):
    recorder: _Recorder

    def log_message(self, *args) -> None:  # 静默，避免污染测试输出
        return

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        method = (query.get("method") or [""])[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)

        if method == "create":
            # ensure_dir 把 path 放在表单 body 里
            fields = parse_qs(raw.decode("utf-8", "replace"))
            path = (fields.get("path") or [""])[0]
            self.recorder.add({"method": "create", "path": path})
            self.recorder.dirs.add(path)
            payload = {"errno": 0, "path": path}
        elif method == "list":
            # ensure_dir 先查询目录是否存在；path 在 URL 的 dir 参数里
            path = (query.get("dir") or [""])[0]
            self.recorder.add({"method": "list", "path": path})
            if path in self.recorder.dirs:
                payload = {"errno": 0, "list": []}
            else:
                payload = {"errno": -9}
        else:
            file_bytes = _extract_file_part(raw)
            self.recorder.add(
                {
                    "method": method,
                    "path": (query.get("path") or [""])[0],
                    "content_length": length,
                    "file_bytes": file_bytes,
                }
            )
            payload = {
                "path": (query.get("path") or [""])[0],
                "size": len(file_bytes),
                "fs_id": "42",
                "md5": hashlib.md5(file_bytes).hexdigest(),
            }

        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # 客户端主动取消时会断开连接，属于预期行为
            pass


def _extract_file_part(raw: bytes) -> bytes:
    """从 multipart 请求体中取出文件字段内容。"""
    marker = raw.find(b"\r\n\r\n")
    if marker < 0:
        return b""
    start = marker + 4
    end = raw.rfind(b"\r\n--")
    if end < start:
        end = len(raw)
    return raw[start:end]


class UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.recorder = _Recorder()
        handler = type("BoundHandler", (_Handler,), {"recorder": cls.recorder})
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls._originals = {
            "_PCS_UPLOAD": baidu_pan._PCS_UPLOAD,
            "_XPAN_FILE": baidu_pan._XPAN_FILE,
        }
        baidu_pan._PCS_UPLOAD = f"{base}/rest/2.0/pcs/file"
        baidu_pan._XPAN_FILE = f"{base}/rest/2.0/xpan/file"

    @classmethod
    def tearDownClass(cls) -> None:
        baidu_pan._PCS_UPLOAD = cls._originals["_PCS_UPLOAD"]
        baidu_pan._XPAN_FILE = cls._originals["_XPAN_FILE"]
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gsb-upload-"))
        with self.recorder.lock:
            self.recorder.requests.clear()
            self.recorder.dirs = {"/"}

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _client(self) -> baidu_pan.BaiduPanClient:
        return baidu_pan.BaiduPanClient(store=_FakeStore(), retries=0)

    def test_upload_sends_exact_bytes_and_reports_real_progress(self) -> None:
        payload = bytes(range(256)) * 4096  # 1 MiB
        source = self.tmp / "slot.sav"
        source.write_bytes(payload)

        seen: list[int] = []
        with self._client() as client:
            result = client.upload(
                source,
                "/apps/bypy/game-save-backup",
                TaskContext(),
                on_progress=seen.append,
            )

        self.assertEqual(result.path, "/apps/bypy/game-save-backup/slot.sav")
        self.assertEqual(result.size, len(payload))

        # 前一个取消用例的请求可能在服务器线程里收尾，按路径过滤避免串扰
        uploads = [
            r for r in self.recorder.requests
            if r["method"] == "upload" and r["path"].endswith("/slot.sav")
        ]
        self.assertEqual(len(uploads), 1)
        received = uploads[0]["file_bytes"]
        self.assertEqual(len(received), len(payload), "服务端收到的字节数必须等于文件大小")
        self.assertEqual(hashlib.md5(received).hexdigest(), hashlib.md5(payload).hexdigest())

        self.assertTrue(seen, "必须上报进度")
        self.assertEqual(seen, sorted(seen), "进度必须单调不减")
        self.assertEqual(seen[-1], len(payload), "最终进度必须等于文件实际字节数")

    def test_content_length_matches_actual_body(self) -> None:
        source = self.tmp / "a.sav"
        source.write_bytes(b"x" * 5000)

        with self._client() as client:
            client.upload(source, "/apps/bypy/d", TaskContext())

        uploads = [
            r for r in self.recorder.requests
            if r["method"] == "upload" and r["path"].endswith("/a.sav")
        ]
        self.assertEqual(len(uploads), 1)
        upload = uploads[0]
        # Content-Length 必须精确覆盖 multipart 头 + 文件 + 尾部
        self.assertGreater(upload["content_length"], len(upload["file_bytes"]))
        self.assertLess(upload["content_length"], len(upload["file_bytes"]) + 1024)

    def test_creates_remote_directories(self) -> None:
        source = self.tmp / "b.sav"
        source.write_bytes(b"y" * 10)

        with self._client() as client:
            client.upload(source, "/apps/bypy/game-save-backup", TaskContext())

        created = [
            r["path"]
            for r in self.recorder.requests
            if r["method"] == "create"
        ]
        self.assertIn("/apps", created)
        self.assertIn("/apps/bypy", created)
        self.assertIn("/apps/bypy/game-save-backup", created)

    def test_cancel_interrupts_before_finishing(self) -> None:
        source = self.tmp / "big.sav"
        source.write_bytes(b"z" * (8 * 1024 * 1024))  # 8 MiB，需要多次读取

        token = CancellationToken()
        seen: list[int] = []

        def _on_progress(sent: int) -> None:
            seen.append(sent)
            if sent >= 1024 * 1024:
                token.cancel()

        with self._client() as client:
            with self.assertRaises(TaskCancelled):
                client.upload(
                    source,
                    "/apps/bypy/d",
                    TaskContext(token=token),
                    on_progress=_on_progress,
                )

        # 取消前不可能把全部 8 MiB 上报完
        self.assertLess(max(seen), len(source.read_bytes()))

    def test_empty_file_rejected(self) -> None:
        source = self.tmp / "empty.sav"
        source.write_bytes(b"")
        with self._client() as client:
            from game_save_file_handle.core.errors import UploadError

            with self.assertRaises(UploadError):
                client.upload(source, "/apps/bypy/d", TaskContext())


class MultipartBodyTests(unittest.TestCase):
    def test_length_matches_streamed_payload(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="gsb-body-"))
        try:
            source = tmp / "x.bin"
            source.write_bytes(b"abc" * 1000)
            body = baidu_pan._MultipartBody(source, "file", TaskContext(), lambda _n: None)
            streamed = b"".join(body)
            self.assertEqual(len(streamed), len(body))
            self.assertIn(b"abc", streamed)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
