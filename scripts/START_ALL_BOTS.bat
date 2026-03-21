@echo off
rem ========================================================
rem  Master Launch Script (Tiled View)
rem  Uses Windows Terminal (wt) for a 4-quadrant layout.
rem ========================================================

cd /d "%~dp0"

where wt.exe >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Windows Terminal (wt.exe) not found.
    echo [INFO] This script requires Windows Terminal for its tiled layout.
    echo [TIP] You can install it from the Microsoft Store or GitHub, 
    echo or use "START_ALL_VPS.bat" for a standard multi-window launch instead.
    pause
    exit
)

echo Launching all bots in Tiled Layout...
wt -d . cmd /k ".\launchers\EURGBP_BOT.bat" ; split-pane -V -d . cmd /k ".\launchers\XAUUSD_BOT.bat" ; focus-pane -t 0 ; split-pane -H -d . cmd /k ".\launchers\EURUSD_BOT.bat" ; focus-pane -t 1 ; split-pane -H -d . cmd /k ".\launchers\AUDNZD_BOT.bat"

exit
