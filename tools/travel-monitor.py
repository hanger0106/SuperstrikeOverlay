#!/usr/bin/env python3
"""Diagnostic: print SUPERSTRIKE left-button travel in real time.

This reads exactly the same value the overlay uses (sample.left.normalized),
replays the overlay's threshold logic on screen, and reports HID sample gaps
(a gap is when no data arrives - the overlay releases the modifier in that case).

It is READ-ONLY: it never sends key events, so nothing can get stuck.

Usage:
    python tools\\travel-monitor.py
    python tools\\travel-monitor.py --seconds 40 --on 0.4 --off 0.05

Exit the overlay first (tray icon -> Quit) if the device cannot be opened.
"""

from __future__ import annotations

import argparse
import threading
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="SUPERSTRIKE travel monitor (read only)")
    parser.add_argument("--seconds", type=float, default=25.0, help="how long to run")
    parser.add_argument("--on", type=float, default=0.60, help="press threshold")
    parser.add_argument("--off", type=float, default=0.20, help="release threshold")
    parser.add_argument("--interval", type=float, default=0.15, help="seconds between status lines")
    parser.add_argument("--gap", type=float, default=0.10, help="report sample gaps above this (seconds)")
    args = parser.parse_args()

    import superstrike_sdk

    try:
        device = superstrike_sdk.SuperstrikeDevice.open()
    except Exception as exc:
        print(f"ERROR: cannot open device: {exc}")
        print("Hint: quit the overlay from the tray menu, then run this again.")
        return 2

    try:
        info = device.device_info()
    except Exception:
        info = "(unknown)"

    print(f"device     : {info}")
    print(f"thresholds : on={args.on:.2f} off={args.off:.2f}  (same logic as the overlay)")
    print(f"duration   : {args.seconds:.0f}s - press and HOLD the left button, then drag a file across drives")
    print()
    print(f"{'t(s)':>7} {'norm':>6} {'smooth':>7} {'raw':>6} {'rate':>7}  event")
    print("-" * 72)

    stop = threading.Event()
    counter = {"samples": 0}

    def heartbeat() -> None:
        while not stop.is_set():
            time.sleep(3.0)
            if not stop.is_set() and counter["samples"] == 0:
                print("  (waiting for HID samples - press and hold the left button)")

    threading.Thread(target=heartbeat, daemon=True).start()

    timer = threading.Timer(args.seconds, stop.set)
    timer.daemon = True
    timer.start()

    start = time.monotonic()
    next_status = start

    key_down = False
    presses = 0
    releases = 0
    chatter = 0
    last_toggle: float | None = None
    last_ts: int | None = None
    max_gap = 0.0
    min_norm = 1.0
    max_norm = 0.0

    try:
        for sample in device.samples(stop_event=stop, timeout_ms=50):
            counter["samples"] += 1
            now = time.monotonic()
            if now - start > args.seconds:
                break

            travel = sample.left.normalized
            smoothed = sample.left.smoothed

            if travel < min_norm:
                min_norm = travel
            if travel > max_norm:
                max_norm = travel

            event = ""

            if last_ts is not None:
                gap = (sample.timestamp_ns - last_ts) / 1_000_000_000
                if gap > max_gap:
                    max_gap = gap
                if gap > args.gap:
                    print(f"{now - start:7.2f} {'-':>6} {'-':>7} {'-':>6} {'-':>7}  HID GAP {gap * 1000:.0f} ms (overlay would release)")
            last_ts = sample.timestamp_ns

            if not key_down and travel >= args.on:
                if last_toggle is not None and (now - last_toggle) < 0.5:
                    chatter += 1
                key_down = True
                presses += 1
                last_toggle = now
                event = ">>> PRESS modifier"
            elif key_down and travel <= args.off:
                key_down = False
                releases += 1
                last_toggle = now
                event = "<<< RELEASE modifier"

            if event or now >= next_status:
                rate = sample.sample_rate_hz or 0.0
                print(
                    f"{now - start:7.2f} {travel:6.2f} {smoothed:7.3f} "
                    f"{sample.left.raw_code:6d} {rate:7.1f}  {event}"
                )
                next_status = now + args.interval
    except KeyboardInterrupt:
        print("\n(interrupted)")
    finally:
        stop.set()
        timer.cancel()
        try:
            device.close()
        except Exception:
            pass

    elapsed = time.monotonic() - start
    print("-" * 72)
    print(f"samples        : {counter['samples']} in {elapsed:.1f}s")
    print(f"norm range     : {min_norm:.2f} .. {max_norm:.2f}")
    print(f"max HID gap    : {max_gap * 1000:.0f} ms")
    print(f"press events   : {presses}")
    print(f"release events : {releases}")
    print(f"chatter (<0.5s): {chatter}")
    print(f"final state    : {'DOWN (modifier still held)' if key_down else 'UP'}")

    if counter["samples"] == 0:
        print()
        print("No samples received. The device may be busy (another app holds it) or asleep.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
