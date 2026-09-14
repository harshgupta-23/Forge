@echo off
setlocal
:: ============================================================
::  Forge - Clean Dev Artifacts
::  Removes build caches, venvs, and dependencies to compress
::  the repository or reset the environment.
:: ============================================================
echo ========================================
echo  Forge - Clean Dev Artifacts
echo ========================================

set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%"

echo.
echo [1/5] Removing Python virtualenv and build caches...
if exist "python_backend\.venv" (
    echo   - Removing python_backend\.venv
    rmdir /s /q "python_backend\.venv"
)
if exist "python_backend\build" (
    echo   - Removing python_backend\build
    rmdir /s /q "python_backend\build"
)
if exist "python_backend\dist" (
    echo   - Removing python_backend\dist
    rmdir /s /q "python_backend\dist"
)
if exist "python_backend\chrome_profile" (
    echo   - Removing python_backend\chrome_profile
    rmdir /s /q "python_backend\chrome_profile"
)
for /d /r "python_backend" %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d"
)
for /d /r "python_backend" %%d in (.pytest_cache) do (
    if exist "%%d" rmdir /s /q "%%d"
)

echo.
echo [2/5] Removing Node dependencies...
if exist "node_modules" (
    echo   - Removing node_modules
    rmdir /s /q "node_modules"
)

echo.
echo [3/5] Removing Rust target build cache (src-tauri\target)...
if exist "src-tauri\target" (
    echo   - Removing src-tauri\target
    rmdir /s /q "src-tauri\target"
)

echo.
echo [4/5] Removing installer resources (src-tauri\resources)...
if exist "src-tauri\resources" (
    echo   - Removing src-tauri\resources
    rmdir /s /q "src-tauri\resources"
)

echo.
echo [5/5] Optional: Runtime user data in ~/.forge...
set "AUTO_YES=0"
if /i "%~1"=="-y" set "AUTO_YES=1"
if /i "%~1"=="--yes" set "AUTO_YES=1"
if /i "%~1"=="--all" set "AUTO_YES=1"
if /i "%~1"=="-f" set "AUTO_YES=1"
if /i "%~1"=="--force" set "AUTO_YES=1"

if "%AUTO_YES%"=="1" (
    set "CONFIRM=y"
) else (
    set "CONFIRM=n"
    set /p CONFIRM="Also remove downloaded Playwright browsers and packages from ~/.forge? (y/N): "
)

if /i "%CONFIRM%"=="y" (
    if exist "%USERPROFILE%\.forge\python-packages" (
        echo   - Removing %USERPROFILE%\.forge\python-packages
        rmdir /s /q "%USERPROFILE%\.forge\python-packages"
    )
    if exist "%USERPROFILE%\.forge\playwright-browsers" (
        echo   - Removing %USERPROFILE%\.forge\playwright-browsers
        rmdir /s /q "%USERPROFILE%\.forge\playwright-browsers"
    )
    echo   Runtime caches removed.
) else (
    echo   Skipping runtime caches (sessions and config preserved).
)

echo.
echo ========================================
echo  Clean complete! Repository is compressed.
echo  To rebuild the dev environment, run:
echo    windows\setup.bat
echo ========================================

