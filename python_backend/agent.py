"""
agent.py — Backward-compatibility shim.
Re-exports symbols from the modular engine/ package to ensure any legacy imports continue to function.
"""

import sys
import asyncio
from pathlib import Path

# Ensure root of python_backend is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.state import AgentState
from engine.utils import (
    count_tokens,
    summarise_history,
    _strip_thoughts,
    SYSTEM_PROMPT,
    get_openai_client,
    build_model_contents
)
from engine.graph import build_graph, get_compiled_graph, stream_graph_execution


def __getattr__(name: str):
    if name in ("app", "compiled_graph"):
        return get_compiled_graph()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def stream_final_response(state: dict, stop_event=None):
    """
    Compatibility generator mimicking legacy agent.stream_final_response.
    Consumes from an asyncio.Queue populated by stream_graph_execution.
    """
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    async def _runner():
        await stream_graph_execution(state, queue, stop_event=stop_event)

    task = loop.create_task(_runner())

    while True:
        event_type, payload = loop.run_until_complete(queue.get())
        if event_type == "__end__":
            break
        yield (event_type, payload)

    loop.close()


__all__ = [
    "AgentState",
    "build_graph",
    "app",
    "count_tokens",
    "summarise_history",
    "stream_final_response",
    "_strip_thoughts",
    "SYSTEM_PROMPT"
]