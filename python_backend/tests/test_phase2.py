"""
test_phase2.py — Automated verification suite for Phase 2 deliverables:
- CheckpointManager AsyncExitStack lifecycle & SQLite fallback
- MetadataStore node labels with conflict resolution
- Turn-level checkpoint aggregation & parent turn resolution
- SessionManager branching and undo
"""

import sys
import asyncio
from pathlib import Path

# Add python_backend to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from storage.checkpointer import CheckpointManager
from storage.metadata import MetadataStore
from storage.tree_adapter import checkpoints_to_tree_data
from storage.session_manager import SessionManager


class MockSnapshot:
    """Mock LangGraph StateSnapshot for unit testing."""
    def __init__(self, checkpoint_id, parent_checkpoint_id, next_nodes, messages):
        self.config = {"configurable": {"checkpoint_id": checkpoint_id}}
        self.parent_config = {"configurable": {"checkpoint_id": parent_checkpoint_id}} if parent_checkpoint_id else None
        self.next = tuple(next_nodes)
        self.values = {"messages": messages}
        self.created_at = "2026-09-14T20:00:00Z"


async def test_checkpoint_manager_lifecycle():
    """Verify CheckpointManager initializes AsyncSqliteSaver with AsyncExitStack and closes cleanly."""
    manager = CheckpointManager(db_url=None)
    saver = await manager.initialize()
    assert saver is not None
    assert manager.backend_type.startswith("sqlite")
    await manager.close()
    assert manager.saver is None
    print("✓ test_checkpoint_manager_lifecycle passed")


async def test_metadata_store():
    """Verify MetadataStore sets and retrieves labels cleanly."""
    store = MetadataStore()
    await store.setup()
    thread_id = "test_thread_meta"
    cid = "chk_turn_1"

    await store.set_label(thread_id, cid, "Initial Planning Turn")
    labels = await store.get_labels(thread_id)
    assert labels.get(cid) == "Initial Planning Turn"

    # Upsert test
    await store.set_label(thread_id, cid, "Updated Branch Label")
    updated_labels = await store.get_labels(thread_id)
    assert updated_labels.get(cid) == "Updated Branch Label"
    print("✓ test_metadata_store passed")


def test_turn_aggregation_and_parent_resolution():
    """
    Verify that micro-steps (planner -> tools -> agent) are aggregated
    into a single conversational turn node where snapshot.next == ().
    """
    # Turn 1:
    # step 1: planner (next=("agent",))
    # step 2: agent (next=("tools",)) with tool_call
    # step 3: tools (next=("agent",)) with ToolMessage
    # step 4: agent (next=()) completed turn!
    m1 = HumanMessage(content="What is the weather?")
    m2 = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "weather"}, "id": "call_1"}])
    m3 = ToolMessage(content="72F Sunny", name="web_search", tool_call_id="call_1")
    m4 = AIMessage(content="The weather is 72F and sunny.")

    s1 = MockSnapshot("c_plan_1", None, ("agent",), [m1])
    s2 = MockSnapshot("c_agent_1", "c_plan_1", ("tools",), [m1, m2])
    s3 = MockSnapshot("c_tool_1", "c_agent_1", ("agent",), [m1, m2, m3])
    s4 = MockSnapshot("c_turn_1", "c_tool_1", (), [m1, m2, m3, m4])

    # Turn 2:
    # step 5: agent (next=()) completed turn!
    m5 = HumanMessage(content="Thanks!")
    m6 = AIMessage(content="You're welcome!")
    s5 = MockSnapshot("c_turn_2", "c_turn_1", (), [m1, m2, m3, m4, m5, m6])

    snapshots = [s5, s4, s3, s2, s1]  # get_state_history returns reverse-chronological

    tree_data = checkpoints_to_tree_data("test_thread", snapshots, active_checkpoint_id="c_turn_2")

    nodes = tree_data["nodes"]
    # Exactly root + 2 turn nodes! (Intermediate steps c_plan_1, c_agent_1, c_tool_1 are condensed)
    assert "node_root" in nodes
    assert "c_turn_1" in nodes
    assert "c_turn_2" in nodes
    assert len(nodes) == 3, f"Expected 3 nodes (root + 2 turns), got {len(nodes)}: {list(nodes.keys())}"

    # Verify parent resolution: c_turn_2's parent is c_turn_1, and c_turn_1's parent is node_root
    assert nodes["c_turn_1"]["parent_id"] == "node_root"
    assert nodes["c_turn_2"]["parent_id"] == "c_turn_1"
    assert "c_turn_2" in nodes["c_turn_1"]["children_ids"]

    # Verify tool results were stitched into c_turn_1
    assert len(nodes["c_turn_1"]["tool_calls"]) == 1
    assert nodes["c_turn_1"]["tool_calls"][0]["name"] == "web_search"
    assert len(nodes["c_turn_1"]["tool_results"]) == 1
    assert "72F Sunny" in nodes["c_turn_1"]["tool_results"][0]["content"]

    # Verify that if active_checkpoint_id is 'node_root', it automatically resolves to latest turn
    tree_data_root = checkpoints_to_tree_data("test_thread", snapshots, active_checkpoint_id="node_root")
    assert tree_data_root["active_node_id"] == "c_turn_2"

    # Verify explicit token metrics on c_turn_1 and c_turn_2
    assert "tokens" in nodes["c_turn_1"]
    assert nodes["c_turn_1"]["tokens"]["user"] > 0
    assert nodes["c_turn_1"]["tokens"]["tools"] > 0
    assert nodes["c_turn_1"]["tokens"]["agent"] > 0
    assert nodes["c_turn_1"]["tokens"]["total"] == (
        nodes["c_turn_1"]["tokens"]["user"] +
        nodes["c_turn_1"]["tokens"]["tools"] +
        nodes["c_turn_1"]["tokens"]["agent"]
    )
    assert nodes["node_root"]["tokens"]["total"] == 0

    print("✓ test_turn_aggregation_and_parent_resolution passed")


