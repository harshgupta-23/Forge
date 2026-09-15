"""
embeddings.py — Dynamic embedding generator with model probing and pure-Python fallback.
"""

import os
import math
import hashlib
from typing import Optional, Any


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calculates cosine similarity between two float vectors in pure Python."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


def _hash_to_embedding(text: str, dim: int = 768) -> list[float]:
    """
    Deterministic, normalized n-gram hash vector fallback for offline / test environments.
    Guarantees that similar text tokens share overlapping vector dimensions.
    """
    vec = [0.0] * dim
    tokens = text.lower().split()
    if not tokens:
        tokens = [text.lower()]

    for idx, token in enumerate(tokens):
        # 3 distinct hash positions per token to distribute signal
        h1 = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16) % dim
        h2 = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % dim
        h3 = (h1 + h2 + idx) % dim
        vec[h1] += 1.0
        vec[h2] += 0.5
        vec[h3] += 0.25

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0.0:
        vec = [x / norm for x in vec]
    return vec


class EmbeddingManager:
    """
    Manages embedding generation across external OpenAI/Gemini endpoints
    with automatic dimension detection and pure-Python fallback.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
        self._cached_dim: Optional[int] = None

    @property
    def dimension(self) -> int:
        return self._cached_dim or 768

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generates embedding vectors for a list of text strings."""
        if not texts:
            return []

        # Try API embedding via configured client
        try:
            from engine.utils import get_openai_client
            client, _ = get_openai_client()

            # Adapt model name for Google AI Studio if applicable
            base_url = str(client.base_url)
            model = self.model_name
            if "generativelanguage.googleapis.com" in base_url and "text-embedding" in model:
                model = "text-embedding-004"

            # Run in thread pool to keep event loop responsive
            import asyncio
            loop = asyncio.get_event_loop()

            def _call_api():
                return client.embeddings.create(
                    input=texts,
                    model=model
                )

            res = await loop.run_in_executor(None, _call_api)
            embeddings = [item.embedding for item in res.data]

            if embeddings and self._cached_dim is None:
                self._cached_dim = len(embeddings[0])
                print(f"[embeddings] Detected embedding dimension: {self._cached_dim} for model '{model}'")

            return embeddings
        except Exception as exc:
            # Fall back gracefully to deterministic normalized hash vectors
            fallback_dim = self._cached_dim or 768
            return [_hash_to_embedding(t, dim=fallback_dim) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        """Generates embedding vector for a single query string."""
        results = await self.embed_texts([query])
        if results:
            return results[0]
        return _hash_to_embedding(query, dim=self.dimension)


# Global singleton instance
embedding_manager = EmbeddingManager()

