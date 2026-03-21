@echo off
title MT5 AUDNZD Bot
color 0A

echo =========================================
echo       Smart Grid MT5 Bot (AUDNZD)
echo =========================================
echo.
echo Starting bot... Please do not close this window.
echo (Press Ctrl+C to stop the bot)
echo.

cd /d "%~dp0..\..\bots\AUDNZD_Grid"
python main.py
pause
