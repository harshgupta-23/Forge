"""
checkpointer.py — Asynchronous CheckpointManager managing connection pools,
PostgreSQL checkpointer, and seamless SQLite fallback via AsyncExitStack.
"""

import os
import pathlib
from contextlib import AsyncExitStack
from typing import Optional, Any

try:
    from server.dependencies import AGENT_HOME
except Exception:
    AGENT_HOME = pathlib.Path.home() / ".forge"
    try:
        AGENT_HOME.mkdir(parents=True, exist_ok=True)
    except Exception:
        AGENT_HOME = pathlib.Path("/tmp/.forge")
        AGENT_HOME.mkdir(parents=True, exist_ok=True)

SQLITE_DB_PATH = AGENT_HOME / "forge_checkpoints.db"


class CheckpointManager:
    """
    Manages the lifecycle of the LangGraph checkpointer.
    Connects to PostgreSQL if DATABASE_URL is configured; otherwise safely
    falls back to an embedded local AsyncSqliteSaver.
    """

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.environ.get("DATABASE_URL", "").strip()
        self.exit_stack = AsyncExitStack()
        self.saver = None
        self.pool = None
        self.backend_type = "sqlite"

    async def initialize(self) -> Any:
        # 1. Attempt PostgreSQL initialization if configured
        if self.db_url and self.db_url.startswith("postgresql"):
            try:
                from psycopg_pool import AsyncConnectionPool
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                print(f"[checkpointer] Attempting connection to PostgreSQL at {self.db_url.split('@')[-1]}...")
                self.pool = AsyncConnectionPool(
                    conninfo=self.db_url,
                    max_size=10,
                    open=False
                )
                await self.exit_stack.enter_async_context(self.pool)
                self.saver = AsyncPostgresSaver(self.pool)
                await self.saver.setup()
                self.backend_type = "postgres"
                print("[checkpointer] Connected to PostgreSQL. Checkpoint tables verified.")
                return self.saver
            except Exception as exc:
                print(f"[checkpointer] PostgreSQL connection failed ({exc}). Falling back to local SQLite...")
                if self.pool:
                    try:
                        await self.pool.close()
                    except Exception:
                        pass
                self.pool = None

        # 2. Local SQLite Fallback (zero-setup out of the box)
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            saver_cm = AsyncSqliteSaver.from_conn_string(str(SQLITE_DB_PATH))
            self.saver = await self.exit_stack.enter_async_context(saver_cm)
            await self.saver.setup()
            self.backend_type = "sqlite"
            print(f"[checkpointer] Running with local SQLite checkpointer at {SQLITE_DB_PATH}")
            return self.saver
        except Exception as exc:
            # In-memory fallback if file-system sqlite fails
            print(f"[checkpointer] SQLite file setup failed ({exc}), using in-memory AsyncSqliteSaver...")
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            saver_cm = AsyncSqliteSaver.from_conn_string(":memory:")
            self.saver = await self.exit_stack.enter_async_context(saver_cm)
            await self.saver.setup()
            self.backend_type = "sqlite_memory"
            return self.saver

    async def close(self) -> None:
        """Closes connection pools and checkpointer context stack cleanly."""
        print("[checkpointer] Closing checkpointer connection stack...")
        await self.exit_stack.aclose()
        self.saver = None
        self.pool = None

    async def reconnect(self, new_db_url: Optional[str] = None) -> Any:
        """Closes existing connections and reinitializes with an updated database URL."""
        await self.close()
        self.exit_stack = AsyncExitStack()
        self.db_url = new_db_url if new_db_url is not None else os.environ.get("DATABASE_URL", "").strip()
        return await self.initialize()


checkpoint_manager = CheckpointManager()


def get_checkpointer():
    """Returns current active checkpointer instance."""
    return checkpoint_manager.saver

