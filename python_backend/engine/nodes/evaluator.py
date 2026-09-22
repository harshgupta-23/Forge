"""
evaluator.py — Conditional edge evaluator routing between tools, continuation, and termination.
Includes:
- Action deduplication loop detector (trips only if prior identical invocation errored)
- Hard turn iteration budget
- Stop event termination
"""

import json
from typing import Literal
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END
from engine.state import AgentState

MAX_ITERATIONS = 15


def _is_error_content(content: str) -> bool:
    """Heuristic detecting error or failure content in a ToolMessage."""
    c_lower = str(content).lower()
    return any(ind in c_lower for ind in (
        "error", "exception", "failed", "access denied",
        "violation", "not found", "timed out"
    ))


def is_stuck_in_repetition_loop(messages: list) -> tuple[bool, str]:
    """
    Detects if the latest AIMessage is repeating an identical tool call (same tool name and
    identical arguments) that already failed with an error in a preceding turn.
    Returns: (is_loop: bool, reason: str)
    """
    if len(messages) < 3:
        return False, ""

    current_ai = messages[-1]
    if not isinstance(current_ai, AIMessage) or not current_ai.tool_calls:
        return False, ""

    try:
        current_calls = [
            (tc.get("name"), json.dumps(tc.get("args", {}), sort_keys=True))
            for tc in current_ai.tool_calls
        ]
    except Exception:
        return False, ""

    # Search backwards for recent ToolMessages that resulted in errors
    for i in range(len(messages) - 2, max(-1, len(messages) - 10), -1):
        prev_msg = messages[i]
        if isinstance(prev_msg, ToolMessage):
            prev_name = getattr(prev_msg, "name", "")
            prev_content = str(prev_msg.content or "")
            prev_call_id = getattr(prev_msg, "tool_call_id", "")

            if _is_error_content(prev_content):
                # Locate the parent AIMessage that issued this call
                for j in range(i - 1, max(-1, i - 6), -1):
                    prior_ai = messages[j]
                    if isinstance(prior_ai, AIMessage) and prior_ai.tool_calls:
                        for prior_tc in prior_ai.tool_calls:
                            tc_id = prior_tc.get("id")
                            if tc_id == prev_call_id or prior_tc.get("name") == prev_name:
                                try:
                                    prior_key = (
                                        prior_tc.get("name"),
                                        json.dumps(prior_tc.get("args", {}), sort_keys=True)
                                    )
                                    if prior_key in current_calls:
                                        return True, f"Repetitive loop detected: Tool '{prior_key[0]}' re-invoked with identical failing arguments."
                                except Exception:
                                    pass
                        break

    return False, ""


def should_continue(state: AgentState, config: RunnableConfig = None) -> Literal["tools", "__end__"]:
    """
    Evaluates whether the agent graph should proceed to tool execution
    or finish execution.
    """
    cfg = (config or {}).get("configurable", {})
    stop_event = cfg.get("stop_event")

    if stop_event and stop_event.is_set():
        return END

    messages = state.get("messages", [])
    if not messages:
        return END

    last_msg = messages[-1]
    iteration = state.get("iteration", 0)

    # Hard turn budget ceiling
    if iteration >= MAX_ITERATIONS:
        return END

    # If the model requested tools, verify it's not stuck in a failing repetition loop
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        is_loop, reason = is_stuck_in_repetition_loop(messages)
        if is_loop:
            # Break loop to prevent burning tokens
            queue = cfg.get("queue")
            if queue:
                try:
                    queue.put_nowait(("status", f"⚠ {reason} Breaking loop."))
                except Exception:
                    pass
            return END
        return "tools"

    return END
