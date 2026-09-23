"""
test_critical_session_listing.py — Verifies that session_manager.list_sessions executes in O(1)
query time without fetching full state histories via graph.aget_state_history().
"""

import time
import pytest
from unittest.mock import MagicMock, AsyncMock
from storage.metadata import metadata_store
from storage.session_manager import session_manager


class TestCriticalSessionListing:
    @pytest.mark.asyncio
    async def test_session_listing_zero_state_history_calls_and_fast(self):
        """Populate 50 sessions via record_turn; assert list_sessions makes 0 graph calls and runs in <50ms."""
        await metadata_store.setup()

        try:
            # Seed 50 sessions
            for i in range(50):
                tid = f"test_thread_{i:03d}"
                preview = f"User message preview for conversation {i}"
                await session_manager.record_turn(
                    thread_id=tid,
                    preview=preview,
                    node_count_increment=20,
                    label=f"Session Label {i}" if i % 5 == 0 else None
                )

            # Mock graph to track any aget_state_history calls
            mock_graph = MagicMock()
            mock_graph.aget_state_history = MagicMock()

            start_time = time.perf_counter()
            sessions = await session_manager.list_sessions(graph=mock_graph)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Assert 0 calls were made to graph.aget_state_history
            assert mock_graph.aget_state_history.call_count == 0, (
                f"Expected 0 calls to graph.aget_state_history, got {mock_graph.aget_state_history.call_count}"
            )

            # Assert all 50 sessions returned
            assert len(sessions) >= 50
            first_session = sessions[0]
            assert "session_id" in first_session
            assert "created_at" in first_session
            assert "node_count" in first_session
            assert "preview" in first_session

            # Latency check: listing 50 sessions must be well under 50ms
            assert elapsed_ms < 50.0, f"Session listing took {elapsed_ms:.2f}ms, exceeding 50ms threshold"
        finally:
            # Cleanup seeded test rows so test database stays pristine
            db = await metadata_store._get_sqlite_conn()
            await db.execute("DELETE FROM forge_session_summaries WHERE thread_id LIKE 'test_thread_%';")
            await db.commit()

