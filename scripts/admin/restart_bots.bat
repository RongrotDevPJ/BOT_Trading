@echo off
title XAUUSD Bot - Restart All Bots
color 0E

echo ============================================================
echo  Restarting all XAUUSD Bots
echo ============================================================
echo.

echo [1/3] Killing existing Python processes (bot instances)...
taskkill /f /im python.exe /t 2>nul
taskkill /f /im pythonw.exe /t 2>nul
timeout /t 2 /nobreak >nul

echo [2/3] Starting Live Bot...
start "XAUUSD Live Bot" cmd /k "scripts\launchers\START_XAUUSD_LIVE.bat"
timeout /t 3 /nobreak >nul

echo [3/3] Starting Simulation Bot...
start "XAUUSD Sim Bot" cmd /k "scripts\launchers\START_SIMULATION.bat"
timeout /t 2 /nobreak >nul

echo Starting Dashboard...
start "XAUUSD Dashboard" cmd /k "scripts\launchers\START_DASHBOARD.bat"

echo.
echo All bots restarted!
echo Dashboard: http://localhost:8501
echo.
pause
