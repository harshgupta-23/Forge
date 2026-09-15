"""
test_phase3.py — Automated verification suite for Phase 3 deliverables:
- Dynamic embeddings & pure-Python cosine similarity fallback
- Document parsing and recursive character chunking
- Dual-backend VectorStore (PostgreSQL pgvector / SQLite fallback)
- Session isolation (no cross-thread context leakage)
- Code token preservation (to_tsvector 'simple' search)
- Lightweight Cross-Encoder reranking
- LangChain semantic_search tool integration
"""

import sys
import asyncio
import tempfile
from pathlib import Path

# Add python_backend to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from rag.embeddings import cosine_similarity, _hash_to_embedding, embedding_manager
from rag.ingestion import _recursive_split_text, ingest_file
from rag.vector_store import VectorStore
from rag.reranker import Reranker
from tools.semantic_search import semantic_search


def test_embeddings_and_similarity():
    """Verify pure-Python vector cosine similarity and fallback embedding normalization."""
    # 1. Cosine similarity properties
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    assert abs(cosine_similarity(v1, v2) - 1.0) < 1e-5

    v_orth = [0.0, 1.0, 0.0]
    assert abs(cosine_similarity(v1, v_orth) - 0.0) < 1e-5

    v_opp = [-1.0, 0.0, 0.0]
    assert abs(cosine_similarity(v1, v_opp) - (-1.0)) < 1e-5

    # 2. Deterministic hash fallback
    emb = _hash_to_embedding("def process_data(user_id): return user_id * 2", dim=768)
    assert len(emb) == 768
    # Check L2 normalization (sum of squares ~ 1.0)
    norm = sum(x * x for x in emb)
    assert abs(norm - 1.0) < 1e-4

    # Identical texts yield identical vectors
    emb2 = _hash_to_embedding("def process_data(user_id): return user_id * 2", dim=768)
    assert emb == emb2

    print("✓ test_embeddings_and_similarity passed")


def test_recursive_chunking():
    """Verify document chunker splits at natural boundaries with overlap."""
    sample_code = (
        "def func_one():\n"
        "    print('Hello World')\n"
        "\n\n"
        "def func_two():\n"
        "    print('Second function')\n"
        "\n\n"
        "def func_three():\n"
        "    print('Third function')\n"
    )

    chunks = _recursive_split_text(sample_code, chunk_size=60, chunk_overlap=10)
    assert len(chunks) >= 2
    assert any("func_one" in c for c in chunks)
    assert any("func_three" in c for c in chunks)

    print("✓ test_recursive_chunking passed")


async def test_vector_store_and_session_isolation():
    """Verify VectorStore adds chunks, isolates sessions, and fuses hybrid search via RRF."""
    store = VectorStore(db_url=None)  # SQLite mode
    await store.initialize()

    sess_a = "sess_alpha_123"
    sess_b = "sess_beta_456"

    # Ingest chunks for Session A
    emb_a1 = _hash_to_embedding("FastAPI route definition for user authentication", dim=768)
    emb_a2 = _hash_to_embedding("PostgreSQL connection pool setup and configuration", dim=768)

    chunks_a = [
        {
            "id": "chunk_a1",
            "session_id": sess_a,
            "file_path": "/app/auth.py",
            "filename": "auth.py",
            "chunk_index": 0,
            "content": "FastAPI route definition for user authentication with JWT tokens",
            "embedding": emb_a1,
            "metadata": {"type": "code"}
        },
        {
            "id": "chunk_a2",
            "session_id": sess_a,
            "file_path": "/app/db.py",
            "filename": "db.py",
            "chunk_index": 0,
            "content": "PostgreSQL connection pool setup and configuration with psycopg",
            "embedding": emb_a2,
            "metadata": {"type": "code"}
        }
    ]

    # Ingest secret chunk for Session B
    emb_b1 = _hash_to_embedding("Secret payment gateway credentials and stripe API keys", dim=768)
    chunks_b = [
        {
            "id": "chunk_b1",
            "session_id": sess_b,
            "file_path": "/secrets/keys.env",
            "filename": "keys.env",
            "chunk_index": 0,
            "content": "Secret payment gateway credentials and stripe API keys confidential",
            "embedding": emb_b1,
            "metadata": {"type": "confidential"}
        }
    ]

    await store.add_chunks(chunks_a)
    await store.add_chunks(chunks_b)

    # 1. Search scoped to Session A
    query = "user authentication JWT"
    q_vec = _hash_to_embedding(query, dim=768)

    results_a = await store.hybrid_search(query=query, query_vector=q_vec, session_id=sess_a, top_k=5)
    assert len(results_a) > 0
    assert results_a[0]["session_id"] == sess_a
    assert "authentication" in results_a[0]["content"]

    # 2. Verify Session Isolation: Searching Session A must NEVER return Session B secrets
    leak_query = "stripe secret credentials"
    leak_vec = _hash_to_embedding(leak_query, dim=768)
    leak_check = await store.hybrid_search(query=leak_query, query_vector=leak_vec, session_id=sess_a, top_k=5)

    assert all(c["session_id"] != sess_b for c in leak_check)
    assert all("keys.env" not in c["filename"] for c in leak_check)

    # Clean up test session
    await store.delete_session_chunks(sess_a)
    await store.delete_session_chunks(sess_b)
    await store.close()

    print("✓ test_vector_store_and_session_isolation passed")


