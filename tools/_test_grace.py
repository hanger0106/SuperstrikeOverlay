"""Temporary check for Overlay._update_modifier (release grace). No keys are sent."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import superstrike_overlay_app as overlay_mod
from PyQt6.QtWidgets import QApplication

calls = []
overlay_mod.send_key = lambda vk, down: calls.append((hex(vk), down))

app = QApplication([])

source = overlay_mod.StaticTravelSource(0.0)
effect = overlay_mod.Effect()

ov = overlay_mod.Overlay(
    source,
    effect,
    on_threshold=0.6,
    off_threshold=0.2,
    modifier="Shift",
)

print("grace =", overlay_mod.RELEASE_GRACE_MS, "ms")


def feed(value, note=""):
    ov._update_modifier(value)
    print(f"  travel={value:.2f} key_down={ov.key_down!s:5} calls={calls} {note}")


print("1) press then hold then dip below off_threshold")
feed(0.30)
feed(0.70, "<- expect PRESS")
feed(0.50)
feed(0.10, "<- expect NO release yet (grace)")

print("2) still below after grace -> release")
time.sleep((overlay_mod.RELEASE_GRACE_MS + 60) / 1000.0)
feed(0.10, "<- expect RELEASE")

print("3) bounce: dip then back above off_threshold cancels the scheduled release")
calls.clear()
feed(0.70, "<- PRESS")
feed(0.10, "<- schedule")
feed(0.35, "<- cancel schedule")
time.sleep((overlay_mod.RELEASE_GRACE_MS + 60) / 1000.0)
feed(0.35, "<- must still be held")
feed(0.10, "<- schedule again")
time.sleep((overlay_mod.RELEASE_GRACE_MS + 60) / 1000.0)
feed(0.10, "<- release")

print("4) release_modifier() clears the schedule")
calls.clear()
feed(0.70, "<- PRESS")
ov.release_modifier()
print(f"  after manual release: key_down={ov.key_down} deadline={ov._release_deadline}")

expected = [(hex(0x10), True), (hex(0x10), False)]
print("FINAL calls (case 3+4):", calls)
ov.close()
