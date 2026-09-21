"""
tree_adapter.py — Turn-level checkpoint aggregator translating LangGraph states
into the n8n-style decision tree format expected by the frontend UI.
"""

from typing import Any, Optional
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from server.dependencies import serialize_message


def _extract_turn_messages(
    current_msgs: list[BaseMessage],
    parent_msgs: list[BaseMessage]
) -> tuple[Optional[dict], Optional[dict], list[dict], list[dict], list[dict]]:
    """
    Extracts the new messages introduced in this turn:
    - User message
    - Agent final response
    - Tool calls & tool results
    - Serialized intermediate messages
    Includes token metrics for each part.
    """
    from engine.utils import estimate_tokens

    parent_len = len(parent_msgs) if parent_msgs else 0
    delta_msgs = current_msgs[parent_len:] if len(current_msgs) >= parent_len else current_msgs

    user_msg_dict = None
    agent_msg_dict = None
    tool_calls = []
    tool_results = []
    inter_serialized = []

    for msg in delta_msgs:
        if isinstance(msg, HumanMessage) and not user_msg_dict:
            u_content = str(msg.content)
            user_msg_dict = {
                "role": "user",
                "content": u_content,
                "attachments": [],
                "tokens": estimate_tokens(u_content)
            }
        elif isinstance(msg, AIMessage):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls.extend(msg.tool_calls)
            a_content = str(msg.content or "")
            agent_msg_dict = {
                "role": "assistant",
                "content": a_content,
                "tool_calls": tool_calls,
                "tool_results": tool_results,
                "tokens": estimate_tokens(a_content)
            }
        elif isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", "tool")
            content_str = str(msg.content or "")
            summary = content_str.split('\n')[0][:80] if content_str else ""
            tool_results.append({
                "name": tool_name,
                "content": content_str,
                "summary": summary,
                "tokens": estimate_tokens(content_str)
            })
            if agent_msg_dict:
                agent_msg_dict["tool_results"] = tool_results

        ser = serialize_message(msg)
        if ser:
            inter_serialized.append(ser)

    return user_msg_dict, agent_msg_dict, tool_calls, tool_results, inter_serialized


def checkpoints_to_tree_data(
    thread_id: str,
    snapshots: list[Any],
    active_checkpoint_id: Optional[str] = None,
    labels: Optional[dict[str, str]] = None
) -> dict[str, Any]:
    """
    Transforms LangGraph StateSnapshot history into the frontend tree graph format:
    1. Filters snapshots down to turn boundaries (where snapshot.next == ()).
    2. Recursively traces parent_checkpoint_id to resolve the true parent turn.
    3. Stitches intermediate tool calls and agent responses into single turn nodes.
    4. Attaches custom node labels from MetadataStore.
    """
    labels = labels or {}

    # Map all snapshots by checkpoint_id for fast parent traversal
    snapshot_map = {}
    for s in snapshots:
        cid = s.config.get("configurable", {}).get("checkpoint_id")
        if cid:
            snapshot_map[cid] = s

    # Identify completed conversational turns (snapshot.next == ())
    turn_snapshots = []
    for s in snapshots:
        if not s.next:  # Finished step waiting on user input
            cid = s.config.get("configurable", {}).get("checkpoint_id")
            if cid:
                turn_snapshots.append(s)

    turn_snapshots.reverse()  # Chronological order

    root_id = "node_root"
    nodes: dict[str, Any] = {
        root_id: {
            "id": root_id,
            "parent_id": None,
            "children_ids": [],
            "created_at": "",
            "type": "root",
            "user_message": None,
            "agent_message": None,
            "tool_calls": [],
            "tool_results": [],
            "label": None,
            "is_pruned": False,
            "intermediate_messages": [],
            "tokens": {
                "user": 0,
                "tools": 0,
                "agent": 0,
                "total": 0
            }
        }
    }

    checkpoint_to_turn_map = {}

    for turn in turn_snapshots:
        turn_cid = turn.config.get("configurable", {}).get("checkpoint_id")
        if not turn_cid:
            continue

        # Trace back parent chain to find the nearest ancestor turn
        parent_turn_id = root_id
        curr = turn
        while curr:
            p_cid = curr.parent_config.get("configurable", {}).get("checkpoint_id") if curr.parent_config else None
            if not p_cid or p_cid not in snapshot_map:
                break
            # Check if this ancestor is a turn boundary
            if p_cid in checkpoint_to_turn_map:
                parent_turn_id = p_cid
                break
            curr = snapshot_map[p_cid]

        # Extract delta messages for this turn
        curr_msgs = turn.values.get("messages", [])
        parent_msgs = snapshot_map[parent_turn_id].values.get("messages", []) if parent_turn_id in snapshot_map else []

        u_msg, a_msg, t_calls, t_results, inter_msgs = _extract_turn_messages(curr_msgs, parent_msgs)

        created_at = turn.created_at if hasattr(turn, "created_at") else ""
        meta = labels.get(turn_cid) if isinstance(labels.get(turn_cid), dict) else {}
        label = meta.get("label") if meta else labels.get(turn_cid)
        is_pruned = bool(meta.get("is_pruned", False)) if meta else False

        # Compute per-part token metrics for this turn node
        from engine.utils import estimate_tokens
        u_tokens = u_msg.get("tokens", 0) if u_msg else 0
        t_call_tokens = sum(estimate_tokens(tc.get("name", "")) + estimate_tokens(str(tc.get("args", ""))) for tc in t_calls)
        t_result_tokens = sum(r.get("tokens", 0) for r in t_results)
        t_tokens = t_call_tokens + t_result_tokens
        a_tokens = a_msg.get("tokens", 0) if a_msg else 0
        total_tokens = u_tokens + t_tokens + a_tokens

        node = {
            "id": turn_cid,
            "parent_id": parent_turn_id,
            "children_ids": [],
            "created_at": str(created_at),
            "type": "turn",
            "user_message": u_msg,
            "agent_message": a_msg,
            "tool_calls": t_calls,
            "tool_results": t_results,
            "label": label,
            "is_pruned": is_pruned,
            "intermediate_messages": inter_msgs,
            "tokens": {
                "user": u_tokens,
                "tools": t_tokens,
                "agent": a_tokens,
                "total": total_tokens
            }
        }

        nodes[turn_cid] = node
        checkpoint_to_turn_map[turn_cid] = turn

        if parent_turn_id in nodes:
            if turn_cid not in nodes[parent_turn_id]["children_ids"]:
                nodes[parent_turn_id]["children_ids"].append(turn_cid)

    # Determine effective active node: default to latest turn if unset or pointing to empty root
    effective_active = active_checkpoint_id
    if not effective_active or effective_active == root_id or effective_active not in nodes:
        if turn_snapshots:
            latest_cid = turn_snapshots[-1].config.get("configurable", {}).get("checkpoint_id")
            effective_active = latest_cid if latest_cid in nodes else root_id
        else:
            effective_active = root_id

    return {
        "type": "tree_data",
        "session_id": thread_id,
        "root_id": root_id,
        "active_node_id": effective_active,
        "nodes": nodes
    }

