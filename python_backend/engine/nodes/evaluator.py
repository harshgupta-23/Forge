"""
evaluator.py — Conditional edge evaluator and recovery router for tool execution loops.
Includes:
- Two-strike self-healing recovery protocol via schema-compliant ToolMessages
- Action deduplication loop detector (trips only if prior identical invocation errored)
- Hard turn iteration budget (MAX_ITERATIONS = 15)
- Stop event cancellation
"""

import json
from typing import Literal, Any
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


def get_failing_tool_signatures(messages: list) -> list[str]:
    """Extracts canonical signatures of tool calls that repeat prior failed invocations."""
    if len(messages) < 3:
        return []

    current_ai = messages[-1]
    if not isinstance(current_ai, AIMessage) or not current_ai.tool_calls:
        return []

    current_calls = {}
    for tc in current_ai.tool_calls:
        try:
            name = tc.get("name", "")
            args_str = json.dumps(tc.get("args", {}), sort_keys=True)
            current_calls[(name, args_str)] = tc
        except Exception:
            pass

    repeated_sigs = []
    # Search backwards for recent ToolMessages that resulted in errors
    for i in range(len(messages) - 2, max(-1, len(messages) - 10), -1):
        prev_msg = messages[i]
        if isinstance(prev_msg, ToolMessage):
            prev_name = getattr(prev_msg, "name", "")
            prev_content = str(prev_msg.content or "")
            prev_call_id = getattr(prev_msg, "tool_call_id", "")

            if _is_error_content(prev_content):
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
                                        sig = f"{prior_key[0]}:{prior_key[1]}"
                                        if sig not in repeated_sigs:
                                            repeated_sigs.append(sig)
                                except Exception:
                                    pass
                        break

    return repeated_sigs


def is_stuck_in_repetition_loop(messages: list) -> tuple[bool, str]:
    """
    Detects if the latest AIMessage is repeating an identical tool call (same tool name and
    identical arguments) that already failed with an error in a preceding turn.
    Returns: (is_loop: bool, reason: str)
    """
    sigs = get_failing_tool_signatures(messages)
    if sigs:
        tool_name = sigs[0].split(":", 1)[0]
        return True, f"Repetitive loop detected: Tool '{tool_name}' re-invoked with identical failing arguments."
    return False, ""


def should_continue(state: AgentState, config: RunnableConfig = None) -> Literal["tools", "recovery", "__end__"]:
    """
    Evaluates whether the agent graph should proceed to tool execution,
    trigger self-correcting recovery, or finish execution.
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

    # If the model requested tools, verify repetition loop status
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        is_loop, reason = is_stuck_in_repetition_loop(messages)
        if is_loop:
            sigs = get_failing_tool_signatures(messages)
            warned = state.get("warned_signatures") or []

            # Strike 2: If any offending call was already warned, halt execution to prevent token burn
            if any(s in warned for s in sigs):
                queue = cfg.get("queue")
                if queue:
                    try:
                        queue.put_nowait(("status", f"[Alert] {reason} Repeated after warning. Halting."))
                    except Exception:
                        pass
                return END

            # Strike 1: Route to recovery node for self-correcting reflection
            queue = cfg.get("queue")
            if queue:
                try:
                    queue.put_nowait(("status", f"[Alert] {reason} Injected recovery guidance."))
                except Exception:
                    pass
            return "recovery"

        return "tools"

    return END


async def recovery_node(state: AgentState, config: RunnableConfig = None) -> dict[str, Any]:
    """
    Self-healing recovery node:
    - Injects schema-compliant ToolMessages for each offending tool call
      (strictly adhering to OpenAI/Gemma turn schemas where every AIMessage tool_call must
      have a matching ToolMessage)
    - Alerts the model to the repetition and prompts an alternative strategy
    - Tracks warned call signatures to enforce Strike 2 termination if repeated again
    """
    messages = state.get("messages", [])
    if not messages:
        return {"iteration": state.get("iteration", 0) + 1}

    last_ai = messages[-1]
    tool_calls = getattr(last_ai, "tool_calls", []) or []

    sigs = get_failing_tool_signatures(messages)
    existing_warned = list(state.get("warned_signatures") or [])
    for s in sigs:
        if s not in existing_warned:
            existing_warned.append(s)

    recovery_messages = []
    for i, tc in enumerate(tool_calls):
        call_id = tc.get("id") or f"call_{i}"
        tool_name = tc.get("name", "tool")
        recovery_content = (
            f"[Guardrail Alert: Repeated Tool Failure]\n"
            f"You attempted to execute tool '{tool_name}' with identical arguments that already failed in a previous attempt.\n"
            f"Do NOT execute this tool with these arguments again.\n"
            f"Please analyze the prior error, choose an alternative tool or modified parameters, "
            f"or explain to the user what is preventing completion."
        )
        recovery_messages.append(
            ToolMessage(
                tool_call_id=str(call_id),
                name=tool_name,
                content=recovery_content
            )
        )

    recovery_count = (state.get("recovery_count") or 0) + 1

    return {
        "messages": recovery_messages,
        "warned_signatures": existing_warned,
        "recovery_count": recovery_count,
        "iteration": state.get("iteration", 0) + 1
    }
