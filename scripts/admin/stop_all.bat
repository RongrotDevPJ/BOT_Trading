<# :
@echo off
setlocal
set "BAT_FILE_PATH=%~f0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "iex ((Get-Content -LiteralPath $env:BAT_FILE_PATH -Raw) -replace '(?s)^.*<#POWERSHELL_START#>', '')"
exit /b %errorlevel%
#>
<#POWERSHELL_START#>
$ErrorActionPreference = "SilentlyContinue"
$Host.UI.RawUI.WindowTitle = "BOT_Trading Stop All"
$botMains = @("core\engine.py", "simulation\sim_engine.py", "dashboard.py")

Write-Host ""
Write-Host "[BOT_Trading] Stopping all bot and dashboard processes..." -ForegroundColor Yellow
$killed = 0
$procs = Get-Process -Name "python*", "streamlit*" -ErrorAction SilentlyContinue
foreach ($proc in $procs) {
    try {
        $wmi = Get-WmiObject Win32_Process -Filter ("ProcessId=" + $proc.Id) -ErrorAction SilentlyContinue
        if ($wmi) {
            $cmdLine = $wmi.CommandLine
            foreach ($m in $botMains) {
                if ($cmdLine -match [regex]::Escape($m)) {
                    Stop-Process -Id $proc.Id -Force
                    Write-Host ("  Stopped: " + $m + " (PID " + $proc.Id + ")") -ForegroundColor Green
                    $killed++
                    break
                }
            }
        }
    } catch {}
}
if ($killed -eq 0) {
    Write-Host "  No running bot processes found." -ForegroundColor Gray
} else {
    Write-Host ""
    Write-Host ("  Total stopped: " + $killed + " process(es)") -ForegroundColor Green
}
Write-Host ""
Start-Sleep -Seconds 2
