@echo off
rem ========================================================
rem  Master Launch Script for Trading Bots
rem  This script opens 4 bots in a 4-quadrant layout 
rem  using Windows Terminal (wt).
rem ========================================================

echo Launching all bots in tiled layout...

rem We CD into the directory first to simplify paths for Windows Terminal
cd /d "%~dp0"

rem Use relative paths (.\) and a single line to avoid '^' issues with spaces
wt -d . cmd /k ".\File_bat\EURGBP_BOT.bat" ; split-pane -V -d . cmd /k ".\File_bat\XAUUSD_BOT.bat" ; focus-pane -t 0 ; split-pane -H -d . cmd /k ".\File_bat\EURUSD_BOT.bat" ; focus-pane -t 1 ; split-pane -H -d . cmd /k ".\File_bat\AUDNZD_BOT.bat"

exit
