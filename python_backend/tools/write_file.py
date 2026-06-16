import traceback
from pathlib import Path
from langchain_core.tools import tool

def is_path_protected(file_path: str) -> bool:
    """Returns True if the path targets config.json, a dot-env file, or the backend folder."""
    try:
        target_path = Path(file_path.strip().strip('"').strip("'")).resolve()
        # Path of the tools directory -> backend directory
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
def write_file(file_path: str, content: str) -> str:
    """
    Write (or overwrite) a file at file_path with the given text content.
    Creates parent directories if they don't exist.
    Use this to save corrected code, updated documents, or any output file.
    """
    if is_path_protected(file_path):
        return "CRITICAL SECURITY ERROR: Access Denied. Writing to application source files or configurations is strictly prohibited."

    path = Path(file_path.strip().strip('"').strip("'"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"OK: File written — {path} ({path.stat().st_size} bytes)"
    except Exception as exc:
        return f"ERROR writing file: {exc}\n{traceback.format_exc()}"