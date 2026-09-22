import traceback
from pathlib import Path
from langchain_core.tools import tool

try:
    from tools.security import is_path_safe
except ImportError:
    from security import is_path_safe

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

@tool
def read_file(file_path: str) -> str:
    """
    Read and return the text content of any file (source code, docs, txt, csv…).
    For binary files it returns a hex dump of the first 2 KB.
    """
    safe, reason = is_path_safe(file_path)
    if not safe:
        return f"CRITICAL SECURITY ERROR: Access Denied. {reason}"

    path = Path(file_path.strip().strip('"').strip("'"))
    
    if not path.exists():
        return f"ERROR: File not found — {path}"
    if not path.is_file():
        return f"ERROR: Path is not a file — {path}"

    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            return f"ERROR: File size ({size:,} bytes) exceeds the 10 MB security limit — {path}"

        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > 20_000:
            text = text[:20_000] + "\n\n[...TRUNCATED — file too large...]"
        return text
    except Exception as exc:
        raw = path.read_bytes()[:2048]
        return f"Binary file (first 2 KB hex):\n{raw.hex()}\nRead error: {exc}"