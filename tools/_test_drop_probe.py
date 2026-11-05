"""用合成的拖放事件檢查 drop-probe.py 的記錄邏輯（不開視窗、不需要真的拖放）。

執行： python tools\\_test_drop_probe.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
)
from PyQt6.QtWidgets import QApplication

spec = importlib.util.spec_from_file_location(
    "drop_probe",
    Path(__file__).with_name("drop-probe.py"),
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

app = QApplication([])

probe = module.DropProbe()
probe.auto_shift.setChecked(False)

mime = QMimeData()
mime.setUrls([QUrl.fromLocalFile("D:/tmp/sample.txt")])

ACTIONS_ALL = (
    Qt.DropAction.CopyAction | Qt.DropAction.MoveAction | Qt.DropAction.LinkAction
)
ACTIONS_COPY = Qt.DropAction.CopyAction

BUTTONS = Qt.MouseButton.LeftButton
NO_MODIFIER = Qt.KeyboardModifier.NoModifier
SHIFT_MODIFIER = Qt.KeyboardModifier.ShiftModifier

CASES = [
    ("allowed=Copy|Move|Link, no modifier", ACTIONS_ALL, NO_MODIFIER),
    ("allowed=Copy|Move|Link, physical Shift", ACTIONS_ALL, SHIFT_MODIFIER),
    ("allowed=Copy only, no modifier", ACTIONS_COPY, NO_MODIFIER),
]

for label, actions, modifiers in CASES:
    print(f"--- {label} ---")

    probe.dragEnterEvent(
        QDragEnterEvent(QPointF(10, 10), actions, mime, BUTTONS, modifiers)
    )
    probe.dragMoveEvent(
        QDragMoveEvent(QPointF(12, 12), actions, mime, BUTTONS, modifiers)
    )
    probe.dropEvent(QDropEvent(QPointF(12, 12), actions, mime, BUTTONS, modifiers))
    probe.dragLeaveEvent(QDragLeaveEvent())

text = probe.log.toPlainText()

print("--- log ---")
print(text)

assert "possible=Copy|Move|Link" in text, "沒有記錄到 possibleActions"
assert "允許清單有 MOVE" in text, "缺少『有 MOVE』的結論"
assert "允許清單沒有 MOVE" in text, "缺少『沒有 MOVE』的結論"
assert "modifiers=Shift" in text, "沒有記錄到實體 Shift"
assert probe._injected is False, "沒勾選時不該注入 Shift"

print()
print("OK: drop-probe 的記錄邏輯正常")
