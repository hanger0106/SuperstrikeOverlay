"""把游標 handle 畫成 PNG，用來辨認「這顆游標到底是哪一顆」。

GetCursorInfo() 拿到的 hCursor 可以丟給 GetIconInfo()，把 icon 的
color bitmap + mask 取出來組回 ARGB，再存成放大 8 倍的 PNG，一眼就能
看出是箭頭、複製(+)、移動、捷徑(彎箭頭) 還是禁用(🚫)。

用法：
    python tools\\_cursor_shot.py 0x3CA0FF3 0x6710931 0x10003
    python tools\\_cursor_shot.py --watch 15        # 即時取樣 15 秒，handle 一變就存圖
    python tools\\_cursor_shot.py                   # 只存目前游標

輸出檔名： tools\\_cursor_shots\\cursor_<handle>.png
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

OUT_DIR = Path(__file__).resolve().parent / "_cursor_shots"


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE),
        ("ptScreenPos", POINT),
    ]


user32.GetIconInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(ICONINFO))
user32.GetIconInfo.restype = wintypes.BOOL
user32.GetCursorInfo.argtypes = (ctypes.POINTER(CURSORINFO),)
user32.GetCursorInfo.restype = wintypes.BOOL
gdi32.GetObjectW.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p)
gdi32.GetObjectW.restype = ctypes.c_int
gdi32.GetDIBits.argtypes = (
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.POINTER(BITMAPINFOHEADER),
    wintypes.UINT,
)
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
gdi32.DeleteObject.restype = wintypes.BOOL
user32.GetDC.argtypes = (wintypes.HWND,)
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
user32.ReleaseDC.restype = ctypes.c_int
gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = (wintypes.HDC,)
gdi32.DeleteDC.restype = wintypes.BOOL
user32.LoadCursorW.argtypes = (wintypes.HINSTANCE, ctypes.c_void_p)
user32.LoadCursorW.restype = wintypes.HANDLE

DIB_RGB_COLORS = 0


def current_cursor() -> int:
    info = CURSORINFO()
    info.cbSize = ctypes.sizeof(CURSORINFO)

    if not user32.GetCursorInfo(ctypes.byref(info)):
        return 0

    return int(info.hCursor or 0)


user32.WindowFromPoint.argtypes = (wintypes.POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD


def window_under_cursor() -> str:
    """游標底下的視窗（OLE 找 drop target 就是從這裡開始）。"""

    info = CURSORINFO()
    info.cbSize = ctypes.sizeof(CURSORINFO)

    if not user32.GetCursorInfo(ctypes.byref(info)):
        return "n/a"

    handle = user32.WindowFromPoint(
        wintypes.POINT(info.ptScreenPos.x, info.ptScreenPos.y)
    )

    if not handle:
        return "n/a"

    class_name = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(handle, class_name, 128)

    title = ctypes.create_unicode_buffer(128)
    user32.GetWindowTextW(handle, title, 128)

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))

    text = f"{class_name.value} (pid={pid.value})"

    if title.value:
        text += f" {title.value!r}"

    return text


def _dib_bits(bitmap: int, width: int, height: int) -> bytes:
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height  # 負值 = top-down
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0  # BI_RGB

    buffer = ctypes.create_string_buffer(width * height * 4)

    # GetIconInfo 給的是 DDB，一定要有 DC 才換得出 pixel
    screen_dc = user32.GetDC(0)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)

    try:
        gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            buffer,
            ctypes.byref(header),
            DIB_RGB_COLORS,
        )
    finally:
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)

    return buffer.raw


def cursor_image(handle: int) -> Image.Image | None:
    """handle → RGBA 影像（拿不到就回 None）。"""

    info = ICONINFO()

    if not user32.GetIconInfo(handle, ctypes.byref(info)):
        return None

    try:
        bitmap = info.hbmColor or info.hbmMask
        bm = BITMAP()

        if not gdi32.GetObjectW(bitmap, ctypes.sizeof(BITMAP), ctypes.byref(bm)):
            return None

        width, height = int(bm.bmWidth), int(bm.bmHeight)

        if width <= 0 or height <= 0:
            return None

        color = _dib_bits(info.hbmColor, width, height) if info.hbmColor else None
        mask = _dib_bits(info.hbmMask, width, height) if info.hbmMask else None

        pixels = bytearray(width * height * 4)

        for index in range(width * height):
            offset = index * 4

            if color:
                blue, green, red, alpha = color[offset : offset + 4]
            else:
                blue, green, red, alpha = 0, 0, 0, 255

            if mask is not None:
                if mask[offset]:
                    alpha = 0  # AND mask 有值 = 透明
                elif alpha == 0:
                    alpha = 255  # mask 不透明但沒有 alpha = 純黑輪廓

            pixels[offset] = red
            pixels[offset + 1] = green
            pixels[offset + 2] = blue
            pixels[offset + 3] = alpha

        return Image.frombytes("RGBA", (width, height), bytes(pixels))

    finally:
        for bitmap in (info.hbmColor, info.hbmMask):
            if bitmap:
                gdi32.DeleteObject(bitmap)


def save_cursor(handle: int, scale: int = 8) -> Path | None:
    if not handle:
        print("  (沒有游標)")
        return None

    image = cursor_image(handle)

    if image is None:
        print(f"  0x{handle:X}: 拿不到游標影像（handle 可能已失效）")
        return None

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    path = OUT_DIR / f"cursor_{handle:X}.png"

    image.resize(
        (image.width * scale, image.height * scale),
        Image.Resampling.NEAREST,
    ).save(path)

    hotspot = ""
    info = ICONINFO()
    if user32.GetIconInfo(handle, ctypes.byref(info)):
        hotspot = f"hotspot=({info.xHotspot},{info.yHotspot})"
        for bitmap in (info.hbmColor, info.hbmMask):
            if bitmap:
                gdi32.DeleteObject(bitmap)

    print(f"  0x{handle:X}: {image.width}x{image.height} {hotspot} -> {path}")

    return path


def main(argv: list[str]) -> int:
    if "--watch" in argv:
        index = argv.index("--watch") + 1
        seconds = float(argv[index]) if index < len(argv) else 15.0

        print(f"開始取樣 {seconds:.0f} 秒：handle 一變就存 PNG（現在去拖放檔案）")

        seen: set[int] = set()
        deadline = time.monotonic() + seconds
        last_window = ""

        while time.monotonic() < deadline:
            handle = current_cursor()
            window = window_under_cursor()

            if window != last_window:
                last_window = window
                print(f"[{time.strftime('%H:%M:%S')}] 游標底下的視窗: {window}")

            if handle and handle not in seen:
                seen.add(handle)
                print(f"[{time.strftime('%H:%M:%S')}] 新游標")
                save_cursor(handle)

            time.sleep(0.05)

        print("取樣結束")
        return 0

    if not argv:
        print("目前游標：")
        save_cursor(current_cursor())
        return 0

    for token in argv:
        save_cursor(int(token, 0))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
