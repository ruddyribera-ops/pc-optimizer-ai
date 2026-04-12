@echo off
echo.
echo ========================================
echo CREATE GITHUB REPO FIRST
echo ========================================
echo.
echo 1. Open this link in your browser:
echo.
echo    https://github.com/new
echo.
echo 2. Fill in the form:
echo    - Repository name: pc-optimizer-ai
echo    - Description: AI PC Optimizer Cloud Service
echo    - Choose: Public
echo    - CLICK: Create repository
echo.
echo 3. COME BACK HERE and press any key...
echo.
echo ========================================
pause

echo.
echo Now pushing code to GitHub...
echo.

cd /d "%~dp0"

git remote add origin https://github.com/ruddyribera-ops/pc-optimizer-ai.git 2>nul
git push -u origin main

echo.
echo ========================================
echo SUCCESS! Now go to Railway:
echo https://railway.com/new
echo ========================================
echo.
pause