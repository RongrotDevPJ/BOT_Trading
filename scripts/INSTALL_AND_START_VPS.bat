@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
rem  VPS One-Click Setup and Launch
echo ========================================================
echo.

echo [1/2] Installing Python dependencies...
python -m pip install --upgrade pip
python -m pip install -r ..\requirements.txt

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Dependency installation failed. 
    echo Please make sure Python is installed and added to PATH.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [2/2] Launching all bots...
timeout /t 2 /nobreak > nul

call START_ALL_VPS.bat

echo.
echo Setup and Launch complete.
endlocal
