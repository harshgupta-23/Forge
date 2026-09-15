"""
migration.py — On-demand legacy JSON session migrator into LangGraph checkpointer.
"""

import json
from pathlib import Path
from typing import Any
from server.dependencies import SESSION_DIR, deserialize_message


async def migrate_legacy_session_if_needed(session_id: str, graph: Any) -> bool:
    """
    If thread_id does not have snapshots in the checkpointer but an existing
    session_<id>.json file exists on disk, reads and migrates it into the checkpointer.
    """
    snapshots = [s async for s in graph.aget_state_history({"configurable": {"thread_id": session_id}})]
    if snapshots:
        return True  # Already present in checkpointer

    json_path = SESSION_DIR / f"session_{session_id}.json"
    if not json_path.exists():
        return False

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        nodes = data.get("nodes", {})
        if not nodes:
            return False

        # Topological traversal from root to children to replay state into checkpointer
        print(f"[migration] Migrating legacy session {session_id} to database checkpointer...")
        root_id = data.get("root_id", "node_root")
        curr_parent = None
        visited = set()

        def get_child(pid):
            for nid, node in nodes.items():
                if node.get("parent_id") == pid and nid not in visited:
                    return nid, node
            return None, None

        curr_id = root_id
        while True:
            child_id, child_node = get_child(curr_id)
            if not child_id:
                break

            visited.add(child_id)
            u_dict = child_node.get("user_message")
            a_dict = child_node.get("agent_message")
            inter_dicts = child_node.get("intermediate_messages", [])

            turn_messages = []
            if u_dict:
                from langchain_core.messages import HumanMessage
                turn_messages.append(HumanMessage(content=u_dict.get("content", "")))

            for d in inter_dicts:
                m = deserialize_message(d)
                if m:
                    turn_messages.append(m)

            if a_dict:
                from langchain_core.messages import AIMessage
                turn_messages.append(AIMessage(content=a_dict.get("content", "")))

            config = {"configurable": {"thread_id": session_id}}
            if curr_parent:
                config["configurable"]["checkpoint_id"] = curr_parent

            # Update state with turn messages
            res = await graph.aupdate_state(config, {"messages": turn_messages})
            curr_parent = res.get("configurable", {}).get("checkpoint_id")
            curr_id = child_id

        print(f"[migration] Successfully migrated legacy session {session_id}.")
        return True
    except Exception as exc:
        print(f"[migration] Error migrating legacy session {session_id}: {exc}")
        return False

