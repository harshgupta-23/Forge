"""
graph.py — Multi-node LangGraph compilation and stateful streaming executor with checkpointer support.
"""

import asyncio
import threading
from typing import Any, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END
from engine.state import AgentState
from engine.nodes.planner import planner_node
from engine.nodes.agent import agent_node
from engine.nodes.tools import tools_node
from engine.nodes.evaluator import should_continue


def build_graph(checkpointer: Optional[Any] = None):
    """
    Constructs and compiles the multi-node StateGraph:
    planner -> agent -> should_continue -> (tools -> agent | END)
    Attaches checkpointer for stateful time-travel checkpoints if provided.
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tools_node)

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END
        }
    )
    workflow.add_edge("tools", "agent")

    return workflow.compile(checkpointer=checkpointer)


compiled_graph = build_graph()


def set_compiled_graph(graph: Any) -> None:
    """Updates the compiled graph instance with the initialized checkpointer."""
    global compiled_graph
    compiled_graph = graph


def get_compiled_graph() -> Any:
    """Returns the current active compiled graph instance."""
    return compiled_graph


async def stream_graph_execution(
    delta_state: dict[str, Any],
    queue: asyncio.Queue,
    thread_id: Optional[str] = None,
    checkpoint_id: Optional[str] = None,
    stop_event: Optional[threading.Event] = None
) -> list[BaseMessage]:
    """
    Executes the multi-node graph with stateful checkpoints:
    - Passes delta_state (new turn messages only) to avoid channel collisions
    - Points configurable['checkpoint_id'] to active_checkpoint_id when forking branches
    - Pushes events ('status', 'token', 'tool_start', 'tool_done', 'done', 'cancelled', 'error')
    - Sends ('__end__', None) upon completion.
    """
    configurable: dict[str, Any] = {
        "queue": queue,
        "stop_event": stop_event
    }
    if thread_id:
        configurable["thread_id"] = thread_id

    # If branching from a historical turn, point to that parent checkpoint
    if checkpoint_id and checkpoint_id != "node_root":
        configurable["checkpoint_id"] = checkpoint_id

    # Observability & LangSmith Tracing integration
    try:
        from observability.tracer import get_tracing_callbacks
        callbacks = get_tracing_callbacks(
            thread_id=thread_id,
            run_name=f"Forge-Turn-{thread_id or 'default'}",
            tags=["forge", "langgraph", f"thread:{thread_id or 'default'}"],
            metadata={
                "session_id": thread_id,
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id
            }
        )
    except Exception:
        callbacks = []

    config: dict[str, Any] = {
        "configurable": configurable,
        "callbacks": callbacks,
        "tags": ["forge", "agentic-tree"],
        "metadata": {
            "session_id": thread_id,
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id
        }
    }

    try:
        graph = get_compiled_graph()
        final_state = await graph.ainvoke(delta_state, config=config)
        messages = final_state.get("messages", [])

        if stop_event and stop_event.is_set():
            await queue.put(("cancelled", messages))
        else:
            await queue.put(("done", messages))
        return messages
    except Exception as exc:
        await queue.put(("error", str(exc)))
        return delta_state.get("messages", [])
    finally:
        await queue.put(("__end__", None))
