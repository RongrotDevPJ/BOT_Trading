<#
.SYNOPSIS
    BOT_Trading — One-Click VPS Setup Script
    Idempotent: safe to run multiple times (renames, migrates, re-registers tasks cleanly)

.USAGE
    Right-click -> "Run with PowerShell"   OR
    Open PowerShell as Admin and run:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
        .\setup.ps1

.WHAT IT DOES
    1. Validates Python installation
    2. Installs/upgrades Python dependencies from requirements.txt
    3. Creates .env from .env.example (if not already present) + prompts user to fill it
    4. Migrates SQLite DB schema (safe for existing data)
    5. Registers 4 bot Scheduled Tasks (auto-start on Windows login)
    6. Registers Weekly Analytics Report task (every Sunday 08:00)
    7. Prints final status summary
#>

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "BOT_Trading Setup"

# ── Colors & Helpers ───────────────────────────────────────────────────────
function Write-Step  { param($msg) Write-Host "`n[STEP] $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "  [OK] $msg"   -ForegroundColor Green }
function Write-WARN  { param($msg) Write-Host "  [!!] $msg"   -ForegroundColor Yellow }
function Write-FAIL  { param($msg) Write-Host " [ERR] $msg"   -ForegroundColor Red }
function Pause-User  { param($msg) Read-Host "`n$msg (press Enter to continue)" }

$ROOT = Split-Path -Parent $PSCommandPath   # .../BOT_Trading
$BOTS  = @("AUDNZD_Grid", "EURGBP_Grid", "EURUSD_Grid", "XAUUSD_Grid")
$TASK_PREFIX = "BOT_Trading"

Write-Host @"
============================================================
   BOT_Trading  --  VPS Setup  (Idempotent)
   Root: $ROOT
============================================================
"@ -ForegroundColor Magenta

# ═══════════════════════════════════════════════════════════════
# STEP 1 — Python check
# ═══════════════════════════════════════════════════════════════
Write-Step "1/6  Validating Python installation"
try {
    $pyVer = python --version 2>&1
    Write-OK "$pyVer found at: $((Get-Command python).Source)"
} catch {
    Write-FAIL "Python not found in PATH. Install Python 3.9+ and retry."
    exit 1
}

# ═══════════════════════════════════════════════════════════════
# STEP 2 — Install dependencies
# ═══════════════════════════════════════════════════════════════
Write-Step "2/6  Installing Python dependencies"
$reqFile = Join-Path $ROOT "requirements.txt"
if (-not (Test-Path $reqFile)) {
    Write-WARN "requirements.txt not found — skipping pip install"
} else {
    python -m pip install --upgrade pip --quiet
    python -m pip install -r $reqFile --quiet
    Write-OK "All packages installed/up-to-date"
}

# ═══════════════════════════════════════════════════════════════
# STEP 3 — .env setup
# ═══════════════════════════════════════════════════════════════
Write-Step "3/6  Environment (.env) setup"
$envFile     = Join-Path $ROOT ".env"
$envExample  = Join-Path $ROOT ".env.example"
if (Test-Path $envFile) {
    Write-OK ".env already exists — NOT overwriting (your credentials are safe)"
} else {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-WARN ".env created from template. IMPORTANT: Open and fill in your credentials!"
        Write-WARN "  File: $envFile"
        Pause-User "Open $envFile, fill in MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, then press Enter"
    } else {
        Write-WARN ".env.example not found — create .env manually"
    }
}

# Quick validation: warn if any value is still blank
$envContent = Get-Content $envFile -Raw -ErrorAction SilentlyContinue
if ($envContent -match 'MT5_LOGIN=0' -or $envContent -match 'MT5_PASSWORD=""') {
    Write-WARN ".env still has placeholder values — bots may fail to connect!"
}

# ═══════════════════════════════════════════════════════════════
# STEP 4 — DB migration
# ═══════════════════════════════════════════════════════════════
Write-Step "4/6  Database schema migration"
$migrateCmd = @"
import sys; sys.path.insert(0, r'$ROOT')
from shared_utils.db_manager import DBManager
import time
db = DBManager()
time.sleep(1)
print('DB migrated OK')
"@
$result = python -c $migrateCmd 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-OK $result
} else {
    Write-FAIL "DB migration failed: $result"
    exit 1
}

