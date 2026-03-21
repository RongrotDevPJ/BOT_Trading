@echo off
rem ========================================================
rem  Master Launch Script (Smart Version)
rem  Detects Windows Terminal for Tiled View, 
rem  otherwise falls back to individual windows.
rem ========================================================

cd /d "%~dp0"

where wt.exe >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo [INFO] Windows Terminal detected. Launching all bots in Tiled View...
    wt -d . cmd /k ".\launchers\EURGBP_BOT.bat" ; split-pane -V -d . cmd /k ".\launchers\XAUUSD_BOT.bat" ; focus-pane -t 0 ; split-pane -H -d . cmd /k ".\launchers\EURUSD_BOT.bat" ; focus-pane -t 1 ; split-pane -H -d . cmd /k ".\launchers\AUDNZD_BOT.bat"
    exit
)

echo [WARNING] Windows Terminal not found.
echo [TIP] To have all bots in one tiled window, please install "Windows Terminal" 
echo from the Microsoft Store or GitHub.
echo.
echo Launching in separate windows as fallback...
echo.

echo Starting EURUSD Bot...
start "EURUSD Bot" cmd /c ".\launchers\EURUSD_BOT.bat"
timeout /t 1 /nobreak > nul

echo Starting XAUUSD Bot...
start "XAUUSD Bot" cmd /c ".\launchers\XAUUSD_BOT.bat"
timeout /t 1 /nobreak > nul

echo Starting AUDNZD Bot...
start "AUDNZD Bot" cmd /c ".\launchers\AUDNZD_BOT.bat"
timeout /t 1 /nobreak > nul

echo Starting EURGBP Bot...
start "EURGBP Bot" cmd /c ".\launchers\EURGBP_BOT.bat"

echo.
echo All bots have been launched.
pause
