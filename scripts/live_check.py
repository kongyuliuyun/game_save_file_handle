"""真实百度账号联调自检。

前置条件：先在程序的「授权」页完成一次 OAuth 授权
（或本机已有 bypy 的 ``~/.bypy/bypy.json`` 令牌）。

用法::

    python scripts/live_check.py            # 只读：令牌、账号信息、网盘配额
    python scripts/live_check.py --upload   # 再上传 1MB 测试文件并核对远端大小，完成后删除
    python scripts/live_check.py --chunked  # 用 1MB 文件强制走 XPAN 分片接口，验证分片链路

脚本不会读取或打印完整的 access_token；所有测试文件都放在
``/apps/bypy/game-save-backup/live-check/`` 下，并在结束时删除。
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _path in (str(ROOT), str(ROOT.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from game_save_file_handle.cloud.auth import TokenStore  # noqa: E402
from game_save_file_handle.cloud.baidu_pan import BaiduPanClient  # noqa: E402
from game_save_file_handle.core.errors import AppError  # noqa: E402
from game_save_file_handle.core.progress import TaskContext  # noqa: E402
from game_save_file_handle.utils.fmt import human_size  # noqa: E402

REMOTE_DIR = "/apps/bypy/game-save-backup/live-check"
_MIB = 1024 * 1024


def _mask(text: str) -> str:
    """只显示令牌首尾，避免把凭据打印到终端历史里。"""
    if len(text) <= 12:
        return "*" * len(text)
    return f"{text[:6]}…{text[-4:]}"


def _prepare_store() -> TokenStore | None:
    """加载令牌；临近过期时尝试自动刷新。"""
    print("== 1. 令牌 ==")
    store = TokenStore()
    if not store.has_token():
        print("  [失败] 未找到授权令牌")
        print("  请先在程序「授权」页完成登录，或确认 %USERPROFILE%\\.bypy\\bypy.json 存在。")
        return None

    try:
        token = store.require()
    except AppError as exc:
        print(f"  [失败] 令牌不可用：{exc.message}")
        return None

    print(f"  [通过] access_token：{_mask(token.access_token)}")
    print(f"  refresh_token：{'有' if token.refresh_token else '无'}")
    if token.expires_at:
        print(f"  剩余有效期：约 {token.expires_in / 3600:.1f} 小时")
    else:
        print("  有效期：服务端未返回（按长期有效处理）")
    return store


def _check_account(client: BaiduPanClient) -> bool:
    print("== 2. 账号与配额 ==")
    try:
        info = client.get_user_info()
    except AppError as exc:
        print(f"  [失败] 获取账号信息失败：{exc.message}")
        return False

    name = info.get("netdisk_name") or info.get("baidu_name") or "（未返回）"
    print(f"  [通过] 账号：{name}")

    try:
        used, total = client.get_quota()
    except AppError as exc:
        print(f"  [失败] 获取配额失败：{exc.message}")
        return False

    print(f"  [通过] 空间：已用 {human_size(used)}，总容量 {human_size(total)}")
    return True


def _fill_file(path: Path, size: int) -> None:
    """生成固定内容的测试文件；大文件用稀疏方式创建，避免占满磁盘。"""
    if size >= 64 * _MIB:
        with open(path, "wb") as stream:
            stream.seek(size - 1)
            stream.write(b"\0")
        return

    block = bytes(range(256)) * 4096  # 1 MiB
    with open(path, "wb") as stream:
        remaining = size
        while remaining > 0:
            piece = block[: min(len(block), remaining)]
            stream.write(piece)
            remaining -= len(piece)


def _upload_once(
    client: BaiduPanClient,
    size: int,
    label: str,
    *,
    filename: str | None = None,
    force_chunked: bool = False,
) -> bool:
    """上传一个测试文件，核对远端大小与目录列表，最后删除。"""
    print(f"== {label}（{human_size(size)}） ==")
    with tempfile.TemporaryDirectory(prefix="gsb-live-") as tmp:
        path = Path(tmp) / (filename or f"live-check-{size}.bin")
        _fill_file(path, size)
        # 写入随机头部，避免命中网盘秒传而跳过真正的分片上传
        with open(path, "r+b") as stream:
            stream.write(os.urandom(16))

        last = {"at": 0.0, "sent": 0}

        def _on_progress(sent: int) -> None:
            now = time.monotonic()
            if now - last["at"] >= 1.0 or sent >= size:
                last["at"] = now
                last["sent"] = sent
                print(
                    f"\r  已发送 {human_size(sent)} / {human_size(size)}",
                    end="",
                    flush=True,
                )

        remote_path = f"{REMOTE_DIR}/{path.name}"
        started = time.monotonic()
        try:
            result = client.upload(
                path,
                REMOTE_DIR,
                TaskContext(),
                on_progress=_on_progress,
                force_chunked=force_chunked,
            )
            elapsed = max(0.001, time.monotonic() - started)
            print()
            if last["sent"] < size:
                print(f"  [失败] 进度回调最终值 {human_size(last['sent'])} ≠ 文件大小")
                return False
            print(f"  [通过] 进度回调到达 100%，平均 {human_size(size / elapsed)}/s")

            if result.size != size:
                print(f"  [失败] 远端大小 {result.size} ≠ 本地 {size}")
                return False
            print(f"  [通过] 远端大小一致：{human_size(result.size)}")

            names = {
                str(item.get("server_filename") or "")
                for item in client.list_dir(REMOTE_DIR)
            }
            if path.name not in names:
                print(f"  [失败] 远端目录中未找到 {path.name}")
                return False
            print("  [通过] 远端目录列表校验通过")
            return True
        except AppError as exc:
            print()
            print(f"  [失败] 上传出错：{exc.message}")
            if exc.detail:
                print(f"  详情：{exc.detail}")
            return False
        finally:
            try:
                client.delete(remote_path)
                print("  测试文件已删除")
            except AppError as exc:
                print(f"  删除测试文件失败，请手动清理 {remote_path}：{exc.message}")
            except Exception as exc:  # 清理失败不影响主流程
                print(f"  删除测试文件失败，请手动清理 {remote_path}：{exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="真实百度账号联调自检")
    parser.add_argument(
        "--upload",
        action="store_true",
        help="上传 1MB 测试文件，验证 PCS 单次上传（完成后自动删除）",
    )
    parser.add_argument(
        "--chunked",
        action="store_true",
        help="用 1MB 文件强制走 XPAN 分片接口，验证 precreate/superfile2/create 链路",
    )
    args = parser.parse_args()

    store = _prepare_store()
    if store is None:
        return 1

    failures = 0
    client = BaiduPanClient(store)
    try:
        if not _check_account(client):
            failures += 1

        if args.upload:
            if not _upload_once(client, 1 * _MIB, "3. PCS 单次上传"):
                failures += 1

        if args.chunked:
            if not _upload_once(
                client,
                1 * _MIB,
                "4. XPAN 分片上传（强制分片）",
                filename="live-check-chunked.bin",
                force_chunked=True,
            ):
                failures += 1
    finally:
        client.close()

    print()
    if failures:
        print(f"联调存在 {failures} 项失败，请保留上面的输出排查。")
        return 1
    print("联调检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
