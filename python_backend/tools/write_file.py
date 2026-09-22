import traceback
from pathlib import Path
from langchain_core.tools import tool

try:
    from tools.security import is_path_safe
except ImportError:
    from security import is_path_safe

@tool
def write_file(file_path: str, content: str) -> str:
    """
    Write (or overwrite) a file at file_path with the given text content.
    Creates parent directories if they don't exist.
    Use this to save corrected code, updated documents, or any output file.
    """
    safe, reason = is_path_safe(file_path, allow_outside_workspace_attached=False)
    if not safe:
        return f"CRITICAL SECURITY ERROR: Access Denied. {reason}"

    path = Path(file_path.strip().strip('"').strip("'"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"OK: File written — {path} ({path.stat().st_size} bytes)"
    except Exception as exc:
        return f"ERROR writing file: {exc}\n{traceback.format_exc()}"