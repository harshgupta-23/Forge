#!/usr/bin/env bash
# ============================================================
#  build_installer.sh
#  Assembles a Python runtime + the Forge backend into
#  src-tauri/resources, then builds Linux installer bundles (deb/appimage).
#
#  Run from project root or linux folder:
#      bash linux/build_installer.sh
# ============================================================
set -euo pipefail

export PATH="$HOME/.cargo/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RESOURCES_DIR="$PROJECT_ROOT/src-tauri/resources"
PYTHON_DIR="$RESOURCES_DIR/python"
BACKEND_SRC_DIR="$PROJECT_ROOT/python_backend"
BACKEND_DEST_DIR="$RESOURCES_DIR/python_backend"
CONFIG_TEMPLATE="$PROJECT_ROOT/config.template.json"
REQ_FILE="$BACKEND_SRC_DIR/requirements-embed.txt"

step() {
    echo ""
    echo -e "\033[1;36m==> $1\033[0m"
}

# ── 0. Sanity checks ────────────────────────────────────────────────────────
step "Running sanity checks"

if [ ! -d "$BACKEND_SRC_DIR" ]; then
    echo "ERROR: python_backend/ not found at $BACKEND_SRC_DIR."
    exit 1
fi

if [ ! -f "$CONFIG_TEMPLATE" ]; then
    echo "ERROR: config.template.json not found at $CONFIG_TEMPLATE."
    exit 1
fi

if [ ! -f "$REQ_FILE" ]; then
    echo "ERROR: requirements-embed.txt not found at $REQ_FILE."
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required."
    exit 1
fi

# ── 1. Clean previous resources ─────────────────────────────────────────────
step "Cleaning previous build output"
rm -rf "$RESOURCES_DIR"
mkdir -p "$PYTHON_DIR"
mkdir -p "$BACKEND_DEST_DIR"

# ── 2. Create isolated Python runtime for bundle ───────────────────────────
if command -v uv >/dev/null 2>&1; then
    step "Setting up isolated Python environment with uv in resources"
    uv venv "$PYTHON_DIR" --python 3.11 --clear

    # ── 3. Install runtime dependencies ─────────────────────────────────────────
    step "Installing Python dependencies with uv from requirements-embed.txt"
    uv pip install -r "$REQ_FILE" --python "$PYTHON_DIR/bin/python"
else
    step "Setting up isolated Python environment in resources"
    python3 -m venv "$PYTHON_DIR" --clear
    "$PYTHON_DIR/bin/pip" install --upgrade pip --no-warn-script-location

    # ── 3. Install runtime dependencies ─────────────────────────────────────────
    step "Installing Python dependencies from requirements-embed.txt"
    "$PYTHON_DIR/bin/pip" install -r "$REQ_FILE" --no-warn-script-location
fi

# ── 4. Copy backend source ──────────────────────────────────────────────────
step "Copying backend source into resources"
rsync -av --exclude='.venv' \
          --exclude='chrome_profile' \
          --exclude='__pycache__' \
          --exclude='requirements.txt' \
          --exclude='requirements-embed.txt' \
          --exclude='*.pyc' \
          "$BACKEND_SRC_DIR/" "$BACKEND_DEST_DIR/"

cp "$CONFIG_TEMPLATE" "$RESOURCES_DIR/config.template.json"

# ── 5. Clean up build artifacts ─────────────────────────────────────────────
step "Cleaning up build artifacts"
find "$RESOURCES_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$RESOURCES_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

# ── 6. Frontend deps (only if missing) ──────────────────────────────────────
if [ ! -d "$PROJECT_ROOT/node_modules" ]; then
    step "Installing frontend dependencies"
    cd "$PROJECT_ROOT"
    npm install
fi

# ── 7. Build bundle ─────────────────────────────────────────────────────────
step "Building Linux packages (deb, appimage)"
cd "$PROJECT_ROOT"
npx tauri build --bundles deb,appimage --config src-tauri/tauri.release.conf.json

# ── 8. Report output ────────────────────────────────────────────────────────
step "Done"
BUNDLE_DIR="$PROJECT_ROOT/src-tauri/target/release/bundle"
echo -e "\033[1;32mBuild output located at: $BUNDLE_DIR\033[0m"
if [ -d "$BUNDLE_DIR" ]; then
    find "$BUNDLE_DIR" -maxdepth 3 -type f \( -name "*.deb" -o -name "*.AppImage" \) 2>/dev/null | while read -r f; do
        echo -e "\033[1;32m - $f\033[0m"
    done
fi

