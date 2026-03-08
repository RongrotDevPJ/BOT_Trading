@echo off
echo Running Environment Check...
python check_env.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [CRITICAL] Python is not found in your PATH or failed to run.
    echo Try running: py check_env.py or python3 check_env.py
)
pause
