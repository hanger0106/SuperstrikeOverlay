"""在「同一次檔案總管拖放」中，逐一比較不同的修飾鍵注入方式，並把游標存成 PNG。

目的：找出為什麼「注入的 Shift」會讓拖放游標變成禁用（🚫），但實體 Shift
不會。做法是把每一種注入方式都試一遍，看哪一種能讓總管顯示正常的
移動/複製游標。

用法：
    python tools\\drag-modifier-probe.py                  # 倒數 8 秒後開始
    python tools\\drag-modifier-probe.py --delay 12 --hold 1.2

流程：
    1. 倒數期間請「開始拖放」一個檔案（例如 D:\\ 拖到 C:\\），
       左鍵按住不放，停留在目標資料夾上，整個腳本跑完前都不要放手。
    2. 腳本會依序：送修飾鍵 → 取樣游標 → 放開 → 等待，並印出游標 handle。
    3. 每顆新游標都會存成 tools\\_cursor_shots\\cursor_<handle>.png，
       可以直接看圖辨認是「移動 / 複製 / 捷徑 / 禁用」。
    4. 腳本結束後才放手，看檔案最後有沒有真的被複製/移動。

注意：所有修飾鍵都會在結束時強制放開（Ctrl+C 也一樣）。
"""

from __future__ import annotations

import argparse
import ctypes
import time
from ctypes import byref, wintypes

from _cursor_shot import CURSORINFO, current_cursor, save_cursor

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

_ULONG_PTR = (
    ctypes.c_ulonglong
    if ctypes.sizeof(ctypes.c_void_p) == 8
    else ctypes.c_ulong
)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUTUNION),
    ]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.keybd_event.argtypes = (wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, _ULONG_PTR)
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short

# 觀察「游標底下現在是哪個視窗」：拖放游標變成 🚫 時，OLE 就是找不到
# 任何註冊了 IDropTarget 的視窗。
user32.WindowFromPoint.argtypes = (wintypes.POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD


def window_under_cursor() -> str:
    """回傳游標底下視窗的「class (pid) 標題」。"""

    info = CURSORINFO()
    info.cbSize = ctypes.sizeof(CURSORINFO)

    if not user32.GetCursorInfo(ctypes.byref(info)):
        return "n/a"

    point = wintypes.POINT(info.ptScreenPos.x, info.ptScreenPos.y)
    handle = user32.WindowFromPoint(point)

    if not handle:
        return "n/a"

    class_name = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(handle, class_name, 128)

    title = ctypes.create_unicode_buffer(128)
    user32.GetWindowTextW(handle, title, 128)

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, byref(pid))

    text = f"{class_name.value} (pid={pid.value})"

    if title.value:
        text += f" {title.value!r}"

    return text


def _mouse_nudge() -> None:
    """原地 1px 來回，逼拖放迴圈重新計算效果。"""

    for dx in (1, -1):
        event = _INPUT(
            type=0,  # INPUT_MOUSE
            u=_INPUTUNION(
                mi=_MOUSEINPUT(
                    dx=dx,
                    dy=0,
                    mouseData=0,
                    dwFlags=0x0001,  # MOUSEEVENTF_MOVE
                    time=0,
                    dwExtraInfo=0,
                )
            ),
        )
        user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))
        time.sleep(0.01)


def send_input_vk(vk: int, scan: int, extra_flags: int):
    """SendInput + 指定 VK / scan code。"""

    def send(down: bool) -> bool:
        flags = extra_flags | (0 if down else KEYEVENTF_KEYUP)
        event = _INPUT(
            type=INPUT_KEYBOARD,
            u=_INPUTUNION(
                ki=_KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
            ),
        )
        return user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT)) == 1

    return send


def send_keybd_event(vk: int, scan: int):
    """舊 API keybd_event（很多老工具用它）。"""

    def send(down: bool) -> bool:
        user32.keybd_event(vk, scan, 0 if down else KEYEVENTF_KEYUP, 0)
        return True

    return send


VK_SHIFT = 0x10
VK_LSHIFT = 0xA0
VK_CONTROL = 0x11
VK_MENU = 0x12
SCAN_LSHIFT = 0x2A

