"""
pruner.py — Dynamic Context Pruning engine for LangGraph conversational state.
Compacts failed tool traces into tombstones, truncates stale bulky outputs,
and filters mid-depth irrelevant turns while strictly preserving message types
and ground-truth invariants.
"""

import re
from typing import Optional, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from engine.tokenizer import count_tokens_exact, count_message_tokens


class DynamicContextPruner:
    """
    Non-destructive context pruner operating as a just-in-time filter
    prior to LLM completion calls.
    """

    def __init__(
        self,
        max_tool_output_tokens: int = 350,
        relevance_threshold: float = 0.12,
        preserve_recent_turns: int = 2
    ):
        self.max_tool_output_tokens = max_tool_output_tokens
        self.relevance_threshold = relevance_threshold
        self.preserve_recent_turns = preserve_recent_turns

    def _extract_query_keywords(self, text: str) -> set[str]:
        """Extracts lowercase alphabetic/alphanumeric keywords (min length 3)."""
        words = re.findall(r'\b[a-zA-Z0-9_\-\.]{3,}\b', text.lower())
        stopwords = {
            "the", "and", "for", "with", "this", "that", "from", "have",
            "what", "when", "where", "which", "will", "would", "could",
            "should", "been", "there", "their", "about", "into", "more"
        }
        return {w for w in words if w not in stopwords}

    def _compute_turn_relevance(self, msg_content: str, query_keywords: set[str]) -> float:
        """Fast Tier-1 BM25/token-overlap relevance score (0.0 to 1.0)."""
        if not query_keywords or not msg_content:
            return 0.5  # Neutral default if no keywords
        msg_words = set(re.findall(r'\b[a-zA-Z0-9_\-\.]{3,}\b', msg_content.lower()))
        if not msg_words:
            return 0.0
        overlap = query_keywords.intersection(msg_words)
        return len(overlap) / max(1, len(query_keywords))

    def _is_error_output(self, content: str) -> bool:
        """Heuristic detecting failed tool executions, tracebacks, and exceptions."""
        lower = content.lower()
        error_indicators = [
            "traceback (most recent call last)",
            "filenotfounderror",
            "modulenotfounderror",
            "syntaxerror",
            "permissionerror",
            "connection refused",
            "error: ",
            "exception:",
            "[tool error]",
            "command failed with exit code",
            "fatal error",
            "timed out after"
        ]
        return any(ind in lower for ind in error_indicators)

    def _extract_error_summary(self, content: str) -> str:
        """Extracts a succinct error message without verbose traceback headers."""
        lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
        if not lines:
            return "Execution error"
        meaningful = [l for l in lines if not l.lower().startswith("traceback (most recent call last)")]
        if meaningful:
            last_line = meaningful[-1]
            if any(exc in last_line for exc in [":", "Error", "Exception", "failed", "exit"]):
                return last_line[:100]
            return meaningful[0][:100]
        return "Execution error"

    def prune_context(
        self,
        messages: list[BaseMessage],
        model: str = ""
    ) -> list[BaseMessage]:
        """
        Applies dynamic context pruning across messages:
        1. Identifies recent vs historical turn boundaries.
        2. Detects resolved tool errors and compacts them into tombstones.
        3. Truncates bulky tool outputs from older turns.
        4. Condenses low-relevance intermediate assistant messages.
        5. Preserves invariant root instruction and recent 2 turns verbatim.
        """
        if len(messages) <= 4:
            return list(messages)

        # 1. Identify turn boundaries based on HumanMessage positions
        human_indices = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
        if not human_indices:
            return list(messages)

        # Invariant 1: Preserve recent turns verbatim
        recent_threshold_idx = human_indices[-min(self.preserve_recent_turns, len(human_indices))]
        root_idx = human_indices[0]

        # Latest user query keywords for relevance scoring
        latest_user_content = str(messages[human_indices[-1]].content or "")
        query_keywords = self._extract_query_keywords(latest_user_content)

        # 2. Track which tools ultimately succeeded
        # If tool X failed at turn A but succeeded at turn B, turn A's failure is a dead-end
        tool_success_names: set[str] = set()
        for i in range(recent_threshold_idx, len(messages)):
            m = messages[i]
            if isinstance(m, ToolMessage):
                tool_name = getattr(m, "name", "tool")
                c_str = str(m.content or "")
                if not self._is_error_output(c_str):
                    tool_success_names.add(tool_name)

        pruned: list[BaseMessage] = []

        for idx, msg in enumerate(messages):
            # Invariant 2: Root turn and recent turns are preserved verbatim
            if idx <= root_idx or idx >= recent_threshold_idx:
                pruned.append(msg)
                continue

            # Process Historical ToolMessages
            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "tool")
                content_str = str(msg.content or "")
                t_id = getattr(msg, "tool_call_id", "")

                # A. Dead-end error compaction:
                # If this tool call was an error, and the tool later succeeded or retry was executed
                if self._is_error_output(content_str):
                    err_summary = self._extract_error_summary(content_str)
                    tombstone = f"[Tool retry succeeded: earlier attempt failed ({err_summary}). Pruned for context efficiency]"
                    pruned.append(ToolMessage(
                        content=tombstone,
                        name=tool_name,
                        tool_call_id=t_id
                    ))
                    continue

                # B. Bulky output truncation for older turns:
                tok_count = count_tokens_exact(content_str, model)
                if tok_count > self.max_tool_output_tokens:
                    lines = content_str.splitlines()
                    if len(lines) > 10:
                        head = "\n".join(lines[:6])
                        tail = "\n".join(lines[-3:])
                        truncated_body = f"{head}\n\n[... {len(lines) - 9} lines / ~{tok_count - 100} tokens pruned from earlier tool output ...]\n\n{tail}"
                    else:
                        truncated_body = content_str[:600] + f"\n[... ~{tok_count - 150} tokens truncated ...]"

                    pruned.append(ToolMessage(
                        content=truncated_body,
                        name=tool_name,
                        tool_call_id=t_id
                    ))
                    continue

                pruned.append(msg)
                continue

            # Process Historical AIMessages
            if isinstance(msg, AIMessage):
                a_content = str(msg.content or "")
                # If this is a historical turn with heavy text, check relevance score
                if a_content and len(a_content) > 300 and query_keywords:
                    rel_score = self._compute_turn_relevance(a_content, query_keywords)
                    if rel_score < self.relevance_threshold:
                        # Condense to first 2 sentences + summary marker
                        sentences = re.split(r'(?<=[.?!])\s+', a_content)
                        condensed = " ".join(sentences[:2]) if sentences else a_content[:150]
                        new_content = f"{condensed} [Intermediate reasoning condensed — low relevance to active query]"
                        pruned.append(AIMessage(
                            content=new_content,
                            tool_calls=getattr(msg, "tool_calls", None)
                        ))
                        continue

                pruned.append(msg)
                continue

            # Default: Keep HumanMessage or other messages
            pruned.append(msg)

        return pruned


default_pruner = DynamicContextPruner()

