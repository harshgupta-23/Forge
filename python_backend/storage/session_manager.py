"""
session_manager.py — Manages active branch pointers, thread sessions, undo,
tree caching, and session history listing backed by database checkpointers.
"""
# ponytail: unified via db_execute, ~290 lines down from ~444

import aiosqlite
from datetime import datetime, timezone
from typing import Optional, Any
from langchain_core.messages import HumanMessage
from storage.checkpointer import checkpoint_manager
import storage.checkpointer as checkpointer
from storage.db import db_execute, _is_postgres


class SessionManager:
    """
    Tracks active checkpoint branches per thread, handles time-travel rollback,
    caches tree states in memory, and lists stored sessions efficiently.
    """

    def __init__(self):
        self.active_checkpoints: dict[str, str] = {}
        self.current_thread_id: Optional[str] = None
        self.tree_cache: dict[str, dict[str, Any]] = {}

    def get_active_checkpoint(self, thread_id: str) -> Optional[str]:
        return self.active_checkpoints.get(thread_id)

    def set_active_checkpoint(self, thread_id: str, checkpoint_id: str) -> None:
        self.active_checkpoints[thread_id] = checkpoint_id
        self.current_thread_id = thread_id

    async def delete_checkpoints(self, thread_id: str, checkpoint_ids: set[str]) -> None:
        """
        Deletes specified checkpoints and their associated writes and metadata in bulk.
        Executes exactly 3 statements instead of an N+1 loop.
        """
        if not checkpoint_ids:
            return

        cids = list(checkpoint_ids)
        # ponytail: PG uses ANY(%s), SQLite uses IN(?,?,...) — structural difference, can't unify further
        if _is_postgres():
            try:
                async with checkpoint_manager.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        for table, cid_col in [("checkpoints", "checkpoint_id"), ("checkpoint_writes", "checkpoint_id"), ("forge_checkpoint_metadata", "checkpoint_id")]:
                            try:
                                await cur.execute(
                                    f"DELETE FROM {table} WHERE thread_id = %s AND {cid_col} = ANY(%s);",
                                    (thread_id, cids)
                                )
                            except Exception:
                                pass
            except Exception as exc:
                print(f"[session_manager] Failed to bulk delete PostgreSQL checkpoints: {exc}")
        else:
            db_path = getattr(checkpointer, "SQLITE_DB_PATH", None)
            if db_path and db_path.exists():
                try:
                    async with aiosqlite.connect(str(db_path)) as db:
                        placeholders = ",".join("?" for _ in cids)
                        params = [thread_id] + cids
                        for table in ["checkpoints", "writes", "forge_checkpoint_metadata"]:
                            try:
                                await db.execute(
                                    f"DELETE FROM {table} WHERE thread_id = ? AND checkpoint_id IN ({placeholders});",
                                    params
                                )
                            except Exception:
                                pass
                        await db.commit()
                except Exception as exc:
                    print(f"[session_manager] Failed to bulk delete SQLite checkpoints: {exc}")

        self.tree_cache.pop(thread_id, None)

    async def undo(
        self,
        thread_id: str,
        graph: Any,
        target_node_id: Optional[str] = None
    ) -> tuple[Optional[str], list]:
        """
        Removes the target/active turn node and any side branch descending from it.
        Rolls back active pointer to the parent turn checkpoint (or 'node_root').
        Returns (new_active_checkpoint_id, restored_messages).
        """
        snapshots = [s async for s in graph.aget_state_history({"configurable": {"thread_id": thread_id}})]
        if not snapshots:
            self.set_active_checkpoint(thread_id, "node_root")
            return "node_root", []

        snapshot_map = {
            s.config.get("configurable", {}).get("checkpoint_id"): s
            for s in snapshots if s.config.get("configurable", {}).get("checkpoint_id")
        }

        turn_snapshots = [s for s in snapshots if not s.next]
        if not turn_snapshots:
            self.set_active_checkpoint(thread_id, "node_root")
            return "node_root", []

        target_id = target_node_id or self.get_active_checkpoint(thread_id)
        if not target_id or target_id == "node_root":
            target_id = turn_snapshots[0].config.get("configurable", {}).get("checkpoint_id")

        if not target_id or target_id == "node_root":
            self.set_active_checkpoint(thread_id, "node_root")
            return "node_root", []

        # Build tree structure using tree adapter
        from storage.tree_adapter import checkpoints_to_tree_data
        from storage.metadata import metadata_store
        meta_map = await metadata_store.get_metadata_map(thread_id)
        tree_dict = checkpoints_to_tree_data(thread_id, snapshots, target_id, meta_map)
        nodes = tree_dict.get("nodes", {})

        if target_id not in nodes or target_id == "node_root":
            for s in turn_snapshots:
                t_cid = s.config.get("configurable", {}).get("checkpoint_id")
                if t_cid in nodes:
                    target_id = t_cid
                    break

        if target_id not in nodes or target_id == "node_root":
            self.set_active_checkpoint(thread_id, "node_root")
            return "node_root", []

        parent_turn_id = nodes[target_id].get("parent_id") or "node_root"

        # Collect target turn and ALL descendant nodes in its side branch / subtree
        turns_to_remove = set()
        queue = [target_id]
        while queue:
            curr_id = queue.pop(0)
            turns_to_remove.add(curr_id)
            c_node = nodes.get(curr_id)
            if c_node:
                for child_id in c_node.get("children_ids", []):
                    if child_id not in turns_to_remove:
                        queue.append(child_id)

        # Build forward parent-to-child map of raw checkpoints
        children_cids: dict[str, list[str]] = {}
        for s in snapshots:
            cid = s.config.get("configurable", {}).get("checkpoint_id")
            p_cid = s.parent_config.get("configurable", {}).get("checkpoint_id") if s.parent_config else None
            if cid and p_cid:
                children_cids.setdefault(p_cid, []).append(cid)

        # Collect all raw checkpoint IDs belonging to these turns
        cids_to_delete = set()
        for t_id in turns_to_remove:
            curr = snapshot_map.get(t_id)
            while curr:
                c_id = curr.config.get("configurable", {}).get("checkpoint_id")
                if not c_id:
                    break
                if c_id == parent_turn_id or (c_id in nodes and c_id not in turns_to_remove):
                    break
                cids_to_delete.add(c_id)
                p_id = curr.parent_config.get("configurable", {}).get("checkpoint_id") if curr.parent_config else None
                if not p_id or p_id == parent_turn_id:
                    break
                curr = snapshot_map.get(p_id)

        # Forward BFS to include intermediate/child step checkpoints
        fwd_queue = list(cids_to_delete)
        while fwd_queue:
            curr_cid = fwd_queue.pop(0)
            for ch_cid in children_cids.get(curr_cid, []):
                if ch_cid not in cids_to_delete:
                    cids_to_delete.add(ch_cid)
                    fwd_queue.append(ch_cid)

        # Ensure parent_turn_id and node_root are never deleted
        cids_to_delete.discard(parent_turn_id)
        cids_to_delete.discard("node_root")

        # Delete from persistent storage
        await self.delete_checkpoints(thread_id, cids_to_delete)

        # Update active checkpoint
        current_active = self.get_active_checkpoint(thread_id)
        if not current_active or current_active in turns_to_remove or current_active not in snapshot_map:
            new_active_cid = parent_turn_id
        else:
            new_active_cid = current_active

        self.set_active_checkpoint(thread_id, new_active_cid)

        restored_messages = []
        if new_active_cid != "node_root" and new_active_cid in snapshot_map:
            restored_messages = snapshot_map[new_active_cid].values.get("messages", [])

        return new_active_cid, restored_messages

    async def record_turn(
        self,
        thread_id: str,
        preview: str = "",
        node_count_increment: int = 1,
        label: Optional[str] = None,
        node_count: Optional[int] = None,
    ) -> None:
        """Upserts session metadata into forge_session_summaries table for fast O(1) listing."""
        now = datetime.now(timezone.utc).isoformat()
        initial_node_count = node_count if node_count is not None else node_count_increment

        if node_count is not None:
            sql = """INSERT INTO forge_session_summaries (thread_id, created_at, updated_at, node_count, preview, label)
                     VALUES (?, ?, ?, ?, ?, ?)
                     ON CONFLICT (thread_id) DO UPDATE SET
                         updated_at = EXCLUDED.updated_at,
                         node_count = ?,
                         preview = CASE WHEN forge_session_summaries.preview IS NOT NULL AND forge_session_summaries.preview <> '' THEN forge_session_summaries.preview ELSE EXCLUDED.preview END,
                         label = COALESCE(EXCLUDED.label, forge_session_summaries.label);"""
            params = (thread_id, now, now, initial_node_count, preview, label, node_count)
        else:
            sql = """INSERT INTO forge_session_summaries (thread_id, created_at, updated_at, node_count, preview, label)
                     VALUES (?, ?, ?, ?, ?, ?)
                     ON CONFLICT (thread_id) DO UPDATE SET
                         updated_at = EXCLUDED.updated_at,
                         node_count = forge_session_summaries.node_count + EXCLUDED.node_count,
                         preview = CASE WHEN forge_session_summaries.preview IS NOT NULL AND forge_session_summaries.preview <> '' THEN forge_session_summaries.preview ELSE EXCLUDED.preview END,
                         label = COALESCE(EXCLUDED.label, forge_session_summaries.label);"""
            params = (thread_id, now, now, node_count_increment, preview, label)

        try:
            await db_execute(sql, params)
        except Exception as exc:
            print(f"[session_manager] Failed to record turn: {exc}")

    async def rename_session(self, thread_id: str, label: str) -> None:
        """Updates the custom label of an existing session."""
        await db_execute("UPDATE forge_session_summaries SET label = ? WHERE thread_id = ?;", (label, thread_id))

    async def delete_session(self, thread_id: str) -> None:
        """Deletes all checkpoints, writes, metadata, and summary for a session."""
        for sql in [
            "DELETE FROM checkpoints WHERE thread_id = ?;",
            "DELETE FROM checkpoint_writes WHERE thread_id = ?;",
            "DELETE FROM writes WHERE thread_id = ?;",
            "DELETE FROM forge_checkpoint_metadata WHERE thread_id = ?;",
            "DELETE FROM forge_session_summaries WHERE thread_id = ?;",
        ]:
            try:
                await db_execute(sql, (thread_id,))
            except Exception:
                pass
        self.tree_cache.pop(thread_id, None)
        self.active_checkpoints.pop(thread_id, None)

    async def sync_missing_summaries(self, graph: Any) -> None:
        """
        Backfills forge_session_summaries for any stored checkpoint threads that lack
        a summary or have an empty preview. Runs in O(missing) time on startup.
        """
        if not graph:
            return

        try:
            rows = await db_execute(
                """SELECT DISTINCT c.thread_id
                   FROM checkpoints c
                   LEFT JOIN forge_session_summaries s ON c.thread_id = s.thread_id
                   WHERE s.thread_id IS NULL OR s.preview IS NULL OR s.preview = '';""",
                fetch=True,
            )
            missing_threads = {r[0] for r in rows if r[0]}
        except Exception:
            missing_threads = set()

        for tid in missing_threads:
            try:
                snapshots = [s async for s in graph.aget_state_history({"configurable": {"thread_id": tid}})]
                turns = [s for s in snapshots if not s.next]
                if not turns:
                    continue
                first_turn_msgs = turns[-1].values.get("messages", [])
                preview = ""
                for m in first_turn_msgs:
                    if isinstance(m, HumanMessage) or getattr(m, "type", None) == "human":
                        preview = str(getattr(m, "content", ""))[:60]
                        break
                await self.record_turn(tid, preview=preview, node_count=len(turns) + 1)
            except Exception:
                continue

    async def list_sessions(self, graph: Any = None) -> list[dict[str, Any]]:
        """
        Lists distinct conversation threads via a single indexed query from forge_session_summaries.
        Performs 0 calls to graph.aget_state_history().
        """
        try:
            rows = await db_execute(
                "SELECT thread_id, created_at, node_count, preview, label FROM forge_session_summaries ORDER BY updated_at DESC;",
                fetch=True,
            )
            sessions = [
                {"session_id": r[0], "created_at": str(r[1]), "node_count": r[2], "preview": r[3] or "", "label": r[4]}
                for r in rows
            ]
        except Exception as exc:
            print(f"[session_manager] Failed to query session summaries: {exc}")
            sessions = []

        # Backward-compatibility fallback only if forge_session_summaries is empty but older checkpoints exist
        if not sessions and graph is not None:
            threads = set()
            if _is_postgres():
                try:
                    async with checkpoint_manager.pool.connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("SELECT DISTINCT thread_id FROM checkpoints;")
                            rows = await cur.fetchall()
                            for r in rows:
                                if r[0]:
                                    threads.add(r[0])
                except Exception:
                    pass
            else:
                if checkpointer.SQLITE_DB_PATH.exists():
                    try:
                        from storage.metadata import metadata_store
                        db = await metadata_store._get_sqlite_conn()
                        async with db.execute("SELECT DISTINCT thread_id FROM checkpoints;") as cursor:
                            rows = await cursor.fetchall()
                            for r in rows:
                                if r[0]:
                                    threads.add(r[0])
                    except Exception:
                        pass

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
