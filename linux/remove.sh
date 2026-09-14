#!/usr/bin/env bash
# ============================================================
#  Forge - Clean Dev Artifacts
#  Removes build caches, venvs, and dependencies to compress
#  the repository or reset the environment.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "========================================"
echo " Forge - Clean Dev Artifacts"
echo "========================================"

echo ""
echo "[1/5] Removing Python virtualenv and build caches..."
rm -rf python_backend/.venv
rm -rf python_backend/build
rm -rf python_backend/dist
rm -rf python_backend/chrome_profile
find python_backend -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find python_backend -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "[2/5] Removing Node dependencies..."
rm -rf node_modules

echo ""
echo "[3/5] Removing Rust target build cache (src-tauri/target)..."
rm -rf src-tauri/target

echo ""
echo "[4/5] Removing installer resources (src-tauri/resources)..."
rm -rf src-tauri/resources

echo ""
echo "[5/5] Optional: Runtime user data in ~/.forge..."
AUTO_YES=false
if [[ "${1:-}" =~ ^(-y|--yes|--all|-f|--force)$ ]]; then
    AUTO_YES=true
fi

if [ "$AUTO_YES" = true ]; then
    CONFIRM="y"
else
    CONFIRM="n"
    read -r -p "Also remove downloaded Playwright browsers and packages from ~/.forge? (y/N): " CONFIRM || CONFIRM="n"
fi

if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "  - Removing ~/.forge/python-packages"
    rm -rf "$HOME/.forge/python-packages"
    echo "  - Removing ~/.forge/playwright-browsers"
    rm -rf "$HOME/.forge/playwright-browsers"
    echo "  Runtime caches removed."
else
    echo "  Skipping runtime caches (sessions and config preserved)."
fi

echo ""
echo "========================================"
echo " Clean complete! Repository is compressed."
echo " To rebuild the dev environment, run:"
echo "   linux/setup.sh"
echo "========================================"

