@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo   D2R Item Advisor: automatic installation
echo ============================================
echo.

REM ---------- 1. Python ----------
call :findpy
if defined PYCMD goto :python_ok

echo [1/4] Python not found - installing via winget...
where winget >nul 2>nul
if errorlevel 1 (
    echo.
    echo   winget is not available on this system.
    echo   Install Python manually: https://www.python.org/downloads/
    echo   ^(check "Add python.exe to PATH" in the installer^)
    pause
    exit /b 1
)
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
call :refreshpath
call :findpy
if not defined PYCMD (
    echo.
    echo   Python was installed, but this console session does not see it yet.
    echo   CLOSE this window and run install.bat AGAIN.
    pause
    exit /b 1
)
:python_ok
echo [1/4] Python OK: %PYCMD%

REM ---------- 2. Tesseract ----------
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" goto :tess_ok
where tesseract >nul 2>nul
if not errorlevel 1 goto :tess_ok

echo [2/4] Tesseract OCR not found - installing via winget...
winget install -e --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" goto :tess_ok
where tesseract >nul 2>nul
if not errorlevel 1 goto :tess_ok
echo.
echo   Could not verify Tesseract installation.
echo   If it failed, install manually: https://github.com/UB-Mannheim/tesseract/wiki
echo   Continuing anyway...
:tess_ok
echo [2/4] Tesseract OK

REM ---------- 3. Python packages ----------
echo [3/4] Installing Python packages...
%PYCMD% -m pip install --upgrade pip >nul 2>nul
%PYCMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   pip failed. Check your internet connection and run install.bat again.
    pause
    exit /b 1
)

REM ---------- 4. Assets not shipped with the repo ----------
echo [4/4] Fetching gamble icons + fast-search workers...
%PYCMD% tools\setup_assets.py
if errorlevel 1 (
    echo.
    echo   Some assets failed to download - the tool still works.
    echo   Re-run later:  python tools\setup_assets.py
)

echo.
echo ============================================
echo   Done! Start the tool with run.bat
echo ============================================
pause
exit /b 0

REM ---------- helpers ----------
:findpy
set "PYCMD="
where py >nul 2>nul && py -3 -c "import sys" >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD (
    where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PYCMD=python"
)
exit /b 0

:refreshpath
REM Pick up PATH changes made by installers without reopening the console.
for /f "usebackq tokens=2,*" %%A in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul`) do set "SYSPATH=%%B"
for /f "usebackq tokens=2,*" %%A in (`reg query "HKCU\Environment" /v Path 2^>nul`) do set "USERPATH=%%B"
set "PATH=%SYSPATH%;%USERPATH%;%PATH%"
exit /b 0
