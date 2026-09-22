# python_backend/tools/security.py
"""
security.py — Centralized, cross-platform security engine for Forge.
Provides:
- Strict path jail and boundary checking (Linux & Windows safe, handles UNC & symlinks)
- Attached file authorization (permits user-attached files outside AGENT_WORK_DIR)
- Subprocess environment scrubbing (zero secret inheritance across child/grandchild processes)
- Outbound secret masking and DLP (redacting API keys, private keys, database passwords)
- Canary token generation and exfiltration detection
"""

import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable

# ── 1. Cross-Platform Relative Path Helper ────────────────────────────────────
def is_relative_to(target: Path, base: Path) -> bool:
    """
    Checks if target is relative to base, safely handling symlinks, UNC paths,
    and Windows case-insensitivity.
    """
    try:
        t = target.resolve(strict=False)
        b = base.resolve(strict=False)

        if sys.platform == "win32":
            # On Windows, drive letters and paths are case-insensitive
            t_str = str(t).lower()
            b_str = str(b).lower()
            return t_str == b_str or t_str.startswith(b_str.rstrip("\\") + "\\")
        else:
            try:
                t.relative_to(b)
                return True
            except ValueError:
                return False
    except Exception:
        return False


# ── 2. System and Credential Blocklists ────────────────────────────────────────
_BLOCKED_FILE_NAMES = {
    "config.json",
    ".env",
    ".env.local",
    ".env.production",
    ".bashrc",
    ".zshrc",
    ".bash_history",
    ".zsh_history",
    ".profile",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "known_hosts",
    "authorized_keys"
}

_BLOCKED_SUBSTRINGS = (
    ".ssh",
    ".aws",
    ".kube",
    ".gnupg",
    ".docker",
)

def _is_unconditional_system_block(path: Path) -> bool:
    """Checks if a resolved path targets critical OS or credential directories."""
    resolved = path.resolve(strict=False)
    resolved_str = str(resolved)
    name_lower = resolved.name.lower()

    if name_lower in _BLOCKED_FILE_NAMES:
        return True

    # Check dot-env variants
    if name_lower.startswith(".env"):
        return True

    # Check sensitive credential folder substrings
    for part in resolved.parts:
        if part.lower() in _BLOCKED_SUBSTRINGS:
            return True

    # Block python_backend itself (to prevent agent self-modification)
    backend_dir = Path(__file__).parent.parent.resolve()
    if is_relative_to(resolved, backend_dir):
        return True

    if sys.platform == "win32":
        # Windows system folder checks
        win_sys_roots = [
            os.environ.get("SYSTEMROOT", r"C:\Windows"),
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("APPDATA", ""),
        ]
        for sroot in win_sys_roots:
            if sroot and is_relative_to(resolved, Path(sroot)):
                return True
    else:
        # Linux / Unix system folder checks
        posix_blocked_roots = [
            Path("/etc"),
            Path("/root"),
            Path("/sys"),
            Path("/proc"),
            Path("/dev"),
            Path("/boot"),
        ]
        for sroot in posix_blocked_roots:
            if is_relative_to(resolved, sroot):
                return True

    return False


# ── 3. Workspace Path Jail & Attached Files ────────────────────────────────────
_CURRENT_ATTACHED_FILES: dict[str, str] | list[str] = {}

def set_active_attached_files(files: dict[str, str] | list[str] | None) -> None:
    """Sets session-active attached files for global path security validation."""
    global _CURRENT_ATTACHED_FILES
    _CURRENT_ATTACHED_FILES = files or {}

def get_active_attached_files() -> dict[str, str] | list[str]:
    return _CURRENT_ATTACHED_FILES

def is_path_safe(
    file_path: str | Path,
    work_dir: str | Path | None = None,
    attached_files: Iterable[str] | dict[str, Any] | None = None,
    allow_outside_workspace_attached: bool = True
) -> tuple[bool, str]:
    """
    Validates if a file path is safe to access:
    1. Unconditionally blocks credentials (~/.ssh, ~/.aws, config.json, .env, OS roots).
    2. Allows user-attached files from session state even if outside AGENT_WORK_DIR.
    3. Requires all other files to be strictly contained within AGENT_WORK_DIR.
    Returns: (is_safe: bool, reason: str)
    """
    try:
        if attached_files is None:
            attached_files = _CURRENT_ATTACHED_FILES

        raw_str = str(file_path).strip().strip('"').strip("'")
        if not raw_str:
            return False, "Path cannot be empty."

        target = Path(raw_str).resolve(strict=False)

        # 1. Unconditional system & credential blocklist check
        if _is_unconditional_system_block(target):
            return False, f"Security Violation: Access to system or credential path '{target.name}' is strictly forbidden."

        # 2. Check if explicitly user-attached
        if allow_outside_workspace_attached and attached_files:
            attached_list = (
                attached_files.values() if isinstance(attached_files, dict)
                else attached_files
            )
            for att in attached_list:
                if not att:
                    continue
                att_path = Path(str(att).strip().strip('"').strip("'")).resolve(strict=False)
                if sys.platform == "win32":
                    if str(target).lower() == str(att_path).lower():
                        return True, "User-attached file"
                else:
                    if target == att_path:
                        return True, "User-attached file"

        # 3. Resolve workspace root
        if not work_dir:
            work_dir = os.environ.get("AGENT_WORK_DIR") or Path.cwd()
        resolved_work_dir = Path(work_dir).resolve(strict=False)

        # 4. Check workspace containment
        if is_relative_to(target, resolved_work_dir):
            return True, "Within workspace boundary"

        return False, f"Security Violation: Path '{target}' is outside the active workspace '{resolved_work_dir}'."
    except Exception as exc:
        return False, f"Security Validation Error: {exc}"


