@echo off
title MT5 BTCUSD Bot
color 0B

echo =========================================
echo       Smart Grid MT5 Bot (BTCUSD)
echo =========================================
echo.
echo Starting BTC bot... Please do not close this window.
echo (Press Ctrl+C to stop the bot)
echo.

cd /d "%~dp0BOT_BTC\Smart Grid"
python main.py
pause
