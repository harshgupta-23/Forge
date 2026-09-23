"""
db.py — Unified async database execution for PostgreSQL / SQLite backends.
Eliminates per-method if/else duplication across metadata.py and session_manager.py.
"""
# ponytail: single helper replaces ~200 lines of duplicated PG/SQLite branching

import aiosqlite
from storage.checkpointer import checkpoint_manager, SQLITE_DB_PATH


def _is_postgres():
    return checkpoint_manager.backend_type == "postgres" and checkpoint_manager.pool


async def db_execute(sql, params=(), *, fetch=False, sqlite_conn=None):
    """
    Execute SQL on the active backend.
    Write SQL with ? placeholders — auto-converted to %s for PostgreSQL.
    Pass sqlite_conn to reuse a persistent connection (skips close/commit).
    Returns list of rows if fetch=True, else None.
    """
    if _is_postgres():
        pg_sql = sql.replace("?", "%s")
        async with checkpoint_manager.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(pg_sql, params)
                return await cur.fetchall() if fetch else None
    else:
        own = sqlite_conn is None
        db = sqlite_conn or await aiosqlite.connect(str(SQLITE_DB_PATH))
        try:
            if fetch:
                async with db.execute(sql, params) as cur:
                    return await cur.fetchall()
            else:
                await db.execute(sql, params)
                await db.commit()
                return None
        finally:
            if own:
                await db.close()


async def db_execute_batch(statements, *, sqlite_conn=None):
    """Execute multiple DDL statements (no params). For table setup."""
    if _is_postgres():
        async with checkpoint_manager.pool.connection() as conn:
            async with conn.cursor() as cur:
                for sql in statements:
                    await cur.execute(sql)
    else:
        own = sqlite_conn is None
        db = sqlite_conn or await aiosqlite.connect(str(SQLITE_DB_PATH))
        try:
            for sql in statements:
                await db.execute(sql)
            await db.commit()
        finally:
            if own:
                await db.close()

