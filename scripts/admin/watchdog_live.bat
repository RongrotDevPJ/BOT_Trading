<# :
@echo off
setlocal
set "BAT_FILE_PATH=%~f0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "iex ((Get-Content -LiteralPath $env:BAT_FILE_PATH -Raw) -replace '(?s)^.*<#POWERSHELL_START#>', '')"
exit /b %errorlevel%
#>
<#POWERSHELL_START#>
$ErrorActionPreference = "SilentlyContinue"
$Host.UI.RawUI.WindowTitle = "BOT_Trading Watchdog"

$ROOT = (Get-Item $env:BAT_FILE_PATH).Directory.Parent.Parent.FullName
$LIVE_BAT = Join-Path $ROOT "scripts\launchers\START_XAUUSD_LIVE.bat"
$TARGET_SCRIPT = "core\engine.py"

Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "   XAUUSD LIVE BOT WATCHDOG" -ForegroundColor Cyan
Write-Host "   Monitoring: $TARGET_SCRIPT" -ForegroundColor Gray
Write-Host "   Interval: 60 seconds" -ForegroundColor Gray
Write-Host "=================================================" -ForegroundColor Cyan

while ($true) {
    $found = $false
    $procs = Get-Process -Name "python*" -ErrorAction SilentlyContinue
    foreach ($proc in $procs) {
        $wmi = Get-WmiObject Win32_Process -Filter ("ProcessId=" + $proc.Id) -ErrorAction SilentlyContinue
        if ($wmi -and $wmi.CommandLine -match [regex]::Escape($TARGET_SCRIPT)) {
            $found = $true
            break
        }
    }

    if (-not $found) {
        Write-Host ("[" + (Get-Date -Format "HH:mm:ss") + "] 🚨 CRITICAL: Live Bot not found! Restarting...") -ForegroundColor Red
        
        # Send a telegram message using python if possible (optional)
        $teleScript = "import sys, urllib.request; sys.path.insert(0, r'$ROOT'); from core.notifier import send_telegram_message; send_telegram_message('🚨 <b>Watchdog Alert</b>\nLive Bot crashed/stopped. Auto-restarting now.')"
        python -c $teleScript 2>&1 | Out-Null
        
        Start-Process -FilePath $LIVE_BAT -WindowStyle Normal
        Start-Sleep -Seconds 10
    } else {
        Write-Host ("[" + (Get-Date -Format "HH:mm:ss") + "] ✅ Live Bot is running smoothly.") -ForegroundColor Green
    }
    
    Start-Sleep -Seconds 60
}
