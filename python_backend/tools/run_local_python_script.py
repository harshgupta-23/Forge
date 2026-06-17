import os
import re
import sys
import tempfile
import traceback
import subprocess
import pathlib
from pathlib import Path
from datetime import datetime
from langchain_core.tools import tool

# Audit log setup
AUDIT_LOG_DIR = Path(os.environ.get("AGENT_AUDIT_DIR", Path.home() / ".agent_scripts"))

def _write_audit_log(script_code: str) -> Path:
    try:
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
        log_path = AUDIT_LOG_DIR / f"{ts}.py"
        log_path.write_text(script_code, encoding="utf-8")
        return log_path
    except Exception:
        return Path("/dev/null")

def _run_subprocess(cmd: list[str], timeout: int = 45) -> str:
    try:
        pip_install_dir = str(pathlib.Path.home() / ".myagent" / "python-packages")
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = pip_install_dir + (os.pathsep + existing if existing else "")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        parts = []
        if result.stdout.strip():
            parts.append(f"STDOUT:\n{result.stdout.strip()}")
        if result.stderr.strip():
            parts.append(f"STDERR:\n{result.stderr.strip()}")
        parts.append(f"EXIT CODE: {result.returncode}")
        return "\n\n".join(parts) if parts else "No output."
    except subprocess.TimeoutExpired:
        return "ERROR: Script timed out after execution limit."
    except Exception as exc:
        return f"ERROR launching subprocess: {exc}\n{traceback.format_exc()}"

_DESTRUCTIVE_PATTERNS = [
    r'\bos\.remove\b', r'\bos\.unlink\b', r'\bos\.rmdir\b', r'\bshutil\.rmtree\b',
    r'\bshutil\.move\b', r'\bpathlib.*\.unlink\b', r'\.unlink\(', r'\bDROP\s+TABLE\b',
    r'\bDROP\s+DATABASE\b', r'\bTRUNCATE\b', r'\bDELETE\s+FROM\b', r'\bformat\b.*\bdisk\b',
    r'\bsubprocess.*\bdel\b', r'\bsubprocess.*\brm\s+-rf\b', r'\brmdir\b'
]

def _check_destructive(script_code: str) -> list[str]:
    found = []
    for pattern in _DESTRUCTIVE_PATTERNS:
        if re.search(pattern, script_code, re.IGNORECASE):
            name = pattern.replace(r'\b', '').replace('\\b', '').replace('(', '').replace('\\s+', ' ').strip('\\').strip()
            found.append(name)
    return found

@tool
def run_local_python_script(script_code: str) -> str:
    """
    Execute a Python script string locally via a subprocess.
    Returns combined STDOUT, STDERR, and exit code.
    Timeout: 45 seconds.
    Every script is saved to ~/.agent_scripts/ for auditing.
    Prompts user confirmation if script contains destructive operations.
    """
    # CRITICAL LOOPHOLE FIREWALL
    forbidden_keywords = ["config.json", "python_backend", "app.py", "agent_engine", "security.py"]
    if any(keyword in script_code for keyword in forbidden_keywords):
        return "CRITICAL SECURITY ERROR: Script execution aborted. Code contains references to protected system files or directories."

    dangerous = _check_destructive(script_code)
    if dangerous:
        print(f"\n\033[93m⚠  WARNING: Script contains potentially destructive operations:\033[0m")
        print(f"   {', '.join(set(dangerous))}\n")
        print("\033[90m── Script preview ──────────────────────────────────────\033[0m")
        lines = script_code.splitlines()
        for i, line in enumerate(lines[:40], 1):
            print(f"  \033[90m{i:>3}│\033[0m {line}")
        if len(lines) > 40:
            print(f"  \033[90m   │ ... ({len(lines) - 40} more lines)\033[0m")
        print("\033[90m────────────────────────────────────────────────────────\033[0m")
        try:
            answer = input("\n\033[93mRun this script? (y/n):\033[0m ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer != "y":
            return "BLOCKED: User declined to run destructive script. Inform the user and ask how to proceed."

    log_path = _write_audit_log(script_code)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
        tmp.write(script_code)
        tmp_path = tmp.name

    try:
        result = _run_subprocess([sys.executable, tmp_path], timeout=45)
        return f"[audit log: {log_path}]\n\n{result}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass