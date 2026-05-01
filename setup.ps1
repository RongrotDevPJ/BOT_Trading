$ErrorActionPreference = "SilentlyContinue"
$Host.UI.RawUI.WindowTitle = "BOT_Trading Setup"

function Write-Step  { param($msg) Write-Host "" ; Write-Host "[STEP] $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-WARN  { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-FAIL  { param($msg) Write-Host " [ERR] $msg" -ForegroundColor Red }

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$BOTS = @("AUDNZD_Grid","EURGBP_Grid","EURUSD_Grid","XAUUSD_Grid")
$TASK_PREFIX = "BOT_Trading"

Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "   BOT_Trading  --  VPS Setup  (Idempotent)" -ForegroundColor Magenta
Write-Host "   Root: $ROOT" -ForegroundColor Magenta
Write-Host "============================================================" -ForegroundColor Magenta

# ═══════════════════════════════════════════════════════════════
# STEP 1 — Python check
# ═══════════════════════════════════════════════════════════════
Write-Step "1/6  Validating Python installation"
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    Write-FAIL "Python not found in PATH. Install Python 3.9+ and retry."
    Read-Host "Press Enter to exit"
    exit 1
}
$pyVer = python --version 2>&1
Write-OK "$pyVer found at: $($pyCmd.Source)"

# ═══════════════════════════════════════════════════════════════
# STEP 2 — Install dependencies
# ═══════════════════════════════════════════════════════════════
Write-Step "2/6  Installing Python dependencies"
$reqFile = Join-Path $ROOT "requirements.txt"
if (-not (Test-Path $reqFile)) {
    Write-WARN "requirements.txt not found -- skipping pip install"
} else {
    python -m pip install --upgrade pip --quiet
    python -m pip install -r $reqFile --quiet
    Write-OK "All packages installed/up-to-date"
}

# ═══════════════════════════════════════════════════════════════
# STEP 3 — .env setup
# ═══════════════════════════════════════════════════════════════
Write-Step "3/6  Environment (.env) setup"
$envFile    = Join-Path $ROOT ".env"
$envExample = Join-Path $ROOT ".env.example"
if (Test-Path $envFile) {
    Write-OK ".env already exists -- NOT overwriting (credentials safe)"
} else {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-WARN ".env created from template."
        Write-WARN "IMPORTANT: Open and fill in your credentials!"
        Write-WARN "File: $envFile"
        Read-Host "Open $envFile, fill in credentials, then press Enter to continue"
    } else {
        Write-WARN ".env.example not found -- create .env manually"
    }
}

$envContent = Get-Content $envFile -Raw -ErrorAction SilentlyContinue
if ($envContent -match "MT5_LOGIN=0") {
    Write-WARN ".env still has placeholder MT5_LOGIN -- bots may fail to connect!"
}

# ═══════════════════════════════════════════════════════════════
# STEP 4 — DB migration
# ═══════════════════════════════════════════════════════════════
Write-Step "4/6  Database schema migration"
$migrateScript = "import sys; sys.path.insert(0, r'" + $ROOT + "'); from shared_utils.db_manager import DBManager; import time; DBManager(); time.sleep(1); print('DB migrated OK')"
$result = python -c $migrateScript 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-OK $result
} else {
    Write-FAIL "DB migration failed: $result"
    Read-Host "Press Enter to exit"
    exit 1
}

# ═══════════════════════════════════════════════════════════════
# STEP 5 — Add bots to Windows Startup Folder (no password needed)
# ═══════════════════════════════════════════════════════════════
Write-Step "5/6  Adding bots to Startup Folder (auto-start on login)"
$pyExe = $pyCmd.Source
$startupFolder = [System.Environment]::GetFolderPath("Startup")
Write-Host "  Startup folder: $startupFolder" -ForegroundColor Gray

