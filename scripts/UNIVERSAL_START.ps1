# Master Universal Launcher for Trading Bots
# This script launches 4 bots and attempts to tile them automatically.

$ErrorActionPreference = "SilentlyContinue"
Set-Location -Path $PSScriptRoot

# 1. Try Windows Terminal first (best experience)
$wt = Get-Command wt.exe -ErrorAction SilentlyContinue
if ($wt) {
    Write-Host "[INFO] Windows Terminal detected. Launching Tiled View..." -ForegroundColor Cyan
    wt -d . cmd /k ".\launchers\EURGBP_BOT.bat" `; split-pane -V -d . cmd /k ".\launchers\XAUUSD_BOT.bat" `; focus-pane -t 0 `; split-pane -H -d . cmd /k ".\launchers\EURUSD_BOT.bat" `; focus-pane -t 1 `; split-pane -H -d . cmd /k ".\launchers\AUDNZD_BOT.bat"
    exit
}

# 2. Fallback: Classic CMD Window Tiling
Write-Host "[WARNING] Windows Terminal not found. Using classic multi-window Tiling." -ForegroundColor Yellow

$bots = @(
    "EURUSD_BOT.bat",
    "XAUUSD_BOT.bat",
    "AUDNZD_BOT.bat",
    "EURGBP_BOT.bat"
)

foreach ($bot in $bots) {
    Write-Host "Starting $bot..."
    Start-Process cmd.exe -ArgumentList "/c .\launchers\$bot" -WindowStyle Normal
    Start-Sleep -Seconds 2
}

# Final Tiling Trick (Standard Windows Shell)
Write-Host "Organizing windows..." -ForegroundColor Green
(New-Object -ComObject Shell.Application).TileVertically()

Write-Host "Done! Bots are running."
Start-Sleep -Seconds 3
