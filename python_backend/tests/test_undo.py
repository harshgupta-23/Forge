import asyncio
import tempfile
import pathlib
import sys
from pathlib import Path

# Add python_backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated, Optional
import operator
import storage.checkpointer as cp
from storage.tree_adapter import checkpoints_to_tree_data
from storage.session_manager import SessionManager


class State(TypedDict):
    messages: Annotated[list, operator.add]


def node_turn(state):
    return {"messages": ["assistant_reply"]}


async def run_turn(graph, thread_id: str, checkpoint_id: Optional[str], text: str):
    cfg = {"configurable": {"thread_id": thread_id}}
    if checkpoint_id and checkpoint_id != "node_root":
        cfg["configurable"]["checkpoint_id"] = checkpoint_id
    await graph.ainvoke({"messages": [text]}, cfg)
    snaps = [s async for s in graph.aget_state_history({"configurable": {"thread_id": thread_id}})]
    return snaps[0].config["configurable"]["checkpoint_id"]


async def main():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db_path = pathlib.Path(tmp.name)

    cp.SQLITE_DB_PATH = db_path
    from storage import metadata
    metadata.SQLITE_DB_PATH = db_path
    await metadata.metadata_store.setup()

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        await saver.setup()
        builder = StateGraph(State)
        builder.add_node("turn", node_turn)
        builder.add_edge(START, "turn")
        builder.add_edge("turn", END)
        graph = builder.compile(checkpointer=saver)

        sm = SessionManager()
        tid = "test_thread_undo"

        # ── Test 1: Single Turn Undo ──────────────────────────────────────────
        t1_cid = await run_turn(graph, tid, None, "user_msg_1")
        sm.set_active_checkpoint(tid, t1_cid)

        snaps = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        td = checkpoints_to_tree_data(tid, snaps, t1_cid)
        assert len(td["nodes"]) == 2  # root + t1
        assert t1_cid in td["nodes"]

        # Call undo
        parent_cid, restored = await sm.undo(tid, graph)
        assert parent_cid == "node_root", f"Expected 'node_root', got {parent_cid}"
        assert restored == [], f"Expected empty restored messages, got {restored}"

        # Verify DB is empty of checkpoints for t1
        snaps_after = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        assert len(snaps_after) == 0, f"Expected 0 snaps, got {len(snaps_after)}"
        td_after = checkpoints_to_tree_data(tid, snaps_after, parent_cid)
        assert list(td_after["nodes"].keys()) == ["node_root"]
        print("✓ Test 1 passed: Single turn undo removed node and returned to root")

        # ── Test 2: Two turns, undo latest ────────────────────────────────────
        t1_cid = await run_turn(graph, tid, None, "turn 1")
        sm.set_active_checkpoint(tid, t1_cid)
        t2_cid = await run_turn(graph, tid, t1_cid, "turn 2")
        sm.set_active_checkpoint(tid, t2_cid)

        snaps = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        td = checkpoints_to_tree_data(tid, snaps, t2_cid)
        assert len(td["nodes"]) == 3  # root + t1 + t2

        parent_cid, restored = await sm.undo(tid, graph)
        assert parent_cid == t1_cid
        assert len(restored) > 0

        snaps_after = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        td_after = checkpoints_to_tree_data(tid, snaps_after, parent_cid)
        assert t2_cid not in td_after["nodes"]
        assert t1_cid in td_after["nodes"]
        assert len(td_after["nodes"]) == 2
        print("✓ Test 2 passed: Two turns undo removed turn 2 and kept turn 1")

        # ── Test 3: Side branch deletion ──────────────────────────────────────
        # Currently we have Root -> Turn 1.
        # Create Main branch: Turn 1 -> Turn 2
        t2_cid = await run_turn(graph, tid, t1_cid, "turn 2 main")
        # Create Side branch from Turn 1: Turn 1 -> Turn 3 -> Turn 4
        t3_cid = await run_turn(graph, tid, t1_cid, "turn 3 side")
        t4_cid = await run_turn(graph, tid, t3_cid, "turn 4 side")

        snaps = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        td = checkpoints_to_tree_data(tid, snaps, t4_cid)
        assert len(td["nodes"]) == 5  # root, t1, t2, t3, t4

        # Now set active to t3 (root of side branch) and undo!
        sm.set_active_checkpoint(tid, t3_cid)
        parent_cid, restored = await sm.undo(tid, graph)
        assert parent_cid == t1_cid

        snaps_after = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        td_after = checkpoints_to_tree_data(tid, snaps_after, parent_cid)
        # BOTH t3 AND t4 must be gone!
        assert t3_cid not in td_after["nodes"], "t3 should be removed"
        assert t4_cid not in td_after["nodes"], "t4 should be removed (side branch)"
        assert t1_cid in td_after["nodes"], "t1 should remain"
        assert t2_cid in td_after["nodes"], "t2 (main branch) should remain"
        assert len(td_after["nodes"]) == 3  # root + t1 + t2
        print("✓ Test 3 passed: Entire side branch (t3 + t4) removed, main branch preserved")

        # ── Test 4: Can continue conversation after branch deletion ───────────
        t5_cid = await run_turn(graph, tid, t1_cid, "turn 5 new branch")
        snaps_final = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        td_final = checkpoints_to_tree_data(tid, snaps_final, t5_cid)
        assert t5_cid in td_final["nodes"]
        assert len(td_final["nodes"]) == 4  # root, t1, t2, t5
        print("✓ Test 4 passed: Continued conversation from parent without errors")


if __name__ == "__main__":
    asyncio.run(main())

