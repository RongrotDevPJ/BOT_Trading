@echo off
title BOT_Trading Uninstall
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\admin\uninstall.ps1"
pause
