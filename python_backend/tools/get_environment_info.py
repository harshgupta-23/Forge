import os
import sys
import platform
import subprocess
from langchain_core.tools import tool

@tool
def get_environment_info(query: str = "all") -> str:
    """
    Return environment details.
    query options: 'all' | 'python' | 'packages' | 'env_vars' | 'platform'
    Use to diagnose missing libraries, path issues, or OS-level problems.
    """
    q = query.lower().strip()
    sections = []

    if q in ("all", "python", "platform"):
        sections.append(
            f"Python: {sys.version}\n"
            f"Executable: {sys.executable}\n"
            f"Platform: {platform.platform()}\n"
            f"CWD: {os.getcwd()}"
        )

    if q in ("all", "packages"):
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=columns"],
            capture_output=True, text=True, timeout=30,
        )
        sections.append("Installed packages:\n" + result.stdout.strip())

    if q in ("all", "env_vars"):
        safe_keys = [
            "PATH", "PYTHONPATH", "HOME", "USERPROFILE", "APPDATA",
            "TEMP", "TMP", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV",
        ]
        env_lines = [
            f"  {k}={os.environ.get(k, '<not set>')}" for k in safe_keys
        ]
        sections.append("Environment variables:\n" + "\n".join(env_lines))

    return "\n\n─────\n\n".join(sections) if sections else "Unknown query type."