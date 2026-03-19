@echo off
title Gofile Downloader Pro Launcher
echo =========================================
echo        Gofile Downloader GUI Pro
echo =========================================
echo.

:: 1. Check Python installation
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH.
    echo.
    echo Opening Python download page...
    echo IMPORTANT: Check the "Add python.exe to PATH" option during installation!
    echo After installing, please run this script again.
    echo.
    pause
    start https://www.python.org/downloads/
    exit /b
)

echo [INFO] Python is installed: 
python --version
echo.

:: 2. Install requirements
echo [INFO] Checking and installing required packages...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] There was an error installing packages.
    echo The program will still run, but errors may happen.
    echo.
) else (
    echo [INFO] All requirements are satisfied!
    echo.
)

:: 3. Run GUI
echo [INFO] Starting Gofile Downloader Pro...
echo.
python gui.py

:: Pause if the program exits
pause
