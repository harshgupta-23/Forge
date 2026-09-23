"""
vector_store.py — Dual-backend vector store (PostgreSQL pgvector / SQLite fallback)
with HNSW vector queries, 'simple' full-text search, and Reciprocal Rank Fusion.
"""

import os
import json
import uuid
import pathlib
import aiosqlite
from typing import Optional, Any
from datetime import datetime, timezone
from rag.embeddings import cosine_similarity, embedding_manager

try:
    from server.dependencies import AGENT_HOME
except Exception:
    AGENT_HOME = pathlib.Path.home() / ".forge"
    try:
        AGENT_HOME.mkdir(parents=True, exist_ok=True)
    except Exception:
        AGENT_HOME = pathlib.Path("/tmp/.forge")
        AGENT_HOME.mkdir(parents=True, exist_ok=True)

LOCAL_DB_PATH = AGENT_HOME / "forge_checkpoints.db"


class VectorStore:
    """
    Manages document chunk storage, HNSW/vector similarity,
    full-text keyword search, and hybrid Reciprocal Rank Fusion (RRF).
    """

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = (db_url or os.environ.get("DATABASE_URL", "")).strip()
        self.backend_type = "sqlite"
        self._pool = None
        self._hnsw_created_for_dim: Optional[int] = None

    async def initialize(self) -> None:
        """Initializes PostgreSQL connection pool or SQLite schema."""
        if self.db_url and (self.db_url.startswith("postgresql://") or self.db_url.startswith("postgres://")):
            try:
                from psycopg_pool import AsyncConnectionPool
                clean_url = self.db_url.replace("postgresql+psycopg://", "postgresql://")
                self._pool = AsyncConnectionPool(
                    conninfo=clean_url,
                    min_size=1,
                    max_size=5,
                    timeout=10.0,
                    open=False
                )
                await self._pool.open(wait=True)
                self.backend_type = "postgres"

                async with self._pool.connection() as conn:
                    # Enable vector extension
                    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                    # Create chunks table with unconstrained vector for model flexibility
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS forge_document_chunks (
                            id TEXT PRIMARY KEY,
                            session_id TEXT NOT NULL,
                            file_path TEXT NOT NULL,
                            filename TEXT NOT NULL,
                            chunk_index INT NOT NULL,
                            content TEXT NOT NULL,
                            embedding vector,
                            metadata JSONB DEFAULT '{}'::jsonb,
                            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    # GIN index for source code & identifier safe full-text search
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS forge_chunks_fts_idx 
                        ON forge_document_chunks USING gin (to_tsvector('simple', content));
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS forge_chunks_session_idx 
                        ON forge_document_chunks (session_id);
                    """)
                print("[vector_store] Initialized PostgreSQL pgvector store.")
                return
            except Exception as exc:
                print(f"[vector_store] PostgreSQL connection failed ({exc}). Falling back to local SQLite...")
                if self._pool:
                    try:
                        await self._pool.close()
                    except Exception:
                        pass
                self._pool = None

        # Local SQLite fallback
        self.backend_type = "sqlite"
        AGENT_HOME.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(LOCAL_DB_PATH)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS forge_document_chunks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_session ON forge_document_chunks (session_id);")
            await db.commit()
        print(f"[vector_store] Initialized local SQLite vector store at {LOCAL_DB_PATH}")

    async def close(self) -> None:
        """Closes any active database pools."""
        if self._pool:
            try:
                await self._pool.close()
            except Exception:
                pass
            self._pool = None

    async def reconnect(self, new_db_url: Optional[str]) -> None:
        """Dynamically re-binds vector store to new database URL."""
        await self.close()
        self.db_url = (new_db_url or "").strip()
        self._hnsw_created_for_dim = None
        await self.initialize()

    async def _ensure_hnsw_index(self, dim: int) -> None:
        """Creates an expression HNSW index once dimension is known in PostgreSQL."""
        if self.backend_type != "postgres" or not self._pool:
            return
        if self._hnsw_created_for_dim == dim:
            return
        try:
            async with self._pool.connection() as conn:
                idx_name = f"forge_chunks_hnsw_{dim}"
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS {idx_name} 
                    ON forge_document_chunks USING hnsw ((embedding::vector({dim})) vector_cosine_ops);
                """)
            self._hnsw_created_for_dim = dim
            print(f"[vector_store] Dynamic HNSW index verified for dim={dim}.")
        except Exception as exc:
            # Non-fatal: pgvector can still perform exact distance scans without the index
            print(f"[vector_store] Note: HNSW expression index creation deferred ({exc}).")

    async def add_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """
        Inserts document chunks with embeddings into the store.
        Each chunk: {id, session_id, file_path, filename, chunk_index, content, embedding, metadata}
        """
        if not chunks:
            return 0

        # Check dimension from first chunk
        first_emb = chunks[0].get("embedding")
        if first_emb and isinstance(first_emb, list):
            dim = len(first_emb)
            await self._ensure_hnsw_index(dim)

        if self.backend_type == "postgres" and self._pool:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    for ch in chunks:
                        cid = ch.get("id") or f"chk_{uuid.uuid4().hex[:12]}"
                        meta = json.dumps(ch.get("metadata", {}))
                        emb_str = f"[{','.join(str(x) for x in ch['embedding'])}]"
                        await cur.execute("""
                            INSERT INTO forge_document_chunks 
                            (id, session_id, file_path, filename, chunk_index, content, embedding, metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s::jsonb)
                            ON CONFLICT (id) DO UPDATE SET
                                content = EXCLUDED.content,
                                embedding = EXCLUDED.embedding,
                                metadata = EXCLUDED.metadata;
                        """, (
                            cid,
                            ch.get("session_id", "global"),
                            ch.get("file_path", ""),
                            ch.get("filename", ""),
                            ch.get("chunk_index", 0),
                            ch.get("content", ""),
                            emb_str,
                            meta
                        ))
            return len(chunks)
        else:
            # SQLite fallback
            async with aiosqlite.connect(str(LOCAL_DB_PATH)) as db:
                for ch in chunks:
                    cid = ch.get("id") or f"chk_{uuid.uuid4().hex[:12]}"
                    meta = json.dumps(ch.get("metadata", {}))
                    emb_json = json.dumps(ch["embedding"])
                    await db.execute("""
                        INSERT OR REPLACE INTO forge_document_chunks 
                        (id, session_id, file_path, filename, chunk_index, content, embedding, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        cid,
                        ch.get("session_id", "global"),
                        ch.get("file_path", ""),
                        ch.get("filename", ""),
                        ch.get("chunk_index", 0),
                        ch.get("content", ""),
                        emb_json,
                        meta
                    ))
                await db.commit()
            return len(chunks)

    async def hybrid_search(
        self,
        query: str,
        query_vector: list[float],
        session_id: Optional[str] = None,
        top_k: int = 5
    ) -> list[dict[str, Any]]:
        """
        Executes hybrid retrieval (vector similarity + full-text search)
        fused via Reciprocal Rank Fusion (RRF: 1/(60 + rank)).
        """
        candidate_pool_limit = max(top_k * 3, 12)

        if self.backend_type == "postgres" and self._pool:
            return await self._hybrid_search_postgres(query, query_vector, session_id, top_k, candidate_pool_limit)
        else:
            return await self._hybrid_search_sqlite(query, query_vector, session_id, top_k, candidate_pool_limit)

    async def _hybrid_search_postgres(
        self,
        query: str,
        query_vector: list[float],
        session_id: Optional[str],
        top_k: int,
        limit: int
    ) -> list[dict[str, Any]]:
        emb_str = f"[{','.join(str(x) for x in query_vector)}]"
        dim = len(query_vector)

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                # 1. Vector similarity candidates
                vec_where = "(session_id = %s OR session_id = 'global')" if session_id else "TRUE"
                params_vec = (session_id, emb_str, limit) if session_id else (emb_str, limit)
                await cur.execute(f"""
                    SELECT id, session_id, file_path, filename, chunk_index, content, metadata,
                           (embedding <=> %s::vector) AS distance
                    FROM forge_document_chunks
                    WHERE {vec_where}
                    ORDER BY distance ASC
                    LIMIT %s;
                """, (emb_str, limit) if not session_id else (session_id, emb_str, limit))
                vec_rows = await cur.fetchall()

                # 2. Full-text search candidates with 'simple' dictionary
                params_fts = (session_id, query, limit) if session_id else (query, limit)
                await cur.execute(f"""
                    SELECT id, session_id, file_path, filename, chunk_index, content, metadata,
                           ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', %s)) AS rank_score
                    FROM forge_document_chunks
                    WHERE {vec_where} AND to_tsvector('simple', content) @@ plainto_tsquery('simple', %s)
                    ORDER BY rank_score DESC
                    LIMIT %s;
                """, (query, limit) if not session_id else (session_id, query, limit))
                fts_rows = await cur.fetchall()

        # Reciprocal Rank Fusion (RRF)
        rrf_scores: dict[str, float] = {}
        chunk_data: dict[str, dict[str, Any]] = {}

        for rank, row in enumerate(vec_rows):
            cid = row[0]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (60.0 + rank + 1))
            if cid not in chunk_data:
                chunk_data[cid] = {
                    "id": row[0],
                    "session_id": row[1],
                    "file_path": row[2],
                    "filename": row[3],
                    "chunk_index": row[4],
                    "content": row[5],
                    "metadata": row[6] if isinstance(row[6], dict) else json.loads(row[6] or "{}"),
                    "vector_distance": float(row[7]),
                }

        for rank, row in enumerate(fts_rows):
            cid = row[0]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (60.0 + rank + 1))
            if cid not in chunk_data:
                chunk_data[cid] = {
                    "id": row[0],
                    "session_id": row[1],
                    "file_path": row[2],
                    "filename": row[3],
                    "chunk_index": row[4],
                    "content": row[5],
                    "metadata": row[6] if isinstance(row[6], dict) else json.loads(row[6] or "{}"),
                    "vector_distance": None,
                }

        # Sort by RRF score descending
        ranked = []
        for cid, score in sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True):
            item = chunk_data[cid]
            item["rrf_score"] = score
            ranked.append(item)

        return ranked[:top_k]

    async def _hybrid_search_sqlite(
        self,
        query: str,
        query_vector: list[float],
        session_id: Optional[str],
        top_k: int,
        limit: int
    ) -> list[dict[str, Any]]:
        query_terms = [t.lower() for t in query.split() if len(t) > 1]
        results = []

        candidate_limit = min(500, max(50, limit * 10))
        async with aiosqlite.connect(str(LOCAL_DB_PATH)) as db:
            where_clauses = []
            base_params: list[Any] = []
            if session_id:
                where_clauses.append("(session_id = ? OR session_id = 'global')")
                base_params.append(session_id)

            # Stage 1: Keyword pre-filtering
            rows = []
            if query_terms:
                like_conditions = " OR ".join(["content LIKE ?" for _ in query_terms[:5]])
                where_keyword = f"({' AND '.join(where_clauses)} AND ({like_conditions}))" if where_clauses else f"({like_conditions})"
                keyword_params = list(base_params) + [f"%{term}%" for term in query_terms[:5]] + [candidate_limit]
                sql_keyword = f"SELECT id, session_id, file_path, filename, chunk_index, content, embedding, metadata FROM forge_document_chunks WHERE {where_keyword} LIMIT ?"
                try:
                    async with db.execute(sql_keyword, keyword_params) as cursor:
                        rows = await cursor.fetchall()
                except Exception:
                    rows = []

            # Stage 2: Backfill up to candidate_limit if needed
            if len(rows) < candidate_limit:
                already_ids = [r[0] for r in rows]
                backfill_where = list(where_clauses)
                backfill_params = list(base_params)
                if already_ids:
                    placeholders = ",".join("?" for _ in already_ids)
                    backfill_where.append(f"id NOT IN ({placeholders})")
                    backfill_params.extend(already_ids)

                remaining = candidate_limit - len(rows)
                where_str = f" WHERE {' AND '.join(backfill_where)}" if backfill_where else ""
                sql_backfill = f"SELECT id, session_id, file_path, filename, chunk_index, content, embedding, metadata FROM forge_document_chunks{where_str} LIMIT ?"
                backfill_params.append(remaining)
                try:
                    async with db.execute(sql_backfill, backfill_params) as cursor:
                        more_rows = await cursor.fetchall()
                        rows.extend(more_rows)
                except Exception:
                    pass

        if not rows:
            return []

        # Vector ranking
        scored_vec = []
        for r in rows:
            cid, sess, fpath, fname, cidx, content, emb_json, meta_str = r
            try:
                emb = json.loads(emb_json)
                sim = cosine_similarity(query_vector, emb)
            except Exception:
                sim = 0.0
            scored_vec.append((cid, sim, r))

        scored_vec.sort(key=lambda x: x[1], reverse=True)

        # Keyword / FTS ranking
        scored_fts = []
        for r in rows:
            cid, _, _, _, _, content, _, _ = r
            c_lower = content.lower()
            overlap = sum(1 for term in query_terms if term in c_lower)
            scored_fts.append((cid, overlap, r))

        scored_fts.sort(key=lambda x: x[1], reverse=True)

        # RRF combination
        rrf_scores: dict[str, float] = {}
        chunk_data: dict[str, dict[str, Any]] = {}

        for rank, (cid, sim, r) in enumerate(scored_vec[:limit]):
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (60.0 + rank + 1))
            chunk_data[cid] = {
                "id": r[0],
                "session_id": r[1],
                "file_path": r[2],
                "filename": r[3],
                "chunk_index": r[4],
                "content": r[5],
                "vector_similarity": sim,
                "metadata": json.loads(r[7] or "{}"),
            }

        for rank, (cid, overlap, r) in enumerate(scored_fts[:limit]):
            if overlap > 0:
                rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (60.0 + rank + 1))
                if cid not in chunk_data:
                    chunk_data[cid] = {
                        "id": r[0],
                        "session_id": r[1],
                        "file_path": r[2],
                        "filename": r[3],
                        "chunk_index": r[4],
                        "content": r[5],
                        "vector_similarity": None,
                        "metadata": json.loads(r[7] or "{}"),
                    }

        ranked = []
        for cid, score in sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True):
            item = chunk_data[cid]
            item["rrf_score"] = score
            ranked.append(item)

        return ranked[:top_k]

    async def delete_session_chunks(self, session_id: str) -> None:
        """Deletes all chunks associated with a specific session."""
        if self.backend_type == "postgres" and self._pool:
            async with self._pool.connection() as conn:
                await conn.execute("DELETE FROM forge_document_chunks WHERE session_id = %s;", (session_id,))
        else:
            async with aiosqlite.connect(str(LOCAL_DB_PATH)) as db:
                await db.execute("DELETE FROM forge_document_chunks WHERE session_id = ?;", (session_id,))
                await db.commit()


# Global vector store singleton
vector_store = VectorStore()


def get_vector_store() -> VectorStore:
    """Lazy accessor to prevent circular imports."""
    return vector_store

