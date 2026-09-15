"""
agent.py — Core reasoning & LLM invocation node with real-time streaming.
"""

import json
import re
import asyncio
from typing import Any
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage
from engine.state import AgentState
from engine.utils import (
    get_openai_client,
    build_model_contents,
    convert_tools_to_openai_specs,
    _strip_thoughts
)
from tools import ALL_TOOLS

_TOOL_XML_RE = re.compile(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', re.DOTALL)


def _parse_fallback_tool_xml(text: str) -> list[dict[str, Any]]:
    """Fallback parser for models emitting legacy <tool_call> XML tags."""
    calls = []
    for m in _TOOL_XML_RE.findall(text):
        try:
            parsed = json.loads(m)
            if isinstance(parsed, dict) and "name" in parsed:
                calls.append({
                    "name": parsed.get("name", ""),
                    "args": parsed.get("args", {}) or {},
                    "id": f"call_{len(calls)}"
                })
        except Exception:
            pass
    return calls


async def agent_node(state: AgentState, config: RunnableConfig = None) -> dict[str, Any]:
    """
    Executes the LLM generation step:
    - Injects queue and stop_event from config['configurable']
    - Streams tokens to the queue in real-time
    - Gathers tool calls (both native OpenAI tool_calls and XML fallback)
    """
    cfg = (config or {}).get("configurable", {})
    queue: asyncio.Queue = cfg.get("queue")
    stop_event = cfg.get("stop_event")

    messages = state["messages"]
    attached = state.get("attached_files", {})
    contents = build_model_contents(messages, attached)
    tool_specs = convert_tools_to_openai_specs(ALL_TOOLS)

    client, model = get_openai_client()

    if stop_event and stop_event.is_set():
        return {
            "messages": [AIMessage(content="[Generation cancelled by user]")],
            "iteration": state.get("iteration", 0) + 1
        }

    # Signal status that thinking/generation is in progress
    if queue:
        await queue.put(("status", "Thinking…"))

    full_content = ""
    tool_call_chunks: dict[int, dict[str, Any]] = {}

    def _call_stream():
        try:
            return client.chat.completions.create(
                model=model,
                messages=contents,
                tools=tool_specs if tool_specs else None,
                stream=True,
            )
        except Exception as exc:
            # If provider fails with tools parameter (e.g. older endpoints), fallback without tools
            err_str = str(exc)
            if "tools" in err_str.lower() or "unsupported" in err_str.lower():
                return client.chat.completions.create(
                    model=model,
                    messages=contents,
                    stream=True,
                )
            raise exc

    loop = asyncio.get_event_loop()
    try:
        response_stream = await loop.run_in_executor(None, _call_stream)
    except Exception as exc:
        err_msg = f"[API Error]: {exc}"
        if queue:
            await queue.put(("error", err_msg))
        return {
            "messages": [AIMessage(content=err_msg)],
            "iteration": state.get("iteration", 0) + 1
        }

    for chunk in response_stream:
        if stop_event and stop_event.is_set():
            try:
                response_stream.close()
            except Exception:
                pass
            break

        choice = chunk.choices[0] if chunk.choices else None
        if not choice:
            continue

        delta = choice.delta
        if delta.content:
            full_content += delta.content

        # Accumulate native tool calls if emitted
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_call_chunks:
                    tool_call_chunks[idx] = {
                        "id": tc.id or f"call_{idx}",
                        "name": tc.function.name if tc.function and tc.function.name else "",
                        "arguments": tc.function.arguments if tc.function and tc.function.arguments else ""
                    }
                else:
                    if tc.id:
                        tool_call_chunks[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_call_chunks[idx]["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_call_chunks[idx]["arguments"] += tc.function.arguments

    # Assemble native tool calls
    parsed_tool_calls: list[dict[str, Any]] = []
    for idx in sorted(tool_call_chunks.keys()):
        raw_tc = tool_call_chunks[idx]
        name = raw_tc["name"]
        raw_args = raw_tc["arguments"]
        parsed_args = {}
        if raw_args and raw_args.strip():
            try:
                parsed_args = json.loads(raw_args)
            except Exception:
                # Fallback: empty dict if unparsable
                parsed_args = {}
        parsed_tool_calls.append({
            "name": name,
            "args": parsed_args if isinstance(parsed_args, dict) else {},
            "id": raw_tc["id"]
        })

    # If no native tool calls, inspect content for XML fallback
    if not parsed_tool_calls and full_content:
        xml_calls = _parse_fallback_tool_xml(full_content)
        if xml_calls:
            parsed_tool_calls = xml_calls

    clean_content = _strip_thoughts(full_content)

    # If this is the final answer (no tool calls), stream tokens word-by-word to queue
    if not parsed_tool_calls and clean_content and queue:
        words = clean_content.split(' ')
        for i, word in enumerate(words):
            if stop_event and stop_event.is_set():
                break
            chunk_str = word + ('' if i == len(words) - 1 else ' ')
            await queue.put(("token", chunk_str))
            # Small yield to let event loop dispatch
            await asyncio.sleep(0.01)

    ai_msg = AIMessage(
        content=clean_content,
        tool_calls=parsed_tool_calls if parsed_tool_calls else []
    )

    return {
        "messages": [ai_msg],
        "iteration": state.get("iteration", 0) + 1
    }

