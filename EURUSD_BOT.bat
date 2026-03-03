@echo off
title MT5 Smart Grid Bot
color 0A

echo =========================================
echo       Smart Grid MT5 Bot (EURUSD)
echo =========================================
echo.
echo Starting bot... Please do not close this window.
echo (Press Ctrl+C to stop the bot)
echo.

cd /d "%~dp0BOT_EURUSD\Smart Grid"
python main.py
pause
