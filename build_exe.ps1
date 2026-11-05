# 重新打包 SuperstrikeOverlay.exe
#   用法：在 PowerShell 執行  .\build_exe.ps1
#   產出：dist\SuperstrikeOverlay.exe（onefile、無主控台、tray icon = x2.ico）

$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

$icon = Join-Path $PSScriptRoot 'x2.ico'

if (-not (Test-Path -LiteralPath $icon)) {
    throw "找不到 $icon"
}

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
