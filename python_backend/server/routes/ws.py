"""
ws.py — WebSocket router for real-time agent execution, stateful LangGraph checkpointer,
branching canvas synchronization, and streaming.
"""

import os
import json
import asyncio
import threading
from typing import Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter

from server.schemas.events import (
    InboundEvent,
    ConfigOutbound,
    StatusOutbound,
    TokenOutbound,
    ToolStartOutbound,
    ToolDoneOutbound,
    DoneOutbound,
    ErrorOutbound,
    TokenBreakdown,
    TokenCountOutbound,
    TokenUsageWindowsOutbound,
    SessionListOutbound,
    SummarisedOutbound,
    ChatHistoryOutbound,
    TreeDataOutbound,
    NodeAddedOutbound,
    IndexingProgressOutbound,
    BranchPromptOutbound,
)
from engine.nodes.topic_gate import evaluate_topic_shift, extract_text_content
from server.dependencies import (
    SESSION_DIR,
    load_config,
    save_config,
    apply_config_to_env,
    set_active_config,
    log_token_usage,
    get_token_usage_windows,
    serialize_message,
)
from engine.utils import count_tokens, estimate_tokens, summarise_history
from engine.graph import get_compiled_graph, stream_graph_execution
from engine.tree_search import auto_prune_dead_ends, revive_branch_if_pruned
from storage import (
    metadata_store,
    checkpoints_to_tree_data,
    session_manager,
)
from storage.tree_adapter import _extract_turn_messages
from storage.migration import migrate_legacy_session_if_needed
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

ws_router = APIRouter()
inbound_adapter = TypeAdapter(InboundEvent)

class ConnectionManager:
    """Tracks active WebSocket connections, roles (main vs secondary), and multi-client session broadcast."""
    def __init__(self):
        self.primary_connections: set[WebSocket] = set()
        self.all_connections: set[WebSocket] = set()
        self.session_sockets: dict[str, set[WebSocket]] = {}
        self.socket_sessions: dict[WebSocket, 'ActiveSession'] = {}
        self.socket_roles: dict[WebSocket, str] = {}
        self.latest_primary_session_id: str | None = None

    def connect(self, websocket: WebSocket, role: str, session: 'ActiveSession') -> None:
        global active_connections
        self.all_connections.add(websocket)
        self.socket_sessions[websocket] = session
        self.socket_roles[websocket] = role
        if role == "main":
            self.primary_connections.add(websocket)
            self.latest_primary_session_id = session.thread_id
        self.session_sockets.setdefault(session.thread_id, set()).add(websocket)
        active_connections = len(self.all_connections)

    def disconnect(self, websocket: WebSocket) -> None:
        global active_connections
        self.all_connections.discard(websocket)
        self.primary_connections.discard(websocket)
        session = self.socket_sessions.pop(websocket, None)
        self.socket_roles.pop(websocket, None)
        if session and session.thread_id in self.session_sockets:
            self.session_sockets[session.thread_id].discard(websocket)
            if not self.session_sockets[session.thread_id]:
                del self.session_sockets[session.thread_id]
        active_connections = len(self.all_connections)

    def rebind_session(self, websocket: WebSocket, old_thread_id: str, new_thread_id: str) -> None:
        if old_thread_id in self.session_sockets:
            self.session_sockets[old_thread_id].discard(websocket)
            if not self.session_sockets[old_thread_id]:
                del self.session_sockets[old_thread_id]
        self.session_sockets.setdefault(new_thread_id, set()).add(websocket)
        if self.socket_roles.get(websocket) == "main":
            self.latest_primary_session_id = new_thread_id

    async def broadcast_to_session(self, thread_id: str, message: str, exclude: WebSocket | None = None) -> None:
        sockets = list(self.session_sockets.get(thread_id, set()))
        for ws in sockets:
            if ws != exclude:
                try:
                    await ws.send_text(message)
                except Exception:
                    pass

    async def propagate_session_switch(self, old_tid: str, new_tid: str, source_ws: WebSocket | None = None) -> None:
        """Notifies secondary/detached windows when the active session is switched."""
        switched_event = json.dumps({"type": "session_switched", "session_id": new_tid})
        for ws, s in list(self.socket_sessions.items()):
            if ws != source_ws and self.socket_roles.get(ws) == "secondary":
                self.rebind_session(ws, s.thread_id, new_tid)
                s.thread_id = new_tid
                try:
                    await ws.send_text(switched_event)
                except Exception:
                    pass

    async def send_or_broadcast_state_and_tree(self, thread_id: str, target_ws: WebSocket | None = None) -> None:
        """Pushes current state and tree data to target socket or broadcasts to all sockets in session."""
        active_cid = session_manager.get_active_checkpoint(thread_id)
        graph = get_compiled_graph()
        snapshots = [s async for s in graph.aget_state_history({"configurable": {"thread_id": thread_id}})]
        meta_map = await metadata_store.get_metadata_map(thread_id)

        tree_dict = checkpoints_to_tree_data(thread_id, snapshots, active_cid, meta_map, allow_root_active=True)
        effective_active = tree_dict.get("active_node_id", "node_root")
        session_manager.set_active_checkpoint(thread_id, effective_active)
        session_manager.tree_cache[thread_id] = tree_dict

        active_msgs = []
        if effective_active != "node_root":
            for s in snapshots:
                cid = s.config.get("configurable", {}).get("checkpoint_id")
                if cid == effective_active:
                    active_msgs = s.values.get("messages", [])
                    break

        serialized_path = [serialize_message(m) for m in active_msgs if serialize_message(m) is not None]

        chat_json = ChatHistoryOutbound(
            messages=serialized_path,
            active_node_id=effective_active
        ).model_dump_json()

        tree_json = TreeDataOutbound(
            session_id=thread_id,
            root_id=tree_dict.get("root_id", "node_root"),
            active_node_id=effective_active,
            nodes=tree_dict.get("nodes", {})
        ).model_dump_json()

        if target_ws:
            await target_ws.send_text(chat_json)
            await target_ws.send_text(tree_json)
        else:
            await self.broadcast_to_session(thread_id, chat_json)
            await self.broadcast_to_session(thread_id, tree_json)

    async def broadcast_state_and_tree(self, thread_id: str) -> None:
        """Pushes current state and tree data to all sockets connected to this thread_id."""
        await self.send_or_broadcast_state_and_tree(thread_id)

    def primary_count(self) -> int:
        return len(self.primary_connections)

    def total_count(self) -> int:
        return len(self.all_connections)


