"""
rag — Semantic retrieval-augmented generation package for Forge.
"""

from rag.embeddings import embedding_manager, EmbeddingManager, cosine_similarity
from rag.vector_store import vector_store, VectorStore, get_vector_store
from rag.ingestion import ingest_file
from rag.reranker import reranker, Reranker, get_reranker

__all__ = [
    "embedding_manager",
    "EmbeddingManager",
    "cosine_similarity",
    "vector_store",
    "VectorStore",
    "get_vector_store",
    "ingest_file",
    "reranker",
    "Reranker",
    "get_reranker",
]

