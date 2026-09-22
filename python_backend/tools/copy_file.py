import shutil
import traceback
from pathlib import Path
from langchain_core.tools import tool

try:
    from tools.security import is_path_safe
except ImportError:
    from security import is_path_safe

@tool
def copy_file(source_path: str, destination_path: str) -> str:
    """
    Copy a file from source_path to destination_path.
    Useful for transferring outputs, making backups before editing, etc.
    Creates destination parent directories if needed.
    """
    safe_src, reason_src = is_path_safe(source_path)
    if not safe_src:
        return f"CRITICAL SECURITY ERROR: Source Access Denied. {reason_src}"

    safe_dst, reason_dst = is_path_safe(destination_path, allow_outside_workspace_attached=False)
    if not safe_dst:
        return f"CRITICAL SECURITY ERROR: Destination Access Denied. {reason_dst}"

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