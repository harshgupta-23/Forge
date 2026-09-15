"""
metadata.py — Sidecar metadata table for mutable node labels and pruning flags.
Compatible with both PostgreSQL and SQLite.
"""

import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from storage.checkpointer import SQLITE_DB_PATH, checkpoint_manager


class MetadataStore:
    """
    Sidecar metadata repository storing user-defined labels and pruning flags
    without altering immutable LangGraph checkpoint hashes.
    """

    async def setup(self) -> None:
        """Initializes the metadata table."""
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


metadata_store = MetadataStore()

