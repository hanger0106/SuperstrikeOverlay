"""用 Windows 內建的標準游標校正 _cursor_shot 的繪製結果（IDC_NO = 🚫）。"""

import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cursor_shot as shot

STANDARD = {
    "ARROW": 32512,
    "NO": 32648,
    "HAND": 32649,
    "SIZEWE": 32644,
    "CROSS": 32515,
}

for name, resource in STANDARD.items():
    handle = shot.user32.LoadCursorW(None, ctypes.c_void_p(resource))
    print(name, resource, hex(int(handle)))
    shot.save_cursor(int(handle), scale=6)
