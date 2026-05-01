<#
.SYNOPSIS
    BOT_Trading — Stop All Bots (without uninstalling)
    Stops all running bot processes. Tasks remain registered for next auto-start.

.USAGE
    Right-click -> "Run with PowerShell"
    OR: .\stop_all.ps1
#>

$ErrorActionPreference = "SilentlyContinue"
$Host.UI.RawUI.WindowTitle = "BOT_Trading — Stop All"

Write-Host "`n[BOT_Trading] Stopping all bot processes..." -ForegroundColor Yellow

$botMains = @("AUDNZD_Grid\main.py","EURGBP_Grid\main.py","EURUSD_Grid\main.py","XAUUSD_Grid\main.py")
$killed = 0

Get-Process -Name "python*" | ForEach-Object {
    try {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
        foreach ($m in $botMains) {
            if ($cmd -like "*$m*") {
                Stop-Process -Id $_.Id -Force
                Write-Host "  Stopped: $m (PID $($_.Id))" -ForegroundColor Green
                $killed++; break
            }
        }
    } catch {}
}

if ($killed -eq 0) {
    Write-Host "  No running bot processes found." -ForegroundColor Gray
} else {
    Write-Host "`n  Total stopped: $killed bot(s)" -ForegroundColor Green
}

Write-Host "`n  Scheduled Tasks are still registered (bots will auto-restart on next login)."
Write-Host "  To permanently remove: run uninstall.ps1`n" -ForegroundColor Gray
Start-Sleep -Seconds 2
