# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（2.0.2）。

用法（项目根目录）::

    pyinstaller GameSaveBackup.spec --clean

说明：

* 入口是 ``run_gui.py``，它会把项目父目录注入 ``sys.path``，
  因此 ``pathex`` 指向父目录，保证 ``game_save_file_handle`` 包能被找到。
* 配置与图标通过 ``datas`` 内嵌，运行时优先读取 exe 同目录的文件。
* PySide6 的 Qt 插件（platforms/styles/imageformats）由 PyInstaller
  内置 hook 自动收集。
* OpenSSL DLL 需要显式收集：Anaconda 把 DLL 放在 ``Library/bin``，
  PyInstaller 可能从 PATH 误拿到 Git 自带的 OpenSSL 3.x，导致打包后
  报 “SSL module is not available”。
"""

import ssl
import sys
from pathlib import Path


def _openssl_dll_names() -> tuple[str, str]:
    """按解释器实际使用的 OpenSSL 版本返回 DLL 文件名。"""
    if ssl.OPENSSL_VERSION.startswith("OpenSSL 3"):
        return "libssl-3-x64.dll", "libcrypto-3-x64.dll"
    return "libssl-1_1-x64.dll", "libcrypto-1_1-x64.dll"


def _collect_openssl() -> list[str]:
    """在常见位置查找 Python 对应的 OpenSSL DLL。"""
    names = _openssl_dll_names()
    search_dirs = (
        Path(sys.base_prefix) / "Library" / "bin",  # Anaconda
        Path(sys.base_prefix) / "DLLs",            # 官方 CPython
        Path(sys.base_prefix),
    )
    found: list[str] = []
    for name in names:
        for directory in search_dirs:
            candidate = directory / name
            if candidate.is_file():
                found.append(str(candidate))
                break
        else:
            print(f"[spec] 警告：未找到 {name}，打包后 HTTPS 可能不可用")
    return found


datas = [
    ("config/config.yaml", "config"),
    ("img/icon.ico", "img"),
]

hiddenimports = [
    "yaml",
    "requests",
    "PySide6.QtSvg",
]

a = Analysis(
    ["run_gui.py"],
    pathex=[".."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# 用解释器实际依赖的 OpenSSL DLL 替换从 PATH 误收集的版本
_openssl_dlls = _collect_openssl()
if _openssl_dlls:
    _needed = {Path(item).name.lower() for item in _openssl_dlls}
    _unwanted = {"libssl-3-x64.dll", "libcrypto-3-x64.dll"} - _needed
    if _unwanted:
        a.binaries = [
            entry for entry in a.binaries
            if Path(entry[0]).name.lower() not in _unwanted
        ]
    _existing = {Path(entry[0]).name.lower() for entry in a.binaries}
    for _source in _openssl_dlls:
        _name = Path(_source).name
        if _name.lower() not in _existing:
            a.binaries.append((_name, _source, "BINARY"))
            print(f"[spec] 已加入 OpenSSL DLL: {_source}")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GameSaveBackup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["img/icon.ico"],
)
