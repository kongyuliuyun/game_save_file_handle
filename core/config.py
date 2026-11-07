"""配置加载与持久化。

相对旧版的核心改进：

1. ``save_extensions`` 旧版写成 ``{'.sav', '.save'}``，PyYAML 会解析成
   ``{'.sav': None, ...}`` 这样的 dict，属于隐性错误；新版统一为字符串列表，
   并兼容读取 dict / set / list 三种历史形态。
2. 配置对象改为 dataclass，支持保存回磁盘，界面修改后可持久化。
3. 路径解析不再静默改写盘符，而是返回 ``(路径, 警告)`` 供界面提示。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

import yaml

from .errors import ConfigError
from ..utils.paths import app_root, config_path, work_dir

__all__ = [
    "DEFAULT_EXTENSIONS",
    "AppConfig",
    "format_whitelist",
    "parse_whitelist",
    "resolve_path",
    "load_config",
    "save_config",
]

DEFAULT_EXTENSIONS: tuple[str, ...] = (
    ".sav",
    ".save",
    ".esm",
    ".esp",
    ".bsa",
    ".ba2",
    ".rpgsave",
    ".rmmzsave",
    ".phxsav",
)

_ENV_PATTERN = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


def _expand(value: str) -> str:
    """展开 ``%VAR%``、``$VAR`` 与用户主目录。"""

    def _replace(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), match.group(0))

    expanded = _ENV_PATTERN.sub(_replace, value)
    expanded = os.path.expandvars(expanded)
    return os.path.expanduser(expanded)


def _coerce_extensions(raw: Any) -> set[str]:
    """把任意历史格式的扩展名配置规整成 ``{'.sav', ...}``。"""
    if raw is None:
        return {item.lower() for item in DEFAULT_EXTENSIONS}

    if isinstance(raw, str):
        items: Iterable[Any] = re.split(r"[,;\s]+", raw)
    elif isinstance(raw, dict):
        items = raw.keys()
    elif isinstance(raw, (set, frozenset, list, tuple)):
        items = raw
    else:
        raise ConfigError(f"save_extensions 配置格式不支持: {type(raw).__name__}")

    result: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        text = item.strip().lower()
        if not text:
            continue
        result.add(text if text.startswith(".") else "." + text)
    return result or {item.lower() for item in DEFAULT_EXTENSIONS}


def _coerce_whitelist(raw: Any) -> dict[str, list[str]]:
    """把白名单规整成 ``{根目录: [游戏名, ...]}``。"""
    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, str):
            names = [value]
        elif isinstance(value, (list, tuple, set)):
            names = [str(item) for item in value]
        else:
            names = []
        result[key] = names
    return result


@dataclass
class AppConfig:
    """全部可调参数。字段默认值即出厂设置。"""

    save_extensions: set[str] = field(
        default_factory=lambda: {item.lower() for item in DEFAULT_EXTENSIONS}
    )
    whitelist: dict[str, list[str]] = field(default_factory=dict)
    backup_root: str = "./game-save-backup"
    zip_root: str = "./game-save-backup-zip"
    remote_dir: str = "/apps/bypy/game-save-backup"
    keep_local_backup: bool = False
    upload_enabled: bool = True
    theme: str = "light"
    upload_threads: int = 3
    verify_upload: bool = True
    unknown: dict[str, Any] = field(default_factory=dict, repr=False)

    # ---------- 派生属性 ----------

    def extensions(self) -> set[str]:
        """返回小写、带点号的扩展名集合（用于 ``str.endswith`` 判断）。"""
        return {item.lower() if item.startswith(".") else "." + item.lower()
                for item in self.save_extensions}

    def backup_dir(self) -> tuple[Path, str]:
        return resolve_path(self.backup_root, base=work_dir())

    def zip_dir(self) -> tuple[Path, str]:
        return resolve_path(self.zip_root, base=work_dir())

    def normalized(self) -> "AppConfig":
        """返回字段已规整的副本，避免下游反复做防御性判断。"""
        threads = self.upload_threads
        try:
            threads = max(1, min(8, int(threads)))
        except (TypeError, ValueError):
            threads = 3
        theme = self.theme if self.theme in ("light", "dark") else "light"
        return replace(
            self,
            save_extensions=self.extensions(),
            whitelist=_coerce_whitelist(self.whitelist),
            upload_threads=threads,
            theme=theme,
            keep_local_backup=bool(self.keep_local_backup),
            upload_enabled=bool(self.upload_enabled),
            verify_upload=bool(self.verify_upload),
        )

    # ---------- 序列化 ----------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        known = {
            "save_extensions": "save_extensions",
            "white_list_root_path": "whitelist",
            "whitelist": "whitelist",
            "save_backup_path": "backup_root",
            "backup_root": "backup_root",
            "zip_backup_path": "zip_root",
            "zip_root": "zip_root",
            "remote_dir": "remote_dir",
            "keep_local_backup": "keep_local_backup",
            "upload_enabled": "upload_enabled",
            "theme": "theme",
            "upload_threads": "upload_threads",
            "verify_upload": "verify_upload",
        }

        cfg = cls()
        unknown: dict[str, Any] = {}
        for key, value in data.items():
            target = known.get(key)
            if target is None:
                unknown[key] = value
                continue
            if target == "save_extensions":
                cfg.save_extensions = _coerce_extensions(value)
            elif target == "whitelist":
                cfg.whitelist = _coerce_whitelist(value)
            elif target == "upload_threads":
                try:
                    cfg.upload_threads = int(value)
                except (TypeError, ValueError):
                    cfg.upload_threads = 3
            elif target in ("keep_local_backup", "verify_upload", "upload_enabled"):
                cfg.__dict__[target] = bool(value)
            else:
                cfg.__dict__[target] = "" if value is None else str(value)

        cfg.unknown = unknown
        return cfg.normalized()

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "save_extensions": sorted(self.extensions()),
            "white_list_root_path": {
                key: list(value) for key, value in self.whitelist.items()
            },
            "save_backup_path": self.backup_root,
            "zip_backup_path": self.zip_root,
            "remote_dir": self.remote_dir,
            "keep_local_backup": self.keep_local_backup,
            "upload_enabled": self.upload_enabled,
            "theme": self.theme,
            "upload_threads": self.upload_threads,
            "verify_upload": self.verify_upload,
        }
        for key, value in self.unknown.items():
            data.setdefault(key, value)
        return data

    def save(self, path: Path | None = None) -> Path:
        """写回 YAML。默认写到当前生效的配置文件，保证「读哪儿写哪儿」。"""
        target = Path(path) if path else config_path()
        payload = yaml.safe_dump(
            self.to_dict(), allow_unicode=True, sort_keys=False, default_flow_style=False
        )
        header = (
            "# 游戏存档备份工具配置文件\n"
            "# 修改后重启程序生效；也可在「设置」页面直接编辑并保存。\n\n"
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(header + payload, encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"配置保存失败: {target}", detail=str(exc)) from exc
        return target


def parse_whitelist(text: str) -> dict[str, list[str]]:
    """把设置页的白名单文本解析成 ``{目录: [游戏名, ...]}``。

    每行格式::

        D:\\Games => 游戏A, 游戏B
        default => all

    - 以 ``#`` 开头的行与空行会被忽略；
    - ``=>`` 与 ``=`` 都可以作为分隔符（``=>`` 优先）；
    - 只写目录不写游戏名 → 视为该目录全部放行；
    - 整体为空 → 返回空 dict，表示不做过滤。
    """
    result: dict[str, list[str]] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" in line:
            key, value = line.split("=>", 1)
        elif "=" in line:
            key, value = line.split("=", 1)
        else:
            key, value = line, ""
        key = key.strip()
        if not key:
            continue
        names = [
            item.strip()
            for item in re.split(r"[,;，；]+", value)
            if item.strip()
        ]
        result[key] = names
    return result


def format_whitelist(whitelist: dict[str, list[str]] | None) -> str:
    """把白名单字典格式化成设置页可编辑的文本（与 :func:`parse_whitelist` 互逆）。"""
    if not whitelist:
        return ""
    lines: list[str] = []
    for key in sorted(whitelist, key=lambda item: (item != "default", item.lower())):
        names = whitelist.get(key) or []
        display = ", ".join(names) if names else "all"
        lines.append(f"{key} => {display}")
    return "\n".join(lines)


def resolve_path(value: str, *, base: Path | None = None) -> tuple[Path, str]:
    """把配置里的路径文本解析成绝对路径。

    返回 ``(路径, 警告信息)``。警告信息非空时表示发生了兜底改写，
    界面应提示用户而不是静默使用。
    """
    base = base or work_dir()
    text = _expand((value or "").strip())
    if not text:
        return base, ""

    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = base / text

    try:
        candidate = Path(os.path.normpath(str(candidate)))
    except (OSError, ValueError):
        return base, f"路径非法，已回退到 {base}"

    drive, _ = os.path.splitdrive(str(candidate))
    if drive and not Path(drive + os.sep).exists():
        fallback_drive, _ = os.path.splitdrive(str(base))
        fallback = Path((fallback_drive or "C:") + str(candidate)[len(drive):])
        return fallback, f"磁盘 {drive} 不存在，已改用 {fallback_drive or 'C:'}"

    return candidate, ""


def load_config(path: Path | None = None) -> AppConfig:
    """读取配置；文件缺失或损坏时返回默认配置而不是崩溃。"""
    target = Path(path) if path else config_path()
    if not target.is_file():
        return AppConfig().normalized()
    try:
        raw = target.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"配置文件无法解析: {target}", detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件内容不是映射结构: {target}")
    return AppConfig.from_dict(data)


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    return config.normalized().save(path)
