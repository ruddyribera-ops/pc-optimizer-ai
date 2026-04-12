@echo off
echo ========================================
echo Step 1: Create GitHub Repo
echo ========================================
echo.
echo 1. Go to: https://github.com/new
echo 2. Enter repository name: pc-optimizer-ai
echo 3. Click "Create repository"
echo.
echo Then press any key to continue...
pause >nul

echo.
echo ========================================
echo Step 2: Push Code
echo ========================================
echo.

cd /d "%~dp0"

git remote add origin https://github.com/ruddyribera-ops/pc-optimizer-ai.git
git push -u origin main

echo.
echo ========================================
echo Done!
echo ========================================
pause