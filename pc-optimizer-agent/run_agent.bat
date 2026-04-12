@echo off
echo PC Optimizer Agent Launcher
echo ============================
echo.

cd /d "%~dp0"

echo Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python from https://python.org
    pause
    exit /b 1
)

echo.
echo Starting PC Optimizer Agent...
echo.
echo Options:
echo 1. Run interactive mode (control tasks manually)
echo 2. Register with cloud and check status
echo 3. Exit
echo.

set /p choice="Select option (1-3): "

if "%choice%"=="1" (
    echo.
    echo Starting interactive mode...
    python agent.py --interactive
) else if "%choice%"=="2" (
    echo.
    echo Registering with cloud backend...
    python agent.py https://pc-optimizer-ai-production-9984.up.railway.app
) else (
    echo Exiting...
)

echo.
pause