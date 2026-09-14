import sys
import subprocess
import pathlib
import importlib
import shutil
from langchain_core.tools import tool

# Mirrors PIP_INSTALL_DIR in app.py (kept independent rather than imported
# from it, to avoid re-importing app.py as a second module distinct from
# the running __main__ instance, which would re-run its startup code).
PIP_INSTALL_DIR = pathlib.Path.home() / ".forge" / "python-packages"
PIP_INSTALL_DIR.mkdir(parents=True, exist_ok=True)

@tool
def pip_install(packages: str) -> str:
    """
    Install one or more Python packages using pip or uv.
    Pass a space-separated string of package names, e.g. 'reportlab pillow'.
    Returns the install output.
    """
    pkg_list = packages.strip().split()
    if not pkg_list:
        return "ERROR: No package names provided."

    # sys.executable always points at whichever interpreter is actually
    # running this process - the dev venv's python in development, or
    # the embedded python inside the installed app in production.
    # Target the writable PIP_INSTALL_DIR rather than the interpreter's
    # own site-packages, since the embedded distro's site-packages lives
    # under Program Files / system directories post-install and is read-only
    # to standard (non-admin) users. app.py adds PIP_INSTALL_DIR to sys.path at
    # startup, so anything installed here becomes importable.

    uv_path = shutil.which("uv")
    result = None

    # 1. Prefer uv if available (ultra-fast, works even when pip is not in venv)
    if uv_path:
        cmd = [
            uv_path, "pip", "install",
            "--target", str(PIP_INSTALL_DIR),
            "--python", sys.executable,
            "--link-mode", "copy",
        ] + pkg_list
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode == 0:
                result = res
        except Exception:
            result = None

    # 2. Fall back to standard pip if uv is not available or if uv failed
    if result is None:
        cmd = [
            sys.executable, "-m", "pip", "install", "--quiet",
            "--target", str(PIP_INSTALL_DIR),
            "--no-warn-script-location",
        ] + pkg_list
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return "ERROR: pip install timed out."
        except Exception as exc:
            return f"ERROR launching installer subprocess: {exc}"

    if result.returncode == 0:
        # Make newly installed packages importable in this same session
        # without restarting the app.
        importlib.invalidate_caches()

    parts = []
    if result.stdout.strip():
        parts.append(f"STDOUT:\n{result.stdout.strip()}")
    if result.stderr.strip():
        parts.append(f"STDERR:\n{result.stderr.strip()}")
    parts.append(f"EXIT CODE: {result.returncode}")
    return "\n\n".join(parts) if parts else "No output."