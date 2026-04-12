@echo off
echo ========================================
echo PC Optimizer AI - GitHub Push
echo ========================================
echo.

echo Enter your GitHub username (press Enter to skip):
set /p username=

if "%username%"=="" (
    echo No username entered. Opening GitHub...
    start https://github.com/new
    echo.
    echo After creating the repo, run this again and enter your username.
    pause
    exit /b
)

echo.
echo Now pushing your code to GitHub...
echo.

cd /d "%~dp0"

git remote add origin https://github.com/%username%/pc-optimizer-ai.git 2>nul
git branch -M main
git push -u origin main

echo.
echo ========================================
echo Done! Now go to Railway to deploy:
echo https://railway.com/new
echo ========================================

pause