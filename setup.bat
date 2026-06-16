@echo off
echo ========================================
echo  Forge - First Time Setup
echo ========================================

:: Python venv
echo.
echo [1/6] Creating Python virtual environment...
cd /d %~dp0python_backend
python -m venv .venv --clear
if errorlevel 1 ( echo ERROR: Python not found. Install Python 3.11+ and try again. & pause & exit /b 1 )

:: Install requirements
echo.
echo [2/6] Installing Python dependencies...
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 ( echo ERROR: pip install failed. & pause & exit /b 1 )

:: Playwright
echo.
echo [3/6] Installing Playwright browsers...
.venv\Scripts\playwright install chromium
if errorlevel 1 ( echo ERROR: Playwright install failed. & pause & exit /b 1 )

:: Node
echo.
echo [4/6] Installing Node dependencies...
cd /d %~dp0
call npm install
if errorlevel 1 ( echo ERROR: npm install failed. Install Node.js 18+ and try again. & pause & exit /b 1 )

:: Config
echo.
echo [5/6] Setting up config...
if not exist "%~dp0config.json" (
    copy "%~dp0config.template.json" "%~dp0config.json"
    echo Created config.json from template.
) else (
    echo config.json already exists, skipping.
)

echo.
echo ========================================
echo  [6/6] First compile starting (5-15 mins)...
echo  After the app opens, you can close it.
echo  Future launches via start.bat are fast.
echo ========================================
cd /d %~dp0
npx tauri dev

echo.
echo ========================================
echo  Setup complete!
echo  1. Run start.bat to launch the app.
echo  2. Open Settings and enter your API key.
echo ========================================
pause