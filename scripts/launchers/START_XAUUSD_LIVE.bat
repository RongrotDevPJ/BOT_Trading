@echo off
title XAUUSD Live Bot — BOT_Trading
color 0A
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   XAUUSD LIVE BOT — BOT_Trading         ║
echo  ║   Regime-Aware Grid + ML Signal Filter  ║
echo  ╚══════════════════════════════════════════╝
echo.
cd /d %~dp0\..\..
echo [INFO] Starting XAUUSD Live Bot...
echo [INFO] Config: configs\XAUUSD_LIVE.py
echo [INFO] Press Ctrl+C to stop gracefully.
echo.
python core\engine.py --config configs\XAUUSD_LIVE.py
pause
