"""SUPERSTRIKE 類比按鍵疊圖（單檔版）

原本的 superstrike_overlay.py + effect.py 合併成一支程式，
再加上系統匣 (tray icon)，用法跟 midkey.ahk 一樣可以縮在右下角。

執行：
    pythonw superstrike_overlay_app.py             # 平常使用（不會開主控台）
    python  superstrike_overlay_app.py --debug     # 顯示除錯訊息
    python  superstrike_overlay_app.py --selftest  # 不碰裝置，驗證繪圖並輸出預覽 PNG

行為：
    * 從 Logitech PRO X2 SUPERSTRIKE (HID++) 讀取左鍵行程 (0.0 ~ 1.0)
    * 行程 >= on_threshold 時按住選定的修飾鍵 (Ctrl / Shift / Alt)
    * 按住期間在滑鼠游標位置畫水波紋，中心光暈與內環用該鍵的代表色
    * 系統匣選單：開關疊圖 / 觸發按鍵(Ctrl,Shift,Alt) / 觸發門檻 /
      重新連線裝置 / 結束
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import threading
import traceback
from ctypes import wintypes
from pathlib import Path

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QGuiApplication,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication,
    QMenu,
    QSystemTrayIcon,
    QWidget,
)

# ---------------------------------------------------------------------------
# 設定值
# ---------------------------------------------------------------------------

APP_NAME = "SUPERSTRIKE Overlay"

# 觸發門檻（0.0 ~ 1.0 的按鍵行程）
ON_THRESHOLD = 0.60
OFF_THRESHOLD = 0.20

# 水波紋主題色 (water theme)
WATER_R = 140
WATER_G = 210
WATER_B = 255

# ---------------------------------------------------------------------------
# 觸發按鍵 (Ctrl / Shift / Alt) 與各自的代表色
#   Ctrl  = 洋紅 magenta (255,  72, 170)
#   Shift = 青綠 mint    (  0, 226, 154)
#   Alt   = 計程車黃      (242, 209,   0)
# 洋紅 / 青綠 / 黃在色相環上大約相距 120 度，且都刻意遠離水波紋的
# 淺藍 (140,210,255)，所以三色一眼可分，也不會跟背景主題混淆。
# ---------------------------------------------------------------------------

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12

MODIFIERS: dict[str, dict] = {
    "Ctrl": {"vk": VK_CONTROL, "color": (255, 72, 170), "label": "洋紅"},
    "Shift": {"vk": VK_SHIFT, "color": (0, 226, 154), "label": "青綠"},
    "Alt": {"vk": VK_MENU, "color": (242, 209, 0), "label": "黃"},
}

MODIFIER_ORDER = ("Ctrl", "Shift", "Alt")

DEFAULT_MODIFIER = "Alt"

# 疊圖更新頻率（毫秒，16ms 約 60fps）
POLL_INTERVAL_MS = 16

# HID 讀取執行緒的單次讀取逾時（毫秒）
HID_READ_TIMEOUT_MS = 50

DEBUG = False


def log(*args: object) -> None:
    """--debug 時才輸出訊息（pythonw 沒有主控台，寫檔案也沒有意義）。"""

    if DEBUG:
        print(*args, flush=True)


# ---------------------------------------------------------------------------
# 修飾鍵送出 (ctypes / SendInput，不需要 pywin32)
# ---------------------------------------------------------------------------

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


_user32 = ctypes.WinDLL("user32", use_last_error=True)

_user32.SendInput.argtypes = (
    wintypes.UINT,
    ctypes.POINTER(_INPUT),
    ctypes.c_int,
)
_user32.SendInput.restype = wintypes.UINT


def send_key(vk: int, down: bool) -> None:
    """送出指定虛擬鍵碼的按下 / 放開事件。"""

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

    sent = _user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))

    if sent != 1:
        log(f"SendInput failed: {ctypes.get_last_error()}")


# ---------------------------------------------------------------------------
# 繪圖 (原本的 effect.py)
# ---------------------------------------------------------------------------


class Effect:
    """水波紋疊圖的狀態與繪製。

    原本 effect.py 是模組級全域變數，這裡改成類別實例，
    繪圖的數值計算與原本完全一致。
    """

    def __init__(
        self,
        water: tuple[int, int, int] = (WATER_R, WATER_G, WATER_B),
        modifier_color: tuple[int, int, int] = MODIFIERS[DEFAULT_MODIFIER]["color"],
    ) -> None:

        self.water = water
        self.modifier_color = modifier_color

        self.key_down = False
        self.travel = 0.0

    # -- 狀態 --------------------------------------------------------------

    def set_modifier_color(self, color: tuple[int, int, int]) -> None:
        """切換觸發按鍵時同步換色（中心光暈 + 內環）。"""

        self.modifier_color = color

    def update(
        self,
        key_down: bool,
        travel: float,
    ) -> None:

        self.key_down = key_down
        self.travel = max(0.0, min(1.0, travel))

    def should_draw(self) -> bool:

        return self.key_down

    # -- 繪製 --------------------------------------------------------------

    def render(
        self,
        painter: QPainter,
        pos: QPoint,
    ) -> None:

        #
        # Screen Size
        #
        screen_w = painter.device().width()
        screen_h = painter.device().height()

        base = min(screen_w, screen_h)

        travel = self.travel
        water_r, water_g, water_b = self.water
        key_r, key_g, key_b = self.modifier_color

        #
        # Main Radius
        #
        shock_radius = int(base * (0.03 + travel * 0.08))

        #
        # Ring Width
        #
        ring_width = max(4, int(4 + travel * 8))

        #
        # Center Glow Radius
        #
        core_radius = int(shock_radius * 0.25)

        # ==================================================
        # Center Glow (觸發按鍵代表色)
        # ==================================================

        core_gradient = QRadialGradient(
            float(pos.x()),
            float(pos.y()),
            float(core_radius),
        )

        core_gradient.setColorAt(
            0.00,
            QColor(key_r, key_g, key_b, 220),
        )

        core_gradient.setColorAt(
            0.35,
            QColor(key_r, key_g, key_b, 120),
        )

        core_gradient.setColorAt(
            0.75,
            QColor(key_r, key_g, key_b, 40),
        )

        core_gradient.setColorAt(
            1.00,
            QColor(key_r, key_g, key_b, 0),
        )

        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(QBrush(core_gradient))

        painter.drawEllipse(
            int(pos.x() - core_radius),
            int(pos.y() - core_radius),
            core_radius * 2,
            core_radius * 2,
        )

        # ==================================================
        # Main Shockwave Gradient Ring
        # ==================================================

        ring_outer = shock_radius

        ring_inner = max(
            1,
            shock_radius - ring_width * 3,
        )

        ring_gradient = QRadialGradient(
            float(pos.x()),
            float(pos.y()),
            float(ring_outer),
        )

        inner_stop = ring_inner / ring_outer if ring_outer else 0.0

        ring_gradient.setColorAt(
            0.00,
            QColor(water_r, water_g, water_b, 0),
        )

        ring_gradient.setColorAt(
            max(0.0, inner_stop - 0.08),
            QColor(water_r, water_g, water_b, 0),
        )

        ring_gradient.setColorAt(
            inner_stop,
            QColor(water_r, water_g, water_b, 80),
        )

        ring_gradient.setColorAt(
            min(1.0, inner_stop + 0.05),
            QColor(water_r, water_g, water_b, 220),
        )

        ring_gradient.setColorAt(
            1.00,
            QColor(water_r, water_g, water_b, 0),
        )

        painter.setBrush(QBrush(ring_gradient))

        painter.setPen(Qt.PenStyle.NoPen)

        painter.drawEllipse(
            int(pos.x() - ring_outer),
            int(pos.y() - ring_outer),
            ring_outer * 2,
            ring_outer * 2,
        )

        # ==================================================
        # Secondary Ring (觸發按鍵代表色)
        # ==================================================

        ring_inner_r = int(shock_radius * 0.92)

        inner_pen = QPen(
            QColor(
                key_r,
                key_g,
                key_b,
                215,
            ),
            max(3, ring_width // 2 + 1),
        )

        painter.setPen(inner_pen)

        painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.drawEllipse(
            int(pos.x() - ring_inner_r),
            int(pos.y() - ring_inner_r),
            ring_inner_r * 2,
            ring_inner_r * 2,
        )


# ---------------------------------------------------------------------------
# 按鍵行程來源
# ---------------------------------------------------------------------------


class TravelSource:
    """提供最新的左鍵行程值；讀不到資料時回傳 None。"""

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def reconnect(self) -> None:
        raise NotImplementedError

    def latest(self) -> float | None:
        raise NotImplementedError

    def connected(self) -> bool:
        raise NotImplementedError

    def status_text(self) -> str:
        raise NotImplementedError


class StaticTravelSource(TravelSource):
    """固定值的假來源，給 --selftest 使用（不會去碰 HID 裝置）。"""

    def __init__(self, value: float = 0.5) -> None:
        self.value = value

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def reconnect(self) -> None:
        pass

    def latest(self) -> float | None:
        return self.value

    def connected(self) -> bool:
        return True

    def status_text(self) -> str:
        return "模擬來源 (selftest)"


class SuperstrikeTravelSource(TravelSource):
    """在背景執行緒持續讀取 SUPERSTRIKE 的 event 1 Raw ADC 樣本。

    superstrike_sdk 的 samples() 是阻塞式產生器（單次讀取最多等
    HID_READ_TIMEOUT_MS），所以不能直接在 Qt 的計時器裡跑，否則畫面會頓；
    這裡用一條背景執行緒讀，GUI 只取最新的 normalized 值。
    """

    def __init__(
        self,
        read_timeout_ms: int = HID_READ_TIMEOUT_MS,
    ) -> None:

        self.read_timeout_ms = read_timeout_ms

        self._lock = threading.Lock()
        self._latest: float | None = None
        self._connected = False
        self._error: str | None = None

        self._device = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- 生命週期 ----------------------------------------------------------

    def start(self) -> None:

        if self._thread is not None and self._thread.is_alive():
            return

        self._stop.clear()

        self._thread = threading.Thread(
            target=self._run,
            name="superstrike-reader",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:

        self._stop.set()

        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

        self._thread = None
        self._close_device()

    def reconnect(self) -> None:

        log("reconnect requested")
        self.stop()
        self.start()

    # -- 供 GUI 取用 -------------------------------------------------------

    def latest(self) -> float | None:

        with self._lock:
            return self._latest

    def connected(self) -> bool:

        with self._lock:
            return self._connected

    def status_text(self) -> str:

        with self._lock:
            connected = self._connected
            error = self._error

        if connected:
            return "裝置：已連線"

        if error:
            return f"裝置：未連線 ({error})"

        return "裝置：連線中…"

    # -- 背景執行緒 --------------------------------------------------------

    def _run(self) -> None:

        # 匯入放在執行緒裡：selftest 模式不需要 superstrike_sdk
        import superstrike_sdk

        backoff = 1.0

        while not self._stop.is_set():

            try:
                device = superstrike_sdk.SuperstrikeDevice.open()
            except Exception as exc:
                self._set_error(f"open 失敗: {exc}")
                log(f"device open failed: {exc}")
                self._stop.wait(backoff)
                backoff = min(backoff * 2.0, 5.0)
                continue

            backoff = 1.0

            with self._lock:
                self._device = device
                self._connected = True
                self._error = None

            log("device opened")

            try:
                for sample in device.samples(
                    stop_event=self._stop,
                    timeout_ms=self.read_timeout_ms,
                ):
                    with self._lock:
                        self._latest = sample.left.normalized

            except Exception as exc:
                self._set_error(f"讀取中斷: {exc}")
                log(f"sample loop failed: {exc}")
                log(traceback.format_exc())

            finally:
                with self._lock:
                    self._connected = False
                    self._latest = None
                    self._device = None
                self._close_device(device)
                log("device closed")

            # 中斷後稍等再重連，除非已經被要求停止
            self._stop.wait(backoff)

    def _set_error(self, message: str) -> None:

        with self._lock:
            self._connected = False
            self._error = message

    def _close_device(self, device: object | None = None) -> None:

        target = device

        if target is None:
            with self._lock:
                target = self._device
                self._device = None

        if target is None:
            return

        try:
            target.close()
        except Exception as exc:
            log(f"device close failed: {exc}")


# ---------------------------------------------------------------------------
# 疊圖視窗
# ---------------------------------------------------------------------------


class Overlay(QWidget):
    """全螢幕透明疊圖：滑鼠穿透、置頂、不搶焦點。"""

    def __init__(
        self,
        source: TravelSource,
        effect: Effect,
        on_threshold: float = ON_THRESHOLD,
        off_threshold: float = OFF_THRESHOLD,
        modifier: str = DEFAULT_MODIFIER,
    ) -> None:

        super().__init__()

        self.source = source
        self.effect = effect

        self.on_threshold = on_threshold
        self.off_threshold = off_threshold

        self.modifier = (
            modifier if modifier in MODIFIERS else DEFAULT_MODIFIER
        )
        self.effect.set_modifier_color(MODIFIERS[self.modifier]["color"])

        self.enabled = True
        self.key_down = False
        self.travel = 0.0

        self.cursor_pos = QCursor.pos()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.setGeometry(self._virtual_geometry())

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_overlay)
        self.timer.start(POLL_INTERVAL_MS)

    # -- 視窗 --------------------------------------------------------------

    @staticmethod
    def _virtual_geometry() -> QRect:

        screen = QGuiApplication.primaryScreen()

        if screen is None:
            return QRect(0, 0, 0, 0)

        return screen.virtualGeometry()

    def show_overlay(self) -> None:

        self.setGeometry(self._virtual_geometry())
        self.show()

    # -- 修飾鍵控制 --------------------------------------------------------

    def press_modifier(self) -> None:

        if self.key_down:
            return

        send_key(MODIFIERS[self.modifier]["vk"], True)
        self.key_down = True

        log(f"{self.modifier.upper()} DOWN")

    def release_modifier(self) -> None:

        if not self.key_down:
            return

        send_key(MODIFIERS[self.modifier]["vk"], False)
        self.key_down = False

        log(f"{self.modifier.upper()} UP")

    def set_modifier(self, modifier: str) -> None:

        if modifier not in MODIFIERS or modifier == self.modifier:
            return

        # 先放開舊鍵，避免兩顆鍵同時卡在按下的狀態
        self.release_modifier()

        self.modifier = modifier
        self.effect.set_modifier_color(MODIFIERS[modifier]["color"])

        log(f"modifier = {modifier}")

    # -- 開關 --------------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:

        self.enabled = enabled

        if enabled:
            self.show_overlay()
            log("overlay enabled")
            return

        self.release_modifier()
        self.effect.update(False, 0.0)
        self.hide()
        log("overlay disabled")

    def set_threshold(self, on_threshold: float, off_threshold: float) -> None:

        self.on_threshold = on_threshold
        self.off_threshold = off_threshold

        log(f"threshold = {on_threshold:.2f} / {off_threshold:.2f}")

    # -- 每個 frame --------------------------------------------------------

    def update_overlay(self) -> None:

        travel = self.source.latest()

        if travel is None:
            # 讀不到資料（例如裝置拔掉）就不要讓修飾鍵卡住
            self.release_modifier()
            self.travel = 0.0

        else:
            self.travel = travel

            if self.enabled:

                if not self.key_down and self.travel >= self.on_threshold:
                    self.press_modifier()

                elif self.key_down and self.travel <= self.off_threshold:
                    self.release_modifier()

        self.effect.update(self.key_down, self.travel)

        self.cursor_pos = QCursor.pos()

        self.update()

    # -- 繪製 --------------------------------------------------------------

    def paintEvent(self, event) -> None:

        if not self.effect.should_draw():
            return

        painter = QPainter(self)

        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            self.effect.render(painter, self.mapFromGlobal(self.cursor_pos))

        finally:
            painter.end()

    # -- 收尾 --------------------------------------------------------------

    def closeEvent(self, event) -> None:

        self.release_modifier()
        self.timer.stop()

        event.accept()


# ---------------------------------------------------------------------------
# 系統匣圖示
# ---------------------------------------------------------------------------


# .ico 檔名（放程式目錄，或 PyInstaller 打包時用 --add-data 一起帶進去）
ICON_CANDIDATES = ("x2.ico", "superstrike.ico", "overlay.ico", "icon.ico")


def _resource_dir() -> Path:
    """資源目錄：PyInstaller 打包後是 sys._MEIPASS，開發時是程式所在目錄。"""

    bundle = getattr(sys, "_MEIPASS", None)

    if bundle:
        return Path(bundle)

    return Path(__file__).resolve().parent


def build_icon(size: int = 64) -> QIcon:
    """優先載入 x2.ico 等圖示檔，找不到就用程式畫一個。"""

    override = os.environ.get("SUPERSTRIKE_ICON")

    if override and Path(override).exists():
        icon = QIcon(override)
        if not icon.isNull():
            return icon

    base = _resource_dir()

    for name in ICON_CANDIDATES:
        path = base / name
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = size / 2.0

        # 水波外環
        outer = QRadialGradient(center, center, center - 1.0)
        outer.setColorAt(0.55, QColor(WATER_R, WATER_G, WATER_B, 0))
        outer.setColorAt(0.80, QColor(WATER_R, WATER_G, WATER_B, 220))
        outer.setColorAt(1.00, QColor(WATER_R, WATER_G, WATER_B, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(outer))
        painter.drawEllipse(0, 0, size, size)

        # 中心水光
        core_radius = int(center * 0.5)
        core = QRadialGradient(center, center, core_radius)
        core.setColorAt(0.0, QColor(WATER_R, WATER_G, WATER_B, 230))
        core.setColorAt(1.0, QColor(WATER_R, WATER_G, WATER_B, 0))

        painter.setBrush(QBrush(core))
        painter.drawEllipse(
            int(center - core_radius),
            int(center - core_radius),
            core_radius * 2,
            core_radius * 2,
        )

        # 代表色內環（找不到 .ico 時的備援圖示）
        ring_r = int(center * 0.86)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                QColor(*MODIFIERS[DEFAULT_MODIFIER]["color"], 220),
                max(2, size // 16),
            )
        )
        painter.drawEllipse(
            int(center - ring_r),
            int(center - ring_r),
            ring_r * 2,
            ring_r * 2,
        )

    finally:
        painter.end()

    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# 設定檔（portable：跟 exe / .py 放一起）
# ---------------------------------------------------------------------------

CONFIG_FILENAME = "prox2_config.json"


def _app_dir() -> Path:
    """程式所在目錄（打包後是 exe 旁邊，開發時是 .py 旁邊）。"""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent


def _config_path() -> Path:
    return _app_dir() / CONFIG_FILENAME


def load_config() -> dict:
    """讀設定；檔案不存在或壞掉就回傳空 dict（用預設值）。"""

    path = _config_path()

    if not path.exists():
        return {}

    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))

    except Exception as exc:
        log(f"config load failed: {exc}")
        return {}

    return data if isinstance(data, dict) else {}


def _config_float(config: dict, key: str, default: float) -> float:
    """從設定檔取值轉 float；壞值一律回退預設。"""

    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return default


def save_config(overlay: "Overlay") -> None:
    """把目前的觸發按鍵與門檻寫回設定檔（失敗不影響程式運作）。"""

    try:
        import json

        data = {
            "modifier": overlay.modifier,
            "on_threshold": overlay.on_threshold,
            "off_threshold": overlay.off_threshold,
        }

        _config_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    except Exception as exc:
        log(f"config save failed: {exc}")


def make_color_dot(color: tuple[int, int, int], size: int = 14) -> QIcon:
    """做一顆實心圓點 QIcon，讓選單上直接看到該鍵的代表色。"""

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(0, 0, 0, 140), 1))
        painter.setBrush(QBrush(QColor(*color)))
        painter.drawEllipse(1, 1, size - 2, size - 2)
    finally:
        painter.end()

    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    """系統匣圖示 + 右鍵選單（等同 midkey.ahk 的 A_TrayMenu）。"""

    THRESHOLD_PRESETS = (0.40, 0.50, 0.60, 0.70, 0.80)

    def __init__(
        self,
        app: QApplication,
        overlay: Overlay,
        source: TravelSource,
    ) -> None:

        super().__init__(build_icon(), app)

        self.app = app
        self.overlay = overlay
        self.source = source

        self.threshold_actions: list[tuple[float, QAction]] = []
        self.modifier_actions: list[tuple[str, QAction]] = []

        self.setToolTip(f"{APP_NAME} (啟動中)")

        self._build_menu()

        self.activated.connect(self._on_activated)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(500)

        self._refresh_status()

    # -- 選單 --------------------------------------------------------------

    def _build_menu(self) -> None:

        menu = QMenu()

        self.overlay_action = menu.addAction(self._overlay_action_text())
        self.overlay_action.setCheckable(True)
        self.overlay_action.setChecked(self.overlay.enabled)
        self.overlay_action.toggled.connect(self._set_overlay_enabled)

        # 觸發按鍵：Ctrl / Shift / Alt（左邊的色點 = 疊圖上的代表色）
        self.modifier_menu = menu.addMenu("觸發按鍵 (按住哪一個鍵)")

        for name in MODIFIER_ORDER:

            action = self.modifier_menu.addAction(
                make_color_dot(MODIFIERS[name]["color"]),
                name,
            )
            action.setCheckable(True)
            action.setChecked(name == self.overlay.modifier)
            action.triggered.connect(
                lambda _checked=False, value=name: self._apply_modifier(value)
            )

            self.modifier_actions.append((name, action))

        threshold_menu = menu.addMenu("觸發門檻")

        for preset in self.THRESHOLD_PRESETS:

            action = threshold_menu.addAction(f"{preset:.0%}")
            action.setCheckable(True)
            action.setChecked(abs(preset - self.overlay.on_threshold) < 1e-9)
            action.triggered.connect(
                lambda _checked=False, value=preset: self._apply_threshold(value)
            )

            self.threshold_actions.append((preset, action))

        menu.addSeparator()

        self.status_action = menu.addAction("裝置：…")
        self.status_action.setEnabled(False)

        self.reconnect_action = menu.addAction("重新連線裝置")
        self.reconnect_action.triggered.connect(self.source.reconnect)

        menu.addSeparator()

        self.quit_action = menu.addAction("結束")
        self.quit_action.triggered.connect(self.app.quit)

        self.setContextMenu(menu)

        # 保留參考，避免選單被垃圾回收
        self._menu = menu

    def _overlay_action_text(self) -> str:

        return f"啟用疊圖 (按住 {self.overlay.modifier} 時顯示)"

    def _set_overlay_enabled(self, enabled: bool) -> None:

        self.overlay.set_enabled(enabled)
        self._refresh_status()

    def _apply_modifier(self, modifier: str) -> None:

        self.overlay.set_modifier(modifier)

        # 互斥勾選：只留目前這一個打勾
        for name, action in self.modifier_actions:
            action.setChecked(name == modifier)

        self.overlay_action.setText(self._overlay_action_text())

        save_config(self.overlay)

        log(f"modifier -> {modifier} {MODIFIERS[modifier]['color']}")

        self._refresh_status()

    def _apply_threshold(self, on_threshold: float) -> None:

        off_threshold = max(0.05, round(on_threshold - 0.40, 2))

        self.overlay.set_threshold(on_threshold, off_threshold)

        for preset, action in self.threshold_actions:
            action.setChecked(abs(preset - on_threshold) < 1e-9)

        save_config(self.overlay)

    # -- 狀態 --------------------------------------------------------------

    def _refresh_status(self) -> None:

        status = self.source.status_text()

        if self.status_action.text() != status:
            self.status_action.setText(status)

        tip = (
            f"{APP_NAME}\n"
            f"觸發按鍵：{self.overlay.modifier}"
            f"（{MODIFIERS[self.overlay.modifier]['label']}）\n"
            f"{status}"
        )
        if not self.overlay.enabled:
            tip += "\n疊圖：已停用"

        if self.toolTip() != tip:
            self.setToolTip(tip)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:

        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.overlay_action.setChecked(not self.overlay_action.isChecked())


# ---------------------------------------------------------------------------
# 進入點
# ---------------------------------------------------------------------------


def _set_app_user_model_id() -> None:
    """讓 Windows 把這個程式視為獨立 App（系統匣 / 通知才會正確歸類）。"""

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Simon.SuperstrikeOverlay"
        )
    except Exception:
        pass


_ERROR_ALREADY_EXISTS = 183
_MUTEX_HANDLE = None


def _acquire_single_instance() -> bool:
    """同一時間只允許一個實例，避免兩個程式同時搶著按 Alt。"""

    global _MUTEX_HANDLE

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        kernel32.CreateMutexW.argtypes = (
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateMutexW(None, False, "Local\\SuperstrikeOverlayApp")

        if not handle:
            return True

        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False

        _MUTEX_HANDLE = handle
        return True

    except Exception:
        # 任何意外都當成可以啟動，不要因此打不開程式
        return True


def _warn_already_running() -> None:
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            "SUPERSTRIKE Overlay 已經在執行中。\n請看右下角系統匣的圖示。",
            APP_NAME,
            0x40,  # MB_ICONINFORMATION
        )
    except Exception:
        pass


def _pick_icon_path() -> str | None:
    """PyInstaller 的 --icon 只能吃檔案路徑，這裡找出實際的 .ico。"""

    base = _resource_dir()

    for name in ICON_CANDIDATES:
        path = base / name
        if path.exists():
            return str(path)

    return None


def run_selftest(preview_path: str | None = None) -> int:
    """不接觸真實裝置、不蓋住螢幕，驗證繪圖 / 圖示 / 選單建構是否正常。"""

    app = QApplication.instance() or QApplication(sys.argv[:1])

    effect = Effect()

    pixmap = QPixmap(640, 480)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    try:
        # 每一列 = 一個觸發按鍵，三色並排方便肉眼比對差異
        for row, name in enumerate(MODIFIER_ORDER):
            effect.set_modifier_color(MODIFIERS[name]["color"])

            for index, travel in enumerate((0.2, 0.6, 1.0), start=1):
                effect.update(True, travel)
                effect.render(
                    painter,
                    QPoint(160 * index, 80 + row * 160),
                )
    finally:
        painter.end()

    target = (
        Path(preview_path)
        if preview_path
        else _app_dir() / "overlay_preview.png"
    )

    saved = pixmap.save(str(target))

    icon = build_icon()

    source = StaticTravelSource(0.0)
    overlay = Overlay(source, effect)
    tray = TrayIcon(app, overlay, source)

    menu_labels = [action.text() for action in tray.contextMenu().actions()]
    modifier_labels = [action.text() for action in tray.modifier_menu.actions()]

    print(f"render    : {'OK' if saved else 'FAILED'} -> {target}")
    print(f"icon      : {'OK' if not icon.isNull() else 'FAILED'}")
    print(f"tray      : {'OK' if not tray.icon().isNull() else 'FAILED'}")
    print(
        "overlay   : "
        f"{overlay.geometry().width()}x{overlay.geometry().height()}"
    )
    print(f"menu      : {menu_labels}")
    print(f"modifiers : {modifier_labels} (current={overlay.modifier})")
    print(
        "key colors: "
        + ", ".join(
            f"{name}={MODIFIERS[name]['color']}" for name in MODIFIER_ORDER
        )
    )
    print(f"config    : {_config_path()}")

    overlay.close()

    return 0 if saved and not icon.isNull() else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        prog="superstrike_overlay_app.py",
        description="SUPERSTRIKE 類比按鍵水波紋疊圖（單檔 + 系統匣）",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="輸出除錯訊息（ALT DOWN / ALT UP / 裝置狀態）",
    )

    parser.add_argument(
        "--selftest",
        action="store_true",
        help="不開啟裝置、不顯示疊圖，只驗證繪圖並輸出預覽 PNG",
    )

    parser.add_argument(
        "--preview",
        metavar="PATH",
        default=None,
        help="--selftest 的預覽圖輸出路徑",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:

    global DEBUG

    args = _parse_args(argv)
    DEBUG = args.debug

    if args.selftest:
        return run_selftest(args.preview)

    if not _acquire_single_instance():
        _warn_already_running()
        return 1

    _set_app_user_model_id()

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(build_icon())
    app.setQuitOnLastWindowClosed(False)

    log(f"icon: {_pick_icon_path() or '(內建繪製)'}")

    config = load_config()

    effect = Effect()

    source = SuperstrikeTravelSource()
    source.start()

    overlay = Overlay(
        source,
        effect,
        on_threshold=_config_float(config, "on_threshold", ON_THRESHOLD),
        off_threshold=_config_float(config, "off_threshold", OFF_THRESHOLD),
        modifier=str(config.get("modifier", DEFAULT_MODIFIER)),
    )
    overlay.show_overlay()

    log(
        f"start: modifier={overlay.modifier} "
        f"threshold={overlay.on_threshold:.2f}/{overlay.off_threshold:.2f} "
        f"config={_config_path()}"
    )

    tray = TrayIcon(app, overlay, source)
    tray.show()

    app.aboutToQuit.connect(overlay.close)
    app.aboutToQuit.connect(source.stop)

    exit_code = app.exec()

    # 保險：離開前一定要放開修飾鍵
    overlay.release_modifier()
    source.stop()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
