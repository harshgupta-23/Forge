import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from langchain_core.tools import tool

SCREENSHOT_DIR = Path(os.environ.get("SCREENSHOT_DIR", r"C:\Users\DELL\OneDrive\Pictures\Screenshots"))

@tool
def take_screenshot(filename: str = "") -> str:
    """
    Take a screenshot of the entire screen and save it as a PNG.
    filename is optional — if omitted a timestamp name is used.
    Saves to SCREENSHOT_DIR (set via SCREENSHOT_DIR env var).
    Auto-installs Pillow if missing.
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "Pillow"], timeout=60)
        from PIL import ImageGrab

    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        if filename.strip():
            name = filename.strip()
            if not name.lower().endswith(".png"):
                name += ".png"
        else:
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            name = f"screenshot_{ts}.png"

        save_path = SCREENSHOT_DIR / name
        img = ImageGrab.grab()
        img.save(save_path, "PNG")
        size_kb = save_path.stat().st_size // 1024
        return f"OK: Screenshot saved → {save_path}  ({size_kb} KB, {img.size[0]}×{img.size[1]})"
    except Exception as exc:
        return f"ERROR taking screenshot: {exc}"