@echo off
title XAUUSD Simulation — SMC/ML Paper Trading
color 0B
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║   XAUUSD SIMULATION BOT — Paper Trading         ║
echo  ║   SMC/ICT + ML (LightGBM + HMM Regime)         ║
echo  ║   NO REAL ORDERS — Results saved to DB          ║
echo  ╚══════════════════════════════════════════════════╝
echo.
cd /d %~dp0\..\..
echo [INFO] Starting Simulation Bot...
echo [INFO] Strategies: SMC/ICT + ML-LightGBM
echo [INFO] Database: data\sim\sim_results.db
echo [INFO] Press Ctrl+C to stop gracefully.
echo.
python simulation\sim_engine.py %*
pause
