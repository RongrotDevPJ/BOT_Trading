@echo off
title MT5 XAUUSD Bot
color 0E

echo =========================================
echo       Smart Grid MT5 Bot (XAUUSD)
echo =========================================
echo.
echo Starting Gold bot... Please do not close this window.
echo (Press Ctrl+C to stop the bot)
echo.

cd /d "%~dp0BOT_XAUUSD\Smart Grid"
python main.py
pause
