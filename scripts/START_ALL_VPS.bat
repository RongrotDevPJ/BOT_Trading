@echo off
rem ========================================================
rem  Master Launch Script for Trading Bots (VPS Compatible)
rem  This version uses the standard 'start' command 
rem  which works on all Windows versions.
rem ========================================================

echo Launching all bots in separate windows...

cd /d "%~dp0"

echo Starting EURUSD Bot...
start "EURUSD Bot" cmd /c ".\launchers\EURUSD_BOT.bat"

timeout /t 2 /nobreak > nul

echo Starting XAUUSD Bot...
start "XAUUSD Bot" cmd /c ".\launchers\XAUUSD_BOT.bat"

timeout /t 2 /nobreak > nul

echo Starting AUDNZD Bot...
start "AUDNZD Bot" cmd /c ".\launchers\AUDNZD_BOT.bat"

timeout /t 2 /nobreak > nul

echo Starting EURGBP Bot...
start "EURGBP Bot" cmd /c ".\launchers\EURGBP_BOT.bat"

echo.
echo All bots have been launched in separate windows.
echo You can close this window now.
pause
