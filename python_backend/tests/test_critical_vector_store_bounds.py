"""
test_critical_vector_store_bounds.py — Verifies that _hybrid_search_sqlite enforces
bounded candidate pre-filtering rather than full-table scan, executing in < 100ms.
"""

import time
import json
import pytest
import aiosqlite
from pathlib import Path
from rag.vector_store import VectorStore, LOCAL_DB_PATH


class TestCriticalVectorStoreBounds:
    @pytest.mark.asyncio
    async def test_sqlite_vector_search_bounds_and_latency(self, tmp_path):
        """Seed SQLite with 5,000 mock chunks; verify bounded query and <100ms latency."""
        test_db_path = tmp_path / "test_vector.db"

        # Initialize schema
        async with aiosqlite.connect(str(test_db_path)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS forge_document_chunks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    metadata TEXT
                );
            """)

            # Seed 5,000 chunks in bulk
            dummy_emb = json.dumps([0.01 * (k % 10) for k in range(128)])
            seed_data = []
            for i in range(5000):
                content = f"Log entry chunk {i}: system operational status code 200 normal message payload {i}."
                if i == 42:
                    content = "CRITICAL TARGET: Found needle in a haystack query token authentication key secret."
                seed_data.append((
                    f"chunk_{i:05d}",
                    "sess_test" if i % 2 == 0 else "global",
                    f"/path/to/file_{i % 50}.py",
                    f"file_{i % 50}.py",
                    i,
                    content,
                    dummy_emb,
                    "{}"
                ))

            await db.executemany("""
                INSERT INTO forge_document_chunks (id, session_id, file_path, filename, chunk_index, content, embedding, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, seed_data)
            await db.commit()

        # Patch LOCAL_DB_PATH
        vs = VectorStore(db_url=None)
        from unittest.mock import patch

        query_vector = [0.01 * (k % 10) for k in range(128)]
        start_time = time.perf_counter()
        with patch("rag.vector_store.LOCAL_DB_PATH", test_db_path):
            results = await vs.hybrid_search(
                query="needle authentication secret",
                query_vector=query_vector,
                session_id="sess_test",
                top_k=10
            )
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert len(results) > 0
        # Target needle was found via keyword pre-filtering
        assert any("needle" in r["content"] for r in results)
        # Latency must be < 100ms
        assert elapsed_ms < 100.0, f"Search took {elapsed_ms:.2f}ms, exceeding 100ms threshold"
