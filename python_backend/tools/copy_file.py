import shutil
import traceback
from pathlib import Path
from langchain_core.tools import tool

@tool
def copy_file(source_path: str, destination_path: str) -> str:
    """
    Copy a file from source_path to destination_path.
    Useful for transferring outputs, making backups before editing, etc.
    Creates destination parent directories if needed.
    """
    src = Path(source_path.strip().strip('"').strip("'"))
    dst = Path(destination_path.strip().strip('"').strip("'"))
    if not src.exists():
        return f"ERROR: Source not found — {src}"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return f"OK: Copied {src} → {dst}"
    except Exception as exc:
        return f"ERROR copying file: {exc}\n{traceback.format_exc()}"