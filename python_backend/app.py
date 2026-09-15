"""
app.py — Main entrypoint launcher shim for Forge Agent Backend.
Spawns the FastAPI + Uvicorn server while preserving compatibility with
Linux start scripts, Windows batch files, and the Tauri Rust supervisor.
"""

import sys
from pathlib import Path

# Resolve python_backend directory for bare package imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from server.main import run_server, app

if __name__ == "__main__":
    run_server()