@echo off
:: ============================================================
::  Forge - First Time Setup (DEV workflow only)
::  Builds a local venv + browsers for development. To build the
::  distributable MSI installer instead, use build_installer.ps1.
:: ============================================================
echo ========================================
echo  Forge - First Time Setup
echo ========================================

:: Check Python version is 3.11+
python -c "import sys; exit(0) if sys.version_info >= (3,11) else exit(1)" 2>nul
if errorlevel 1 (
    echo ERROR: Python 3.11 or higher is required.
    echo Your current Python version:
    python --version
    echo Download Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Python venv
echo.
echo [1/5] Creating Python virtual environment...
cd /d %~dp0python_backend
python -m venv .venv --clear
if errorlevel 1 ( echo ERROR: Python not found. Install Python 3.11+ and try again. & pause & exit /b 1 )

:: Install requirements
echo.
echo [2/5] Installing Python dependencies...
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 ( echo ERROR: pip install failed. & pause & exit /b 1 )

:: Playwright — installed to the same path app.py redirects to at
:: runtime (~/.myagent/playwright-browsers), so dev and the eventual
:: packaged app share one browser cache instead of two separate downloads.
echo.
echo [3/5] Installing Playwright browsers...
set "PLAYWRIGHT_BROWSERS_PATH=%USERPROFILE%\.myagent\playwright-browsers"
.venv\Scripts\playwright install chromium
if errorlevel 1 ( echo ERROR: Playwright install failed. & pause & exit /b 1 )
if not exist "%PLAYWRIGHT_BROWSERS_PATH%" mkdir "%PLAYWRIGHT_BROWSERS_PATH%"
type nul > "%PLAYWRIGHT_BROWSERS_PATH%\.chromium_installed"

:: Node
echo.
echo [4/5] Installing Node dependencies...
cd /d %~dp0
call npm install
if errorlevel 1 ( echo ERROR: npm install failed. Install Node.js 18+ and try again. & pause & exit /b 1 )

echo.
echo ========================================
echo  [5/5] First compile starting (5-15 mins)...
echo  After the app opens, you can close it.
echo  Future launches use start.bat instead.
echo.
echo  config.json is created automatically on first
echo  launch at %%USERPROFILE%%\.myagent\config.json
echo  - open Settings in the app to add your API key.
echo ========================================
cd /d %~dp0
npx tauri dev

echo.
echo ========================================
echo  Setup complete!
echo  1. Run start.bat to launch the app from now on.
echo  2. Open Settings and enter your API key.
echo ========================================
pause