# (顯示名稱, 監看的 VK, 送出函式)
VARIANTS = [
    ("baseline（完全不送鍵）", VK_SHIFT, lambda down: True),
    (
        "SendInput VK_SHIFT scan=0        <- 目前 app 的做法",
        VK_SHIFT,
        send_input_vk(VK_SHIFT, 0, 0),
    ),
    ("SendInput VK_LSHIFT scan=0", VK_LSHIFT, send_input_vk(VK_LSHIFT, 0, 0)),
    ("SendInput VK_SHIFT scan=0x2A", VK_SHIFT, send_input_vk(VK_SHIFT, SCAN_LSHIFT, 0)),
    (
        "SendInput scan=0x2A +KEYEVENTF_SCANCODE",
        VK_SHIFT,
        send_input_vk(0, SCAN_LSHIFT, KEYEVENTF_SCANCODE),
    ),
    ("keybd_event VK_SHIFT scan=0x2A", VK_SHIFT, send_keybd_event(VK_SHIFT, SCAN_LSHIFT)),
    ("SendInput VK_CONTROL scan=0     <- 對照組", VK_CONTROL, send_input_vk(VK_CONTROL, 0, 0)),
    ("SendInput VK_MENU scan=0        <- 對照組", VK_MENU, send_input_vk(VK_MENU, 0, 0)),
]


def sample(duration: float, interval: float = 0.05) -> list[tuple[int, str]]:
    samples: list[tuple[int, str]] = []
    deadline = time.monotonic() + duration

    while time.monotonic() < deadline:
        handle = current_cursor()
        if handle:
            samples.append((handle, window_under_cursor()))
        time.sleep(interval)

    return samples


def dominant(values: list[int]) -> int:
    if not values:
        return 0
    return max(set(values), key=values.count)


def main() -> int:
    parser = argparse.ArgumentParser(description="拖放中比較各種修飾鍵注入方式")
    parser.add_argument("--delay", type=int, default=8, help="開始前倒數幾秒（預設 8）")
    parser.add_argument("--hold", type=float, default=1.0, help="每個變體按住幾秒（預設 1.0）")
    parser.add_argument("--settle", type=float, default=0.6, help="變體間空檔秒數（預設 0.6）")
    parser.add_argument("--nudge", action="store_true", help="送鍵後原地 1px 抖動，逼總管重算")
    args = parser.parse_args()

    print("=" * 74)
    print("現在開始拖放一個檔案（例如 D:\\ 的檔案拖到 C:\\ 的資料夾）")
    print("左鍵按住不放，停在目標資料夾上，腳本跑完才可以放手。")
    print("=" * 74)

    for remaining in range(args.delay, 0, -1):
        print(f"  倒數 {remaining}s  cursor=0x{current_cursor():X}")
        time.sleep(1)

    saved: dict[int, str] = {}
    rows: list[tuple[str, int, int, list[tuple[int, str]], bool]] = []
    pressed = None

    try:
        for label, vk, send in VARIANTS:
            before = current_cursor()
            if before not in saved:
                saved[before] = str(save_cursor(before))

            send(True)
            pressed = (vk, send)

            time.sleep(0.30)

            if args.nudge:
                _mouse_nudge()

            handles = sample(args.hold)
            held = (user32.GetAsyncKeyState(vk) & 0x8000) != 0

            send(False)
            pressed = None

            time.sleep(args.settle)

            rows.append(
                (
                    label,
                    before,
                    dominant([handle for handle, _ in handles]),
                    handles,
                    held,
                )
            )

    finally:
        if pressed is not None:
            pressed[1](False)

        # 保險：把所有修飾鍵都放開
        for vk in (VK_SHIFT, VK_LSHIFT, VK_CONTROL, VK_MENU):
            if (user32.GetAsyncKeyState(vk) & 0x8000) != 0:
                send_input_vk(vk, 0, 0)(False)

        print()
        print("=" * 74)
        print(f"{'變體':<42}{'按下前':>13}{'按住中':>13}  判定")
        print("-" * 74)

        for label, before, during, handles, held in rows:
            verdict = "沒變（總管沒反應）" if during == before else "游標改變"
            print(f"{label:<42}0x{before:<11X}0x{during:<11X}  {verdict}")

            for handle, window in handles[:1]:
                print(f"{'':<42}游標底下的視窗: {window}")

            unique = sorted({f"0x{h:X}" for h, _ in handles})
            if len(unique) > 1:
                print(f"{'':<42}期間出現: {', '.join(unique)}")
            if not held:
                print(f"{'':<42}注意：系統沒把這個 VK 當成按下了")

        print("-" * 74)
        print("游標圖檔（放大 8 倍，可直接開啟比對）：")
        for handle, path in sorted(saved.items()):
            print(f"  0x{handle:X} -> {path}")
        print("=" * 74)
        print("現在可以放手了：看檔案是否真的被複製/移動，並對照上面的 PNG。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
