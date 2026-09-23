import os
from pathlib import Path
from langchain_core.tools import tool

try:
    from tools.security import is_path_safe
except ImportError:
    from security import is_path_safe

@tool
def list_directory(directory_path: str) -> str:
    """
    List files and sub-directories inside directory_path.
    Returns names, types (file/dir), and sizes.
    """
    safe, reason = is_path_safe(directory_path)
    if not safe:
        return f"CRITICAL SECURITY ERROR: Access Denied. {reason}"

    path = Path(directory_path.strip().strip('"').strip("'"))
    if not path.exists():
        return f"ERROR: Directory not found — {path}"
    if not path.is_dir():
        return f"ERROR: Path is not a directory — {path}"

    lines = [f"Contents of {path}:\n"]
    try:
        with os.scandir(path) as it:
            entries = sorted(it, key=lambda e: e.name)
            for entry in entries:
                is_d = entry.is_dir(follow_symlinks=False)
                is_f = entry.is_file(follow_symlinks=False)
                kind = "DIR " if is_d else "FILE"
                size = ""
                if is_f:
                    try:
                        size = f"  {entry.stat(follow_symlinks=False).st_size:,} bytes"
                    except OSError:
                        size = ""
                lines.append(f"  [{kind}]  {entry.name}{size}")
    except OSError as e:
        return f"ERROR: Could not read directory — {e}"

    return "\n".join(lines) if len(lines) > 1 else f"{path} is empty."