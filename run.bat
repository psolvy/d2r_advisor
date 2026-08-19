@echo off
title D2R Item Advisor
cd /d "%~dp0"

set "PYCMD="
where py >nul 2>nul && py -3 -c "import sys" >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD (
    where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PYCMD=python"
)
if not defined PYCMD (
    echo.
    echo   Python not found!
    echo.
    echo   1. Download it from:  https://www.python.org/downloads/
    echo   2. Run the installer and CHECK the box "Add python.exe to PATH"
    echo   3. Then run install.bat once, and run.bat after that.
    echo.
    pause
    exit /b 1
)

%PYCMD% main.py
if errorlevel 1 pause
