@echo off
title Scriper - One-Time Setup
color 0A

echo.
echo  =============================================
echo   Scriper - One-Time Setup
echo   This only needs to run once.
echo  =============================================
echo.

REM ── Check Python is installed ────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python is not installed on this computer.
    echo.
    echo  Please do the following:
    echo.
    echo   1. Open your browser and go to:
    echo      https://www.python.org/downloads/
    echo.
    echo   2. Click the big yellow "Download Python" button.
    echo.
    echo   3. Run the file that downloads.
    echo      IMPORTANT: On the first screen of the installer,
    echo      tick the box that says "Add Python to PATH"
    echo      before clicking Install Now.
    echo.
    echo   4. Once Python is installed, come back to this folder
    echo      and double-click this file again.
    echo.
    pause
    exit /b 1
)

echo  Python found.
python --version
echo.

REM ── Install Python packages ───────────────────────────────────────────────
echo  Installing required packages (this may take a minute) ...
echo.
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Something went wrong installing packages.
    echo  Please take a screenshot of this window and send it for support.
    echo.
    pause
    exit /b 1
)
echo.

REM ── Install Chromium browser ──────────────────────────────────────────────
echo  Installing the browser engine (Chromium) ...
echo  This downloads about 150 MB - please wait.
echo.
python -m playwright install chromium
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Browser installation failed.
    echo  Please take a screenshot of this window and send it for support.
    echo.
    pause
    exit /b 1
)

echo.
echo  =============================================
echo   Setup complete!
echo.
echo   You can now double-click:
echo   "2. Run Scriper.bat"
echo   to open the tool.
echo  =============================================
echo.
pause
