# 第三方元件授權（Third-Party Notices）

本專案使用下列第三方元件。散布本專案（含打包後的 `SuperstrikeOverlay.exe`）時，
請一併保留本檔案與各元件要求的授權聲明。

---

## 1. superstrike-sdk 0.1.0 — MIT License

- 專案：<https://github.com/fawhfi/superstrike-sdk>
- 使用版本：commit `e875b4bef31ed94a98933b0195dbc81135bea8b4`（v0.1.0）
- 作者標示：*Superstrike SDK contributors*
- 用途：Logitech PRO X2 SUPERSTRIKE 的 HID++ 無線特徵讀取（Raw ADC → normalized / smoothed 行程值）。
  本專案的 HID 讀取完全由此 SDK 提供，本專案未自行實作 HID 協定。

```text
MIT License

Copyright (c) 2026 Superstrike SDK contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 2. hidapi（Python binding：`hidapi`）— BSD-3-Clause / GPL-3.0 雙授權

- 專案：<https://github.com/trezor/cython-hidapi>
- 底層：<https://github.com/libusb/hidapi>
- 用途：`superstrike-sdk` 的底層 HID 傳輸（`HidApiTransport`）。

---

## 3. PyQt6 / Qt 6 — GPL-3.0 或商業授權

- 專案：<https://riverbankcomputing.com/software/pyqt/>
- 用途：透明置頂疊圖視窗、`QPainter` 水波紋繪圖、`QSystemTrayIcon` 系統匣。
- ⚠️ **注意**：PyQt6 採 GPL-3.0（或向 Riverbank 購買商業授權）。
  若你要**對外散布**本程式（含 GitHub Releases 上的 exe），GPL 的傳染性與原始碼提供義務
  需要一併評估；若僅自己使用則不受散布條款影響。

---

## 4. PyInstaller — GPL-2.0 with bootloader exception

- 專案：<https://pyinstaller.org/>
- 用途：打包成單一 `--onefile --windowed` exe。
  Bootloader exception 允許以非 GPL 授權散布打包後的產物。

---

## 5. 商標

「Logitech」「PRO X2」「SUPERSTRIKE」為 Logitech 的商標。本專案為非官方愛好者專案，
與 Logitech 無任何關聯，也未獲其背書。
