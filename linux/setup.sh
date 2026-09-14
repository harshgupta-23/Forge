#!/usr/bin/env bash
# ============================================================
#  Forge - First Time Setup (DEV workflow only)
#  Builds a local venv + browsers for development.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "========================================"
echo " Forge - First Time Setup (Linux)"
echo "========================================"

# Check for uv or standard Python 3.11+
USE_UV=false
if command -v uv >/dev/null 2>&1; then
    echo "Found 'uv' package manager. Using uv for virtual environment and dependency installation."
    USE_UV=true
else
    echo "'uv' not found. Falling back to standard python3."
    if ! command -v python3 >/dev/null 2>&1; then
        echo "ERROR: Neither 'uv' nor 'python3' could be found."
        echo "Please install uv (https://astral.sh/uv) or Python 3.11+."
        exit 1
    fi

    python3 -c "import sys; exit(0) if sys.version_info >= (3,11) else exit(1)" 2>/dev/null || {
        echo "ERROR: Python 3.11 or higher is required."
        echo "Your current Python version: $(python3 --version)"
        exit 1
    }
fi

# Check Node.js and npm
if ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: npm could not be found. Install Node.js 18+ and try again."
    exit 1
fi

# Python venv
cd "$PROJECT_ROOT/python_backend"
if [ "$USE_UV" = true ]; then
    echo ""
    echo "[1/5] Creating Python virtual environment with uv..."
    uv venv .venv --python 3.11 --clear

    # Install requirements
    echo ""
    echo "[2/5] Installing Python dependencies with uv..."
    uv pip install -r requirements.txt --python "$PROJECT_ROOT/python_backend/.venv/bin/python"
else
    echo ""
    echo "[1/5] Creating Python virtual environment..."
    python3 -m venv .venv --clear

    # Install requirements
    echo ""
    echo "[2/5] Installing Python dependencies..."
    "$PROJECT_ROOT/python_backend/.venv/bin/pip" install --upgrade pip
    "$PROJECT_ROOT/python_backend/.venv/bin/pip" install -r requirements.txt
fi

# Playwright browsers
echo ""
echo "[3/5] Installing Playwright browsers..."
export PLAYWRIGHT_BROWSERS_PATH="$HOME/.forge/playwright-browsers"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
"$PROJECT_ROOT/python_backend/.venv/bin/playwright" install chromium
touch "$PLAYWRIGHT_BROWSERS_PATH/.chromium_installed"

# Node dependencies
echo ""
echo "[4/5] Installing Node dependencies..."
cd "$PROJECT_ROOT"
npm install

echo ""
echo "========================================"
echo " [5/5] First compile starting..."
echo " After the app opens, you can close it."
echo " Future launches use linux/start.sh instead."
echo ""
echo " config.json is created automatically on first"
echo " launch at ~/.forge/config.json"
echo " - open Settings in the app to add your API key."
echo "========================================"
cd "$PROJECT_ROOT"
npx tauri dev

echo ""
echo "========================================"
echo " Setup complete!"
echo " 1. Run linux/start.sh to launch the app from now on."
echo " 2. Open Settings and enter your API key."
echo "========================================"