def test_explicit_token_breakdown():
    """Verify estimate_tokens, message_tokens, serialize_message tokens, and TokenCountOutbound schema."""
    from engine.utils import estimate_tokens, message_tokens
    from server.dependencies import serialize_message
    from server.schemas.events import TokenBreakdown, TokenCountOutbound

    # 1. estimate_tokens
    assert estimate_tokens(None) == 0
    assert estimate_tokens("") == 0
    assert estimate_tokens("hi") == 1
    assert estimate_tokens("12345678") == 2

    # 2. message_tokens & serialize_message
    h_msg = HumanMessage(content="What is the weather in Delhi?")
    ser_h = serialize_message(h_msg)
    assert ser_h["type"] == "human"
    assert ser_h["tokens"] > 0
    assert ser_h["tokens"] == estimate_tokens(h_msg.content)

    t_msg = ToolMessage(content="Weather in Delhi: 30C and clear", name="web_search", tool_call_id="call_1")
    ser_t = serialize_message(t_msg)
    assert ser_t["type"] == "tool"
    assert ser_t["tokens"] > 0

    ai_msg = AIMessage(
        content="It is 30C in Delhi.",
        tool_calls=[{"name": "web_search", "args": {"query": "weather delhi"}, "id": "call_1"}]
    )
    ser_ai = serialize_message(ai_msg)
    assert ser_ai["type"] == "ai"
    assert ser_ai["tokens"] > estimate_tokens(ai_msg.content)  # includes tool_calls args

    # 3. TokenBreakdown and TokenCountOutbound
    bd = TokenBreakdown(user=10, tools=50, agent=25, turn_total=85, context_total=400)
    outbound = TokenCountOutbound(content=400, breakdown=bd)
    dumped = outbound.model_dump()
    assert dumped["content"] == 400
    assert dumped["breakdown"]["user"] == 10
    assert dumped["breakdown"]["tools"] == 50
    assert dumped["breakdown"]["agent"] == 25
    assert dumped["breakdown"]["turn_total"] == 85
    print("✓ test_explicit_token_breakdown passed")


def test_session_manager():
    """Verify SessionManager active checkpoint tracking."""
    sm = SessionManager()
    tid = "sess_test_1"
    assert sm.get_active_checkpoint(tid) is None
    sm.set_active_checkpoint(tid, "chk_100")
    assert sm.get_active_checkpoint(tid) == "chk_100"
    print("✓ test_session_manager passed")


async def test_database_config_and_reconnect():
    """Verify DATABASE_URL configuration propagation and CheckpointManager reconnect."""
    from server.dependencies import apply_config_to_env
    from server.schemas.rest import ConfigModel
    import os

    cfg_payload = {
        "API_KEY": "test-key",
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/forge"
    }
    apply_config_to_env(cfg_payload)
    assert os.environ.get("DATABASE_URL") == "postgresql://postgres:postgres@localhost:5432/forge"

    cfg_model = ConfigModel(DATABASE_URL="postgresql://postgres:postgres@localhost:5432/forge")
    assert cfg_model.DATABASE_URL == "postgresql://postgres:postgres@localhost:5432/forge"

    # Test reconnect fallback to SQLite when PostgreSQL host is not reachable
    manager = CheckpointManager()
    saver = await manager.reconnect("postgresql://invalid:invalid@localhost:5432/nonexistent")
    assert saver is not None
    assert manager.backend_type.startswith("sqlite")
    await manager.close()
    os.environ.pop("DATABASE_URL", None)
    print("✓ test_database_config_and_reconnect passed")


