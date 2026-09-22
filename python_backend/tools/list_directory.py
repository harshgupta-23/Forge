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
    for item in sorted(path.iterdir()):
        kind = "DIR " if item.is_dir() else "FILE"
        size = ""
        if item.is_file():
            size = f"  {item.stat().st_size:,} bytes"
        lines.append(f"  [{kind}]  {item.name}{size}")
    return "\n".join(lines) if len(lines) > 1 else f"{path} is empty."