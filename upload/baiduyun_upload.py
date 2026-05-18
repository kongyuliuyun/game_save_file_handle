import io
import json
import os
import socket
import sys

from bypy import ByPy, const


class ByPyAuthError(Exception):
    """百度云未授权异常。"""


def upload_to_baiduyun(filepath, progress_callback=None):
    """
    上传文件到百度云盘。

    Args:
        filepath: 要上传的文件路径
        progress_callback: 进度回调 (filename, status, message)
    """

    def log(msg):
        if progress_callback:
            progress_callback('', 'upload_info', msg)

    log("开始备份至百度云")

    _fix_stdio()
    _validate_token()

    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(300)
        bypy = ByPy()
        bypy.syncup(filepath, os.path.basename(filepath))
    finally:
        socket.setdefaulttimeout(old_timeout)

    log("备份至百度云完成")


def _validate_token():
    """验证令牌文件存在且包含有效字段，否则给出明确指引。"""
    token_path = os.path.join(const.ConfigDir, 'bypy.json')

    if not os.path.exists(token_path):
        raise ByPyAuthError(
            "百度云尚未授权。请切换到「百度云授权」标签页，\n"
            "点击「获取授权链接」完成百度账号授权后再执行备份。"
        )

    try:
        with open(token_path, 'r', encoding='utf-8') as f:
            token = json.load(f)
        if 'access_token' not in token:
            raise ByPyAuthError(
                "百度云授权令牌无效。请切换到「百度云授权」标签页重新授权。"
            )
    except (json.JSONDecodeError, IOError):
        raise ByPyAuthError(
            "百度云授权文件损坏。请切换到「百度云授权」标签页重新授权。"
        )


def _fix_stdio():
    """修复 --windowed 模式下 std* 为 None 导致 ByPy 报错或挂起。"""
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()
    if sys.stdin is None:
        sys.stdin = _DevNullStdin()


class _DevNullStdin:
    """模拟 stdin，任何读取操作立即抛出 EOFError。"""
    def read(self, *args):
        raise EOFError("stdin unavailable in windowed mode")
    def readline(self, *args):
        raise EOFError("stdin unavailable in windowed mode")
    def flush(self):
        pass


if __name__ == '__main__':
    upload_to_baiduyun("D:\\MyDownload\\game-save-backup-zip")
