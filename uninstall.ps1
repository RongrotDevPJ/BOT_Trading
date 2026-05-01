<#
.SYNOPSIS
    BOT_Trading — One-Click Uninstall Script
    Stops all bots, removes Scheduled Tasks. Does NOT delete your DB or logs.

.USAGE
    Right-click -> "Run with PowerShell"   OR
    Open PowerShell as Admin and run:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
        .\uninstall.ps1
#>

#Requires -RunAsAdministrator
$ErrorActionPreference = "SilentlyContinue"
$Host.UI.RawUI.WindowTitle = "BOT_Trading Uninstall"

function Write-Step { param($msg) Write-Host "`n[STEP] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  [OK] $msg"   -ForegroundColor Green }
function Write-WARN { param($msg) Write-Host "  [!!] $msg"   -ForegroundColor Yellow }

$TASK_PREFIX = "BOT_Trading"

Write-Host @"
============================================================
   BOT_Trading  --  Uninstall
   (Your .env, DB, and log files will NOT be deleted)
============================================================
"@ -ForegroundColor Magenta

# ═══════════════════════════════════════════════════════════════
# STEP 1 — Stop all running bot processes
# ═══════════════════════════════════════════════════════════════
Write-Step "1/2  Stopping all running bot Python processes"

$botMains = @("AUDNZD_Grid\main.py", "EURGBP_Grid\main.py", "EURUSD_Grid\main.py", "XAUUSD_Grid\main.py")

$killed = 0
Get-Process -Name "python*" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
        foreach ($m in $botMains) {
            if ($cmdLine -like "*$m*") {
                Stop-Process -Id $_.Id -Force
                Write-OK "Stopped PID $($_.Id) ($m)"
                $killed++
                break
            }
        }
    } catch {}
}

if ($killed -eq 0) {
    Write-WARN "No running bot processes found (already stopped)"
} else {
    Write-OK "Stopped $killed bot process(es)"
}

# ═══════════════════════════════════════════════════════════════
# STEP 2 — Remove Scheduled Tasks
# ═══════════════════════════════════════════════════════════════
Write-Step "2/2  Removing Scheduled Tasks"

$tasks = Get-ScheduledTask | Where-Object { $_.TaskName -like "$TASK_PREFIX*" }
if ($tasks.Count -eq 0) {
    Write-WARN "No BOT_Trading Scheduled Tasks found (already removed)"
} else {
    foreach ($t in $tasks) {
        Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
        Write-OK "Removed task: $($t.TaskName)"
    }
}

# ═══════════════════════════════════════════════════════════════
# DONE
# ═══════════════════════════════════════════════════════════════
Write-Host "`n============================================================" -ForegroundColor Magenta
Write-Host "  UNINSTALL COMPLETE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host @"

What was removed:
  - All BOT_Trading Scheduled Tasks
  - All running bot Python processes

What was KEPT (safe):
  - .env (your credentials)
  - Log_HistoryOrder/ (trade history + DB)
  - All source code

To reinstall: run setup.ps1 again
"@ -ForegroundColor White

Read-Host "Press Enter to close"
