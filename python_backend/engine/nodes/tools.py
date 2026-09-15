"""
tools.py — Tool execution node with live event streaming and security checks.
"""

import json
import asyncio
from typing import Any
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage, ToolMessage
from engine.state import AgentState
from tools import ALL_TOOLS


def _fmt_args(args: dict[str, Any]) -> str:
    """Formats argument dict into a readable single-line summary."""
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        s = str(v)
        parts.append(f"{k}={s[:57] + '…' if len(s) > 60 else s!r}")
    return ", ".join(parts)


def _safe_parse_args(raw_args: Any) -> dict[str, Any]:
    """Ensures tool arguments are a valid dictionary, falling back to {}."""
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


async def tools_node(state: AgentState, config: RunnableConfig = None) -> dict[str, Any]:
    """
    Executes tool calls requested by the agent node:
    - Emits tool_start and tool_done events to the UI via queue
    - Executes tools in thread pool to prevent blocking asyncio loop
    - Returns list of ToolMessage objects
    """
    cfg = (config or {}).get("configurable", {})
    queue: asyncio.Queue = cfg.get("queue")
    stop_event = cfg.get("stop_event")

    messages = state.get("messages", [])
    if not messages:
        return {"messages": []}

    last_msg = messages[-1]
    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return {"messages": []}

    tool_map = {t.name: t for t in ALL_TOOLS}
    tool_messages: list[ToolMessage] = []
    loop = asyncio.get_event_loop()

    for tc in last_msg.tool_calls:
        if stop_event and stop_event.is_set():
            break

        tool_name = tc.get("name", "")
        raw_args = tc.get("args", {})
        args = _safe_parse_args(raw_args)
        call_id = tc.get("id") or f"call_{tool_name}"

        args_preview = _fmt_args(args)
        if queue:
            await queue.put(("tool_start", f"⚙  {tool_name}({args_preview})"))

        if tool_name not in tool_map:
            result_str = f"[Error]: Unknown tool '{tool_name}'"
        else:
            thread_id = cfg.get("thread_id")
            if tool_name == "semantic_search" and thread_id and "session_id" not in args:
                args["session_id"] = thread_id

            def _execute(target_tool=tool_map[tool_name], target_args=args):
                try:
                    return target_tool.invoke(target_args)
                except Exception as exc:
                    return f"[Tool Error in {target_tool.name}]: {exc}"

            try:
                result_str = await loop.run_in_executor(None, _execute)
            except Exception as exc:
                result_str = f"[Execution Error]: {exc}"

        from engine.utils import estimate_tokens
        toks = estimate_tokens(str(result_str))
        summary = next((ln.strip() for ln in str(result_str).splitlines() if ln.strip()), "")[:80]
        if queue:
            await queue.put(("tool_done", (f"  ✓  {tool_name} → {summary}", toks)))

        tool_messages.append(ToolMessage(
            content=str(result_str),
            name=tool_name,
            tool_call_id=call_id
        ))

    return {"messages": tool_messages}

