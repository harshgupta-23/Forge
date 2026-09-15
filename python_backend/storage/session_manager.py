"""
session_manager.py — Manages active branch pointers, thread sessions, undo,
and session history listing backed by database checkpointers.
"""

import aiosqlite
from typing import Optional, Any
from langchain_core.messages import HumanMessage
from storage.checkpointer import SQLITE_DB_PATH, checkpoint_manager


class SessionManager:
    """
    Tracks active checkpoint branches per thread, handles time-travel rollback,
    and lists stored sessions.
    """

    def __init__(self):
        self.active_checkpoints: dict[str, str] = {}
        self.current_thread_id: Optional[str] = None

    def get_active_checkpoint(self, thread_id: str) -> Optional[str]:
        return self.active_checkpoints.get(thread_id)

    def set_active_checkpoint(self, thread_id: str, checkpoint_id: str) -> None:
        self.active_checkpoints[thread_id] = checkpoint_id
        self.current_thread_id = thread_id

    async def undo(self, thread_id: str, graph: Any) -> tuple[Optional[str], list]:
        """
        Rolls back the active pointer of thread_id to the parent turn checkpoint.
        Returns (new_active_checkpoint_id, restored_messages).
        """
        active_cid = self.get_active_checkpoint(thread_id)
        if not active_cid or active_cid == "node_root":
            return "node_root", []

        snapshots = [s async for s in graph.aget_state_history({"configurable": {"thread_id": thread_id}})]
        snapshot_map = {
            s.config.get("configurable", {}).get("checkpoint_id"): s
            for s in snapshots if s.config.get("configurable", {}).get("checkpoint_id")
        }

        active_snap = snapshot_map.get(active_cid)
        if not active_snap:
            return "node_root", []

        # Trace parent chain up to find the previous completed turn
        curr = active_snap
        parent_turn_id = "node_root"
        while curr:
            p_cid = curr.parent_config.get("configurable", {}).get("checkpoint_id") if curr.parent_config else None
            if not p_cid or p_cid not in snapshot_map:
                break
            p_snap = snapshot_map[p_cid]
            if not p_snap.next:
                parent_turn_id = p_cid
                break
            curr = p_snap

        self.set_active_checkpoint(thread_id, parent_turn_id)

        if parent_turn_id in snapshot_map:
            messages = snapshot_map[parent_turn_id].values.get("messages", [])
        else:
            messages = []

        return parent_turn_id, messages

    async def list_sessions(self, graph: Any) -> list[dict[str, Any]]:
        """
        Lists distinct conversation threads from checkpointer storage.
        """
        sessions = []
        threads = set()

        if checkpoint_manager.backend_type == "postgres" and checkpoint_manager.pool:
            try:
                async with checkpoint_manager.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT DISTINCT thread_id FROM checkpoints;")
                        rows = await cur.fetchall()
                        for r in rows:
                            if r[0]:
                                threads.add(r[0])
            except Exception as exc:
                print(f"[session_manager] Failed to query PostgreSQL threads: {exc}")
        else:
            if SQLITE_DB_PATH.exists():
                try:
                    async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
                        async with db.execute("SELECT DISTINCT thread_id FROM checkpoints;") as cursor:
                            rows = await cursor.fetchall()
                            for r in rows:
                                if r[0]:
                                    threads.add(r[0])
                except Exception as exc:
                    print(f"[session_manager] Failed to query SQLite threads: {exc}")

        for tid in threads:
            try:
                snapshots = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
                turns = [s for s in snapshots if not s.next]
                if not turns:
                    continue

                preview = ""
                for msg in turns[-1].values.get("messages", []):
                    if isinstance(msg, HumanMessage):
                        preview = str(msg.content)[:60]
                        break

                created_at = turns[0].created_at if hasattr(turns[0], "created_at") else ""
                sessions.append({
                    "session_id": tid,
                    "created_at": str(created_at),
                    "node_count": len(turns),
                    "preview": preview,
                    "label": None,
                })
            except Exception:
                continue

        sessions.sort(key=lambda s: s.get("created_at") or "", reverse=True)
        return sessions


session_manager = SessionManager()

