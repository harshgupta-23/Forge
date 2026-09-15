"""
reranker.py — Lightweight cross-encoder reranker using low-latency compact LLM indexing
and pure-Python lexical-semantic fusion fallback (zero torch/sentence-transformers).
"""

import re
import json
import asyncio
from typing import Any, Optional


class Reranker:
    """
    Reranks candidate document chunks retrieved from hybrid search.
    Tier 1: Fast zero-shot LLM index ranking via get_openai_client() (< 300ms).
    Tier 2: Pure-Python lexical-positional scoring fallback when offline.
    """

    def __init__(self):
        pass

    async def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 5
    ) -> list[dict[str, Any]]:
        """
        Takes candidate document chunks (typically 8-12) and returns the top_k
        highest-relevance chunks ordered by cross-encoder score.
        """
        if not candidates or len(candidates) <= 1:
            return candidates[:top_k]

        # Limit candidate pool to 10 for low latency
        pool = candidates[:10]

        try:
            from engine.utils import get_openai_client
            client, model = get_openai_client()

            # Build compact prompt
            prompt_lines = [
                f"User Query: {query}",
                "Candidate Excerpts:"
            ]
            for idx, c in enumerate(pool):
                snippet = c.get("content", "").replace("\n", " ")[:200]
                prompt_lines.append(f"[{idx}]: {snippet}")

            prompt_lines.append(
                f"\nTask: Return a JSON array of the top {top_k} candidate indices most relevant to the query in descending order."
                "\nOutput only the JSON array (e.g. [2, 0, 1]). Do not include explanations or markdown."
            )

            prompt_text = "\n".join(prompt_lines)

            loop = asyncio.get_event_loop()

            def _call_llm():
                return client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a fast cross-encoder reranking engine. Output only a compact JSON array of indices."},
                        {"role": "user", "content": prompt_text}
                    ],
                    max_tokens=64,
                    temperature=0.0
                )

            # Cap timeout to 1.5 seconds to avoid slowing down agent loop
            resp = await asyncio.wait_for(loop.run_in_executor(None, _call_llm), timeout=1.5)
            raw_output = resp.choices[0].message.content.strip()

            # Extract json array
            match = re.search(r'\[[\d,\s]+\]', raw_output)
            if match:
                indices = json.loads(match.group(0))
                reranked = []
                seen = set()
                for i in indices:
                    if isinstance(i, int) and 0 <= i < len(pool) and i not in seen:
                        seen.add(i)
                        item = pool[i]
                        item["rerank_method"] = "llm_cross_encoder"
                        reranked.append(item)

                # Fill any missing candidates from original ranking
                for idx, item in enumerate(pool):
                    if idx not in seen and len(reranked) < top_k:
                        seen.add(idx)
                        reranked.append(item)

                return reranked[:top_k]

        except Exception as exc:
            # Non-blocking fallback: Tier 2 lexical-positional overlap scoring
            pass

        return self._fallback_rerank(query, pool, top_k)

    def _fallback_rerank(self, query: str, pool: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        """Tier 2 fallback: pure-Python token overlap + exact match boost."""
        q_tokens = set(re.findall(r'\w+', query.lower()))
        if not q_tokens:
            return pool[:top_k]

        scored = []
        for idx, item in enumerate(pool):
            text = item.get("content", "").lower()
            t_tokens = set(re.findall(r'\w+', text))
            overlap = len(q_tokens.intersection(t_tokens))
            exact_phrase_bonus = 2.0 if query.lower() in text else 0.0
            
            # Combine hybrid search base score with lexical overlap
            base_score = item.get("rrf_score", 0.0)
            score = (base_score * 10) + overlap + exact_phrase_bonus
            item["rerank_method"] = "lexical_fallback"
            item["rerank_score"] = score
            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored][:top_k]


# Singleton instance
reranker = Reranker()


def get_reranker() -> Reranker:
    """Lazy accessor to prevent circular imports."""
    return reranker

