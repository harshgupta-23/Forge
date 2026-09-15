"""
planner.py — High-level task planner node.
Analyzes user inputs, sets iteration counter, and prepares execution state.
"""

from typing import Any
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import HumanMessage
from engine.state import AgentState


async def planner_node(state: AgentState, config: RunnableConfig = None) -> dict[str, Any]:
    """
    Initializes execution cycle, verifies inputs, and sets state iteration to 0.
    Can emit a planning status to the streaming queue if provided.
    """
    cfg = (config or {}).get("configurable", {})
    queue = cfg.get("queue")
    stop_event = cfg.get("stop_event")

    if stop_event and stop_event.is_set():
        return {"iteration": 0, "is_streaming": False}

    messages = state.get("messages", [])
    last_user_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_msg = str(msg.content)
            break

    # If task is complex or multi-turn, set up initial planning metadata
    plan = None
    if any(keyword in last_user_msg.lower() for keyword in ["then", "and then", "after that", "steps", "first"]):
        plan = ["Analyze task", "Execute operations", "Synthesize findings"]

    if queue:
        await queue.put(("status", "Analyzing request..."))

    return {
        "iteration": state.get("iteration", 0),
        "plan": plan,
        "is_streaming": False
    }

