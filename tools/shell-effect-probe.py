"""直接問 Windows Shell：這個「來源檔案 → 目的資料夾」組合在按著 Shift 時
到底會給 MOVE 還是 NONE（🚫）。

原理：拖放的「效果」是目的端的 IDropTarget 算出來的。這裡不靠滑鼠、
不靠注入，直接自己組一個 IDataObject（來源檔案清單）、取得目的資料夾的
IDropTarget，然後用不同的 grfKeyState（有沒有 MK_SHIFT / MK_CONTROL）
呼叫 DragEnter / DragOver，把回傳的 effect 印出來。

    DROPEFFECT_NONE = 0    → 游標會是禁用（🚫）
    DROPEFFECT_COPY = 1    → 複製（+）
    DROPEFFECT_MOVE = 2    → 移動
    DROPEFFECT_LINK = 4    → 建立捷徑

用法：
    python tools\\shell-effect-probe.py
    python tools\\shell-effect-probe.py --source "D:\\some\\file.txt" --target "C:\\Users\\me\\Desktop"
"""

from __future__ import annotations

import argparse
import ctypes
import os
import tempfile
from ctypes import POINTER, byref, c_void_p, wintypes
from pathlib import Path

ole32 = ctypes.oledll.ole32
shell32 = ctypes.oledll.shell32
user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.RegisterClipboardFormatW.argtypes = (wintypes.LPCWSTR,)
user32.RegisterClipboardFormatW.restype = wintypes.UINT


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, text: str) -> None:
        super().__init__()
        ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(self))


