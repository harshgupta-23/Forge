#!/usr/bin/env bash
# ============================================================
#  Forge - Dev launcher (every run after setup.sh)
#  Starts python backend from dev venv, then launches Tauri in dev mode.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Starting Forge Agent..."

BACKEND_PID=""

cleanup() {
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo ""
        echo "Shutting down Python backend (PID $BACKEND_PID)..."
        kill -TERM "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# Start Python backend in background
cd "$PROJECT_ROOT/python_backend"
if [ ! -f ".venv/bin/python" ]; then
    echo "ERROR: Python virtual environment not found in python_backend/.venv"
    echo "Please run linux/setup.sh first."
    exit 1
fi

.venv/bin/python app.py &
BACKEND_PID=$!

# Wait for Python backend to be ready
sleep 3

# Start Tauri from project root
cd "$PROJECT_ROOT"
npx tauri dev

