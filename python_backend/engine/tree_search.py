"""
tree_search.py — Algorithmic tree search, value-guided branch evaluation,
and dead-end subtree detection.
"""

from typing import Any, Optional
from langchain_core.messages import BaseMessage, ToolMessage, AIMessage
from storage.metadata import metadata_store


def evaluate_turn_outcome(turn_messages: list[BaseMessage]) -> float:
    """
    Evaluates the quality / success score of a conversational turn ($0.0$ to $1.0$).
    Deducts score for tool errors, tracebacks, or repeated looping calls.
    """
    if not turn_messages:
        return 0.5

    score = 1.0
    tool_calls_seen = []

    for msg in turn_messages:
        if isinstance(msg, AIMessage):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    sig = (tc.get("name", ""), str(tc.get("args", "")))
                    if sig in tool_calls_seen:
                        score -= 0.3  # Repetition loop penalty
                    tool_calls_seen.append(sig)

        elif isinstance(msg, ToolMessage):
            c_str = str(msg.content or "").lower()
            if any(err in c_str for err in [
                "traceback", "error:", "exception", "failed with exit code", "filenotfound"
            ]):
                score -= 0.35  # Error penalty

    return max(0.0, min(1.0, score))


def detect_dead_end_subtrees(
    snapshots: list[Any],
    max_consecutive_failures: int = 3
) -> list[str]:
    """
    Analyzes LangGraph state history to detect stalled or failing branches.
    Returns list of checkpoint IDs that represent dead ends.
    """
    dead_ends: list[str] = []

    # Map snapshots by checkpoint ID and resolve parent links
    snapshot_map = {}
    for s in snapshots:
        cid = s.config.get("configurable", {}).get("checkpoint_id")
        if cid:
            snapshot_map[cid] = s

    for s in snapshots:
        # Check turn boundaries
        if not s.next:
            cid = s.config.get("configurable", {}).get("checkpoint_id")
            if not cid:
                continue

            msgs = s.values.get("messages", [])
            # Count recent tool failures in this snapshot
            consecutive_errors = 0
            for m in reversed(msgs):
                if isinstance(m, ToolMessage):
                    c_str = str(m.content or "").lower()
                    if "error" in c_str or "traceback" in c_str or "failed" in c_str:
                        consecutive_errors += 1
                    else:
                        break
                elif isinstance(m, AIMessage) and consecutive_errors > 0:
                    continue
                else:
                    break

            if consecutive_errors >= max_consecutive_failures:
                dead_ends.append(cid)

    return dead_ends


async def auto_prune_dead_ends(thread_id: str, snapshots: list[Any]) -> list[str]:
    """
    Identifies dead-end checkpoints and flags them as is_pruned = 1 in MetadataStore.
    Returns list of pruned checkpoint IDs.
    """
    dead_ends = detect_dead_end_subtrees(snapshots)
    for cid in dead_ends:
        try:
            await metadata_store.set_pruned(thread_id, cid, True)
        except Exception:
            pass
    return dead_ends


async def revive_branch_if_pruned(thread_id: str, checkpoint_id: str) -> None:
    """
    Allows a user to revive a previously pruned branch by clicking it
    or issuing a follow-up query from it.
    """
    try:
        await metadata_store.set_pruned(thread_id, checkpoint_id, False)
    except Exception:
        pass

