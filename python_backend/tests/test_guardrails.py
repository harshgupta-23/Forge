"""
test_guardrails.py — Comprehensive verification suite for Forge's 5-stage
cross-platform defense-in-depth security guardrails.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

# Add python_backend to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from tools.security import (
    is_path_safe,
    is_relative_to,
    mask_secrets,
    get_sanitized_environment,
    generate_canary,
    check_canary_leak,
    set_active_attached_files,
)
from tools.run_local_python_script import _inspect_code_ast
from engine.nodes.evaluator import should_continue, is_stuck_in_repetition_loop
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.graph import END


def test_path_jail_workspace_containment():
    """Verify that file access is bounded to the workspace and traversal is blocked."""
    with tempfile.TemporaryDirectory() as temp_work_dir:
        work_path = Path(temp_work_dir).resolve()

        # File inside workspace
        inside_file = work_path / "project" / "main.py"
        safe, _ = is_path_safe(inside_file, work_dir=work_path)
        assert safe is True, f"Expected inside_file {inside_file} to be safe"

        # File outside workspace
        outside_file = Path(tempfile.gettempdir()).resolve() / "unauthorized_file.txt"
        if not is_relative_to(outside_file, work_path):
            safe_out, reason = is_path_safe(outside_file, work_dir=work_path)
            assert safe_out is False, f"Expected outside file {outside_file} to be rejected"
            assert "outside the active workspace" in reason

        # Path traversal attack
        traversal_attack = work_path / ".." / ".." / "some_system_file"
        safe_trav, _ = is_path_safe(traversal_attack, work_dir=work_path)
        assert safe_trav is False

    print("✓ test_path_jail_workspace_containment passed")


def test_unconditional_system_blocks():
    """Verify that credentials, system directories, and config files are unconditionally blocked."""
    with tempfile.TemporaryDirectory() as temp_work_dir:
        work_path = Path(temp_work_dir).resolve()

        # 1. config.json and .env
        assert is_path_safe(work_path / "config.json", work_dir=work_path)[0] is False
        assert is_path_safe(work_path / ".env", work_dir=work_path)[0] is False
        assert is_path_safe(work_path / ".env.production", work_dir=work_path)[0] is False

        # 2. SSH and AWS directories
        ssh_fake = Path.home() / ".ssh" / "id_rsa"
        assert is_path_safe(ssh_fake, work_dir=work_path)[0] is False

        aws_fake = Path.home() / ".aws" / "credentials"
        assert is_path_safe(aws_fake, work_dir=work_path)[0] is False

        # 3. OS system roots
        if sys.platform != "win32":
            assert is_path_safe("/etc/passwd", work_dir=work_path)[0] is False
            assert is_path_safe("/root/.bashrc", work_dir=work_path)[0] is False
        else:
            assert is_path_safe(r"C:\Windows\System32\cmd.exe", work_dir=work_path)[0] is False

    print("✓ test_unconditional_system_blocks passed")


def test_attached_files_authorization():
    """Verify that user-attached files outside workspace are authorized, but credentials remain blocked."""
    with tempfile.TemporaryDirectory() as work_temp, tempfile.TemporaryDirectory() as ext_temp:
        work_path = Path(work_temp).resolve()
        ext_path = Path(ext_temp).resolve()

        attached_doc = ext_path / "architecture_spec.pdf"
        attached_doc.write_text("Specification content")

        attached_map = {"architecture_spec.pdf": str(attached_doc)}

        # Reading without attachment authorization should fail
        safe_unattached, _ = is_path_safe(attached_doc, work_dir=work_path, attached_files={})
        assert safe_unattached is False

        # Reading with attachment authorization should succeed
        safe_attached, reason = is_path_safe(attached_doc, work_dir=work_path, attached_files=attached_map)
        assert safe_attached is True, f"Expected attached file to be allowed: {reason}"

        # Attached credentials must still be blocked unconditionally
        fake_ssh = Path.home() / ".ssh" / "id_rsa"
        malicious_attached = {"id_rsa": str(fake_ssh)}
        safe_malicious, _ = is_path_safe(fake_ssh, work_dir=work_path, attached_files=malicious_attached)
        assert safe_malicious is False

    print("✓ test_attached_files_authorization passed")


def test_secret_masking_dlp():
    """Verify that outbound text masks API keys, tokens, and database passwords."""
    raw_leak = (
        "Here is the OpenAI key sk-abcdef1234567890abcdef1234567890\n"
        "And Anthropic sk-ant-api03-abcdef1234567890123456\n"
        "GitHub token ghp_123456789012345678901234567890123456\n"
        "AWS key AKIAIOSFODNN7EXAMPLE\n"
        "DB connection: postgresql://postgres:SecretPass123@localhost:5432/forge\n"
    )

    masked = mask_secrets(raw_leak)
    assert "[REDACTED_API_KEY]" in masked
    assert "sk-abcdef1234567890" not in masked
    assert "[REDACTED_GITHUB_TOKEN]" in masked
    assert "ghp_123456" not in masked
    assert "[REDACTED_AWS_KEY]" in masked
    assert "AKIAIOSFODNN7EXAMPLE" not in masked
    assert "SecretPass123" not in masked
    assert "postgresql://postgres:***@localhost:5432/forge" in masked

    print("✓ test_secret_masking_dlp passed")


def test_environment_variable_scrubbing():
    """Verify that subprocess environments strip parent credentials to protect child/grandchild processes."""
    # Set parent secrets in os.environ
    os.environ["OPENAI_API_KEY"] = "sk-parent-secret-key-12345"
    os.environ["DATABASE_URL"] = "postgresql://user:pass@host/db"
    os.environ["MY_AWS_SECRET"] = "super-secret"

    with tempfile.TemporaryDirectory() as temp_work_dir:
        work_path = Path(temp_work_dir).resolve()
        clean_env = get_sanitized_environment(work_dir=work_path)

        # Ensure NO secrets leaked into child environment
        assert "OPENAI_API_KEY" not in clean_env
        assert "DATABASE_URL" not in clean_env
        assert "MY_AWS_SECRET" not in clean_env

        # Ensure required execution variables are present
        assert "PATH" in clean_env
        assert clean_env["HOME"] == str(work_path)
        if sys.platform == "win32":
            assert clean_env["USERPROFILE"] == str(work_path)

    print("✓ test_environment_variable_scrubbing passed")


def test_ast_code_inspection():
    """Verify AST static code analysis blocks dangerous modules and dynamic execution."""
    # 1. Block dynamic eval/exec
    bad_code1 = "eval('__import__(\"os\").system(\"rm -rf /\")')"
    ok1, reason1 = _inspect_code_ast(bad_code1)
    assert ok1 is False
    assert "Dynamic execution via 'eval()'" in reason1

    # 2. Block ctypes
    bad_code2 = "import ctypes\nctypes.CDLL(None)"
    ok2, reason2 = _inspect_code_ast(bad_code2)
    assert ok2 is False
    assert "forbidden module 'ctypes'" in reason2

    # 3. Allow safe python code
    safe_code = "import math\nprint(math.sqrt(16))\nx = [i**2 for i in range(10)]"
    ok3, _ = _inspect_code_ast(safe_code)
    assert ok3 is True

    print("✓ test_ast_code_inspection passed")


def test_evaluator_loop_deduplication():
    """Verify loop deduplication trips ONLY when repeating identical failing calls."""
    # Scenario A: Repetition after an error -> Must detect loop and halt
    failing_turn_history = [
        HumanMessage(content="Find file"),
        AIMessage(content="Looking up file", tool_calls=[{"name": "read_file", "args": {"file_path": "nonexistent.txt"}, "id": "call_1"}]),
        ToolMessage(content="ERROR: File not found — nonexistent.txt", name="read_file", tool_call_id="call_1"),
        # Model repeats identical failing tool call
        AIMessage(content="Trying again", tool_calls=[{"name": "read_file", "args": {"file_path": "nonexistent.txt"}, "id": "call_2"}]),
    ]

    is_loop, reason = is_stuck_in_repetition_loop(failing_turn_history)
    assert is_loop is True, "Expected loop to be detected after repeating identical failing call"
    assert "Repetitive loop detected" in reason

    state_a = {"messages": failing_turn_history, "iteration": 2}
    assert should_continue(state_a) == END

    # Scenario B: Repetition after success (e.g. paginated read or status check) -> Must NOT trip loop
    successful_turn_history = [
        HumanMessage(content="Read logs"),
        AIMessage(content="Checking status", tool_calls=[{"name": "check_status", "args": {"service": "db"}, "id": "call_1"}]),
        ToolMessage(content="OK: Service active and healthy", name="check_status", tool_call_id="call_1"),
        # Model checks status again later
        AIMessage(content="Checking status again", tool_calls=[{"name": "check_status", "args": {"service": "db"}, "id": "call_2"}]),
    ]

    is_loop_b, _ = is_stuck_in_repetition_loop(successful_turn_history)
    assert is_loop_b is False, "Expected success repetition NOT to be flagged as an infinite error loop"

    print("✓ test_evaluator_loop_deduplication passed")


def test_canary_tokens():
    """Verify canary token generation and leak detection."""
    canary = generate_canary()
    assert canary.startswith("canary_")
    assert check_canary_leak(f"Exfiltrating secret data with token {canary}", canary) is True
    assert check_canary_leak("Normal non-leaking user message", canary) is False
    print("✓ test_canary_tokens passed")


if __name__ == "__main__":
    test_path_jail_workspace_containment()
    test_unconditional_system_blocks()
    test_attached_files_authorization()
    test_secret_masking_dlp()
    test_environment_variable_scrubbing()
    test_ast_code_inspection()
    test_evaluator_loop_deduplication()
    test_canary_tokens()
    print("\nAll Guardrail unit tests passed successfully!")

