"""回歸測試：疊圖必須是「真正的 click-through」。

背景：Windows 對 layered window 的命中測試是「按像素 alpha」判斷的。
水波紋中心光暈畫在游標底下時（alpha > 0），WindowFromPoint 會選到疊圖
視窗 → OLE 拖放找不到 IDropTarget → 游標變禁用（🚫）、放手也不會動作。
所以疊圖一定要帶 WS_EX_TRANSPARENT（真正穿透）。

本測試會讓疊圖處於「正在畫水波紋」的狀態（send_key 已換成 no-op，不會
真的送出按鍵），然後檢查：
    1. exstyle 有 WS_EX_TRANSPARENT
    2. key_down / should_draw 為 True（真的有在畫）
    3. WindowFromPoint(游標實體座標) 不是疊圖視窗

執行： python tools\\_test_click_through.py
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import superstrike_overlay_app as overlay_mod  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.WindowFromPoint.argtypes = (wintypes.POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetClassNameW.restype = ctypes.c_int

# 不要真的送出按鍵，只讓疊圖進入「正在畫水波紋」的狀態
overlay_mod.send_key = lambda vk, down: None  # type: ignore[assignment]

app = QApplication([])

overlay = overlay_mod.Overlay(
    overlay_mod.StaticTravelSource(0.9),
    overlay_mod.Effect(),
    on_threshold=overlay_mod.ON_THRESHOLD,
    off_threshold=overlay_mod.OFF_THRESHOLD,
    modifier="Shift",
)

overlay.show_overlay()
app.processEvents()

failures: list[str] = []
lines: list[str] = []


def check() -> None:
    hwnd = int(overlay.winId())
    ex_style = int(overlay_mod._get_window_long(hwnd, overlay_mod.GWL_EXSTYLE))

    lines.append(f"hwnd          = 0x{hwnd:X}")
    lines.append(f"exstyle       = 0x{ex_style:08X}")
    lines.append(f"key_down      = {overlay.key_down}")
    lines.append(f"should_draw   = {overlay.effect.should_draw()}")

    if not ex_style & overlay_mod.WS_EX_TRANSPARENT:
        failures.append("exstyle 少了 WS_EX_TRANSPARENT（疊圖會擋住拖放）")

    if not overlay.key_down or not overlay.effect.should_draw():
        failures.append("疊圖沒有進入繪製狀態，這個測試就失去意義")

    position = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(position))

    under = int(user32.WindowFromPoint(position) or 0)

    class_name = ctypes.create_unicode_buffer(128)
    if under:
        user32.GetClassNameW(under, class_name, 128)

    lines.append(f"WindowFromPoint({position.x},{position.y}) -> 0x{under:X} {class_name.value!r}")

    if under == hwnd:
        failures.append("WindowFromPoint 選到疊圖視窗：拖放會被擋掉（🚫）")

    app.quit()


QTimer.singleShot(400, check)
app.exec()

print("\n".join(lines))
print()

if failures:
    for failure in failures:
        print(f"FAIL: {failure}")
    raise SystemExit(1)

print("OK: 疊圖是真正的 click-through，畫水波紋時也不會擋拖放")
