"""GUI 启动入口，兼容开发运行与 PyInstaller 打包。

用法：

    python run_gui.py

或作为模块：

    python -m game_save_file_handle.run_gui
"""

from __future__ import annotations

import os
import sys


def _bootstrap() -> None:
    """把项目父目录加入 sys.path，保证包可以按绝对路径导入。"""
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    for path in (parent, here):
        if path not in sys.path:
            sys.path.insert(0, path)


_bootstrap()

from game_save_file_handle.app.bootstrap import run  # noqa: E402


def _self_check() -> int:
    """诊断模式：验证打包后的 SSL、证书与 HTTPS 是否可用。

    结果写入系统临时目录的 ``GameSaveBackup-selfcheck.json``。
    打包产物没有控制台，因此用文件输出结果，供部署后排查网络问题。
    """
    import json
    import ssl
    import tempfile
    import traceback
    from pathlib import Path

    result: dict[str, object] = {"ok": False}
    try:
        import requests

        result["ssl"] = ssl.OPENSSL_VERSION
        response = requests.get("https://pan.baidu.com", timeout=15)
        result["http_status"] = response.status_code
        result["ok"] = response.status_code < 500
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()

    target = Path(tempfile.gettempdir()) / "GameSaveBackup-selfcheck.json"
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    sys.exit(run())
