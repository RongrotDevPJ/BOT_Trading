@echo off
title BOT_Trading — Dual System Dashboard
color 0E
echo.
echo  ╔════════════════════════════════════════════╗
echo  ║   XAUUSD DUAL SYSTEM DASHBOARD            ║
echo  ║   Live Trading ^& Simulation Tracking      ║
echo  ╚════════════════════════════════════════════╝
echo.
cd /d "%~dp0\..\.."
echo [INFO] Starting Streamlit Dashboard...
echo [INFO] Your browser will open automatically.
echo.
streamlit run dashboard.py
pause