async def test_code_search_and_reranker():
    """Verify code tokens (camelCase, symbols) and Reranker candidate scoring."""
    store = VectorStore(db_url=None)
    await store.initialize()

    sess_id = "sess_code_test"
    code_content = (
        "async def getUserById(userId: str) -> dict:\n"
        "    return await database.find_user(userId)\n"
    )
    emb = _hash_to_embedding(code_content, dim=768)

    chunk = {
        "id": "chunk_code_1",
        "session_id": sess_id,
        "file_path": "/src/users.ts",
        "filename": "users.ts",
        "chunk_index": 0,
        "content": code_content,
        "embedding": emb,
        "metadata": {"lang": "typescript"}
    }
    await store.add_chunks([chunk])

    # Search by exact camelCase identifier
    query = "getUserById"
    q_vec = _hash_to_embedding(query, dim=768)
    candidates = await store.hybrid_search(query, q_vec, session_id=sess_id, top_k=5)
    assert len(candidates) > 0
    assert "getUserById" in candidates[0]["content"]

    # Test Reranker
    reranker = Reranker()
    reranked = await reranker.rerank(query, candidates, top_k=3)
    assert len(reranked) > 0
    assert "getUserById" in reranked[0]["content"]

    await store.delete_session_chunks(sess_id)
    await store.close()
    print("✓ test_code_search_and_reranker passed")


async def test_file_ingestion_and_tool():
    """Verify full end-to-end file ingestion into VectorStore and semantic_search tool."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(
            "# Payment Gateway Module\n"
            "class StripeProcessor:\n"
            "    def charge_customer(self, amount: float, customer_id: str):\n"
            "        '''Charges the customer card via payment gateway API.'''\n"
            "        return {'status': 'success', 'amount': amount}\n"
        )
        temp_path = f.name

    sess_id = "sess_tool_test"
    try:
        progress_steps = []

        async def _progress(step, pct, msg, count):
            progress_steps.append((step, pct))

        res = await ingest_file(temp_path, session_id=sess_id, progress_callback=_progress)
        assert res["chunks_count"] >= 1
        assert any(s[0] == "indexed" for s in progress_steps)

        # Execute semantic_search tool
        tool_result = semantic_search.invoke({
            "query": "charge_customer payment",
            "session_id": sess_id,
            "top_k": 3
        })

        assert "StripeProcessor" in tool_result
        assert "charge_customer" in tool_result
        assert "Excerpt 1" in tool_result

    finally:
        Path(temp_path).unlink(missing_ok=True)
        from rag.vector_store import get_vector_store
        await get_vector_store().delete_session_chunks(sess_id)

    print("✓ test_file_ingestion_and_tool passed")


async def main():
    test_embeddings_and_similarity()
    test_recursive_chunking()
    await test_vector_store_and_session_isolation()
    await test_code_search_and_reranker()
    await test_file_ingestion_and_tool()
    print("\nAll Phase 3 unit tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())

