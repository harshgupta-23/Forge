import os
import re
import sys
import ast
import shutil
import tempfile
import traceback
import subprocess
import pathlib
from pathlib import Path
from datetime import datetime
from langchain_core.tools import tool

try:
    from tools.security import get_sanitized_environment, is_path_safe
except ImportError:
    from security import get_sanitized_environment, is_path_safe

# Audit log setup (all stored under ~/.forge/agent_scripts)
AUDIT_LOG_DIR = Path(os.environ.get("AGENT_AUDIT_DIR", Path.home() / ".forge" / "agent_scripts"))


def _write_audit_log(script_code: str) -> Path:
    try:
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
        log_path = AUDIT_LOG_DIR / f"{ts}.py"
        log_path.write_text(script_code, encoding="utf-8")
        return log_path
    except Exception:
        return Path("/dev/null")


def _inspect_code_ast(script_code: str) -> tuple[bool, str]:
    """
    Parses the script AST to detect forbidden imports, dynamic evaluation (eval/exec),
    and attempts to reference sensitive paths.
    """
    try:
        tree = ast.parse(script_code)
    except SyntaxError as e:
        return False, f"Syntax error in script: {e}"

    blocked_modules = {"ctypes", "pty", "winreg"}
    blocked_calls = {"eval", "exec", "compile"}

    for node in ast.walk(tree):
        # Check module imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0].lower()
                if root_pkg in blocked_modules:
                    return False, f"Security Violation: Import of forbidden module '{alias.name}' is blocked."
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_pkg = node.module.split(".")[0].lower()
                if root_pkg in blocked_modules:
                    return False, f"Security Violation: Import from forbidden module '{node.module}' is blocked."

        # Check dynamic execution calls
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in blocked_calls:
                return False, f"Security Violation: Dynamic execution via '{func.id}()' is blocked."

    return True, "AST inspection passed"


def _run_subprocess(cmd: list[str], work_dir: Path, timeout: int = 45) -> str:
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        env = get_sanitized_environment(work_dir=work_dir)

        final_cmd = cmd
        # On Linux, wrap with bubblewrap if available for filesystem isolation
        if sys.platform.startswith("linux"):
            bwrap_bin = shutil.which("bwrap")
            if bwrap_bin:
                try:
                    bwrap_args = [
                        bwrap_bin,
                        "--ro-bind", "/", "/",
                        "--bind", str(work_dir), str(work_dir),
                        "--dev", "/dev",
                        "--proc", "/proc",
                        "--tmpfs", "/tmp",
                    ]
                    ssh_dir = Path.home() / ".ssh"
                    if ssh_dir.exists():
                        bwrap_args.extend(["--tmpfs", str(ssh_dir)])
                    aws_dir = Path.home() / ".aws"
                    if aws_dir.exists():
                        bwrap_args.extend(["--tmpfs", str(aws_dir)])
                    final_cmd = bwrap_args + cmd
                except Exception:
                    final_cmd = cmd

        result = subprocess.run(
            final_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(work_dir),
            close_fds=(sys.platform != "win32")
        )
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
    Execute a Python script string locally in an isolated subprocess.
    Returns combined STDOUT, STDERR, and exit code.
    Timeout: 45 seconds.
    Every script is saved to ~/.forge/agent_scripts/ for auditing.
    Subprocesses execute with scrubbed environment to protect credentials.
    """
    # 1. Critical keyword firewall
    forbidden_keywords = ["config.json", "python_backend", "app.py", "agent_engine", "security.py", ".ssh", ".aws"]
    for keyword in forbidden_keywords:
        if keyword in script_code:
            return f"CRITICAL SECURITY ERROR: Script execution aborted. Code contains reference to protected keyword: '{keyword}'."

    # 2. AST Static Code Analysis
    ast_ok, ast_reason = _inspect_code_ast(script_code)
    if not ast_ok:
        return f"CRITICAL SECURITY ERROR: {ast_reason}"

    # 3. Check for destructive operations
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
    work_dir = Path(os.environ.get("AGENT_WORK_DIR", Path.cwd())).resolve()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir=str(work_dir), encoding="utf-8") as tmp:
        tmp.write(script_code)
        tmp_path = tmp.name

    try:
        result = _run_subprocess([sys.executable, tmp_path], work_dir=work_dir, timeout=45)
        return f"[audit log: {log_path}]\n\n{result}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass