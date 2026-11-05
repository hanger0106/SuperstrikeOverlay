"""檢查疊圖視窗是否會影響「游標命中測試」（WindowFromPoint / WM_NCHITTEST）。

Windows 的 OLE 拖放在每一次滑鼠移動時，都是用 WindowFromPoint 找出
游標底下的視窗、再往上找有註冊 IDropTarget 的那一個。如果疊圖視窗
被 WindowFromPoint 選中（不是 HTTRANSPARENT），拖放的效果就會被
「不是拖放目標的視窗」或「權限層級不同的視窗」蓋掉，游標就變成
禁用（🚫）符號，而且放手也不會複製/移動。

本程式會建立跟 superstrike_overlay_app.Overlay 一樣的視窗，
印出 exstyle、WM_NCHITTEST 結果，以及 WindowFromPoint 實際選到誰。
不會送出任何按鍵。

執行： python tools\\_probe_hittest.py
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import superstrike_overlay_app as app_mod  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.WindowFromPoint.argtypes = (wintypes.POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
user32.GetCursorPos.restype = wintypes.BOOL
user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.SendMessageW.restype = wintypes.LPARAM
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.GetWindowLongW.restype = wintypes.LONG
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetDesktopWindow.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND

WM_NCHITTEST = 0x0084
GWL_EXSTYLE = -20

EXSTYLE_NAMES = {
    0x00000008: "WS_EX_TOPMOST",
    0x00000020: "WS_EX_TRANSPARENT",
    0x00000080: "WS_EX_TOOLWINDOW",
    0x00040000: "WS_EX_APPWINDOW",
    0x00080000: "WS_EX_LAYERED",
    0x02000000: "WS_EX_COMPOSITED",
    0x08000000: "WS_EX_NOACTIVATE",
}

HT_NAMES = {
    -1: "HTTRANSPARENT（滑鼠穿透，WindowFromPoint 會跳過）",
    0: "HTNOWHERE",
    1: "HTCLIENT",
    2: "HTCAPTION",
}


def describe(hwnd: int) -> str:
    if not hwnd:
        return "(null)"

    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    return f"hwnd=0x{hwnd:X} class={buf.value!r} pid={pid.value}"


def decode_exstyle(value: int) -> str:
    names = [name for bit, name in EXSTYLE_NAMES.items() if value & bit]
    return f"0x{value & 0xFFFFFFFF:08X} ({', '.join(names) if names else '無'})"


def main() -> int:
    qapp = QApplication([])

    # 不要真的送出按鍵（只為了讓疊圖進入「正在畫水波紋」的狀態）
    app_mod.send_key = lambda vk, down: None  # type: ignore[assignment]

    # travel 0.9 -> 超過門檻 -> key_down=True -> paintEvent 會畫水波紋
    source = app_mod.StaticTravelSource(0.9)
    effect = app_mod.Effect()

    overlay = app_mod.Overlay(
        source,
        effect,
        on_threshold=app_mod.ON_THRESHOLD,
        off_threshold=app_mod.OFF_THRESHOLD,
        modifier="Shift",
    )

    overlay.show_overlay()
    qapp.processEvents()

    results: list[str] = []

    def probe_point(x: int, y: int, note: str, hwnd: int) -> None:
        """在指定點問 WindowFromPoint 選到誰。"""

        point = wintypes.POINT(x, y)
        under = user32.WindowFromPoint(point)

        results.append(f"  ({x},{y}) {note}")
        results.append(f"    WindowFromPoint -> {describe(under)}")
        results.append(
            "    "
            + (
                "❌ 選到疊圖視窗：拖放會被擋（OLE 找不到 drop target → 🚫）"
                if under == hwnd
                else "✅ 沒選到疊圖視窗"
            )
        )

    def probe() -> None:
        hwnd = int(overlay.winId())
        rect = overlay.geometry()

        center_x = rect.center().x()
        center_y = rect.center().y()

        cursor_x, cursor_y = overlay.cursor_pos.x(), overlay.cursor_pos.y()

        # Qt 的座標是邏輯像素；WindowFromPoint 要實體像素。直接用 Win32 拿。
        physical = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(physical))

        ratio = overlay.screen().devicePixelRatio() if overlay.screen() else 1.0

        exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

        hit = user32.SendMessageW(
            hwnd,
            WM_NCHITTEST,
            0,
            (center_y << 16) | (center_x & 0xFFFF),
        )

        results.append(f"疊圖視窗      : {describe(hwnd)}")
        results.append(f"geometry      : {rect.x()},{rect.y()} {rect.width()}x{rect.height()}")
        results.append(f"exstyle       : {decode_exstyle(exstyle)}")
        results.append(f"WM_NCHITTEST  : {hit} = {HT_NAMES.get(hit, '其他')}")
        results.append(
            f"畫圖狀態      : key_down={overlay.key_down} "
            f"should_draw={effect.should_draw()} travel={overlay.travel:.2f}"
        )
        results.append(f"水波紋畫在    : ({cursor_x},{cursor_y})（Qt 邏輯座標）")
        results.append(
            f"實際游標      : ({physical.x},{physical.y})（實體像素，DPI={ratio:g}）"
        )

        # 截一張水波紋附近的圖，證明「真的有畫出來」
        try:
            from PIL import Image, ImageGrab

            box = (cursor_x - 150, cursor_y - 150, cursor_x + 150, cursor_y + 150)
            shot = ImageGrab.grab(bbox=box, all_screens=True)
            path = Path(__file__).resolve().parent / "_cursor_shots" / "ripple_check.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            shot.resize(
                (shot.width * 2, shot.height * 2),
                Image.Resampling.NEAREST,
            ).save(path)
            results.append(f"截圖          : {path}")
        except Exception as exc:
            results.append(f"截圖          : 失敗 ({exc})")

        probe_point(center_x, center_y, "螢幕中心（水波紋外，alpha=0）", hwnd)
        probe_point(cursor_x, cursor_y, "Qt 邏輯座標（水波紋中心）", hwnd)
        probe_point(physical.x, physical.y, "實體像素（真正的游標位置）", hwnd)

        results.append(f"DesktopWindow : {describe(user32.GetDesktopWindow())}")
        results.append(f"ForegroundWnd : {describe(user32.GetForegroundWindow())}")

        overlay.hide()
        qapp.quit()

    QTimer.singleShot(400, probe)
    qapp.exec()

    print("\n".join(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