manager = ConnectionManager()
active_connections: int = 0
shutdown_task: asyncio.Task | None = None
server_instance = None


def set_server_instance(srv):
    global server_instance
    server_instance = srv


async def delayed_shutdown(delay_seconds: int = 5):
    await asyncio.sleep(delay_seconds)
    if manager.primary_count() > 0:
        print("[server] Primary client reconnected during grace period. Aborting shutdown.")
        return
    print(f"[server] No primary clients connected for {delay_seconds} seconds. Shutting down gracefully...")
    if server_instance:
        server_instance.should_exit = True
    else:
        os._exit(0)


class ActiveSession:
    """Holds active connection state, thread identifier, and attachments."""
    def __init__(self, thread_id: str | None = None):
        import uuid
        from datetime import datetime, timezone
        self.thread_id = thread_id or f"sess_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.attached_files: dict[str, str] = {}
        self.stop_event: threading.Event | None = None
        self.generation_task: asyncio.Task | None = None
        self.pending_branch_query: dict[str, Any] | None = None


async def send_state_and_tree(websocket: WebSocket, session: ActiveSession) -> None:
    """Queries checkpointer history and pushes serialized tree and chat path to frontend."""
    await manager.send_or_broadcast_state_and_tree(session.thread_id, target_ws=websocket)


