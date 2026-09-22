"""
agent.py — Core reasoning & LLM invocation node with real-time streaming,
balanced-bracket tool parsing, and native AsyncOpenAI integration.
"""

import json
import asyncio
from typing import Any
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage
from engine.state import AgentState
from engine.utils import (
    get_async_openai_client,
    build_model_contents,
    convert_tools_to_openai_specs,
    _strip_thoughts
)
from engine.pruner import default_pruner
from engine.summarizer import hierarchical_summarizer
from engine.tokenizer import calculate_token_savings
from tools import ALL_TOOLS


def _extract_balanced_json(text: str, start_pos: int) -> tuple[dict[str, Any] | None, int]:
    """
    Scans text from start_pos to find the first '{' and extracts the complete
    balanced JSON object, respecting quotes, escape sequences, and nesting.
    Returns (parsed_dict, next_pos).
    """
    brace_start = text.find('{', start_pos)
    if brace_start == -1:
        return None, start_pos

    depth = 0
    in_string = False
    escape = False
    i = brace_start

    while i < len(text):
        c = text[i]
        if escape:
            escape = False
        elif c == '\\' and in_string:
            escape = True
        elif c == '"':
            in_string = not in_string
        elif not in_string:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    raw_json = text[brace_start:i + 1]
                    try:
                        parsed = json.loads(raw_json)
                        if isinstance(parsed, dict):
                            return parsed, i + 1
                    except Exception:
                        pass
                    return None, i + 1
        i += 1

    return None, start_pos


def _parse_fallback_tool_xml(text: str) -> list[dict[str, Any]]:
    """
    Balanced-bracket parser for legacy <tool_call> XML tags.
    Handles nested dictionaries, multi-line arguments, and escaped quotes.
    Always assigns a deterministic non-empty fallback ID so recovery nodes have valid strings.
    """
    calls = []
    pos = 0
    tag_open = "<tool_call>"
    tag_close = "</tool_call>"

    while True:
        idx = text.lower().find(tag_open, pos)
        if idx == -1:
            break
        json_start = idx + len(tag_open)
        parsed, next_pos = _extract_balanced_json(text, json_start)
        if parsed and "name" in parsed:
            call_id = parsed.get("id") or f"call_{len(calls)}"
            calls.append({
                "name": str(parsed.get("name", "")),
                "args": parsed.get("args", {}) or {},
                "id": str(call_id)
            })
        close_idx = text.lower().find(tag_close, json_start)
        if close_idx != -1:
            pos = close_idx + len(tag_close)
        else:
            pos = next_pos if next_pos > json_start else json_start + 1

    return calls


class StreamingThoughtFilter:
    """
    Real-time streaming filter that suppresses thinking blocks and tool call markup
    while streaming clean tokens to the async queue with 0ms artificial sleep delay.
    Includes an initial hysteresis buffer to inspect opening text for tool calls or tags.
    """
    def __init__(self, queue: asyncio.Queue | None, hysteresis_chars: int = 40):
        self.queue = queue
        self.hysteresis_chars = hysteresis_chars
        self.buffer = ""
        self.inside_thought = False
        self.suppress_all = False
        self.flushed_hysteresis = False

    def mark_tool_call_detected(self):
        """Immediately suppresses chat token emission if tool calls are present."""
        self.suppress_all = True

    async def feed(self, text: str):
        if self.suppress_all or not text:
            return

        self.buffer += text
        buf_lower = self.buffer.lower()

        # If XML tool call is detected in stream, suppress chat token output
        if "<tool_call" in buf_lower:
            self.suppress_all = True
            return

        # Hysteresis buffer check before flushing initial tokens
        if not self.flushed_hysteresis:
            if "<" in self.buffer:
                # Potential tag starting; wait until tag resolves or closes
                if "<thought" in buf_lower or "<thinking" in buf_lower:
                    self.inside_thought = True
                    if "</thought>" in buf_lower:
                        end_idx = buf_lower.find("</thought>") + len("</thought>")
                        self.buffer = self.buffer[end_idx:]
                        self.inside_thought = False
                    elif "</thinking>" in buf_lower:
                        end_idx = buf_lower.find("</thinking>") + len("</thinking>")
                        self.buffer = self.buffer[end_idx:]
                        self.inside_thought = False
                    else:
                        return
                elif len(self.buffer) < self.hysteresis_chars:
                    return

            if len(self.buffer) < self.hysteresis_chars:
                return

            self.flushed_hysteresis = True

        # Process and stream clean content
        await self._process_stream()

    async def _process_stream(self):
        while self.buffer:
            buf_lower = self.buffer.lower()
            if self.inside_thought:
                if "</thought>" in buf_lower:
                    end_idx = buf_lower.find("</thought>") + len("</thought>")
                    self.buffer = self.buffer[end_idx:]
                    self.inside_thought = False
                elif "</thinking>" in buf_lower:
                    end_idx = buf_lower.find("</thinking>") + len("</thinking>")
                    self.buffer = self.buffer[end_idx:]
                    self.inside_thought = False
                else:
                    self.buffer = ""
                    break
            else:
                tag_start = -1
                for tag in ("<thought>", "<thinking>", "<thought", "<thinking"):
                    idx = buf_lower.find(tag)
                    if idx != -1 and (tag_start == -1 or idx < tag_start):
                        tag_start = idx

                if tag_start != -1:
                    clean_prefix = self.buffer[:tag_start]
                    if clean_prefix and self.queue:
                        await self.queue.put(("token", clean_prefix))
                    self.buffer = self.buffer[tag_start:]
                    self.inside_thought = True
                else:
                    # If buffer ends with an unclosed '<', hold trailing characters
                    last_lt = self.buffer.rfind("<")
                    if last_lt != -1 and len(self.buffer) - last_lt < 12:
                        to_emit = self.buffer[:last_lt]
                        self.buffer = self.buffer[last_lt:]
                    else:
                        to_emit = self.buffer
                        self.buffer = ""

                    if to_emit and self.queue:
                        await self.queue.put(("token", to_emit))
                    break

    async def flush(self):
        """Flushes any remaining clean text at the end of stream."""
        if self.suppress_all:
            return
        if not self.inside_thought and self.buffer and self.queue:
            buf_lower = self.buffer.lower()
            if "<tool_call" not in buf_lower and "<thought" not in buf_lower and "<thinking" not in buf_lower:
                await self.queue.put(("token", self.buffer))
        self.buffer = ""