class POINTL(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


IID_IDataObject = GUID("{0000010e-0000-0000-C000-000000000046}")
IID_IDropTarget = GUID("{00000122-0000-0000-C000-000000000046}")
IID_IShellFolder = GUID("{000214E6-0000-0000-C000-000000000046}")

DROPEFFECT_NAMES = {
    0: "NONE（禁用）",
    1: "COPY（複製）",
    2: "MOVE（移動）",
    4: "LINK（建立捷徑）",
    3: "COPY|MOVE",
}

MK_LBUTTON = 0x0001
MK_SHIFT = 0x0004
MK_CONTROL = 0x0008
MK_ALT = 0x0020

shell32.SHParseDisplayName.argtypes = (
    wintypes.LPCWSTR,
    c_void_p,
    POINTER(c_void_p),
    wintypes.DWORD,
    POINTER(wintypes.DWORD),
)
shell32.SHParseDisplayName.restype = ctypes.c_long
shell32.SHBindToObject.argtypes = (c_void_p, c_void_p, c_void_p, POINTER(GUID), POINTER(c_void_p))
shell32.SHBindToObject.restype = ctypes.c_long


def com_method(interface: c_void_p, index: int, restype, *argtypes):
    """取 COM 介面的第 index 個 vtable 函式。"""

    vtable = ctypes.cast(interface, POINTER(POINTER(c_void_p)))[0]
    prototype = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return prototype(vtable[index])


def release(interface: c_void_p) -> None:
    if interface:
        com_method(interface, 2, ctypes.c_ulong)(interface)


def parse_display_name(path: str) -> c_void_p:
    pidl = c_void_p()
    attributes = wintypes.DWORD()

    shell32.SHParseDisplayName(path, None, byref(pidl), 0, byref(attributes))

    if not pidl:
        raise RuntimeError(f"SHParseDisplayName 失敗：{path}")

    return pidl


def make_data_object(file_path: str) -> c_void_p:
    """用「來源檔案」組一個 shell IDataObject（等同從檔案總管拖出去的東西）。"""

    pidl = parse_display_name(file_path)

    shell_folder = c_void_p()
    pidl_child = c_void_p()

    shell32.SHBindToParent(
        pidl,
        byref(IID_IShellFolder),
        byref(shell_folder),
        byref(pidl_child),
    )

    if not shell_folder:
        raise RuntimeError("拿不到父資料夾的 IShellFolder")

    data_object = c_void_p()

    get_ui_object = com_method(
        shell_folder,
        10,  # IShellFolder::GetUIObjectOf
        ctypes.c_long,
        wintypes.HWND,
        wintypes.UINT,
        POINTER(c_void_p),
        POINTER(GUID),
        POINTER(wintypes.UINT),
        POINTER(c_void_p),
    )

    child_array = (c_void_p * 1)(pidl_child)
    reserved = wintypes.UINT(0)

    get_ui_object(
        shell_folder,
        None,
        1,
        child_array,
        byref(IID_IDataObject),
        byref(reserved),
        byref(data_object),
    )

    release(shell_folder)

    if not data_object:
        raise RuntimeError("拿不到 IDataObject")

    return data_object


def make_drop_target(folder_path: str) -> c_void_p:
    """取得目的資料夾的 IDropTarget（就是決定 🚫 還是 MOVE 的那一方）。"""

    pidl = parse_display_name(folder_path)

    shell_folder = c_void_p()

    shell32.SHBindToObject(
        None,
        pidl,
        None,
        byref(IID_IShellFolder),
        byref(shell_folder),
    )

    if not shell_folder:
        raise RuntimeError(f"拿不到資料夾的 IShellFolder：{folder_path}")

    drop_target = c_void_p()

    create_view_object = com_method(
        shell_folder,
        8,  # IShellFolder::CreateViewObject
        ctypes.c_long,
        wintypes.HWND,
        POINTER(GUID),
        POINTER(c_void_p),
    )

    create_view_object(
        shell_folder,
        None,
        byref(IID_IDropTarget),
        byref(drop_target),
    )

    release(shell_folder)

    if not drop_target:
        raise RuntimeError(f"資料夾沒有 IDropTarget：{folder_path}")

    return drop_target


class DragResult(ctypes.Structure):
    _fields_ = [
        ("effect", wintypes.DWORD),
        ("used_keys", wintypes.DWORD),
        ("button", wintypes.DWORD),
    ]


class FORMATETC(ctypes.Structure):
    _fields_ = [
        ("cfFormat", wintypes.WORD),
        ("ptd", c_void_p),
        ("dwAspect", wintypes.DWORD),
        ("lindex", wintypes.LONG),
        ("tymed", wintypes.DWORD),
    ]


class STGMEDIUM(ctypes.Structure):
    _fields_ = [
        ("tymed", wintypes.DWORD),
        ("hGlobal", c_void_p),
        ("pUnkForRelease", c_void_p),
    ]


DVASPECT_CONTENT = 1
TYMED_HGLOBAL = 1
GMEM_MOVEABLE = 0x0042

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
kernel32.GlobalAlloc.restype = c_void_p
kernel32.GlobalLock.argtypes = (c_void_p,)
kernel32.GlobalLock.restype = c_void_p
kernel32.GlobalUnlock.argtypes = (c_void_p,)
kernel32.GlobalUnlock.restype = wintypes.BOOL


def set_preferred_drop_effect(data_object: c_void_p, effect: int) -> int:
    """在 IDataObject 上設 CFSTR_PREFERREDDROPEFFECT（檔案總管拖曳時會帶這個）。

    回傳 HRESULT（0 = S_OK）。
    """

    format_id = wintypes.UINT(user32.RegisterClipboardFormatW("Preferred DropEffect"))

    if not format_id.value:
        raise RuntimeError("RegisterClipboardFormat(Preferred DropEffect) 失敗")

    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, ctypes.sizeof(wintypes.DWORD))
    pointer = kernel32.GlobalLock(handle)
    ctypes.cast(pointer, POINTER(wintypes.DWORD))[0] = effect
    kernel32.GlobalUnlock(handle)

    format_etc = FORMATETC(
        cfFormat=format_id.value,
        ptd=None,
        dwAspect=DVASPECT_CONTENT,
        lindex=-1,
        tymed=TYMED_HGLOBAL,
    )
    medium = STGMEDIUM(tymed=TYMED_HGLOBAL, hGlobal=handle, pUnkForRelease=None)

    set_data = com_method(
        data_object,
        7,  # IDataObject::SetData
        ctypes.c_long,
        POINTER(FORMATETC),
        POINTER(STGMEDIUM),
        wintypes.BOOL,
    )

    return set_data(data_object, byref(format_etc), byref(medium), True)


def drag_enter_effect(
    data_object: c_void_p,
    drop_target: c_void_p,
    key_state: int,
    allowed: int = 1 | 2 | 4,
) -> tuple[int, int]:
    """回傳 (DragEnter 的 effect, DragOver 的 effect)。

    allowed 就是來源端允許的效果（DoDragDrop 的 dwOKEffects），
    檔案總管會在「拖曳開始那一刻」決定它。
    """

    drag_enter = com_method(
        drop_target,
        3,  # IDropTarget::DragEnter
        ctypes.c_long,
        c_void_p,
        wintypes.DWORD,
        POINTL,
        POINTER(wintypes.DWORD),
    )
    drag_over = com_method(
        drop_target,
        4,  # IDropTarget::DragOver
        ctypes.c_long,
        wintypes.DWORD,
        POINTL,
        POINTER(wintypes.DWORD),
    )
    drag_leave = com_method(
        drop_target,
        5,  # IDropTarget::DragLeave
        ctypes.c_long,
    )

    point = POINTL(40000, 40000)  # 遠離任何項目，避免命中子資料夾

    effect = wintypes.DWORD(allowed)
    drag_enter(drop_target, data_object, key_state, point, byref(effect))
    enter_effect = effect.value

    effect = wintypes.DWORD(allowed)
    drag_over(drop_target, key_state, point, byref(effect))
    over_effect = effect.value

    drag_leave(drop_target)

    return enter_effect, over_effect


