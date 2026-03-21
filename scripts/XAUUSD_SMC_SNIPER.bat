@echo off
title XAUUSD SMC SNIPER BOT
:: Navigate to the bot directory
cd /d "%~dp0"
cd ..\bots\XAUUSD_SMC

:: Virtual Environment Activation (Optional - uncomment if you use one)
:: call venv\Scripts\activate

echo ======================================================
echo Starting XAUUSD SMC ^& Price Action Sniper Bot...
echo ======================================================
python main.py
pause