@ws_router.websocket("/")
@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global shutdown_task
    await websocket.accept()
    set_active_config(load_config())

    role = websocket.query_params.get("role", "main").lower()
    requested_session_id = websocket.query_params.get("session_id")
    if role == "secondary" and not requested_session_id and manager.latest_primary_session_id:
        requested_session_id = manager.latest_primary_session_id

    session = ActiveSession(thread_id=requested_session_id)
    manager.connect(websocket, role, session)

    if role == "main":
        if shutdown_task and not shutdown_task.done():
            shutdown_task.cancel()
            print("[server] Primary client connected. Cancelled pending shutdown.")
        print(f"[server] Primary client connected (session={session.thread_id}). Total active: {manager.total_count()}")
    else:
        print(f"[server] Secondary client connected (role={role}, session={session.thread_id}). Total active: {manager.total_count()}")

    async def _execute_generation(delta: dict[str, Any], t_id: str, c_id: str | None):
        queue: asyncio.Queue = asyncio.Queue()
        turn_pruned_savings = 0

        graph_task = asyncio.create_task(
            stream_graph_execution(
                delta_state=delta,
                queue=queue,
                thread_id=t_id,
                checkpoint_id=c_id,
                stop_event=session.stop_event
            )
        )

        try:
            while True:
                event_type, payload = await queue.get()

                if event_type == "__end__":
                    await websocket.send_text(DoneOutbound().model_dump_json())
                    break

                elif event_type == "token_savings":
                    if isinstance(payload, tuple) and len(payload) == 3:
                        _, _, savings = payload
                        turn_pruned_savings = savings

                elif event_type == "branch_prompt":
                    analysis = payload if isinstance(payload, dict) else {}
                    human_text = ""
                    if delta.get("messages"):
                        for m in reversed(delta["messages"]):
                            if isinstance(m, HumanMessage):
                                human_text = extract_text_content(m.content)
                                break
                    session.pending_branch_query = {
                        "user_text": human_text,
                        "active_cid": c_id,
                        "parent_cid": c_id
                    }
                    await websocket.send_text(BranchPromptOutbound(
                        topic=analysis.get("topic", "New Topic"),
                        reason=analysis.get("reason", "Detected topic shift"),
                        user_text=human_text
                    ).model_dump_json())

                elif event_type in ("done", "cancelled"):
                    if session.pending_branch_query:
                        # Halted at topic_gate pending user branching decision; do not advance active turn
                        continue

                    # Update active checkpoint pointer to the newly written turn checkpoint
                    graph = get_compiled_graph()
                    snapshots = [s async for s in graph.aget_state_history({"configurable": {"thread_id": t_id}})]
                    if snapshots:
                        latest_turn_cid = snapshots[0].config.get("configurable", {}).get("checkpoint_id")
                        if latest_turn_cid:
                            session_manager.set_active_checkpoint(t_id, latest_turn_cid)

                        active_msgs = snapshots[0].values.get("messages", [])
                        tokens = count_tokens(active_msgs)

                        # Compute turn-level breakdown between latest turn and its parent turn
                        if c_id == "node_root":
                            parent_turn = None
                            parent_cid = "node_root"
                            parent_msgs = []
                        elif c_id:
                            parent_turn = next((s for s in snapshots if s.config.get("configurable", {}).get("checkpoint_id") == c_id), None)
                            parent_cid = c_id
                            parent_msgs = parent_turn.values.get("messages", []) if parent_turn else []
                        else:
                            parent_turn = next((s for s in snapshots[1:] if not s.next), None)
                            parent_msgs = parent_turn.values.get("messages", []) if parent_turn else []
                            parent_cid = parent_turn.config.get("configurable", {}).get("checkpoint_id") if parent_turn else None

                        u_msg, a_msg, t_calls, t_results, inter_serialized = _extract_turn_messages(active_msgs, parent_msgs)
                        u_tok = u_msg.get("tokens", 0) if u_msg else 0
                        t_call_tok = sum(estimate_tokens(tc.get("name", "")) + estimate_tokens(str(tc.get("args", ""))) for tc in t_calls)
                        t_res_tok = sum(r.get("tokens", 0) for r in t_results)
                        t_tok = t_call_tok + t_res_tok
                        a_tok = a_msg.get("tokens", 0) if a_msg else 0
                        turn_tok = u_tok + t_tok + a_tok

                        breakdown = TokenBreakdown(
                            user=u_tok,
                            tools=t_tok,
                            agent=a_tok,
                            turn_total=turn_tok,
                            context_total=tokens,
                            pruned_savings=turn_pruned_savings
                        )

                        await websocket.send_text(TokenCountOutbound(content=tokens, breakdown=breakdown).model_dump_json())
                        log_token_usage(tokens)
                        await websocket.send_text(TokenUsageWindowsOutbound(**get_token_usage_windows()).model_dump_json())

                        # Record turn in forge_session_summaries for O(1) session listing
                        preview = (u_msg.get("content", "") if u_msg else "")[:60]
                        exact_node_count = len([s for s in snapshots if not s.next]) + 1
                        await session_manager.record_turn(t_id, preview, node_count=exact_node_count)

                        # Run background dead-end detection on updated graph
                        await auto_prune_dead_ends(t_id, snapshots)

                    if event_type == "cancelled":
                        await websocket.send_text(StatusOutbound(content="Generation stopped by user.").model_dump_json())

                    # Incremental tree update if cached, else full broadcast
                    if t_id in session_manager.tree_cache and snapshots and latest_turn_cid:
                        tree_dict = session_manager.tree_cache[t_id]
                        new_node = {
                            "id": latest_turn_cid,
                            "parent_id": parent_cid or "node_root",
                            "children_ids": [],
                            "created_at": str(snapshots[0].created_at if hasattr(snapshots[0], "created_at") else ""),
                            "type": "turn",
                            "user_message": u_msg,
                            "agent_message": a_msg,
                            "tool_calls": t_calls,
                            "tool_results": t_results,
                            "label": None,
                            "is_pruned": False,
                            "intermediate_messages": inter_serialized,
                            "tokens": {
                                "user": u_tok,
                                "tools": t_tok,
                                "agent": a_tok,
                                "total": turn_tok
                            }
                        }
                        tree_dict.setdefault("nodes", {})[latest_turn_cid] = new_node
                        tree_dict["active_node_id"] = latest_turn_cid
                        p_id = new_node["parent_id"]
                        if p_id in tree_dict["nodes"]:
                            if latest_turn_cid not in tree_dict["nodes"][p_id].get("children_ids", []):
                                tree_dict["nodes"][p_id].setdefault("children_ids", []).append(latest_turn_cid)

                        node_added_json = NodeAddedOutbound(
                            session_id=t_id,
                            node=new_node,
                            active_node_id=latest_turn_cid
                        ).model_dump_json()
                        await manager.broadcast_to_session(t_id, node_added_json)

                        tree_json = TreeDataOutbound(
                            session_id=t_id,
                            root_id=tree_dict.get("root_id", "node_root"),
                            active_node_id=latest_turn_cid,
                            nodes=tree_dict.get("nodes", {})
                        ).model_dump_json()
                        await manager.broadcast_to_session(t_id, tree_json)

                        serialized_path = [serialize_message(m) for m in active_msgs if serialize_message(m) is not None]
                        chat_json = ChatHistoryOutbound(
                            messages=serialized_path,
                            active_node_id=latest_turn_cid
                        ).model_dump_json()
                        await manager.broadcast_to_session(t_id, chat_json)
                    else:
                        await manager.broadcast_state_and_tree(t_id)

                elif event_type == "error":
                    await websocket.send_text(ErrorOutbound(content=str(payload)).model_dump_json())

                elif event_type == "token":
                    await websocket.send_text(TokenOutbound(content=str(payload)).model_dump_json())

                elif event_type == "tool_start":
                    await websocket.send_text(ToolStartOutbound(content=str(payload)).model_dump_json())

                elif event_type == "tool_done":
                    if isinstance(payload, tuple) and len(payload) == 2:
                        t_content, t_tokens = payload
                        await websocket.send_text(ToolDoneOutbound(content=str(t_content), tokens=t_tokens).model_dump_json())
                    else:
                        await websocket.send_text(ToolDoneOutbound(content=str(payload)).model_dump_json())

                elif event_type == "status":
                    await websocket.send_text(StatusOutbound(content=str(payload)).model_dump_json())

        except Exception as exc:
            await websocket.send_text(ErrorOutbound(content=str(exc)).model_dump_json())
            await websocket.send_text(DoneOutbound().model_dump_json())
        finally:
            if not graph_task.done():
                graph_task.cancel()

    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                event = inbound_adapter.validate_json(raw_text)
            except Exception as parse_exc:
                try:
                    raw_dict = json.loads(raw_text)
                    ev_type = raw_dict.get("type", "unknown")
                except Exception:
                    ev_type = "unknown"
                err_msg = f"Invalid event frame for '{ev_type}': {parse_exc}"
                await websocket.send_text(ErrorOutbound(content=err_msg).model_dump_json())
                continue

            ev_type = event.type

            # ── get_config ────────────────────────────────────────────────────
            if ev_type == "get_config":
                await websocket.send_text(ConfigOutbound(data=load_config()).model_dump_json())
                await send_state_and_tree(websocket, session)

            # ── save_config ───────────────────────────────────────────────────
            elif ev_type == "save_config":
                cfg = event.data
                set_active_config(cfg)
                old_db_url = os.environ.get("DATABASE_URL", "").strip()
                save_config(cfg)
                apply_config_to_env(cfg)
                try:
                    from observability.tracer import sync_tracing_env
                    sync_tracing_env(cfg)
                except Exception:
                    pass
                new_db_url = os.environ.get("DATABASE_URL", "").strip()
                status_msg = "Configuration saved and applied."

                if new_db_url != old_db_url:
                    try:
                        from storage import checkpoint_manager, metadata_store
                        from rag.vector_store import get_vector_store
                        from engine.graph import build_graph, set_compiled_graph
                        new_saver = await checkpoint_manager.reconnect(new_db_url)
                        await metadata_store.setup()
                        await get_vector_store().reconnect(new_db_url)
                        new_graph = build_graph(checkpointer=new_saver)
                        set_compiled_graph(new_graph)
                        status_msg = f"Configuration saved. Database switched to {checkpoint_manager.backend_type}."
                    except Exception as exc:
                        status_msg = f"Configuration saved, but database reconnection failed: {exc}"

                await websocket.send_text(StatusOutbound(content=status_msg).model_dump_json())

            # ── save_session ──────────────────────────────────────────────────
            elif ev_type == "save_session":
                filename = f"session_{session.thread_id}.txt"
                client_content = event.content or ""
                full_path = SESSION_DIR / filename
                try:
                    log_lines = []
                    graph = get_compiled_graph()
                    snapshots = [s async for s in graph.aget_state_history({"configurable": {"thread_id": session.thread_id}})]
                    if snapshots:
                        active_cid = session_manager.get_active_checkpoint(session.thread_id)
                        for s in snapshots:
                            cid = s.config.get("configurable", {}).get("checkpoint_id")
                            if cid == active_cid or not active_cid:
                                for m in s.values.get("messages", []):
                                    if isinstance(m, HumanMessage):
                                        log_lines.append(f"[You] {m.content}")
                                    elif isinstance(m, AIMessage):
                                        log_lines.append(f"[Agent] {m.content}")
                                    else:
                                        log_lines.append(f"[Tool:{getattr(m,'name','?')}] {m.content}")
                                break

                    final_content = client_content + "\n".join(log_lines)
                    full_path.write_text(final_content, encoding="utf-8")
                    await websocket.send_text(StatusOutbound(content=f"Session saved → {full_path}").model_dump_json())
                except Exception as exc:
                    await websocket.send_text(ErrorOutbound(content=f"Could not save session: {exc}").model_dump_json())

            # ── list_sessions ────────────────────────────────────────────────
            elif ev_type == "list_sessions":
                db_sessions = await session_manager.list_sessions(get_compiled_graph())
                await websocket.send_text(SessionListOutbound(sessions=db_sessions).model_dump_json())

            # ── load_session ─────────────────────────────────────────────────
            elif ev_type == "load_session":
                target_id = (event.data or {}).get("session_id") if isinstance(event.data, dict) else event.content
                if not target_id:
                    await websocket.send_text(ErrorOutbound(content="No session_id specified.").model_dump_json())
                else:
                    try:
                        # Check on-demand legacy migration if needed
                        await migrate_legacy_session_if_needed(target_id, get_compiled_graph())
                        old_tid = session.thread_id
                        session.thread_id = target_id
                        session.pending_branch_query = None
                        manager.rebind_session(websocket, old_tid, target_id)

                        # Propagate session switch to secondary/detached windows
                        await manager.propagate_session_switch(old_tid, target_id, websocket)

                        await websocket.send_text(StatusOutbound(content=f"Resumed session ({session.thread_id}).").model_dump_json())
                        await manager.broadcast_state_and_tree(session.thread_id)
                    except Exception as exc:
                        await websocket.send_text(ErrorOutbound(content=f"Could not load session: {exc}").model_dump_json())

            # ── rename_session ───────────────────────────────────────────────
            elif ev_type == "rename_session":
                data = getattr(event, "data", None)
                target_id = getattr(data, "session_id", None) or (data.get("session_id") if isinstance(data, dict) else None)
                label = getattr(data, "label", "") or (data.get("label", "") if isinstance(data, dict) else "")
                if target_id:
                    await session_manager.rename_session(target_id, label)
                    db_sessions = await session_manager.list_sessions(get_compiled_graph())
                    await websocket.send_text(SessionListOutbound(sessions=db_sessions).model_dump_json())
                    await websocket.send_text(StatusOutbound(content=f"Session renamed to '{label}'").model_dump_json())

            # ── delete_session ───────────────────────────────────────────────
            elif ev_type == "delete_session":
                data = getattr(event, "data", None)
                target_id = getattr(data, "session_id", None) or (data.get("session_id") if isinstance(data, dict) else None)
                if target_id:
                    from rag.vector_store import get_vector_store
                    await session_manager.delete_session(target_id)
                    try:
                        await get_vector_store().delete_session_chunks(target_id)
                    except Exception:
                        pass

                    if session.thread_id == target_id:
                        import uuid
                        from datetime import datetime, timezone
                        old_tid = session.thread_id
                        new_tid = f"sess_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
                        session.thread_id = new_tid
                        session.pending_branch_query = None
                        manager.rebind_session(websocket, old_tid, new_tid)
                        session_manager.set_active_checkpoint(new_tid, "node_root")
                        await manager.propagate_session_switch(old_tid, new_tid, websocket)
                        await manager.broadcast_state_and_tree(new_tid)

                    db_sessions = await session_manager.list_sessions(get_compiled_graph())
                    await websocket.send_text(SessionListOutbound(sessions=db_sessions).model_dump_json())
                    await websocket.send_text(StatusOutbound(content="Session deleted.").model_dump_json())

            # ── get_token_usage ──────────────────────────────────────────────
            elif ev_type == "get_token_usage":
                windows = get_token_usage_windows()
                await websocket.send_text(TokenUsageWindowsOutbound(**windows).model_dump_json())

            # ── shutdown ─────────────────────────────────────────────────────
            elif ev_type == "shutdown":
                print("[server] Shutdown requested by client.")
                if server_instance:
                    server_instance.should_exit = True
                else:
                    os._exit(0)

            # ── attach_file ───────────────────────────────────────────────────
            elif ev_type == "attach_file":
                name = event.name
                path = event.path
                if name and path:
                    session.attached_files[name] = path

                    async def _index_progress(step: str, pct: int, msg: str, count: int):
                        await websocket.send_text(IndexingProgressOutbound(
                            filename=name,
                            step=step,
                            progress_pct=pct,
                            chunks_count=count,
                            message=msg
                        ).model_dump_json())

                    try:
                        from rag.ingestion import ingest_file
                        res = await ingest_file(
                            file_path=path,
                            session_id=session.thread_id,
                            progress_callback=_index_progress
                        )
                        await websocket.send_text(StatusOutbound(
                            content=f"File attached & indexed ({res['chunks_count']} chunks): {name}"
                        ).model_dump_json())
                    except Exception as exc:
                        await websocket.send_text(IndexingProgressOutbound(
                            filename=name,
                            step="error",
                            progress_pct=0,
                            chunks_count=0,
                            message=f"Indexing notice: {exc}"
                        ).model_dump_json())
                        await websocket.send_text(StatusOutbound(content=f"File attached: {name}").model_dump_json())

            # ── clear ─────────────────────────────────────────────────────────
            elif ev_type == "clear":
                import uuid
                from datetime import datetime, timezone
                old_tid = session.thread_id
                new_tid = f"sess_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
                session.thread_id = new_tid
                session.pending_branch_query = None
                manager.rebind_session(websocket, old_tid, new_tid)
                session_manager.set_active_checkpoint(new_tid, "node_root")

                # Propagate session switch to secondary/detached windows
                await manager.propagate_session_switch(old_tid, new_tid, websocket)

                await websocket.send_text(StatusOutbound(content="Started a new session.").model_dump_json())
                await manager.broadcast_state_and_tree(new_tid)

            # ── undo ──────────────────────────────────────────────────────────
            elif ev_type == "undo":
                target_node_id = None
                if hasattr(event, "node_id") and event.node_id:
                    target_node_id = event.node_id
                elif isinstance(getattr(event, "data", None), dict) and event.data.get("node_id"):
                    target_node_id = event.data["node_id"]
                elif isinstance(getattr(event, "data", None), str) and event.data:
                    target_node_id = event.data
                elif hasattr(event, "content") and event.content:
                    target_node_id = event.content

                parent_cid, _ = await session_manager.undo(
                    session.thread_id,
                    get_compiled_graph(),
                    target_node_id=target_node_id
                )
                if parent_cid and parent_cid != "node_root":
                    await websocket.send_text(StatusOutbound(content="Undone: turn & side branch removed.").model_dump_json())
                else:
                    await websocket.send_text(StatusOutbound(content="Undone: moved to conversation root.").model_dump_json())
                await manager.broadcast_state_and_tree(session.thread_id)

            # ── stop_generation ───────────────────────────────────────────────
            elif ev_type == "stop_generation":
                if session.stop_event and not session.stop_event.is_set():
                    session.stop_event.set()
                    await websocket.send_text(StatusOutbound(content="Stopping generation…").model_dump_json())
                else:
                    await websocket.send_text(StatusOutbound(content="Nothing to stop.").model_dump_json())

            # ── summarise ─────────────────────────────────────────────────────
            elif ev_type == "summarise":
                graph = get_compiled_graph()
                snapshots = [s async for s in graph.aget_state_history({"configurable": {"thread_id": session.thread_id}})]
                turns = [s for s in snapshots if not s.next]

                if len(turns) <= 2:
                    await websocket.send_text(StatusOutbound(content="Conversation path too short to summarise.").model_dump_json())
                else:
                    active_cid = session_manager.get_active_checkpoint(session.thread_id)
                    active_msgs = []
                    for s in turns:
                        if s.config.get("configurable", {}).get("checkpoint_id") == active_cid:
                            active_msgs = s.values.get("messages", [])
                            break
                    if not active_msgs and turns:
                        active_msgs = turns[0].values.get("messages", [])

                    before = count_tokens(active_msgs)
                    compressed_msgs = await summarise_history(
                        active_msgs,
                        session.attached_files
                    )
                    after = count_tokens(compressed_msgs)
                    summary_text = str(compressed_msgs[1].content) if len(compressed_msgs) > 1 else ""

                    # Save summary as checkpoint update
                    res = await graph.aupdate_state(
                        {"configurable": {"thread_id": session.thread_id, "checkpoint_id": active_cid}},
                        {"messages": compressed_msgs}
                    )
                    new_cid = res.get("configurable", {}).get("checkpoint_id")
                    if new_cid:
                        session_manager.set_active_checkpoint(session.thread_id, new_cid)
                        await metadata_store.set_label(session.thread_id, new_cid, f"Summary of {len(turns) - 2} turns")

                    await websocket.send_text(StatusOutbound(content=f"History compressed: {before:,} → {after:,} tokens.").model_dump_json())
                    await websocket.send_text(SummarisedOutbound(content=summary_text or "Summary complete.").model_dump_json())
                    await manager.broadcast_state_and_tree(session.thread_id)

            # ── set_active ────────────────────────────────────────────────────
            elif ev_type == "set_active":
                target_cid = event.content or event.data
                if target_cid:
                    session_manager.set_active_checkpoint(session.thread_id, target_cid)
                    await revive_branch_if_pruned(session.thread_id, target_cid)
                    await websocket.send_text(StatusOutbound(content="Switched active node.").model_dump_json())
                    await manager.broadcast_state_and_tree(session.thread_id)

            # ── set_label ─────────────────────────────────────────────────────
            elif ev_type == "set_label":
                target_cid = event.data.node_id
                label = event.data.label
                if target_cid:
                    await metadata_store.set_label(session.thread_id, target_cid, label)
                    await websocket.send_text(StatusOutbound(content="Updated node label.").model_dump_json())
                    await manager.broadcast_state_and_tree(session.thread_id)

            # ── branch_decision ───────────────────────────────────────────────
            elif ev_type == "branch_decision":
                pending = session.pending_branch_query
                if not pending:
                    await websocket.send_text(StatusOutbound(content="No pending branch decision.").model_dump_json())
                    continue

                session.pending_branch_query = None
                decision = getattr(event, "decision", "continue")
                pending_user_text = pending["user_text"]
                target_cid = pending["active_cid"]

                if decision == "branch":
                    parent_cid = pending.get("parent_cid", "node_root")
                    session_manager.set_active_checkpoint(session.thread_id, parent_cid)
                    target_cid = parent_cid
                    await websocket.send_text(StatusOutbound(content="Branching from previous turn...").model_dump_json())
                    await manager.broadcast_state_and_tree(session.thread_id)

                delta_state = {
                    "messages": [HumanMessage(content=pending_user_text)],
                    "attached_files": session.attached_files,
                    "plan": None,
                    "iteration": 0,
                    "is_streaming": True,
                    "skip_topic_gate": True
                }
                set_active_config(load_config())
                session.stop_event = threading.Event()
                session.generation_task = asyncio.create_task(
                    _execute_generation(delta_state, session.thread_id, target_cid)
                )

            # ── user_message ──────────────────────────────────────────────────
            elif ev_type == "user_message":
                user_text = event.content.strip()
                if not user_text:
                    continue

                if session.generation_task and not session.generation_task.done():
                    await websocket.send_text(StatusOutbound(content="Already generating — stop it first or wait for it to finish.").model_dump_json())
                    continue

                cfg = load_config()
                if not cfg.get("API_KEY"):
                    await websocket.send_text(ErrorOutbound(content="API_KEY is not set. Open Settings and add your key.").model_dump_json())
                    await websocket.send_text(DoneOutbound().model_dump_json())
                    continue
                set_active_config(cfg)

                thread_id = session.thread_id
                active_cid = session_manager.get_active_checkpoint(thread_id)

                # Check if there is prior conversation to evaluate topic shift
                graph = get_compiled_graph()
                snapshots = [s async for s in graph.aget_state_history({"configurable": {"thread_id": thread_id}})]
                active_msgs = []
                if snapshots and active_cid and active_cid != "node_root":
                    for s in snapshots:
                        if s.config.get("configurable", {}).get("checkpoint_id") == active_cid:
                            active_msgs = s.values.get("messages", [])
                            break

                # Robust fallback to latest completed turn if active_cid was unset
                if not active_msgs and snapshots:
                    turns = [s for s in snapshots if not s.next]
                    if turns and not active_cid:
                        active_msgs = turns[0].values.get("messages", [])
                        active_cid = turns[0].config.get("configurable", {}).get("checkpoint_id")
                        session_manager.set_active_checkpoint(thread_id, active_cid)

                # If prior conversation exists (at least one user message and agent response)
                if active_msgs and len(active_msgs) >= 2:
                    try:
                        shift_info = await evaluate_topic_shift(user_text, active_msgs)
                        print(f"[topic_gate] Shift check for '{user_text[:30]}': is_related={shift_info.get('is_related')}, topic={shift_info.get('topic')}")
                        if not shift_info.get("is_related", True):
                            meta_map = await metadata_store.get_metadata_map(thread_id)
                            tree_dict = checkpoints_to_tree_data(thread_id, snapshots, active_cid, meta_map)
                            parent_turn_id = tree_dict.get("nodes", {}).get(active_cid, {}).get("parent_id", "node_root")

                            session.pending_branch_query = {
                                "user_text": user_text,
                                "active_cid": active_cid,
                                "parent_cid": parent_turn_id
                            }

                            await websocket.send_text(BranchPromptOutbound(
                                topic=shift_info.get("topic", "New Topic"),
                                reason=shift_info.get("reason", "Detected topic shift"),
                                user_text=user_text
                            ).model_dump_json())
                            continue
                    except Exception as exc:
                        print(f"[topic_gate] Topic shift evaluation notice: {exc}")

                # Send ONLY the delta (new user message) so LangGraph forks from active_cid
                delta_state = {
                    "messages": [HumanMessage(content=user_text)],
                    "attached_files": session.attached_files,
                    "plan": None,
                    "iteration": 0,
                    "is_streaming": True
                }

                session.stop_event = threading.Event()
                session.generation_task = asyncio.create_task(
                    _execute_generation(delta_state, thread_id, active_cid)
                )


    except WebSocketDisconnect:
        pass
    finally:
        if session.generation_task and not session.generation_task.done():
            session.generation_task.cancel()
        manager.disconnect(websocket)
        print(f"[server] Client disconnected. Remaining primaries: {manager.primary_count()}, total active: {manager.total_count()}")
        if manager.primary_count() == 0:
            print("[server] All primary clients disconnected. Starting 5s shutdown countdown...")
            shutdown_task = asyncio.create_task(delayed_shutdown(5))
