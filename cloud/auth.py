"""百度网盘 OAuth 授权与令牌管理。

旧版把「打开浏览器」「换 token」「写文件」混在 Tk 线程里，且令牌过期后
没有任何刷新机制，一旦 30 天有效期到就必须手动重新授权。

新版把职责拆开：

* :class:`Token` —— 令牌值对象，兼容 bypy 的 ``~/.bypy/bypy.json`` 格式；
* :class:`TokenStore` —— 读写、过期判断、自动刷新；
* 模块级函数 —— 生成授权 URL、用授权码换取令牌。
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import AuthError
from ..utils.paths import token_file

__all__ = [
    "BAIDU_APP_KEY",
    "BAIDU_SECRET_KEY",
    "Token",
    "TokenStore",
    "build_authorize_url",
    "exchange_code",
    "refresh_access_token",
]

# bypy 开源项目内置的公开凭据，用于访问 `/apps/bypy` 授权目录。
# 可通过环境变量覆盖，便于自行申请应用后替换。
BAIDU_APP_KEY = os.environ.get("BAIDU_APP_KEY", "q8WE4EpCsau1oS0MplgMKNBn")
BAIDU_SECRET_KEY = os.environ.get("BAIDU_SECRET_KEY", "PA4MhwB5RE7DacKtoP2i8ikCnNzAqYTD")

_AUTHORIZE_URL = "https://openapi.baidu.com/oauth/2.0/authorize"
_TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"
_SCOPE = "basic netdisk"
_REDIRECT_URI = "oob"

# 提前 5 分钟视为过期，避免上传到一半恰好失效
_EXPIRY_MARGIN = 300


@dataclass(slots=True)
class Token:
    """OAuth 令牌。字段名与百度返回、bypy 缓存保持一致。"""

    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    scope: str = ""
    session_key: str = ""
    session_secret: str = ""

    @property
    def expired(self) -> bool:
        if not self.expires_at:
            return False
        return time.time() >= self.expires_at

    @property
    def expires_in(self) -> float:
        return max(0.0, self.expires_at - time.time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
            "session_key": self.session_key,
            "session_secret": self.session_secret,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Token":
        if not isinstance(data, dict) or not data.get("access_token"):
            raise AuthError("授权令牌格式无效")

        expires_at = data.get("expires_at")
        if not isinstance(expires_at, (int, float)) or expires_at <= 0:
            expires_in = data.get("expires_in")
            try:
                expires_at = time.time() + float(expires_in) if expires_in else 0.0
            except (TypeError, ValueError):
                expires_at = 0.0

        return cls(
            access_token=str(data["access_token"]),
            refresh_token=str(data.get("refresh_token") or ""),
            expires_at=float(expires_at),
            scope=str(data.get("scope") or ""),
            session_key=str(data.get("session_key") or ""),
            session_secret=str(data.get("session_secret") or ""),
        )


def _post_form(url: str, payload: dict[str, str], timeout: float = 30.0) -> dict[str, Any]:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # pragma: no cover - 极端情况
            detail = ""
        raise AuthError(f"授权服务返回 HTTP {exc.code}", detail=detail) from exc
    except urllib.error.URLError as exc:  # type: ignore[attr-defined]
        raise AuthError("无法连接百度授权服务，请检查网络", detail=str(exc)) from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise AuthError("授权服务响应异常", detail=str(exc)) from exc


def _parse_token_response(data: dict[str, Any]) -> Token:
    if "error" in data:
        message = str(data.get("error_description") or data.get("error"))
        raise AuthError(f"授权失败：{message}")
    if not data.get("access_token"):
        raise AuthError("授权服务未返回令牌", detail=str(data)[:300])

    expires_in = data.get("expires_in")
    try:
        ttl = float(expires_in) if expires_in else 0.0
    except (TypeError, ValueError):
        ttl = 0.0

    return Token(
        access_token=str(data["access_token"]),
        refresh_token=str(data.get("refresh_token") or ""),
        expires_at=(time.time() + ttl - _EXPIRY_MARGIN) if ttl else 0.0,
        scope=str(data.get("scope") or ""),
        session_key=str(data.get("session_key") or ""),
        session_secret=str(data.get("session_secret") or ""),
    )


def build_authorize_url() -> str:
    """生成可粘贴到浏览器的授权地址（``redirect_uri=oob`` 授权码模式）。"""
    params = urllib.parse.urlencode(
        {
            "client_id": BAIDU_APP_KEY,
            "response_type": "code",
            "redirect_uri": _REDIRECT_URI,
            "scope": _SCOPE,
            "display": "page",
        }
    )
    return f"{_AUTHORIZE_URL}?{params}"


def exchange_code(code: str) -> Token:
    """用授权码换取 access token。"""
    code = (code or "").strip()
    if len(code) < 8:
        raise AuthError("授权码格式不正确，请重新复制")
    data = _post_form(
        _TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": BAIDU_APP_KEY,
            "client_secret": BAIDU_SECRET_KEY,
            "redirect_uri": _REDIRECT_URI,
        },
    )
    return _parse_token_response(data)


def refresh_access_token(token: Token) -> Token:
    """用 refresh_token 换新令牌。无 refresh_token 时直接报错。"""
    if not token.refresh_token:
        raise AuthError("授权已过期且无法自动续期，请重新授权")
    data = _post_form(
        _TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
            "client_id": BAIDU_APP_KEY,
            "client_secret": BAIDU_SECRET_KEY,
        },
    )
    refreshed = _parse_token_response(data)
    # 百度刷新接口有时不返回 refresh_token，沿用旧的
    if not refreshed.refresh_token:
        refreshed.refresh_token = token.refresh_token
    return refreshed


class TokenStore:
    """令牌的持久化与生命周期管理。

    默认路径与 bypy 一致（``~/.bypy/bypy.json``），因此本项目与 bypy
    可以共用同一份授权，用户不必重复登录。
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else token_file()
        self._token: Token | None = None
        self._loaded = False
        # 并发上传时多个线程会同时 require()，必须保证只刷新一次、只落盘一次
        self._lock = threading.RLock()

    # ---------- 持久化 ----------

    def load(self) -> Token | None:
        with self._lock:
            if self._loaded:
                return self._token
            self._loaded = True
            if not self.path.is_file():
                self._token = None
                return None
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._token = None
                return None
            try:
                self._token = Token.from_dict(data)
            except AuthError:
                self._token = None
            return self._token

    def save(self, token: Token) -> None:
        with self._lock:
            self._token = token
            self._loaded = True
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    json.dumps(token.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as exc:
                raise AuthError("授权令牌保存失败", detail=str(exc)) from exc

    def clear(self) -> None:
        with self._lock:
            self._token = None
            self._loaded = True
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass

    # ---------- 生命周期 ----------

    def current(self) -> Token | None:
        return self.load()

    def has_token(self) -> bool:
        return self.load() is not None

    def require(self, *, auto_refresh: bool = True) -> Token:
        """取一个可用令牌；过期时自动刷新并落盘。

        持锁执行刷新，保证并发上传时不会出现多个线程同时换 token、
        导致其中一个 refresh_token 失效。
        """
        with self._lock:
            token = self.load()
            if token is None:
                raise AuthError("尚未完成百度网盘授权，请先在「授权」页面登录")

            if not token.expired:
                return token

            if not auto_refresh:
                raise AuthError("百度网盘授权已过期，请重新授权")

            refreshed = refresh_access_token(token)
            self.save(refreshed)
            return refreshed

    def force_refresh(self) -> Token:
        with self._lock:
            token = self.load()
            if token is None:
                raise AuthError("尚未完成百度网盘授权，请先在「授权」页面登录")
            refreshed = refresh_access_token(token)
            self.save(refreshed)
            return refreshed

    def describe(self) -> dict[str, Any]:
        """给界面用的状态摘要。"""
        token = self.load()
        if token is None:
            return {"authorized": False, "message": "未授权"}
        if token.expired:
            return {
                "authorized": False,
                "message": "授权已过期" if token.refresh_token else "授权已过期，需重新登录",
                "renewable": bool(token.refresh_token),
            }
        return {
            "authorized": True,
            "message": "已授权",
            "expires_in": token.expires_in,
            "scope": token.scope,
        }
