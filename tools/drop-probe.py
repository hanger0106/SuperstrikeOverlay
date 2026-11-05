"""把檔案從檔案總管拖到這個視窗，直接看 OLE 拖放真正的參數。

為什麼需要這個：
    拖放的效果不是「每次移動都重新問一次」，來源端在 DoDragDrop() 當下就
    把「允許的效果」(dwOKEffects) 固定住了。Qt 的 QDragEnterEvent
    .possibleActions() 就是那個值。

    * possibleActions 有 Move  → Shift（要求 Move）會被接受
    * possibleActions 沒有 Move → Shift 會被拒絕，總管回 DROPEFFECT_NONE，
      游標就是禁用（🚫），放手也什麼都不會發生

用法：
    python tools\\drop-probe.py

    1. 從檔案總管把一個檔案拖到這個視窗上（先不要放手）
    2. 視窗會在 2 秒後自動注入 Shift（可利用核取方塊關掉），
       觀察 log 裡的 possibleActions / proposedAction 有沒有變
    3. 也可以直接用實體 Shift 鍵做對照
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

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


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


def send_key(vk: int, down: bool) -> None:
    event = _INPUT(
        type=INPUT_KEYBOARD,
        u=_INPUTUNION(
            ki=_KEYBDINPUT(
                wVk=vk,
                wScan=0,
                dwFlags=0 if down else KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )
    user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))


def _value(action) -> int:
    """PyQt6 的 Qt.DropAction / KeyboardModifier 是 Python enum，不能直接 int()。"""

    return int(getattr(action, "value", action))


def action_text(action) -> str:
    from PyQt6.QtCore import Qt as QtEnum

    names = []
    mapping = [
        (QtEnum.DropAction.CopyAction, "Copy"),
        (QtEnum.DropAction.MoveAction, "Move"),
        (QtEnum.DropAction.LinkAction, "Link"),
        (QtEnum.DropAction.IgnoreAction, "Ignore"),
        (QtEnum.DropAction.TargetMoveAction, "TargetMove"),
    ]
    for flag, name in mapping:
        if action & flag:
            names.append(name)
    return "|".join(names) if names else f"0x{_value(action):X}"


def modifier_text(modifiers) -> str:
    from PyQt6.QtCore import Qt as QtEnum

    names = []
    if modifiers & QtEnum.KeyboardModifier.ShiftModifier:
        names.append("Shift")
    if modifiers & QtEnum.KeyboardModifier.ControlModifier:
        names.append("Ctrl")
    if modifiers & QtEnum.KeyboardModifier.AltModifier:
        names.append("Alt")
    return "+".join(names) if names else "（無）"


class DropProbe(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("OLE 拖放參數觀察器")
        self.resize(720, 420)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)

        layout.addWidget(
            QLabel(
                "從檔案總管把檔案拖進來，停在視窗上不要放手。\n"
                "possibleActions = 來源端允許的效果（拖放開始那一刻就固定了）"
            )
        )

        self.auto_shift = QCheckBox("停在視窗上 2 秒後自動注入 Shift（模擬深按滑鼠；做實體鍵對照時請取消勾選）")
        self.auto_shift.setChecked(False)
        layout.addWidget(self.auto_shift)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        self._last_state: tuple[int, int] | None = None
        self._injected = False
        self._timer: QTimer | None = None

    # -- 記錄 --------------------------------------------------------------

    def write(self, text: str) -> None:
        self.log.appendPlainText(text)

    def describe(self, event) -> str:
        possible = event.possibleActions()

        if possible & Qt.DropAction.MoveAction:
            verdict = "允許清單有 MOVE（中途注入 Shift 會被接受）"
        else:
            verdict = "允許清單沒有 MOVE（中途注入 Shift 一定變禁用 🚫）"

        return (
            f"possible={action_text(possible)}"
            f"  proposed={action_text(event.proposedAction())}"
            f"  modifiers={modifier_text(event.modifiers())}"
            f"\n           → {verdict}"
        )

    # -- 拖放事件 ----------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        self._last_state = None
        self._injected = False

        urls = [url.toString() for url in event.mimeData().urls()]
        self.write(f"DragEnter  {self.describe(event)}")
        self.write(f"           資料：{urls}")

        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

        if self.auto_shift.isChecked() and self._timer is None:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.inject_shift)
            self._timer.start(2000)

    def dragMoveEvent(self, event) -> None:
        state = (_value(event.possibleActions()), _value(event.proposedAction()))

        if state != self._last_state:
            self._last_state = state
            self.write(f"DragMove   {self.describe(event)}")

        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dropEvent(self, event) -> None:
        self.write(f"Drop       {self.describe(event)}")
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.release_shift()

    def dragLeaveEvent(self, event) -> None:
        self.write("DragLeave")
        self.release_shift()
        event.accept()

    # -- 注入 --------------------------------------------------------------

    def inject_shift(self) -> None:
        if self._injected:
            return

        self._injected = True
        self.write("---- 注入 Shift DOWN ----")
        send_key(VK_SHIFT, True)

        QTimer.singleShot(2500, self.release_shift)

    def release_shift(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

        if not self._injected:
            return

        self._injected = False
        self.write("---- 放開 Shift ----")
        send_key(VK_SHIFT, False)


def main() -> int:
    app = QApplication(sys.argv)
    window = DropProbe()
    window.show()

    try:
        return app.exec()
    finally:
        send_key(VK_SHIFT, False)


if __name__ == "__main__":
    raise SystemExit(main())
