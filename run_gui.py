"""GUI 启动入口，兼容开发运行和 PyInstaller 打包。"""

import os
import sys

# 添加父目录到 sys.path，确保 game_save_file_handle 包可导入
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from game_save_file_handle.gui.app import main

if __name__ == "__main__":
    main()
