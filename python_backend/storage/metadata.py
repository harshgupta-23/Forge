"""
metadata.py — Sidecar metadata table for mutable node labels, pruning flags,
and persistent hierarchical summary caching.
Compatible with both PostgreSQL and SQLite.
"""

import aiosqlite
from datetime import datetime, timezone
from typing import Optional, Any
from storage.checkpointer import SQLITE_DB_PATH, checkpoint_manager


class MetadataStore:
    """
    Sidecar metadata repository storing user-defined labels, pruning flags,
    and hierarchical summaries without altering immutable LangGraph checkpoint hashes.
    """

    async def setup(self) -> None:
        """Initializes the metadata and summary caching tables."""
        if checkpoint_manager.backend_type == "postgres" and checkpoint_manager.pool:
            async with checkpoint_manager.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS forge_checkpoint_metadata (
                            thread_id TEXT NOT NULL,
                            checkpoint_id TEXT PRIMARY KEY,
                            label TEXT,
                            is_pruned INTEGER DEFAULT 0,
                            created_at TEXT
                        );
                        CREATE TABLE IF NOT EXISTS forge_turn_summaries (
                            cache_key TEXT PRIMARY KEY,
                            thread_id TEXT NOT NULL,
                            summary_text TEXT NOT NULL,
                            created_at TEXT
                        );
                    """)
        else:
            async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS forge_checkpoint_metadata (
                        thread_id TEXT NOT NULL,
                        checkpoint_id TEXT PRIMARY KEY,
                        label TEXT,
                        is_pruned INTEGER DEFAULT 0,
                        created_at TEXT
                    );
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS forge_turn_summaries (
                        cache_key TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL,
                        summary_text TEXT NOT NULL,
                        created_at TEXT
                    );
                """)
                await db.commit()

    async def set_label(self, thread_id: str, checkpoint_id: str, label: Optional[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if checkpoint_manager.backend_type == "postgres" and checkpoint_manager.pool:
            async with checkpoint_manager.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        INSERT INTO forge_checkpoint_metadata (thread_id, checkpoint_id, label, is_pruned, created_at)
                        VALUES (%s, %s, %s, 0, %s)
                        ON CONFLICT (checkpoint_id) DO UPDATE SET label = EXCLUDED.label;
                    """, (thread_id, checkpoint_id, label, now))
        else:
            async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
                await db.execute("""
                    INSERT INTO forge_checkpoint_metadata (thread_id, checkpoint_id, label, is_pruned, created_at)
                    VALUES (?, ?, ?, 0, ?)
                    ON CONFLICT (checkpoint_id) DO UPDATE SET label = excluded.label;
                """, (thread_id, checkpoint_id, label, now))
                await db.commit()

    async def set_pruned(self, thread_id: str, checkpoint_id: str, is_pruned: bool = True) -> None:
        """Flags a checkpoint as dead-end pruned or active."""
        now = datetime.now(timezone.utc).isoformat()
        flag = 1 if is_pruned else 0
        if checkpoint_manager.backend_type == "postgres" and checkpoint_manager.pool:
            async with checkpoint_manager.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        INSERT INTO forge_checkpoint_metadata (thread_id, checkpoint_id, label, is_pruned, created_at)
                        VALUES (%s, %s, NULL, %s, %s)
                        ON CONFLICT (checkpoint_id) DO UPDATE SET is_pruned = EXCLUDED.is_pruned;
                    """, (thread_id, checkpoint_id, flag, now))
        else:
            async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
                await db.execute("""
                    INSERT INTO forge_checkpoint_metadata (thread_id, checkpoint_id, label, is_pruned, created_at)
                    VALUES (?, ?, NULL, ?, ?)
                    ON CONFLICT (checkpoint_id) DO UPDATE SET is_pruned = excluded.is_pruned;
                """, (thread_id, checkpoint_id, flag, now))
                await db.commit()

    async def get_labels(self, thread_id: str) -> dict[str, str]:
        labels = {}
        if checkpoint_manager.backend_type == "postgres" and checkpoint_manager.pool:
            async with checkpoint_manager.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT checkpoint_id, label FROM forge_checkpoint_metadata
                        WHERE thread_id = %s;
                    """, (thread_id,))
                    rows = await cur.fetchall()
                    for r in rows:
                        if r[1]:
                            labels[r[0]] = r[1]
        else:
            if not SQLITE_DB_PATH.exists():
                return {}
            async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
                async with db.execute("""
                    SELECT checkpoint_id, label FROM forge_checkpoint_metadata
                    WHERE thread_id = ?;
                """, (thread_id,)) as cursor:
                    rows = await cursor.fetchall()
                    for r in rows:
                        if r[1]:
                            labels[r[0]] = r[1]
        return labels

    async def get_metadata_map(self, thread_id: str) -> dict[str, dict[str, Any]]:
        """Returns map of checkpoint_id -> {'label': str, 'is_pruned': bool}."""
        res = {}
        if checkpoint_manager.backend_type == "postgres" and checkpoint_manager.pool:
            async with checkpoint_manager.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT checkpoint_id, label, is_pruned FROM forge_checkpoint_metadata
                        WHERE thread_id = %s;
                    """, (thread_id,))
                    rows = await cur.fetchall()
                    for r in rows:
                        res[r[0]] = {
                            "label": r[1],
                            "is_pruned": bool(r[2])
                        }
        else:
            if not SQLITE_DB_PATH.exists():
                return {}
            async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
                async with db.execute("""
                    SELECT checkpoint_id, label, is_pruned FROM forge_checkpoint_metadata
                    WHERE thread_id = ?;
                """, (thread_id,)) as cursor:
                    rows = await cursor.fetchall()
                    for r in rows:
                        res[r[0]] = {
                            "label": r[1],
                            "is_pruned": bool(r[2])
                        }
        return res

    async def save_summary(self, cache_key: str, thread_id: str, summary_text: str) -> None:
        """Caches a hierarchical subtree summary across server restarts."""
        now = datetime.now(timezone.utc).isoformat()
        if checkpoint_manager.backend_type == "postgres" and checkpoint_manager.pool:
            async with checkpoint_manager.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        INSERT INTO forge_turn_summaries (cache_key, thread_id, summary_text, created_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (cache_key) DO UPDATE SET summary_text = EXCLUDED.summary_text;
                    """, (cache_key, thread_id, summary_text, now))
        else:
            async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
                await db.execute("""
                    INSERT INTO forge_turn_summaries (cache_key, thread_id, summary_text, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (cache_key) DO UPDATE SET summary_text = excluded.summary_text;
                """, (cache_key, thread_id, summary_text, now))
                await db.commit()

    async def get_summary(self, cache_key: str) -> Optional[str]:
        """Retrieves a cached hierarchical summary by its deterministic hash."""
        if checkpoint_manager.backend_type == "postgres" and checkpoint_manager.pool:
            async with checkpoint_manager.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT summary_text FROM forge_turn_summaries
                        WHERE cache_key = %s;
                    """, (cache_key,))
                    row = await cur.fetchone()
                    return row[0] if row else None
        else:
            if not SQLITE_DB_PATH.exists():
                return None
            async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
                async with db.execute("""
                    SELECT summary_text FROM forge_turn_summaries
                    WHERE cache_key = ?;
                """, (cache_key,)) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else None


metadata_store = MetadataStore()
