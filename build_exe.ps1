# 重新打包 SuperstrikeOverlay.exe
#   用法：在 PowerShell 執行  .\build_exe.ps1
#   產出：dist\SuperstrikeOverlay.exe（onefile、無主控台、tray icon = x2.ico）

$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

$icon = Join-Path $PSScriptRoot 'x2.ico'

if (-not (Test-Path -LiteralPath $icon)) {
    throw "找不到 $icon"
}

# PyInstaller 的 INFO 訊息是寫到 stderr 的，Windows PowerShell 5.1 在
# $ErrorActionPreference = 'Stop' 之下會把原生命令的 stderr 當成終止錯誤，
# 所以打包這一段放寬，成敗一律看 $LASTEXITCODE。
$ErrorActionPreference = 'Continue'

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name 'SuperstrikeOverlay' `
    --icon $icon `
    --add-data "$icon;." `
    --distpath $PSScriptRoot `
    --workpath (Join-Path $PSScriptRoot 'build') `
    'superstrike_overlay_app.py'

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 失敗 (exit=$LASTEXITCODE)"
}

$exe = Join-Path $PSScriptRoot 'SuperstrikeOverlay.exe'

if (-not (Test-Path -LiteralPath $exe)) {
    throw "找不到輸出檔 $exe"
}

$size = [math]::Round((Get-Item -LiteralPath $exe).Length / 1MB, 1)

Write-Host ''
Write-Host "完成：$exe ($size MB)" -ForegroundColor Green