foreach ($bot in $BOTS) {
    $botDir     = Join-Path $ROOT ("bots\" + $bot)
    $mainScript = Join-Path $botDir "main.py"
    $shortcutPath = Join-Path $startupFolder ($bot + ".lnk")

    if (-not (Test-Path $mainScript)) {
        Write-WARN "main.py not found for $bot -- skipping"
        continue
    }

    # Remove old shortcut
    if (Test-Path $shortcutPath) { Remove-Item $shortcutPath -Force }

    # Create shortcut via WScript.Shell (PS 2.0 compatible, no password needed)
    $shell = New-Object -ComObject WScript.Shell
    $sc    = $shell.CreateShortcut($shortcutPath)
    $sc.TargetPath       = $pyExe
    $sc.Arguments        = "`"$mainScript`""
    $sc.WorkingDirectory = $botDir
    $sc.WindowStyle      = 1
    $sc.Description      = "BOT_Trading $bot auto-start"
    $sc.Save()

    if (Test-Path $shortcutPath) {
        Write-OK "Startup shortcut created: $bot"
    } else {
        Write-WARN "Failed to create shortcut for $bot"
    }
}

# ═══════════════════════════════════════════════════════════════
# STEP 6 — Register Weekly Report via schtasks (time-based, OK without ONLOGON)
# ═══════════════════════════════════════════════════════════════
Write-Step "6/6  Registering Weekly Analytics Report task (Sun 08:00)"
$reportTask   = $TASK_PREFIX + "_WeeklyReport"
$reportScript = Join-Path $ROOT "scripts\tools\weekly_report.py"

& "$env:SystemRoot\System32\schtasks.exe" /delete /tn $reportTask /f 2>&1 | Out-Null
$rCmd = "`"" + $pyExe + "`" `"" + $reportScript + "`""
$out2 = & "$env:SystemRoot\System32\schtasks.exe" /create /tn $reportTask /tr $rCmd /sc WEEKLY /d SUN /st 08:00 /ru SYSTEM /f 2>&1
$ec2  = $LASTEXITCODE

if ($ec2 -eq 0) {
    Write-OK "Task registered: $reportTask (runs as SYSTEM every Sunday 08:00)"
} else {
    # Fallback: add to startup folder as well
    Write-WARN "schtasks failed ($out2) -- adding weekly report to Startup folder as fallback"
    $shortcutPath2 = Join-Path $startupFolder "BOT_WeeklyReport.lnk"
    if (Test-Path $shortcutPath2) { Remove-Item $shortcutPath2 -Force }
    $shell2 = New-Object -ComObject WScript.Shell
    $sc2    = $shell2.CreateShortcut($shortcutPath2)
    $sc2.TargetPath       = $pyExe
    $sc2.Arguments        = "`"$reportScript`""
    $sc2.WorkingDirectory = $ROOT
    $sc2.WindowStyle      = 1
    $sc2.Save()
    if (Test-Path $shortcutPath2) { Write-OK "Weekly report added to Startup folder" }
}

# ═══════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "  SETUP COMPLETE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "Registered Scheduled Tasks:" -ForegroundColor White
$allTasks = & $schtasks /query /fo CSV 2>&1
$allTasks | ForEach-Object {
    if ($_ -like "*BOT_Trading*") {
        $name = ($_ -split ',')[0] -replace '"',''
        Write-Host ("  - " + $name) -ForegroundColor Cyan
    }
}
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor White
Write-Host "  1. Verify .env has correct MT5 + Telegram credentials"
Write-Host "  2. Start bots NOW: double-click scripts\UNIVERSAL_START.ps1"
Write-Host "  3. Bots will AUTO-START on next Windows Login/Reboot"
Write-Host "  4. Weekly report sent to Telegram every Sunday 08:00"
Write-Host ""
Write-Host "To STOP all bots:   STOP_ALL_RUN_ME.bat"
Write-Host "To UNINSTALL:       UNINSTALL_RUN_ME.bat"
Write-Host ""
Read-Host "Press Enter to close"
