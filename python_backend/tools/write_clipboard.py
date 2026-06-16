import sys
import subprocess
from langchain_core.tools import tool

@tool
def write_clipboard(text: str) -> str:
    """
    Write text to the system clipboard so the user can paste it anywhere.
    Use this to deliver corrected code, results, or any output back to the user.
    Auto-installs pyperclip if missing.
    """
    try:
        import pyperclip
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pyperclip"], timeout=60)
        import pyperclip

    try:
        pyperclip.copy(text)
        preview = text[:120] + ("…" if len(text) > 120 else "")
        return f"OK: {len(text):,} chars written to clipboard.\nPreview: {preview}"
    except Exception as exc:
        return f"ERROR writing clipboard: {exc}"