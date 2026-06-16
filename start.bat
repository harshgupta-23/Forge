@echo off
echo Starting Agent...

:: Start Python backend in its own window
start "Python Backend" cmd /k "cd /d %~dp0python_backend && .venv\Scripts\activate && python app.py"

:: Wait for Python to be ready
timeout /t 3 /nobreak >nul

:: Start Tauri from project root
cd /d %~dp0
npx tauri dev