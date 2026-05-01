@echo off
title BOT_Trading Setup
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\admin\setup.ps1"
pause
