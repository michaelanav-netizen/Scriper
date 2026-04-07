@echo off
title Scriper

REM Change to the folder where this .bat file lives,
REM so Python can find config.py and all other files.
cd /d "%~dp0"

python gui.py

if %errorlevel% neq 0 (
    echo.
    echo  Something went wrong starting Scriper.
    echo  If you have not run "1. Install (run this first).bat" yet, do that first.
    echo  Otherwise, take a screenshot of this window and send it for support.
    echo.
    pause
)
