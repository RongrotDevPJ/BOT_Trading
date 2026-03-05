@echo off
title MT5 Smart Grid Bot - EURGBP
color 0B

echo =========================================
echo       Smart Grid MT5 Bot (EURGBP)
echo =========================================
echo.
echo Starting EURGBP bot... Please do not close this window.
echo (Press Ctrl+C to stop the bot)
echo.

cd /d "%~dp0..\BOT_EURGBP\Smart Grid"
python main.py
pause
