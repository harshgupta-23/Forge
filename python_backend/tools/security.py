# python_backend/security.py
import os
from pathlib import Path

def is_path_protected(file_path: str) -> bool:
    """
    Returns True if the path targets config.json, a dot-env file, 
    or any file inside the python_backend system directory.
    """
    try:
        # Resolve to an absolute, real system path to catch tricks like "../../"
        target_path = Path(file_path.strip().strip('"').strip("'")).resolve()
        backend_dir = Path(__file__).parent.resolve()
        root_dir = backend_dir.parent.resolve()
        config_file = root_dir / "config.json"

        # 1. Block access to config.json or environment files directly
        if target_path.name.lower() in ("config.json", ".env") or target_path == config_file:
            return True

        # 2. Block access to ANYTHING inside the python_backend directory
        if backend_dir in target_path.parents or target_path == backend_dir:
            return True

        return False
    except Exception:
        # If path resolution fails for any reason, fail-safe by blocking access
        return True