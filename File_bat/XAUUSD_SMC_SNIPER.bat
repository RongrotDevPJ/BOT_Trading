@echo off
title XAUUSD SMC SNIPER BOT
:: Navigate to the bot directory
cd /d "%~dp0"
cd ..\"BOT_XAUUSD\SMC_Price Action_Multiple Checklists[Trader2P]"

:: Virtual Environment Activation (Optional - uncomment if you use one)
:: call venv\Scripts\activate

echo ======================================================
echo Starting XAUUSD SMC ^& Price Action Sniper Bot...
echo ======================================================
python main.py
pause
