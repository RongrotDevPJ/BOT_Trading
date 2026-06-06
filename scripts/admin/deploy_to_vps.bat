@echo off
REM ============================================================
REM  Auto-Deploy to VPS via Git
REM  Usage: Double-click this file or run from cmd
REM  Requires: Git configured with VPS remote (SSH or HTTPS)
REM ============================================================

title XAUUSD Bot - Deploy to VPS
color 0A

echo ============================================================
echo  XAUUSD Bot - Auto Deploy to VPS
echo ============================================================
echo.

REM Stage all changes
echo [1/4] Staging all changes...
git add -A
if %errorlevel% neq 0 (
    echo ERROR: git add failed. Check if this is a git repo.
    pause
    exit /b 1
)

REM Commit with timestamp
for /f "tokens=1-6 delims=/: " %%a in ("%date% %time%") do set TIMESTAMP=%%a-%%b-%%c_%%d%%e
set COMMIT_MSG=Auto-deploy %TIMESTAMP%
echo [2/4] Committing: %COMMIT_MSG%
git commit -m "%COMMIT_MSG%" --allow-empty

REM Push to remote
echo [3/4] Pushing to remote (VPS)...
git push origin main
if %errorlevel% neq 0 (
    echo ERROR: git push failed.
    echo Make sure VPS remote is configured: git remote add vps user@vps-ip:/path/to/repo
    pause
    exit /b 1
)

echo [4/4] Deploy complete!
echo.
echo Next step on VPS:
echo   git pull
echo   scripts\launchers\START_XAUUSD_LIVE.bat
echo   scripts\launchers\START_SIMULATION.bat  
echo   scripts\launchers\START_DASHBOARD.bat
echo.
pause
