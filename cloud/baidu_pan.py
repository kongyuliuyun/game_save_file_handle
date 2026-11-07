"""百度网盘上传客户端（PCS / XPAN 直连）。

为什么不继续用 bypy
-------------------
bypy 的 ``syncup`` 内部只做一次性大 POST，既不暴露进度回调，也无法在上传
中途取消，这正是旧版界面只能显示「转圈」的根因。

本模块直接调用百度网盘开放接口，并按 ``blocksize`` 分块产出请求体，
因此可以：

* 按**已发送字节数**上报真实进度；
* 在任意数据块边界检查取消信号；
* 对可恢复的网络错误自动重试，且重试不会让进度倒退。

接口选择
--------
* 小于 2GB：``pcs/file?method=upload``（bypy 同款，兼容性最好）；
* 大于 2GB：``xpan`` 分片上传（precreate → superfile2 → create）。

注意：``requests`` 的 ``files=`` 参数会把文件整体读进内存，所以这里手工
构造 multipart 请求体，用生成器流式发送。
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlencode

import requests

from ..core.errors import AuthError, NetworkError, QuotaExceeded, TaskCancelled, UploadError
from ..core.progress import Stage, TaskContext
from .auth import TokenStore

__all__ = ["RemoteFile", "BaiduPanClient"]

_USER_AGENT = "pan.baidu.com"
_PCS_UPLOAD = "https://c.pcs.baidu.com/rest/2.0/pcs/file"
_PCS_FILE = "https://pcs.baidu.com/rest/2.0/pcs/file"
_XPAN_FILE = "https://pan.baidu.com/rest/2.0/xpan/file"
_XPAN_SUPERFILE = "https://d.pcs.baidu.com/rest/2.0/pcs/superfile2"
_QUOTA_API = "https://pan.baidu.com/api/quota"
_NAS_API = "https://pan.baidu.com/rest/2.0/xpan/nas"

# 普通上传接口上限 2GB，超过改用分片上传
_SINGLE_UPLOAD_LIMIT = 2 * 1024 ** 3
_CHUNK_SIZE = 4 * 1024 ** 2      # 百度要求分片为 4MB
_MAX_PARTS = 1024                # 普通用户分片数量上限
_READ_BLOCK = 512 * 1024         # 每次从磁盘读取并发送的块大小

# 可重试的错误码（网络抖动、服务端繁忙、限流）
_RETRYABLE_ERRNO = {111, 31034, 31062, 31064}
_AUTH_ERRNO = {-6, 31045, 31061, 110}
_QUOTA_ERRNO = {-10, 112}

_ERRNO_MESSAGE = {
    -1: "服务端内部错误",
    -6: "身份验证失败，请重新授权",
    -7: "文件名非法",
    -8: "目标路径不存在",
    -9: "文件不存在",
    -10: "网盘空间不足",
    2: "参数错误",
    110: "访问被拒绝，授权可能已失效",
    111: "服务端繁忙",
    112: "网盘空间不足",
    31034: "请求过于频繁，请稍后再试",
    31062: "参数错误",
    31064: "参数错误",
    31066: "未授权，请重新登录百度网盘",
    31299: "文件名非法",
}


@dataclass(slots=True)
class RemoteFile:
    """一次成功上传的结果。"""

    path: str
    size: int
    fs_id: str = ""
    md5: str = ""


class _MultipartBody:
    """流式 multipart 请求体。

    同时实现 ``__len__`` 与 ``__iter__``，让 ``requests`` 采用
    ``Content-Length`` 而非 chunked 编码（百度接口对 chunked 支持不佳），
    并在逐块产出时回调进度、检查取消。
    """

    __slots__ = ("_head", "_tail", "_path", "_size", "_length", "_on_progress", "_ctx", "boundary")

    def __init__(
        self,
        path: Path,
        field_name: str,
        ctx: TaskContext,
        on_progress: Callable[[int], None],
    ) -> None:
        boundary = f"----GameSaveBoundary{uuid.uuid4().hex}"
        self.boundary = boundary
        self._path = path
        self._size = path.stat().st_size
        self._ctx = ctx
        self._on_progress = on_progress
        # 固定 filename="file"，避免中文文件名在 multipart 头里编码出错；
        # 真正的远端文件名由 path 参数决定。
        self._head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field_name}"; filename="file"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        self._tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
        self._length = len(self._head) + self._size + len(self._tail)

    def __len__(self) -> int:
        return self._length

    def __iter__(self) -> Iterator[bytes]:
        yield self._head
        sent = 0
        with open(self._path, "rb") as stream:
            while True:
                self._ctx.check()
                chunk = stream.read(_READ_BLOCK)
                if not chunk:
                    break
                sent += len(chunk)
                self._on_progress(sent)
                yield chunk
        yield self._tail

    @property
    def content_type(self) -> str:
        return f"multipart/form-data; boundary={self.boundary}"


class BaiduPanClient:
    """百度网盘上传客户端。

    Parameters
    ----------
    store:
        令牌仓库，负责自动刷新。
    timeout:
        单次请求的超时（连接, 读取）秒数。
    retries:
        网络类错误的最大重试次数。
    """

    def __init__(
        self,
        store: TokenStore | None = None,
        *,
        timeout: tuple[float, float] = (15.0, 90.0),
        retries: int = 3,
    ) -> None:
        self.store = store or TokenStore()
        self.timeout = timeout
        self.retries = retries
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})
        self._known_dirs: set[str] = set()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._session.close()

    def clone(self) -> "BaiduPanClient":
        """创建共享令牌、独立 HTTP 会话的客户端。

        ``requests.Session`` 不适合多个线程同时使用；并发上传时每个
        工作线程通过本方法拿到自己的会话。令牌仓库本身是线程安全的。
        """
        return BaiduPanClient(self.store, timeout=self.timeout, retries=self.retries)

    def __enter__(self) -> "BaiduPanClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 基础请求
    # ------------------------------------------------------------------

    def _token(self) -> str:
        return self.store.require().access_token

    def _sleep_backoff(self, attempt: int, ctx: TaskContext | None) -> None:
        """指数退避 + 抖动；退避期间仍然响应取消。"""
        delay = min(8.0, 0.8 * (2 ** attempt)) + random.uniform(0, 0.4)
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            if ctx is not None:
                ctx.check()
            time.sleep(0.1)

    def _post(
        self,
        url: str,
        *,
        params: dict[str, str],
        data: bytes | _MultipartBody | None = None,
        files: dict | None = None,
        ctx: TaskContext | None = None,
        tolerate_errno: set[int] | None = None,
    ) -> dict:
        """带重试的 POST，返回解析后的 JSON。"""
        tolerate = tolerate_errno or set()
        current_params = dict(params)
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            if ctx is not None:
                ctx.check()
            try:
                headers: dict[str, str] = {}
                if isinstance(data, _MultipartBody):
                    headers["Content-Type"] = data.content_type

                response = self._session.post(
                    url,
                    params=current_params,
                    data=data,
                    files=files,
                    headers=headers,
                    timeout=self.timeout,
                )

                if response.status_code in (401, 403):
                    raise AuthError("百度网盘拒绝访问，授权可能已失效")
                if response.status_code >= 500:
                    raise NetworkError(f"服务端返回 HTTP {response.status_code}")
                if response.status_code != 200:
                    raise UploadError(
                        f"上传失败（HTTP {response.status_code}）",
                        detail=response.text[:300],
                    )

                payload = self._parse_json(response)
                self._raise_for_errno(payload, tolerate)
                return payload

            except TaskCancelled:
                raise
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise NetworkError("网络连接失败，请检查网络后重试", detail=str(exc)) from exc
                self._sleep_backoff(attempt, ctx)
            except NetworkError as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise
                self._sleep_backoff(attempt, ctx)
            except AuthError:
                # 令牌可能刚过期：强制刷新后重试一次
                if attempt == 0:
                    self.store.force_refresh()
                    current_params["access_token"] = self._token()
                    continue
                raise
            except UploadError as exc:
                if getattr(exc, "retryable", False) and attempt < self.retries:
                    self._sleep_backoff(attempt, ctx)
                    continue
                raise

        raise NetworkError("上传失败", detail=str(last_error or ""))

    @staticmethod
    def _parse_json(response: requests.Response) -> dict:
        try:
            payload = response.json()
        except ValueError:
            raise UploadError(
                "服务端返回了无法解析的内容", detail=response.text[:300]
            ) from None
        if not isinstance(payload, dict):
            raise UploadError("服务端返回格式异常", detail=str(payload)[:300])
        return payload

    @classmethod
    def _raise_for_errno(cls, payload: dict, tolerate: set[int] | None = None) -> None:
        # xpan 用 errno，旧 pcs 用 error_code
        raw_errno = payload.get("errno", payload.get("error_code", 0))
        try:
            errno = int(raw_errno)
        except (TypeError, ValueError):
            errno = 0
        if errno == 0 or (tolerate and errno in tolerate):
            return

        message = _ERRNO_MESSAGE.get(errno) or str(
            payload.get("error_msg") or payload.get("errmsg") or f"错误码 {errno}"
        )
        detail = json.dumps(payload, ensure_ascii=False)[:300]

        if errno in _AUTH_ERRNO:
            raise AuthError(message, detail=detail)
        if errno in _QUOTA_ERRNO:
            raise QuotaExceeded(message, detail=detail)

        error = UploadError(f"{message}（错误码 {errno}）", detail=detail)
        error.retryable = errno in _RETRYABLE_ERRNO  # type: ignore[attr-defined]
        raise error

    # ------------------------------------------------------------------
    # 业务接口
    # ------------------------------------------------------------------

    def get_user_info(self) -> dict:
        """获取当前授权账号信息，用于授权页展示。"""
        return self._post(
            _NAS_API,
            params={"method": "uinfo", "access_token": self._token()},
        )

    def get_quota(self) -> tuple[int, int]:
        """返回 ``(已用字节, 总字节)``。"""
        response = self._session.get(
            _QUOTA_API,
            params={"access_token": self._token(), "checkfree": 1},
            timeout=self.timeout,
        )
        payload = self._parse_json(response)
        self._raise_for_errno(payload)
        used = int(payload.get("used", 0) or 0)
        # 真实接口返回 total；部分旧文档写 quota，两种都兼容
        total = int(payload.get("total") or payload.get("quota") or 0)
        return used, total

    def ensure_dir(self, remote_dir: str) -> None:
        """确保远端目录存在。

        注意：XPAN 的 create 接口在目标已存在时不会返回错误，而是自动
        创建一个带时间戳后缀的副本（实测行为）。因此必须先查询目标目录
        是否存在，否则每运行一次任务就会在网盘里多出一份空目录。
        """
        normalized = "/" + remote_dir.strip("/")
        if normalized in self._known_dirs or normalized == "/":
            return

        current = ""
        for part in [p for p in normalized.strip("/").split("/") if p]:
            current = f"{current}/{part}"
            if current in self._known_dirs:
                continue
            if not self._dir_exists(current):
                self._post(
                    _XPAN_FILE,
                    params={"method": "create", "access_token": self._token()},
                    data=_form_body({"path": current, "isdir": "1", "size": "0"}),
                    tolerate_errno={-8},  # 目录已存在
                )
            self._known_dirs.add(current)

    def _dir_exists(self, remote_path: str) -> bool:
        """目录存在返回 ``True``；服务端明确返回 -9（文件不存在）时返回 ``False``。"""
        try:
            self.list_dir(remote_path)
            return True
        except UploadError as exc:
            try:
                errno = int(json.loads(exc.detail or "{}").get("errno", 0))
            except (TypeError, ValueError, json.JSONDecodeError):
                errno = 0
            if errno == -9:
                return False
            raise

    def upload(
        self,
        local_path: Path,
        remote_dir: str,
        ctx: TaskContext,
        *,
        on_progress: Callable[[int], None] | None = None,
        force_chunked: bool = False,
    ) -> RemoteFile:
        """上传单个文件。

        ``on_progress`` 收到的是**本文件已发送的字节数**（从 0 到文件大小），
        整体进度由调用方换算。

        ``force_chunked=True`` 时即使文件小于 2GB 也走 XPAN 分片接口，
        供联调脚本在不传大文件的情况下验证分片链路。
        """
        local_path = Path(local_path)
        if not local_path.is_file():
            raise UploadError(f"待上传文件不存在: {local_path}")

        size = local_path.stat().st_size
        if size <= 0:
            raise UploadError(f"文件为空，跳过上传: {local_path.name}")

        self.ensure_dir(remote_dir)
        remote_path = f"/{remote_dir.strip('/')}/{local_path.name}"
        progress = on_progress or (lambda _sent: None)

        if force_chunked or size > _SINGLE_UPLOAD_LIMIT:
            return self._upload_chunked(local_path, remote_path, ctx, progress)
        return self._upload_single(local_path, remote_path, ctx, progress)

    def _upload_single(
        self,
        local_path: Path,
        remote_path: str,
        ctx: TaskContext,
        on_progress: Callable[[int], None],
    ) -> RemoteFile:
        body = _MultipartBody(local_path, "file", ctx, on_progress)
        payload = self._post(
            _PCS_UPLOAD,
            params={
                "method": "upload",
                "access_token": self._token(),
                "path": remote_path,
                "ondup": "overwrite",
            },
            data=body,
            ctx=ctx,
        )
        size = int(payload.get("size", local_path.stat().st_size) or 0)
        return RemoteFile(
            path=str(payload.get("path") or remote_path),
            size=size,
            fs_id=str(payload.get("fs_id") or ""),
            md5=str(payload.get("md5") or ""),
        )

    @staticmethod
    def _md5_of(stream, length: int) -> str:
        digest = hashlib.md5()
        remaining = length
        while remaining > 0:
            chunk = stream.read(min(_READ_BLOCK, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        return digest.hexdigest()

    def _upload_chunked(
        self,
        local_path: Path,
        remote_path: str,
        ctx: TaskContext,
        on_progress: Callable[[int], None],
    ) -> RemoteFile:
        """分片上传：precreate → superfile2 逐片 → create。

        进度按「已上传分片字节数」推进；若服务端已有部分分片（断点/秒传），
        会先补记这部分进度，保证进度条只增不减。
        """
        size = local_path.stat().st_size
        parts = (size + _CHUNK_SIZE - 1) // _CHUNK_SIZE
        if parts > _MAX_PARTS:
            raise UploadError(f"文件过大（{size / 1024 ** 3:.1f} GB），超过网盘单文件上限")

        # 1. 逐片计算 MD5（用于秒传与完整性校验）
        block_md5: list[str] = []
        with open(local_path, "rb") as stream:
            for index in range(parts):
                ctx.check()
                length = min(_CHUNK_SIZE, size - index * _CHUNK_SIZE)
                block_md5.append(self._md5_of(stream, length))
                ctx.report(
                    Stage.UPLOAD,
                    0,
                    0,
                    unit="bytes",
                    message="正在校验文件",
                    detail=f"{local_path.name} · 分片 {index + 1}/{parts}",
                )

        # 2. precreate：获取 uploadid 与仍需上传的分片
        precreate = self._post(
            _XPAN_FILE,
            params={"method": "precreate", "access_token": self._token()},
            data=_form_body({
                "path": remote_path,
                "size": str(size),
                "isdir": "0",
                "autoinit": "1",
                "block_list": json.dumps(block_md5),
                "rtype": "1",
            }),
            ctx=ctx,
        )
        upload_id = str(precreate.get("uploadid") or "")
        if not upload_id:
            raise UploadError("网盘未返回上传会话 ID")

        raw_pending = precreate.get("block_list")
        pending = {int(item) for item in raw_pending} if raw_pending else set(range(parts))

        skipped_bytes = sum(
            min(_CHUNK_SIZE, size - index * _CHUNK_SIZE)
            for index in range(parts)
            if index not in pending
        )
        if skipped_bytes:
            on_progress(skipped_bytes)

        # 3. 逐片上传
        uploaded = skipped_bytes
        with open(local_path, "rb") as stream:
            for index in sorted(pending):
                ctx.check()
                offset = index * _CHUNK_SIZE
                length = min(_CHUNK_SIZE, size - offset)
                stream.seek(offset)
                data = stream.read(length)
                if not data or len(data) != length:
                    raise UploadError("读取文件时长度不一致，文件可能已被修改")

                self._post(
                    _XPAN_SUPERFILE,
                    params={
                        "method": "upload",
                        "access_token": self._token(),
                        "type": "tmpfile",
                        "path": remote_path,
                        "uploadid": upload_id,
                        "partseq": str(index),
                    },
                    files={"file": ("file", data, "application/octet-stream")},
                    ctx=ctx,
                )
                uploaded += length
                on_progress(uploaded)

        # 4. create 落盘
        payload = self._post(
            _XPAN_FILE,
            params={"method": "create", "access_token": self._token()},
            data=_form_body({
                "path": remote_path,
                "size": str(size),
                "isdir": "0",
                "uploadid": upload_id,
                "block_list": json.dumps(block_md5),
                "rtype": "1",
            }),
            ctx=ctx,
        )
        return RemoteFile(
            path=str(payload.get("path") or remote_path),
            size=size,
            fs_id=str(payload.get("fs_id") or ""),
            md5=str(payload.get("md5") or ""),
        )

    def delete(self, remote_path: str) -> None:
        """删除远端单个文件。

        用于联调脚本清理测试文件，也可供将来实现「保留最近 N 份备份」。
        """
        self._post(
            _PCS_FILE,
            params={
                "method": "delete",
                "access_token": self._token(),
                "path": "/" + remote_path.strip("/"),
            },
        )

    def list_dir(self, remote_dir: str) -> list[dict]:
        """列出远端目录，用于上传后校验。"""
        payload = self._post(
            _XPAN_FILE,
            params={
                "method": "list",
                "access_token": self._token(),
                "dir": "/" + remote_dir.strip("/"),
                "limit": "1000",
                "order": "time",
            },
        )
        items = payload.get("list") or []
        return items if isinstance(items, list) else []


def _form_body(fields: dict[str, str]) -> bytes:
    """把表单字段编码成 ``application/x-www-form-urlencoded`` 请求体。"""
    return urlencode(fields).encode("utf-8")
