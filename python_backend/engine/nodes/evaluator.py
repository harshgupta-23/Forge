"""
evaluator.py — Conditional edge evaluator routing between tools, continuation, and termination.
"""

from typing import Literal
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage
from langgraph.graph import END
from engine.state import AgentState


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

    # If the model requested tools and has not hit iteration limit
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls and iteration < 10:
        return "tools"

    return END

