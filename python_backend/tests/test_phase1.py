"""
test_phase1.py — Automated verification suite for Phase 1 deliverables:
- Pydantic discriminated union schemas
- LangGraph multi-node graph structure
- Gemma strict alternation & ToolMessage coalescing
- FastAPI app instantiation & route registration
"""

import sys
from pathlib import Path

# Add python_backend to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from engine.state import AgentState
from engine.graph import build_graph
from engine.utils import build_model_contents, _strip_thoughts
from server.schemas.events import InboundEvent
from server.main import create_app
from pydantic import TypeAdapter


def test_pydantic_inbound_events():
    """Verify that InboundEvent discriminated union parses legacy frontend payloads correctly."""
    adapter = TypeAdapter(InboundEvent)

    # 1. get_config event (with extra data object from jsonStringifyEvent)
    e1 = adapter.validate_json('{"type": "get_config", "data": {}}')
    assert e1.type == "get_config"

    # 2. user_message event
    e2 = adapter.validate_json('{"type": "user_message", "content": "Hello Forge"}')
    assert e2.type == "user_message"
    assert e2.content == "Hello Forge"

    # 3. set_label event
    e3 = adapter.validate_json('{"type": "set_label", "data": {"node_id": "node_123", "label": "Feature Branch"}}')
    assert e3.type == "set_label"
    assert e3.data.node_id == "node_123"
    assert e3.data.label == "Feature Branch"

    # 4. attach_file event
    e4 = adapter.validate_json('{"type": "attach_file", "name": "doc.pdf", "path": "/path/to/doc.pdf"}')
    assert e4.type == "attach_file"
    assert e4.name == "doc.pdf"

    # 5. rename_session event
    e5 = adapter.validate_json('{"type": "rename_session", "data": {"session_id": "sess_1", "label": "test label"}}')
    assert e5.type == "rename_session"
    assert e5.data.session_id == "sess_1"
    assert e5.data.label == "test label"

    # 6. delete_session event
    e6 = adapter.validate_json('{"type": "delete_session", "data": {"session_id": "sess_1"}}')
    assert e6.type == "delete_session"
    assert e6.data.session_id == "sess_1"

    print("✓ test_pydantic_inbound_events passed")


def test_gemma_strict_alternation_coalescing():
    """Verify that multiple consecutive ToolMessages are coalesced into a single user turn."""
    msgs = [
        HumanMessage(content="Query with two tools"),
        AIMessage(content="Running tools"),
        ToolMessage(content="Result from Tool 1", name="tool1", tool_call_id="c1"),
        ToolMessage(content="Result from Tool 2", name="tool2", tool_call_id="c2"),
    ]

    contents = build_model_contents(msgs, {})

    # Expected order: system -> user -> assistant -> user (coalesced Tool 1 + Tool 2)
    roles = [entry["role"] for entry in contents]
    assert roles == ["system", "user", "assistant", "user"], f"Unexpected roles: {roles}"

    last_user_turn = contents[-1]["content"]
    assert "[TOOL RESULT: tool1]" in last_user_turn
    assert "[TOOL RESULT: tool2]" in last_user_turn
    assert "Result from Tool 1" in last_user_turn
    assert "Result from Tool 2" in last_user_turn

    print("✓ test_gemma_strict_alternation_coalescing passed")


def test_strip_thoughts():
    """Verify that <thought> and <thinking> tags are cleanly stripped."""
    raw = "<thought>Thinking about solution...</thought>Here is the answer."
    assert _strip_thoughts(raw) == "Here is the answer."

    raw2 = "<thinking>Multi-line\ninternal reasoning\n</thinking>Done."
    assert _strip_thoughts(raw2) == "Done."
    print("✓ test_strip_thoughts passed")


def test_langgraph_multi_node_compilation():
    """Verify that the multi-node LangGraph compiles successfully with planner, agent, tools."""
    graph = build_graph()
    assert graph is not None
    # Check nodes
    assert "planner" in graph.nodes
    assert "agent" in graph.nodes
    assert "tools" in graph.nodes
    print("✓ test_langgraph_multi_node_compilation passed")


def test_fastapi_app_routes():
    """Verify that FastAPI app creates and registers all WS and REST routes."""
    app = create_app()
    route_paths = []
    for r in app.routes:
        p = getattr(r, "path", None)
        if p:
            route_paths.append(p)
        if hasattr(r, "original_router") and hasattr(r.original_router, "routes"):
            for sr in r.original_router.routes:
                sp = getattr(sr, "path", None)
                if sp:
                    route_paths.append(sp)

    assert "/" in route_paths
    assert "/ws" in route_paths
    assert "/health" in route_paths
    assert "/api/config" in route_paths
    assert "/api/sessions" in route_paths
    assert "/api/chat/stream" in route_paths
    print("✓ test_fastapi_app_routes passed")


def test_multi_connection_roles_and_shutdown():
    """Verify ConnectionManager role tracking: main window ownership vs detached tree secondary sockets."""
    from server.routes.ws import ConnectionManager, ActiveSession
    from unittest.mock import MagicMock

    mgr = ConnectionManager()
    ws_main = MagicMock()
    ws_tree = MagicMock()

    sess_main = ActiveSession(thread_id="sess_100")
    sess_tree = ActiveSession(thread_id="sess_100")

    # Connect primary main window
    mgr.connect(ws_main, role="main", session=sess_main)
    assert mgr.primary_count() == 1
    assert mgr.total_count() == 1
    assert mgr.latest_primary_session_id == "sess_100"
    assert ws_main in mgr.session_sockets["sess_100"]

    # Connect secondary detached tree window
    mgr.connect(ws_tree, role="secondary", session=sess_tree)
    assert mgr.primary_count() == 1  # Primary count must not increase
    assert mgr.total_count() == 2
    assert ws_tree in mgr.session_sockets["sess_100"]

    # Rebind session (e.g. main window loads another session)
    mgr.rebind_session(ws_main, old_thread_id="sess_100", new_thread_id="sess_200")
    assert mgr.latest_primary_session_id == "sess_200"
    assert ws_main in mgr.session_sockets["sess_200"]
    assert ws_main not in mgr.session_sockets.get("sess_100", set())

    # Disconnecting secondary tree window leaves primary intact
    mgr.disconnect(ws_tree)
    assert mgr.primary_count() == 1
    assert mgr.total_count() == 1

    # Disconnecting primary drops primary count to 0 (shutdown trigger condition)
    mgr.disconnect(ws_main)
    assert mgr.primary_count() == 0
    assert mgr.total_count() == 0
    print("✓ test_multi_connection_roles_and_shutdown passed")


if __name__ == "__main__":
    test_pydantic_inbound_events()
    test_gemma_strict_alternation_coalescing()
    test_strip_thoughts()
    test_langgraph_multi_node_compilation()
    test_fastapi_app_routes()
    test_multi_connection_roles_and_shutdown()
    print("\nAll Phase 1 unit tests passed successfully!")


