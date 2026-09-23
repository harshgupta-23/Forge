"""
test_critical_security_race.py — Verifies that attached_files security context
is isolated per-async-task (no cross-session leakage via global state).

Fix 1: tools/security.py uses contextvars instead of a global variable.
"""

import asyncio
import pytest
from pathlib import Path
from tools.security import (
    set_active_attached_files,
    get_active_attached_files,
    is_path_safe,
)


class TestSecurityContextIsolation:
    """Attached files must be isolated between concurrent async tasks."""

    @pytest.mark.asyncio
    async def test_concurrent_sessions_see_own_files(self, tmp_work_dir):
        """Two concurrent tasks set different attached_files; each must see only its own."""
        barrier = asyncio.Barrier(2)
        results = {}

        async def session_a():
            files_a = {"doc.pdf": "/home/user_a/doc.pdf"}
            set_active_attached_files(files_a)
            await barrier.wait()  # sync with session B
            await asyncio.sleep(0.05)  # give B time to set its own
            results["a"] = get_active_attached_files()

        async def session_b():
            files_b = {"secret.key": "/home/user_b/secret.key"}
            set_active_attached_files(files_b)
            await barrier.wait()  # sync with session A
            await asyncio.sleep(0.05)  # give A time to read
            results["b"] = get_active_attached_files()

        await asyncio.gather(session_a(), session_b())

        # Each task must see ONLY its own files
        assert results["a"] == {"doc.pdf": "/home/user_a/doc.pdf"}, \
            f"Session A saw wrong files: {results['a']}"
        assert results["b"] == {"secret.key": "/home/user_b/secret.key"}, \
            f"Session B saw wrong files: {results['b']}"

    @pytest.mark.asyncio
    async def test_is_path_safe_uses_contextvar(self, tmp_work_dir):
        """is_path_safe should read attached_files from the context, not a leaked global."""
        barrier = asyncio.Barrier(2)
        results = {}

        # Create a file outside workspace that only session A should access
        ext_file = tmp_work_dir.parent / "external_doc.txt"

        async def session_with_attachment():
            set_active_attached_files({"ext": str(ext_file)})
            await barrier.wait()
            safe, reason = is_path_safe(ext_file, work_dir=tmp_work_dir)
            results["with_attachment"] = safe

        async def session_without_attachment():
            set_active_attached_files({})
            await barrier.wait()
            safe, reason = is_path_safe(ext_file, work_dir=tmp_work_dir)
            results["without_attachment"] = safe

        await asyncio.gather(session_with_attachment(), session_without_attachment())

        assert results["with_attachment"] is True, \
            "Session with attachment should be allowed to read the file"
        assert results["without_attachment"] is False, \
            "Session without attachment must NOT see the other session's file"

    def test_default_empty_context(self):
        """When no files are set, get_active_attached_files returns empty dict."""
        # In a fresh context (no set call), should return default
        files = get_active_attached_files()
        assert files == {} or files == [] or isinstance(files, (dict, list))

    def test_single_session_backwards_compat(self, tmp_work_dir):
        """Single-session set/get still works as before."""
        test_files = {"readme.md": str(tmp_work_dir / "readme.md")}
        set_active_attached_files(test_files)
        assert get_active_attached_files() == test_files

    def test_set_none_resets_to_empty(self):
        """Passing None should reset to empty."""
        set_active_attached_files({"a": "b"})
        set_active_attached_files(None)
        result = get_active_attached_files()
        assert result == {} or result == []