async def agent_node(state: AgentState, config: RunnableConfig = None) -> dict[str, Any]:
    """
    Executes the LLM generation step:
    - Decoupled model resolution via get_async_openai_client("agent")
    - Real-time token streaming with 0ms artificial delay
    - Streaming thought sanitization & tool suppression
    - Gathers tool calls (native OpenAI tool_calls and balanced XML fallback)
    """
    cfg = (config or {}).get("configurable", {})
    queue: asyncio.Queue = cfg.get("queue")
    stop_event = cfg.get("stop_event")

    messages = state["messages"]
    attached = state.get("attached_files", {})
    thread_id = cfg.get("thread_id", "default")
    client, model = get_async_openai_client(role="agent")

    # Step 1: Dynamic Context Pruning (dead-ends, bulky outputs, low-relevance turns)
    pruned_messages = default_pruner.prune_context(messages, model=model)

    # Step 2: Hierarchical Subtree Summarization (compacts older ancestor blocks)
    compacted_messages = await hierarchical_summarizer.compact_ancestor_history(
        pruned_messages,
        thread_id=thread_id,
        attached_files=attached
    )

    # Step 3: Exact BPE Token Accounting & Savings Calculation
    raw_tok, pruned_tok, savings = calculate_token_savings(messages, compacted_messages, model=model)
    if queue and savings > 0:
        await queue.put(("token_savings", (raw_tok, pruned_tok, savings)))

    # Step 4: Strict Gemma Turn Alternation & Role Coalescing
    contents = build_model_contents(compacted_messages, attached)
    tool_specs = convert_tools_to_openai_specs(ALL_TOOLS)

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
    stream_filter = StreamingThoughtFilter(queue=queue)

    try:
        response_stream = await client.chat.completions.create(
            model=model,
            messages=contents,
            tools=tool_specs if tool_specs else None,
            stream=True,
        )
    except Exception as exc:
        err_str = str(exc)
        if "tools" in err_str.lower() or "unsupported" in err_str.lower():
            try:
                response_stream = await client.chat.completions.create(
                    model=model,
                    messages=contents,
                    stream=True,
                )
            except Exception as inner_exc:
                err_msg = f"[API Error]: {inner_exc}"
                if queue:
                    await queue.put(("error", err_msg))
                return {
                    "messages": [AIMessage(content=err_msg)],
                    "iteration": state.get("iteration", 0) + 1
                }
        else:
            err_msg = f"[API Error]: {exc}"
            if queue:
                await queue.put(("error", err_msg))
            return {
                "messages": [AIMessage(content=err_msg)],
                "iteration": state.get("iteration", 0) + 1
            }

    try:
        async for chunk in response_stream:
            if stop_event and stop_event.is_set():
                try:
                    await response_stream.close()
                except Exception:
                    pass
                break

            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue

            delta = choice.delta
            if delta.tool_calls:
                stream_filter.mark_tool_call_detected()
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

            if delta.content:
                full_content += delta.content
                await stream_filter.feed(delta.content)
    except Exception as exc:
        err_msg = f"[Streaming Error]: {exc}"
        if queue:
            await queue.put(("error", err_msg))

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
                parsed_args = {}
        parsed_tool_calls.append({
            "name": name,
            "args": parsed_args if isinstance(parsed_args, dict) else {},
            "id": raw_tc["id"]
        })

    # If no native tool calls, inspect content with balanced bracket XML fallback parser
    if not parsed_tool_calls and full_content:
        xml_calls = _parse_fallback_tool_xml(full_content)
        if xml_calls:
            parsed_tool_calls = xml_calls
            stream_filter.mark_tool_call_detected()

    clean_content = _strip_thoughts(full_content)

    # If no tool calls were made, flush remaining tokens to queue
    if not parsed_tool_calls:
        await stream_filter.flush()

    ai_msg = AIMessage(
        content=clean_content,
        tool_calls=parsed_tool_calls if parsed_tool_calls else []
    )

    return {
        "messages": [ai_msg],
        "iteration": state.get("iteration", 0) + 1
    }
