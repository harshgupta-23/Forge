@echo off
:: ============================================================
::  Forge - Dev launcher (every run after setup.bat)
::  Manually starts python.exe from the dev venv, then launches
::  Tauri in dev mode. The embedded-sidecar auto-spawn in lib.rs
::  is gated to release builds only, so it stays out of the way
::  here - this script remains the single thing starting Python
::  during development.
:: ============================================================
echo Starting Agent...

:: Start Python backend in its own window
start "Python Backend" cmd /k "cd /d %~dp0python_backend && .venv\Scripts\activate && python app.py"

:: Wait for Python to be ready
timeout /t 3 /nobreak >nul

:: Start Tauri from project root
cd /d %~dp0
npx tauri dev