def main() -> int:
    parser = argparse.ArgumentParser(description="問 shell：Shift 之下到底給 MOVE 還是 NONE")
    parser.add_argument("--source", action="append", default=[], help="來源檔案（可重複）")
    parser.add_argument("--target", action="append", default=[], help="目的資料夾（可重複）")
    parser.add_argument(
        "--preferred",
        choices=("none", "copy", "move", "copy|move"),
        default="none",
        help="在資料物件上預先塞 CFSTR_PREFERREDDROPEFFECT（模擬拖曳開始時的效果）",
    )
    parser.add_argument(
        "--allowed",
        default="copy,move,link",
        help="來源端允許的效果，逗號分隔：copy,move,link（預設全給）",
    )
    args = parser.parse_args()

    allowed = 0
    for token in args.allowed.split(","):
        token = token.strip().lower()
        if token == "copy":
            allowed |= 1
        elif token == "move":
            allowed |= 2
        elif token == "link":
            allowed |= 4
        elif token:
            raise SystemExit(f"看不懂的效果：{token}")

    preferred_effect = {
        "none": 0,
        "copy": 1,
        "move": 2,
        "copy|move": 3,
    }[args.preferred]

    ole32.OleInitialize(None)

    work = Path(tempfile.gettempdir()) / "prox2_shell_probe"
    (work / "src").mkdir(parents=True, exist_ok=True)
    (work / "dst").mkdir(parents=True, exist_ok=True)

    sample = work / "src" / "probe.txt"
    sample.write_text("probe", encoding="utf-8")

    sources = args.source or [str(sample)]
    targets = args.target or [
        str(work / "dst"),
        str(work / "src"),
        str(Path(os.environ.get("USERPROFILE", "C:/")) / "Desktop"),
    ]

    combos = [
        ("只有左鍵（無修飾鍵）", MK_LBUTTON),
        ("左鍵 + Shift", MK_LBUTTON | MK_SHIFT),
        ("左鍵 + Ctrl", MK_LBUTTON | MK_CONTROL),
        ("左鍵 + Ctrl+Shift", MK_LBUTTON | MK_CONTROL | MK_SHIFT),
        ("左鍵 + Alt", MK_LBUTTON | MK_ALT),
    ]

    print("=" * 78)
    print("直接詢問 Windows Shell 的 IDropTarget（沒有滑鼠、沒有注入按鍵）")
    print("=" * 78)

    for source in sources:
        data_object = make_data_object(source)

        preferred_note = "（沒有設定）"
        if preferred_effect:
            result = set_preferred_drop_effect(data_object, preferred_effect)
            preferred_note = DROPEFFECT_NAMES.get(preferred_effect, str(preferred_effect))
            if result != 0:
                preferred_note += f"（SetData 失敗 0x{result & 0xFFFFFFFF:08X}）"

        print(f"來源檔案：{source}")
        print(f"  資料物件的 Preferred DropEffect：{preferred_note}")

        for target in targets:
            if not Path(target).is_dir():
                print(f"  目的資料夾不存在，跳過：{target}")
                continue

            drop_target = make_drop_target(target)

            print(f"  目的資料夾：{target}")
            for label, key_state in combos:
                enter_effect, over_effect = drag_enter_effect(
                    data_object,
                    drop_target,
                    key_state,
                    allowed,
                )
                enter_name = DROPEFFECT_NAMES.get(enter_effect, str(enter_effect))
                over_name = DROPEFFECT_NAMES.get(over_effect, str(over_effect))
                print(f"    {label:<22} DragEnter={enter_name:<18} DragOver={over_name}")

            release(drop_target)
            print()

        release(data_object)

    print("=" * 78)
    print("解讀：Shift 拿到 NONE 就代表「這個來源→目的不允許移動」，是 Windows 的規則，")
    print("      跟注入方式無關（實體 Shift 也會一樣）。")
    print("=" * 78)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
