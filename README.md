# SUPERSTRIKE Overlay

**⬇️ 下載執行檔（免安裝，Windows 10 / 11 x64）**
<https://github.com/hanger0106/SuperstrikeOverlay/releases/latest>

把 Logitech **G PRO X2 SUPERSTRIKE** 的類比主鍵行程（continuous button travel）變成看得見的水波紋，
並在按住期間自動幫你壓住 `Ctrl` / `Shift` / `Alt`。Windows 系統匣常駐小工具，單一 Python 檔即可執行。

- 讀取左鍵行程 `0.0 ~ 1.0`，**超過門檻就按下**修飾鍵，**回落到釋放門檻才放開**（含遲滯，不會抖動）
- 按住的期間在滑鼠游標位置畫水波紋，中心光暈與內環用該修飾鍵的代表色
- 全螢幕透明疊圖：滑鼠穿透、置頂、不搶焦點（真正的 click-through，`WS_EX_TRANSPARENT`，
  連檔案總管的拖放都不會被水波紋擋住）
- 系統匣右鍵選單：開關疊圖、切換觸發按鍵、切換門檻、重新連線裝置、結束
- 設定會自動存檔，下次啟動沿用

> **HID / HID++ 讀取不是本專案實作的**，而是使用現成的開源 SDK
> [`fawhfi/superstrike-sdk`](https://github.com/fawhfi/superstrike-sdk)（MIT）。
> 本專案只負責「讀值 → 判斷門檻 → 送出修飾鍵 → 畫水波紋 → 系統匣」。
> 詳細出處與授權見 [出處與致謝](#出處與致謝)。

---

## 需求

| 項目 | 說明 |
|---|---|
| OS | Windows 10 / 11（程式用到 `SendInput`、`HID`，只能在 Windows 跑） |
| Python | 3.10 以上 |
| 硬體 | Logitech **G PRO X2 SUPERSTRIKE** 滑鼠（其他型號讀不到 Raw ADC） |
| 套件 | `PyQt6`、`superstrike-sdk`（會連帶安裝 `hidapi`、`websockets`） |

## 安裝

```powershell
git clone git@github.com:hanger0106/SuperstrikeOverlay.git
cd SuperstrikeOverlay
python -m pip install -r requirements.txt
```

> `superstrike-sdk` 沒有發佈在 PyPI，所以 `requirements.txt` 直接指定 GitHub 上的 commit
> （`e875b4b`），確保每台機器裝到的版本一致。

## 使用

```powershell
pythonw superstrike_overlay_app.py              # 平常使用（不開主控台，只留系統匣圖示）
python  superstrike_overlay_app.py --debug      # 顯示除錯訊息（ALT DOWN / ALT UP / 裝置狀態）
python  superstrike_overlay_app.py --selftest   # 不碰裝置，驗證繪圖並輸出預覽 PNG
python  superstrike_overlay_app.py --selftest --preview preview.png   # 指定預覽圖輸出路徑
```

- 啟動後**沒有主視窗**，只會在右下角系統匣出現圖示（用 `pythonw` 才不會留下黑色主控台視窗）。
- 同一時間只允許一個實例；重複啟動會提示「已在執行中」。
- `--selftest` 會在程式目錄產生 `overlay_preview.png`（三種修飾鍵 × 三種行程的對照圖），
  不需要接上滑鼠就能確認畫得對不對。
- 結束程式前一定會放開修飾鍵（`aboutToQuit` + `closeEvent` 雙重保險），不會讓 `Alt` 卡住。

### 系統匣右鍵選單

| 選單項目 | 說明 |
|---|---|
| 啟用疊圖 (按住 {鍵} 時顯示) | 打勾 = 啟用；取消 = 停止送鍵並隱藏水波紋（左鍵單擊/雙擊圖示也可切換） |
| 觸發按鍵 (按住哪一個鍵) | `Ctrl`（洋紅）/ `Shift`（青綠）/ `Alt`（黃），左側色點就是疊圖上的代表色 |
| 觸發門檻 | 40% / 50% / 60% / 70% / 80%；釋放門檻自動取「門檻 − 0.40」（最低 0.05） |
| 裝置：… | 唯讀狀態列，每 0.5 秒更新（已連線 / 連線中 / 未連線原因） |
| 重新連線裝置 | 收掉裝置並重開（拔插滑鼠後用） |
| 結束 | 離開程式 |

門檻與觸發按鍵一改就會寫回 `prox2_config.json`。

## 設定檔

程式目錄下的 `prox2_config.json`（打包後 = exe 旁邊；開發時 = `.py` 旁邊）。
檔案不存在或格式壞掉時一律用程式內建預設值，不會因此啟動失敗。

```json
{
  "modifier": "Alt",
  "on_threshold": 0.6,
  "off_threshold": 0.2
}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `modifier` | `"Ctrl"` / `"Shift"` / `"Alt"` | 觸發的修飾鍵，非法值退回 `Alt` |
| `on_threshold` | `0.0 ~ 1.0` | 行程 ≥ 此值 → 按下修飾鍵 |
| `off_threshold` | `0.0 ~ 1.0` | 行程 ≤ 此值 → 放開修飾鍵（必須小於 `on_threshold` 才有遲滯效果） |

> 這個檔案是「每台機器自己的偏好」，已列入 `.gitignore`，不會進版控。

## 打包成 exe

```powershell
python -m pip install -r requirements-dev.txt
.\build_exe.ps1
```

- 產出：專案根目錄的 `SuperstrikeOverlay.exe`（PyInstaller `--onefile --windowed`，約 33 MB）
- 圖示：`x2.ico`（`--icon` 指定，並用 `--add-data` 一起打包，執行時找不到就畫內建的）
- `SuperstrikeOverlay.spec`、`build/`、`dist/`、`*.exe` 都是產物，已在 `.gitignore` 內。
  要發佈執行檔請走 GitHub **Releases**，不要 commit 進 repo。

## 專案結構

| 檔案 | 說明 |
|---|---|
| `superstrike_overlay_app.py` | 全部程式：HID 讀取執行緒、門檻判斷、`SendInput` 送鍵、水波紋繪圖、系統匣、selftest |
| `build_exe.ps1` | 一行指令重新打包 exe |
| `x2.ico` / `x2.png` | 圖示素材 |
| `requirements.txt` / `requirements-dev.txt` | 執行期 / 打包相依 |
| `prox2_config.json` | 執行期產生的設定（不進版控） |

程式內部主要區塊：`Effect`（水波紋繪製）、`SuperstrikeTravelSource`（背景執行緒讀 SDK）、
`Overlay`（透明置頂視窗 + 門檻遲滯）、`TrayIcon`（系統匣選單）。

## 出處與致謝

| 元件 | 出處 | 授權 | 用途 |
|---|---|---|---|
| **superstrike-sdk** | [github.com/fawhfi/superstrike-sdk](https://github.com/fawhfi/superstrike-sdk)（`e875b4b`，v0.1.0，作者 *Superstrike SDK contributors*） | MIT | **HID++ `0x1B0C event 1` Raw ADC 讀取、校正、平滑** — 本專案的核心資料來源，非本人實作 |
| hidapi（`hidapi` py binding） | [github.com/trezor/cython-hidapi](https://github.com/trezor/cython-hidapi) / [libusb/hidapi](https://github.com/libusb/hidapi) | BSD-3-Clause / GPL-3.0（擇一） | SDK 的底層 HID 傳輸 |
| PyQt6 / Qt 6 | [riverbankcomputing.com/software/pyqt](https://riverbankcomputing.com/software/pyqt/) | GPL-3.0（或商業授權） | 透明疊圖視窗、繪圖、系統匣 |
| PyInstaller | [pyinstaller.org](https://pyinstaller.org/) | GPL-2.0 + bootloader exception | 打包成單一 exe |

本專案原作者實作的部分：門檻遲滯邏輯、`SendInput` 送鍵（純 `ctypes`，不需 pywin32）、
水波紋繪圖、系統匣選單與設定存檔、`--selftest` 預覽。
程式碼註解提到的 `midkey.ahk` 是本專案前一個 AutoHotkey 版本，只作為行為對照。

第三方的完整授權條文與注意事項見 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。

## 免責聲明

SDK 讀到的是**按鍵行程（Raw ADC 換算的比例值）**，不是經過校正的力量感測器。
請不要把它描述成牛頓、毫米或「物理壓力」。非官方 HID++ 實作，羅技原廠不提供支援；
若原廠韌體改動私有特徵，讀值可能失效。

## 授權

本專案程式碼為 MIT License，見 [LICENSE](LICENSE)。
使用的第三方元件各自採用其原授權（PyQt6 為 GPL-3.0，散布 exe 時請自行確認授權相容性）。
