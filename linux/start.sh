#!/usr/bin/env bash
# ============================================================
#  Forge - Dev launcher (every run after setup.sh)
#  Starts python backend from dev venv, then launches Tauri in dev mode.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Workaround for WebKitGTK WebProcess crash under WSL2 / WSLg software rendering
export WEBKIT_DISABLE_DMABUF_RENDERER=1
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export GDK_BACKEND=x11
export LIBGL_ALWAYS_SOFTWARE=1

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

# Check for --docker flag
USE_DOCKER=0
for arg in "$@"; do
    if [ "$arg" == "--docker" ] || [ "$arg" == "-d" ]; then
        USE_DOCKER=1
    fi
done

if [ "$USE_DOCKER" -eq 1 ] || [ "${CONTAINER_MODE:-0}" == "1" ]; then
    echo "[start.sh] Starting Forge in containerized Docker mode..."
    cd "$PROJECT_ROOT"
    docker compose up -d --build
    echo "[start.sh] Docker containers running on port 8765. Launching desktop interface..."
    npx tauri dev
    exit 0
fi

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

