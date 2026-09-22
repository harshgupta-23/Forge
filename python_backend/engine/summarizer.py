"""
summarizer.py — Hierarchical Subtree Summarization with persistent checkpoint-hash caching.
Replaces destructive one-shot summarization with automated, progressive block-level compaction.
"""

import hashlib
from typing import Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from storage.metadata import metadata_store
from engine.utils import get_openai_client, _strip_thoughts, build_model_contents


class HierarchicalSubtreeSummarizer:
    """
    Tiered rolling block summarizer that compacts older ancestor chains
    into structured summary checkpoints while preserving graph topology.
    """

    def __init__(self, block_size: int = 4, activation_turn_depth: int = 6):
        self.block_size = block_size
        self.activation_turn_depth = activation_turn_depth
        self._memory_cache: dict[str, str] = {}

    def _compute_block_cache_key(self, thread_id: str, start_id: str, end_id: str) -> str:
        """Derives a deterministic hash from thread and turn slice IDs."""
        raw = f"{thread_id}::{start_id}::{end_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _summarize_block(
        self,
        block_messages: list[BaseMessage],
        thread_id: str,
        start_id: str,
        end_id: str,
        attached_files: dict[str, str]
    ) -> str:
        """
        Summarizes a block of turns, checking the in-memory and MetadataStore DB cache first.
        """
        cache_key = self._compute_block_cache_key(thread_id, start_id, end_id)

        # 1. Check memory cache
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]

        # 2. Check persistent DB cache
        db_summary = await metadata_store.get_summary(cache_key)
        if db_summary:
            self._memory_cache[cache_key] = db_summary
            return db_summary

        # 3. Generate summary via LLM or extractive fallback
        transcript_lines = [
            "Summarise this specific conversation block concisely.",
            "List: primary user objectives, tools executed, files modified/read, and key outcomes.",
            "Be factual, concise, and preserve technical details and paths.\n\nBLOCK TRANSCRIPT:\n"
        ]
        for m in block_messages:
            if isinstance(m, HumanMessage):
                transcript_lines.append(f"USER: {str(m.content)[:400]}")
            elif isinstance(m, AIMessage):
                transcript_lines.append(f"ASSISTANT: {str(m.content)[:400]}")
            elif isinstance(m, ToolMessage):
                name = getattr(m, "name", "tool")
                first_line = str(m.content).split("\n")[0][:150]
                transcript_lines.append(f"TOOL({name}): {first_line}")

        prompt = "\n".join(transcript_lines)
        summary_text = ""

        try:
            client, model = get_openai_client(role="summarizer")
            contents = build_model_contents([HumanMessage(content=prompt)], attached_files)
            resp = client.chat.completions.create(
                model=model,
                messages=contents,
                max_tokens=350,
                temperature=0.2
            )
            summary_text = _strip_thoughts(resp.choices[0].message.content or "").strip()
        except Exception:
            # Fallback extractive summary
            actions = []
            for m in block_messages:
                if isinstance(m, HumanMessage):
                    actions.append(f"• User: {str(m.content)[:80]}")
                elif isinstance(m, ToolMessage):
                    actions.append(f"• Ran {getattr(m, 'name', 'tool')}: {str(m.content)[:60]}")
            summary_text = "Summary of earlier steps:\n" + "\n".join(actions[:6])

        # 4. Save to both memory and DB
        self._memory_cache[cache_key] = summary_text
        try:
            await metadata_store.save_summary(cache_key, thread_id, summary_text)
        except Exception:
            pass

        return summary_text

    async def compact_ancestor_history(
        self,
        messages: list[BaseMessage],
        thread_id: str = "default",
        attached_files: Optional[dict[str, str]] = None
    ) -> list[BaseMessage]:
        """
        Slices deep ancestor chains into hierarchical summary blocks.
        Preserves root turn and the latest 2 turns verbatim.
        """
        attached = attached_files or {}
        human_indices = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
        total_turns = len(human_indices)

        if total_turns < self.activation_turn_depth:
            return list(messages)

        # Retain root turn and recent 2 turns verbatim
        recent_cutoff = human_indices[-2]
        root_idx = human_indices[0]

        # Extract intermediate turns to hierarchically summarize
        # Turn slices: between root_idx and recent_cutoff
        intermediate_msgs = messages[root_idx + 1: recent_cutoff]
        if len(intermediate_msgs) < self.block_size:
            return list(messages)

        # Generate block summary
        start_id = f"turn_{root_idx}"
        end_id = f"turn_{recent_cutoff}"
        block_summary = await self._summarize_block(
            intermediate_msgs,
            thread_id,
            start_id,
            end_id,
            attached
        )

        # Assemble compacted stream:
        # [Root Message] -> [Hierarchical Block Summary] -> [Recent Turns Verbatim]
        compacted: list[BaseMessage] = [messages[root_idx]]
        compacted.append(HumanMessage(content="[System Context: Hierarchical summary of preceding conversation turns]"))
        compacted.append(AIMessage(content=f"[Hierarchical Summary]\n{block_summary}"))
        compacted.extend(messages[recent_cutoff:])

        return compacted


hierarchical_summarizer = HierarchicalSubtreeSummarizer()

