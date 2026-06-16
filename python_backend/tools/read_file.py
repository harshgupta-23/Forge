import traceback
from pathlib import Path
from langchain_core.tools import tool

def is_path_protected(file_path: str) -> bool:
    """Returns True if the path targets config.json, a dot-env file, or the backend folder."""
    try:
        target_path = Path(file_path.strip().strip('"').strip("'")).resolve()
        backend_dir = Path(__file__).parent.parent.resolve()
        root_dir = backend_dir.parent.resolve()
        config_file = root_dir / "config.json"

        if target_path.name.lower() in ("config.json", ".env") or target_path == config_file:
            return True
        if backend_dir in target_path.parents or target_path == backend_dir:
            return True
        return False
    except Exception:
        return True

@tool
def read_file(file_path: str) -> str:
    """
    Read and return the text content of any file (source code, docs, txt, csv…).
    For binary files it returns a hex dump of the first 2 KB.
    """
    if is_path_protected(file_path):
        return "CRITICAL SECURITY ERROR: Access Denied. Reading application source files or configurations is strictly prohibited."

    path = Path(file_path.strip().strip('"').strip("'"))
    
    if not path.exists():
        return f"ERROR: File not found — {path}"
    if not path.is_file():
        return f"ERROR: Path is not a file — {path}"

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > 20_000:
            text = text[:20_000] + "\n\n[...TRUNCATED — file too large...]"
        return text
    except Exception as exc:
        raw = path.read_bytes()[:2048]
        return f"Binary file (first 2 KB hex):\n{raw.hex()}\nRead error: {exc}"