import sys
import subprocess
import shutil
from langchain_core.tools import tool

@tool
def pip_install(packages: str) -> str:
    """
    Install one or more Python packages using pip.
    Pass a space-separated string of package names, e.g. 'reportlab pillow'.
    Returns the pip output.
    """
    pkg_list = packages.strip().split()
    if not pkg_list:
        return "ERROR: No package names provided."

    # In frozen exe, sys.executable is the bundled exe — find real system Python instead
    if getattr(sys, 'frozen', False):
        python = shutil.which("python") or shutil.which("python3")
        if not python:
            return "ERROR: No system Python found. Please install Python and add it to PATH."
    else:
        python = sys.executable

    cmd = [python, "-m", "pip", "install", "--quiet"] + pkg_list

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        parts = []
        if result.stdout.strip():
            parts.append(f"STDOUT:\n{result.stdout.strip()}")
        if result.stderr.strip():
            parts.append(f"STDERR:\n{result.stderr.strip()}")
        parts.append(f"EXIT CODE: {result.returncode}")
        return "\n\n".join(parts) if parts else "No output."
    except subprocess.TimeoutExpired:
        return "ERROR: pip install timed out."
    except Exception as exc:
        return f"ERROR launching subprocess: {exc}"