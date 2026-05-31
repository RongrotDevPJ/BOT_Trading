$ErrorActionPreference = "SilentlyContinue"
$Host.UI.RawUI.WindowTitle = "BOT_Trading Uninstall"

function Write-OK   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-WARN { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }

$TASK_PREFIX = "BOT_Trading"
$botMains = @("core\engine.py", "simulation\sim_engine.py", "dashboard.py")

Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "   BOT_Trading  --  Uninstall" -ForegroundColor Magenta
Write-Host "   (DB, logs, and .env will NOT be deleted)" -ForegroundColor Magenta
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host ""

# STEP 1 — Stop running bot processes
Write-Host "[STEP] 1/2  Stopping all running processes" -ForegroundColor Cyan
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
                    Write-OK ("Stopped PID " + $proc.Id + " (" + $m + ")")
                    $killed++
                    break
                }
            }
        }
    } catch {}
}
if ($killed -eq 0) {
    Write-WARN "No running bot processes found (already stopped)"
} else {
    Write-OK ("Stopped " + $killed + " process(es)")
}

# STEP 2 — Remove Scheduled Tasks and Startup Shortcuts
Write-Host ""
Write-Host "[STEP] 2/2  Removing Scheduled Tasks and Shortcuts" -ForegroundColor Cyan
$taskNames = @(
    "BOT_Trading_WeeklyReport"
)
foreach ($t in $taskNames) {
    $out = schtasks /delete /tn $t /f 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Removed task: $t"
    } else {
        Write-WARN "Task not found (already removed): $t"
    }
}

$startupFolder = [System.Environment]::GetFolderPath("Startup")
$shortcuts = @("BOT_Trading_XAUUSD_LIVE.lnk", "BOT_Trading_SIMULATION.lnk", "BOT_Trading_DASHBOARD.lnk", "BOT_WeeklyReport.lnk")
foreach ($s in $shortcuts) {
    $p = Join-Path $startupFolder $s
    if (Test-Path $p) {
        Remove-Item $p -Force
        Write-OK "Removed startup shortcut: $s"
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "  UNINSTALL COMPLETE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "Removed: All BOT_Trading Scheduled Tasks, Shortcuts, + running processes"
Write-Host "Kept:    .env, data/, logs/, all source code"
Write-Host ""
Write-Host "To reinstall: Run setup.ps1 again"
Write-Host ""
Read-Host "Press Enter to close"
