$ErrorActionPreference = "SilentlyContinue"
$Host.UI.RawUI.WindowTitle = "BOT_Trading Uninstall"

function Write-OK   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-WARN { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }

$TASK_PREFIX = "BOT_Trading"
$botMains = @("AUDNZD_Grid\main.py","EURGBP_Grid\main.py","EURUSD_Grid\main.py","XAUUSD_Grid\main.py")

Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "   BOT_Trading  --  Uninstall" -ForegroundColor Magenta
Write-Host "   (DB, logs, and .env will NOT be deleted)" -ForegroundColor Magenta
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host ""

# STEP 1 — Stop running bot processes
Write-Host "[STEP] 1/2  Stopping all running bot Python processes" -ForegroundColor Cyan
$killed = 0
$procs = Get-Process -Name "python*" -ErrorAction SilentlyContinue
foreach ($proc in $procs) {
    try {
        $wmi = Get-WmiObject Win32_Process -Filter ("ProcessId=" + $proc.Id) -ErrorAction SilentlyContinue
        if ($wmi) {
            $cmdLine = $wmi.CommandLine
            foreach ($m in $botMains) {
                if ($cmdLine -like ("*" + $m + "*")) {
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
    Write-OK ("Stopped " + $killed + " bot process(es)")
}

# STEP 2 — Remove Scheduled Tasks
Write-Host ""
Write-Host "[STEP] 2/2  Removing Scheduled Tasks" -ForegroundColor Cyan
$taskNames = @(
    "BOT_Trading_AUDNZD_Grid",
    "BOT_Trading_EURGBP_Grid",
    "BOT_Trading_EURUSD_Grid",
    "BOT_Trading_XAUUSD_Grid",
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

Write-Host ""
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "  UNINSTALL COMPLETE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "Removed: All BOT_Trading Scheduled Tasks + running processes"
Write-Host "Kept:    .env, Log_HistoryOrder/, all source code"
Write-Host ""
Write-Host "To reinstall: double-click SETUP_RUN_ME.bat"
Write-Host ""
Read-Host "Press Enter to close"
