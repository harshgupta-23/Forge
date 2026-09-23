"""
test_critical_bulk_delete.py — Verifies that session_manager.delete_checkpoints
executes bulk vectorized queries (3 statements total) rather than N+1 per-checkpoint loops.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from storage.session_manager import session_manager
from storage.checkpointer import checkpoint_manager
from storage.metadata import metadata_store


class TestCriticalBulkDelete:
    @pytest.mark.asyncio
    async def test_bulk_delete_exact_query_count_sqlite(self):
        """In SQLite, deleting 25 checkpoints must execute exactly 3 DELETE statements."""
        thread_id = "bulk_del_thread"
        checkpoint_ids = {f"chk_{i:03d}" for i in range(25)}

        executed_statements = []

        class MockCursor:
            async def fetchall(self):
                return []
            async def fetchone(self):
                return None
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        class MockDb:
            async def execute(self, sql, params=None):
                executed_statements.append((sql, params))
                return MockCursor()
            async def commit(self):
                pass

        mock_db = MockDb()

        mock_conn_ctx = MagicMock()
        mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_conn_ctx.__aexit__ = AsyncMock(return_value=None)

        from unittest.mock import patch
        import storage.checkpointer as cp

        orig_backend = checkpoint_manager.backend_type
        checkpoint_manager.backend_type = "sqlite"

        mock_path = MagicMock()
        mock_path.exists.return_value = True

        try:
            with patch("storage.checkpointer.SQLITE_DB_PATH", mock_path), \
                 patch("aiosqlite.connect", return_value=mock_conn_ctx):
                await session_manager.delete_checkpoints(thread_id, checkpoint_ids)
        finally:
            checkpoint_manager.backend_type = orig_backend

        # Verify exactly 3 DELETE queries were executed
        assert len(executed_statements) == 3, (
            f"Expected exactly 3 bulk queries, but executed {len(executed_statements)} statements: {executed_statements}"
        )

        # Verify each query targets the correct table and contains 'IN' clause
        tables = ["checkpoints", "writes", "forge_checkpoint_metadata"]
        for idx, table in enumerate(tables):
            sql, params = executed_statements[idx]
            assert f"DELETE FROM {table}" in sql, f"Statement {idx} did not target {table}: {sql}"
            assert "WHERE thread_id = ? AND checkpoint_id IN (" in sql, f"Statement {idx} missing bulk IN clause: {sql}"
            assert params[0] == thread_id
            # Remaining params are all 25 checkpoint IDs
            assert set(params[1:]) == checkpoint_ids