async def test_dynamic_compiled_graph_with_checkpointer():
    """Verify get_compiled_graph and set_compiled_graph provide active checkpointer to callers."""
    from engine.graph import build_graph, set_compiled_graph, get_compiled_graph
    import agent

    # 1. Uncheckpointed graph raises ValueError on aget_state_history
    uncheckpointed = build_graph()
    set_compiled_graph(uncheckpointed)
    try:
        _ = [s async for s in get_compiled_graph().aget_state_history({"configurable": {"thread_id": "t1"}})]
        assert False, "Expected ValueError('No checkpointer set')"
    except ValueError as exc:
        assert "No checkpointer set" in str(exc)

    # 2. Attach initialized checkpointer
    manager = CheckpointManager()
    saver = await manager.initialize()
    checkpointed_graph = build_graph(checkpointer=saver)
    set_compiled_graph(checkpointed_graph)

    # 3. Verify get_compiled_graph returns graph that can query state history without error
    active_graph = get_compiled_graph()
    snapshots = [s async for s in active_graph.aget_state_history({"configurable": {"thread_id": "test_thread"}})]
    assert snapshots == []

    # 4. Verify agent.app and agent.compiled_graph resolve dynamically
    assert agent.app is active_graph
    assert agent.compiled_graph is active_graph

    await manager.close()
    print("✓ test_dynamic_compiled_graph_with_checkpointer passed")


async def test_undo_and_branch_deletion():
    """Verify undo removes active turn node and its entire side branch while preserving sibling branches."""
    import tempfile
    import pathlib
    import storage.checkpointer as cp
    from storage.session_manager import SessionManager
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.graph import StateGraph, START, END
    from typing import TypedDict, Annotated
    import operator

    class State(TypedDict):
        messages: Annotated[list, operator.add]

    def dummy_node(state):
        return {"messages": ["assistant_reply"]}

    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db_path = pathlib.Path(tmp.name)
    cp.SQLITE_DB_PATH = db_path

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        await saver.setup()
        builder = StateGraph(State)
        builder.add_node("turn", dummy_node)
        builder.add_edge(START, "turn")
        builder.add_edge("turn", END)
        graph = builder.compile(checkpointer=saver)

        sm = SessionManager()
        tid = "test_undo_branch_tid"

        # 1. Turn 1
        await graph.ainvoke({"messages": ["turn 1"]}, {"configurable": {"thread_id": tid}})
        snaps = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        t1_cid = snaps[0].config["configurable"]["checkpoint_id"]
        sm.set_active_checkpoint(tid, t1_cid)

        # 2. Main branch: Turn 1 -> Turn 2
        await graph.ainvoke({"messages": ["turn 2 main"]}, {"configurable": {"thread_id": tid, "checkpoint_id": t1_cid}})
        snaps = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        t2_cid = snaps[0].config["configurable"]["checkpoint_id"]

        # 3. Side branch from Turn 1: Turn 1 -> Turn 3 -> Turn 4
        await graph.ainvoke({"messages": ["turn 3 side"]}, {"configurable": {"thread_id": tid, "checkpoint_id": t1_cid}})
        snaps = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        t3_cid = snaps[0].config["configurable"]["checkpoint_id"]

        await graph.ainvoke({"messages": ["turn 4 side"]}, {"configurable": {"thread_id": tid, "checkpoint_id": t3_cid}})
        snaps = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        t4_cid = snaps[0].config["configurable"]["checkpoint_id"]

        # Undo on Turn 3 (root of side branch)
        sm.set_active_checkpoint(tid, t3_cid)
        parent_cid, restored = await sm.undo(tid, graph)

        assert parent_cid == t1_cid, f"Expected parent to be {t1_cid}, got {parent_cid}"
        assert sm.get_active_checkpoint(tid) == t1_cid

        snaps_after = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
        td_after = checkpoints_to_tree_data(tid, snaps_after, parent_cid)

        # Verify side branch (Turn 3 and Turn 4) is completely removed from tree and checkpointer
        assert t3_cid not in td_after["nodes"], "Turn 3 should be removed"
        assert t4_cid not in td_after["nodes"], "Turn 4 (side branch) should be removed"
        assert t1_cid in td_after["nodes"], "Turn 1 should remain"
        assert t2_cid in td_after["nodes"], "Turn 2 (main branch) should remain"
        assert len(td_after["nodes"]) == 3  # node_root, t1, t2

    print("✓ test_undo_and_branch_deletion passed")


async def main():
    await test_checkpoint_manager_lifecycle()
    await test_metadata_store()
    test_turn_aggregation_and_parent_resolution()
    test_explicit_token_breakdown()
    test_session_manager()
    await test_database_config_and_reconnect()
    await test_dynamic_compiled_graph_with_checkpointer()
    await test_undo_and_branch_deletion()
    print("\nAll Phase 2 unit tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())

