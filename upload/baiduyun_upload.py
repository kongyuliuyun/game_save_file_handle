import io
import os
import sys

from bypy import ByPy


def upload_to_baiduyun(filepath, progress_callback=None):
    """
    上传文件到百度云盘。

    Args:
        filepath: 要上传的文件路径
        progress_callback: 进度回调函数 (filename: str, status: str, message: str)
    """

    def log(msg):
        if progress_callback:
            progress_callback('', 'upload_info', msg)

    log("开始备份至百度云")

    # 修复 PyInstaller --windowed 模式下 stdout/stderr 为 None 的问题
    _fix_stdio()

    bypy = ByPy()
    bypy.syncup(filepath, os.path.basename(filepath))

    log("备份至百度云完成")


def _fix_stdio():
    """确保 stdout / stderr 可用，防止 --windowed 模式下 ByPy 调用 flush 时报错。"""
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()


if __name__ == '__main__':
    upload_to_baiduyun("D:\\MyDownload\\game-save-backup-zip")
