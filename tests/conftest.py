"""让测试可以直接 ``import game_save_file_handle.xxx``。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_PARENT = PROJECT_ROOT.parent
for path in (str(PACKAGE_PARENT), str(PROJECT_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
