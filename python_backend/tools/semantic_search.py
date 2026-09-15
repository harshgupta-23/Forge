"""
semantic_search.py — Hybrid semantic vector search & keyword retrieval tool
with cross-encoder reranking over attached documents and knowledge files.
"""

import asyncio
from typing import Optional, Any
from langchain_core.tools import tool


def _run_async(coro):
    """Executes an async coroutine safely from sync tool execution threads."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


@tool
def semantic_search(query: str, top_k: int = 5, session_id: Optional[str] = None) -> str:
    """
    Performs hybrid vector similarity and keyword search with cross-encoder reranking
    over all attached documents and knowledge files.
    Use this to find specific code functions, variables, definitions, documentation,
    or passages in large attached files rather than reading entire files into memory.

    Args:
        query: The search query or semantic concept to look up.
        top_k: Number of most relevant snippets to return (default 5).
        session_id: Optional session identifier filter. If not provided, searches active session.
    """
    if not query or not query.strip():
        return "ERROR: Please provide a valid non-empty search query."

    # Lazy imports to prevent circular dependencies during auto-discovery in tools/__init__.py
    from rag.embeddings import embedding_manager
    from rag.vector_store import get_vector_store
    from rag.reranker import get_reranker
    from storage.session_manager import session_manager

    active_sess = session_id or getattr(session_manager, "current_thread_id", None)

    async def _search():
        store = get_vector_store()
        reranker = get_reranker()

        # 1. Embed query
        query_vector = await embedding_manager.embed_query(query)

        # 2. Hybrid search (vector + full-text with 'simple' dictionary fused by RRF)
        candidates = await store.hybrid_search(
            query=query,
            query_vector=query_vector,
            session_id=active_sess,
            top_k=max(top_k * 2, 10)
        )

        if not candidates:
            return None

        # 3. Cross-encoder reranking
        reranked = await reranker.rerank(query=query, candidates=candidates, top_k=top_k)
        return reranked

    try:
        results = _run_async(_search())
    except Exception as exc:
        return f"[semantic_search Error]: {exc}"

    if not results:
        sess_note = f" for session '{active_sess}'" if active_sess else ""
        return f"No relevant document chunks found matching query '{query}'{sess_note}. Ensure documents have been attached and indexed."

    output_lines = [
        f"Found {len(results)} relevant excerpt(s) for query: {query!r}\n"
    ]

    for idx, item in enumerate(results, 1):
        filename = item.get("filename", "unknown")
        fpath = item.get("file_path", "")
        chunk_idx = item.get("chunk_index", 0)
        content = item.get("content", "").strip()
        score_note = ""
        if "rrf_score" in item:
            score_note = f" (RRF score: {item['rrf_score']:.4f})"
        elif "rerank_score" in item:
            score_note = f" (relevance: {item['rerank_score']:.2f})"

        output_lines.append(f"--- [Excerpt {idx}: {filename} (Chunk #{chunk_idx})]{score_note} ---")
        output_lines.append(f"Path: {fpath}")
        output_lines.append(content)
        output_lines.append("")

    return "\n".join(output_lines).strip()