# ═══════════════════════════════════════════════════════════════
# STEP 5 — Register bot Scheduled Tasks
# ═══════════════════════════════════════════════════════════════
Write-Step "5/6  Registering bot Scheduled Tasks (auto-start on login)"

$pyExe      = (Get-Command python).Source
$launchersDir = Join-Path $ROOT "scripts\launchers"

foreach ($bot in $BOTS) {
    $taskName   = "$TASK_PREFIX`_$bot"
    $botDir     = Join-Path $ROOT "bots\$bot"
    $mainScript = Join-Path $botDir "main.py"

    if (-not (Test-Path $mainScript)) {
        Write-WARN "main.py not found for $bot — skipping"
        continue
    }

    # Idempotent: unregister old task silently before re-registering
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

    $action   = New-ScheduledTaskAction `
                    -Execute $pyExe `
                    -Argument "`"$mainScript`"" `
                    -WorkingDirectory $botDir

    # Trigger: At logon of current user (VPS persists session)
    $trigger  = New-ScheduledTaskTrigger -AtLogOn

    $settings = New-ScheduledTaskSettingsSet `
                    -ExecutionTimeLimit         (New-TimeSpan -Hours 0) `
                    -RestartCount               5 `
                    -RestartInterval            (New-TimeSpan -Minutes 1) `
                    -MultipleInstances          IgnoreNew `
                    -StartWhenAvailable         $true

    $principal = New-ScheduledTaskPrincipal `
                    -UserId      $env:USERNAME `
                    -LogonType   Interactive `
                    -RunLevel    Highest

    Register-ScheduledTask `
        -TaskName   $taskName `
        -Action     $action `
        -Trigger    $trigger `
        -Settings   $settings `
        -Principal  $principal `
        -Description "SmartGrid MT5 Bot — $bot (auto-start on logon)" `
        -Force | Out-Null

    Write-OK "Task registered: $taskName"
}

# ═══════════════════════════════════════════════════════════════
# STEP 6 — Register Weekly Analytics Report task
# ═══════════════════════════════════════════════════════════════
Write-Step "6/6  Registering Weekly Analytics Report task (Sun 08:00)"

$reportTask   = "$TASK_PREFIX`_WeeklyReport"
$reportScript = Join-Path $ROOT "scripts\tools\weekly_report.py"

Unregister-ScheduledTask -TaskName $reportTask -Confirm:$false -ErrorAction SilentlyContinue

$rAction = New-ScheduledTaskAction `
                -Execute $pyExe `
                -Argument "`"$reportScript`"" `
                -WorkingDirectory $ROOT

$rTrigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "08:00AM"
$rSettings = New-ScheduledTaskSettingsSet `
                -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
                -RestartCount 1

$rPrincipal = New-ScheduledTaskPrincipal `
                -UserId   $env:USERNAME `
                -LogonType Interactive `
                -RunLevel Highest

Register-ScheduledTask `
    -TaskName   $reportTask `
    -Action     $rAction `
    -Trigger    $rTrigger `
    -Settings   $rSettings `
    -Principal  $rPrincipal `
    -Description "BOT_Trading 30-day analytics report — every Sunday 08:00" `
    -Force | Out-Null

Write-OK "Task registered: $reportTask"

# ═══════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════
Write-Host "`n============================================================" -ForegroundColor Magenta
Write-Host "  SETUP COMPLETE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Magenta

Write-Host "`nRegistered Scheduled Tasks:" -ForegroundColor White
Get-ScheduledTask | Where-Object { $_.TaskName -like "$TASK_PREFIX*" } | ForEach-Object {
    Write-Host ("  - {0,-45} [{1}]" -f $_.TaskName, $_.State) -ForegroundColor Cyan
}

Write-Host @"

Next Steps:
  1. Verify .env has correct MT5 + Telegram credentials
  2. Start bots NOW (optional):
       Run: .\scripts\UNIVERSAL_START.ps1
  3. Bots will AUTO-START on next Windows Login/Reboot
  4. Weekly report sent to Telegram every Sunday 08:00

To STOP all bots:   .\stop_all.ps1
To UNINSTALL:       .\uninstall.ps1

"@ -ForegroundColor White

Read-Host "Press Enter to close"
