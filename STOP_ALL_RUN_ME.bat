@echo off
title BOT_Trading Stop All
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\admin\stop_all.ps1"
pause