def is_path_protected(file_path: str) -> bool:
    """
    Backward-compatibility wrapper for legacy tools.
    Returns True if the path is NOT safe (blocked).
    """
    safe, _ = is_path_safe(file_path)
    return not safe


# ── 4. Subprocess Environment Scrubbing ────────────────────────────────────────
def get_sanitized_environment(
    work_dir: Path | str | None = None,
    extra_env: dict[str, str] | None = None
) -> dict[str, str]:
    """
    Creates a minimal, scrubbed environment dictionary for subprocess execution.
    Guarantees child, grandchild, and descendant processes inherit ZERO parent
    API keys, database URLs, or secret tokens.
    """
    if sys.platform == "win32":
        safe_keys = {
            "PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT",
            "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "TZ"
        }
    else:
        safe_keys = {
            "PATH", "LANG", "LC_ALL", "TERM", "TZ"
        }

    clean_env = {k: os.environ[k] for k in safe_keys if k in os.environ}

    w_dir = Path(work_dir).resolve(strict=False) if work_dir else Path.cwd().resolve()

    # Point home directories to the workspace sandbox
    clean_env["HOME"] = str(w_dir)
    clean_env["TMPDIR"] = str(w_dir / "tmp")
    if sys.platform == "win32":
        clean_env["USERPROFILE"] = str(w_dir)
        clean_env["TEMP"] = str(w_dir / "tmp")
        clean_env["TMP"] = str(w_dir / "tmp")

    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"

    # Merge user-installed packages path if present
    pip_install_dir = str(Path.home() / ".forge" / "python-packages")
    existing_py_path = clean_env.get("PYTHONPATH", "")
    clean_env["PYTHONPATH"] = pip_install_dir + (os.pathsep + existing_py_path if existing_py_path else "")

    if extra_env:
        for k, v in extra_env.items():
            # Never allow sensitive keys to be overridden back in
            k_upper = k.upper()
            if not any(bad in k_upper for bad in ("KEY", "SECRET", "TOKEN", "PASSWORD", "DATABASE_URL")):
                clean_env[k] = v

    return clean_env


# ── 5. Secret Masking & DLP ───────────────────────────────────────────────────
_SECRET_PATTERNS = [
    # OpenAI API Keys
    (re.compile(r'\bsk-[a-zA-Z0-9_\-]{20,}\b'), '[REDACTED_API_KEY]'),
    # Anthropic API Keys
    (re.compile(r'\bsk-ant-[a-zA-Z0-9_\-]{20,}\b'), '[REDACTED_API_KEY]'),
    # GitHub Personal Access Tokens
    (re.compile(r'\b(ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}\b'), '[REDACTED_GITHUB_TOKEN]'),
    # AWS Access Key IDs
    (re.compile(r'\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b'), '[REDACTED_AWS_KEY]'),
    # Private Keys (RSA, EC, OpenSSH)
    (re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'), '[REDACTED_PRIVATE_KEY]'),
    # Database connection URLs with embedded passwords
    (re.compile(r'((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?):\/\/[^\s:]+:)([^@\s]+)(@)'), r'\1***\3'),
]

def mask_secrets(text: str) -> str:
    """Masks high-entropy credentials, tokens, and private keys in outbound text."""
    if not text:
        return text
    sanitized = text
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


# ── 6. Canary Token Traps ─────────────────────────────────────────────────────
def generate_canary() -> str:
    """Generates a unique per-session canary token to detect exfiltration."""
    return f"canary_{uuid.uuid4().hex[:12]}"

def check_canary_leak(text: str, canary: str) -> bool:
    """Returns True if the canary token is detected in outbound traffic."""
    if not canary or not text:
        return False
    return canary in text