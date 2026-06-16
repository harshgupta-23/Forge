import sys
import subprocess
from langchain_core.tools import tool

@tool
def read_clipboard() -> str:
    """
    Read and return the current text content of the system clipboard.
    Useful when the user says 'fix this' or 'use what I just copied'.
    Auto-installs pyperclip if missing.
    """
    try:
        import pyperclip
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pyperclip"], timeout=60)
        import pyperclip

    try:
        text = pyperclip.paste()
        if not text:
            return "Clipboard is empty."
        if len(text) > 20_000:
            text = text[:20_000] + "\n\n[...TRUNCATED — clipboard too large...]"
        return f"Clipboard contents ({len(text):,} chars):\n\n{text}"
    except Exception as exc:
        return f"ERROR reading clipboard: {exc}"