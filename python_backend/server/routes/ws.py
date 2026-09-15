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
    IndexingProgressOutbound,
)
from server.dependencies import (
    SESSION_DIR,
    load_config,
    save_config,
    apply_config_to_env,
    log_token_usage,
    get_token_usage_windows,
    serialize_message,
)
from engine.utils import count_tokens, estimate_tokens, summarise_history
from engine.graph import get_compiled_graph, stream_graph_execution
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

active_connections = 0
shutdown_task: asyncio.Task | None = None
server_instance = None


def set_server_instance(srv):
    global server_instance
    server_instance = srv


async def delayed_shutdown(delay_seconds: int = 5):
    await asyncio.sleep(delay_seconds)
    print(f"[server] No clients connected for {delay_seconds} seconds. Shutting down gracefully...")
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


async def send_state_and_tree(websocket: WebSocket, session: ActiveSession) -> None:
    """Queries checkpointer history and pushes serialized tree and chat path to frontend."""
    thread_id = session.thread_id
    active_cid = session_manager.get_active_checkpoint(thread_id)

    graph = get_compiled_graph()
    snapshots = [s async for s in graph.aget_state_history({"configurable": {"thread_id": thread_id}})]
    labels = await metadata_store.get_labels(thread_id)

    tree_dict = checkpoints_to_tree_data(thread_id, snapshots, active_cid, labels)
    effective_active = tree_dict.get("active_node_id", "node_root")
    session_manager.set_active_checkpoint(thread_id, effective_active)

    # Resolve messages along active branch
    active_msgs = []
    if effective_active != "node_root":
        # Find snapshot matching effective_active
        for s in snapshots:
            cid = s.config.get("configurable", {}).get("checkpoint_id")
            if cid == effective_active:
                active_msgs = s.values.get("messages", [])
                break

    serialized_path = [serialize_message(m) for m in active_msgs if serialize_message(m) is not None]

    chat_out = ChatHistoryOutbound(
        messages=serialized_path,
        active_node_id=effective_active
    )
    await websocket.send_text(chat_out.model_dump_json())

    tree_out = TreeDataOutbound(
        session_id=thread_id,
        root_id=tree_dict.get("root_id", "node_root"),
        active_node_id=effective_active,
        nodes=tree_dict.get("nodes", {})
    )
    await websocket.send_text(tree_out.model_dump_json())


@ws_router.websocket("/")
@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global active_connections, shutdown_task
    await websocket.accept()

    active_connections += 1
    if shutdown_task and not shutdown_task.done():
        shutdown_task.cancel()
        print("[server] Client connected. Cancelled pending shutdown.")

    session = ActiveSession()

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
                old_db_url = os.environ.get("DATABASE_URL", "").strip()
                save_config(cfg)
                apply_config_to_env(cfg)
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
                        session.thread_id = target_id
                        await websocket.send_text(StatusOutbound(content=f"Resumed session ({session.thread_id}).").model_dump_json())
                        await send_state_and_tree(websocket, session)
                    except Exception as exc:
                        await websocket.send_text(ErrorOutbound(content=f"Could not load session: {exc}").model_dump_json())

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
                session.thread_id = f"sess_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
                session_manager.set_active_checkpoint(session.thread_id, "node_root")
                await websocket.send_text(StatusOutbound(content="Started a new session.").model_dump_json())
                await send_state_and_tree(websocket, session)

            # ── undo ──────────────────────────────────────────────────────────
            elif ev_type == "undo":
                parent_cid, _ = await session_manager.undo(session.thread_id, get_compiled_graph())
                if parent_cid and parent_cid != "node_root":
                    await websocket.send_text(StatusOutbound(content="Undone: moved to parent branch.").model_dump_json())
                else:
                    await websocket.send_text(StatusOutbound(content="Moved to conversation root.").model_dump_json())
                await send_state_and_tree(websocket, session)

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
                    loop = asyncio.get_event_loop()
                    compressed_msgs = await loop.run_in_executor(
                        None,
                        summarise_history,
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
                    await send_state_and_tree(websocket, session)

            # ── set_active ────────────────────────────────────────────────────
            elif ev_type == "set_active":
                target_cid = event.content or event.data
                if target_cid:
                    session_manager.set_active_checkpoint(session.thread_id, target_cid)
                    await websocket.send_text(StatusOutbound(content="Switched active node.").model_dump_json())
                    await send_state_and_tree(websocket, session)

            # ── set_label ─────────────────────────────────────────────────────
            elif ev_type == "set_label":
                target_cid = event.data.node_id
                label = event.data.label
                if target_cid:
                    await metadata_store.set_label(session.thread_id, target_cid, label)
                    await websocket.send_text(StatusOutbound(content="Updated node label.").model_dump_json())
                    await send_state_and_tree(websocket, session)

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

                thread_id = session.thread_id
                active_cid = session_manager.get_active_checkpoint(thread_id)

                # Send ONLY the delta (new user message) so LangGraph forks from active_cid
                delta_state = {
                    "messages": [HumanMessage(content=user_text)],
                    "attached_files": session.attached_files,
                    "plan": None,
                    "iteration": 0,
                    "is_streaming": True
                }

                session.stop_event = threading.Event()

                async def _generate_task(delta=delta_state, t_id=thread_id, c_id=active_cid):
                    queue: asyncio.Queue = asyncio.Queue()

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

                            elif event_type in ("done", "cancelled"):
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
                                    parent_cid = snapshots[0].parent_config.get("configurable", {}).get("checkpoint_id") if snapshots[0].parent_config else None
                                    parent_msgs = []
                                    if parent_cid:
                                        for s in snapshots[1:]:
                                            if s.config.get("configurable", {}).get("checkpoint_id") == parent_cid:
                                                parent_msgs = s.values.get("messages", [])
                                                break

                                    u_msg, a_msg, t_calls, t_results, _ = _extract_turn_messages(active_msgs, parent_msgs)
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
                                        context_total=tokens
                                    )

                                    await websocket.send_text(TokenCountOutbound(content=tokens, breakdown=breakdown).model_dump_json())
                                    log_token_usage(tokens)
                                    await websocket.send_text(TokenUsageWindowsOutbound(**get_token_usage_windows()).model_dump_json())

                                if event_type == "cancelled":
                                    await websocket.send_text(StatusOutbound(content="Generation stopped by user.").model_dump_json())

                                await send_state_and_tree(websocket, session)

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

                session.generation_task = asyncio.create_task(_generate_task())

    except WebSocketDisconnect:
        pass
    finally:
        if session.generation_task and not session.generation_task.done():
            session.generation_task.cancel()
        active_connections -= 1
        print(f"[server] Client disconnected. Remaining active connections: {active_connections}")
        if active_connections == 0:
            shutdown_task = asyncio.create_task(delayed_shutdown(5))
