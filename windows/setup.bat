@echo off
:: ============================================================
::  Forge - First Time Setup (DEV workflow only)
::  Builds a local venv + browsers for development. To build the
::  distributable MSI installer instead, use build_installer.ps1.
:: ============================================================
echo ========================================
echo  Forge - First Time Setup
echo ========================================

:: Check for uv or Python
where uv >nul 2>&1
if %errorlevel% equ 0 (
    set "USE_UV=1"
    echo Found 'uv' package manager. Using uv for fast environment setup.
) else (
    set "USE_UV=0"
    echo 'uv' not found. Falling back to standard Python.
    :: Check Python version is 3.11+
    python -c "import sys; exit(0) if sys.version_info >= (3,11) else exit(1)" 2>nul
    if errorlevel 1 (
        echo ERROR: Neither 'uv' nor Python 3.11+ was found.
        echo Your current Python version:
        python --version 2>nul
        echo Please install uv (https://astral.sh/uv) or Python 3.11+ from https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

:: Python venv & dependencies
cd /d "%~dp0..\python_backend"

if "%USE_UV%"=="1" (
    echo.
    echo [1/5] Creating Python virtual environment with uv...
    uv venv .venv --python 3.11 --clear
    if errorlevel 1 ( echo ERROR: uv venv failed. & pause & exit /b 1 )

    echo.
    echo [2/5] Installing Python dependencies with uv...
    uv pip install -r requirements.txt --python "%~dp0..\python_backend\.venv\Scripts\python.exe"
    if errorlevel 1 ( echo ERROR: uv pip install failed. & pause & exit /b 1 )
) else (
    echo.
    echo [1/5] Creating Python virtual environment...
    python -m venv .venv --clear
    if errorlevel 1 ( echo ERROR: Python not found. Install Python 3.11+ and try again. & pause & exit /b 1 )

    echo.
    echo [2/5] Installing Python dependencies...
    .venv\Scripts\pip install --upgrade pip
    .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 ( echo ERROR: pip install failed. & pause & exit /b 1 )
)

:: Playwright — installed to the same path app.py redirects to at
:: runtime (~/.forge/playwright-browsers), so dev and the eventual
:: packaged app share one browser cache instead of two separate downloads.
echo.
echo [3/5] Installing Playwright browsers...
set "PLAYWRIGHT_BROWSERS_PATH=%USERPROFILE%\.forge\playwright-browsers"
.venv\Scripts\playwright install chromium
if errorlevel 1 ( echo ERROR: Playwright install failed. & pause & exit /b 1 )
if not exist "%PLAYWRIGHT_BROWSERS_PATH%" mkdir "%PLAYWRIGHT_BROWSERS_PATH%"
type nul > "%PLAYWRIGHT_BROWSERS_PATH%\.chromium_installed"

:: Node
echo.
echo [4/5] Installing Node dependencies...
cd /d "%~dp0.."
call npm install
if errorlevel 1 ( echo ERROR: npm install failed. Install Node.js 18+ and try again. & pause & exit /b 1 )

echo.
echo ========================================
echo  [5/5] First compile starting (5-15 mins)...
echo  After the app opens, you can close it.
echo  Future launches use start.bat instead.
echo.
echo  config.json is created automatically on first
echo  launch at %%USERPROFILE%%\.forge\config.json
echo  - open Settings in the app to add your API key.
echo ========================================
cd /d "%~dp0.."
npx tauri dev

echo.
echo ========================================
echo  Setup complete!
echo  1. Run windows\start.bat to launch the app from now on.
echo  2. Open Settings and enter your API key.
echo  3. Checkpointing: Defaults to local SQLite (%USERPROFILE%\.forge\forge_checkpoints.db).
echo     To use PostgreSQL, run 'docker compose up -d' and set Database URL in Settings.
echo ========================================
pause

