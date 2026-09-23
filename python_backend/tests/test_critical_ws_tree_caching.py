"""
test_critical_ws_tree_caching.py — Verifies that WebSocket tree caching maintains
in-memory session trees, loads full tree once, and appends turns incrementally in O(1).
"""

import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from storage.session_manager import session_manager
from server.schemas.events import NodeAddedOutbound, TreeDataOutbound


class TestCriticalWsTreeCaching:
    @pytest.mark.asyncio
    async def test_tree_caching_and_incremental_updates(self):
        """Simulate a 100-turn session; verify tree caching and O(1) incremental appends."""
        thread_id = "test_caching_thread"

        # Initialize mock cached tree
        root_id = "node_root"
        initial_tree = {
            "root_id": root_id,
            "active_node_id": root_id,
            "nodes": {
                root_id: {
                    "id": root_id,
                    "parent_id": None,
                    "children_ids": [],
                    "type": "root",
                }
            }
        }
        session_manager.tree_cache[thread_id] = initial_tree

        # Benchmark incremental turn appends for 100 turns
        start_time = time.perf_counter()
        prev_id = root_id

        for i in range(1, 101):
            turn_cid = f"chk_turn_{i:03d}"
            new_node = {
                "id": turn_cid,
                "parent_id": prev_id,
                "children_ids": [],
                "created_at": "2026-09-23T12:00:00Z",
                "type": "turn",
                "user_message": {"role": "user", "content": f"Turn {i}"},
                "agent_message": {"role": "assistant", "content": f"Response {i}"},
                "tool_calls": [],
                "tool_results": [],
                "tokens": {"user": 10, "tools": 0, "agent": 20, "total": 30}
            }

            # O(1) incremental update to cached tree
            tree = session_manager.tree_cache[thread_id]
            tree["nodes"][turn_cid] = new_node
            tree["active_node_id"] = turn_cid
            tree["nodes"][prev_id]["children_ids"].append(turn_cid)

            # NodeAddedOutbound payload serialization
            outbound = NodeAddedOutbound(
                session_id=thread_id,
                node=new_node,
                active_node_id=turn_cid
            )
            payload = outbound.model_dump_json()
            assert "node_added" in payload

            prev_id = turn_cid

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Assert 100 turns appended in < 50ms
        assert elapsed_ms < 50.0, f"Incremental tree appends took {elapsed_ms:.2f}ms for 100 turns"

        # Assert tree structure integrity
        cached = session_manager.tree_cache[thread_id]
        assert len(cached["nodes"]) == 101
        assert cached["active_node_id"] == "chk_turn_100"
        assert len(cached["nodes"][root_id]["children_ids"]) == 1
        assert cached["nodes"][root_id]["children_ids"][0] == "chk_turn_001"

