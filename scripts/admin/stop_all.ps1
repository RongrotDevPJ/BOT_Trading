$ErrorActionPreference = "SilentlyContinue"
$Host.UI.RawUI.WindowTitle = "BOT_Trading Stop All"
$botMains = @("configs\AUDNZD.py","configs\EURGBP.py","configs\EURUSD.py","configs\XAUUSD.py")

Write-Host ""
Write-Host "[BOT_Trading] Stopping all bot processes..." -ForegroundColor Yellow
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
    Write-Host ("  Total stopped: " + $killed + " bot(s)") -ForegroundColor Green
}
Write-Host ""
Write-Host "  Tasks remain registered (bots auto-restart on next login)." -ForegroundColor Gray
Write-Host "  To permanently remove: UNINSTALL_RUN_ME.bat" -ForegroundColor Gray
Write-Host ""
Start-Sleep -Seconds 2
