<# :
@echo off
setlocal
set "BAT_FILE_PATH=%~f0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "iex ((Get-Content -LiteralPath $env:BAT_FILE_PATH -Raw) -replace '(?s)^.*<#POWERSHELL_START#>', '')"
exit /b %errorlevel%
#>
<#POWERSHELL_START#>
# Master Universal Launcher for Dual XAUUSD System
# This script launches Live Bot, Simulation Bot, and the Dashboard automatically.

$ErrorActionPreference = "SilentlyContinue"
Set-Location -Path $PSScriptRoot

# 1. Try Windows Terminal first (best experience)
$wt = Get-Command wt.exe -ErrorAction SilentlyContinue
if ($wt) {
    Write-Host "[INFO] Windows Terminal detected. Launching Tiled View..." -ForegroundColor Cyan
    wt -d . cmd /k ".\launchers\START_XAUUSD_LIVE.bat" `; split-pane -V -d . cmd /k ".\launchers\START_SIMULATION.bat" `; split-pane -H -d . cmd /k ".\launchers\START_DASHBOARD.bat"
    exit
}

# 2. Fallback: Classic CMD Window Tiling
Write-Host "[WARNING] Windows Terminal not found. Using classic multi-window Tiling." -ForegroundColor Yellow

$components = @(
    "START_XAUUSD_LIVE.bat",
    "START_SIMULATION.bat",
    "START_DASHBOARD.bat"
)

foreach ($comp in $components) {
    Write-Host "Starting $comp..."
    Start-Process cmd.exe -ArgumentList "/c .\launchers\$comp" -WindowStyle Normal
    Start-Sleep -Seconds 2
}

# Final Tiling Trick (Standard Windows Shell)
Write-Host "Organizing windows..." -ForegroundColor Green
(New-Object -ComObject Shell.Application).TileVertically()

Write-Host "Done! Dual XAUUSD System is running."
Start-Sleep -Seconds 3
