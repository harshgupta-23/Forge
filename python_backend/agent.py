"""
agent.py — LangGraph autonomous agent (API backend)
"""

import os
import re
import json
import shutil
from typing import Annotated
from typing_extensions import TypedDict
import re as _re

_THOUGHT_RE = _re.compile(
    r'<thought>.*?</thought>|<thinking>.*?</thinking>',
    _re.DOTALL | _re.IGNORECASE
)
def _strip_thoughts(text: str) -> str:
    return _THOUGHT_RE.sub('', text).strip()

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

from langchain_core.messages import (
    HumanMessage, AIMessage, ToolMessage
)
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from tools import ALL_TOOLS

# ─── Configuration ────────────────────────────────────────────────────────────

API_KEY = os.environ.get("API_KEY", "")
MODEL   = os.environ.get("MODEL", "gemini-2.0-flash")
_WORK_DIR      = os.environ.get("AGENT_WORK_DIR", "")

# ─── State ────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    attached_files: dict[str, str]

# ─── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an autonomous local-PC execution agent with full Python code execution and file management powers.

For simple factual questions just answer directly. Only call tools when the task genuinely requires running code or touching files.

TOOL CALLING FORMAT — use this exact format when you need a tool:

<tool_call>
{
  "name": "tool_name",
  "args": { "param": "value" }
}
</tool_call>

Available tools:
- run_local_python_script(script_code: str)
- pip_install(packages: str)
- read_file(file_path: str)
- write_file(file_path: str, content: str)
- copy_file(source_path: str, destination_path: str)
- list_directory(directory_path: str)
- get_environment_info(query: str)
- web_search(query: str, max_results: int)     — DuckDuckGo search, returns titles/URLs/snippets
- read_clipboard()                              — read current clipboard text
- write_clipboard(text: str)                   — write text to clipboard
- take_screenshot(filename: str)               — screenshot saved to SCREENSHOT_DIR
- browser_action(instructions: str)            — browser automation; pass plain-English steps
                                                 e.g. "Go to https://youtube.com and search for lo-fi"
                                                 e.g. "Open https://site.com, fill Name=John, click Submit"
                                                 e.g. "Go to https://news.ycombinator.com, return top 10 titles"

Rules:
- Scripts must be complete with all imports. Use absolute paths inside scripts.
- If STDERR has ModuleNotFoundError: pip_install then re-run immediately.
- Before editing any file: copy_file to .bak first.
- For code correction: read_file → fix → write_file.
- For Word docs: python-docx. For PDFs: reportlab.
- Use web_search for live data: prices, news, weather, recent events. Do NOT use LLM knowledge for things that change.
- Use browser_action for anything requiring actual browser interaction: YouTube search, form filling, downloading files, scraping JS-heavy pages. Always include the full URL in instructions, e.g. "Go to https://youtube.com and search for X" not just "search youtube for X". For YouTube searches use: "Go to https://youtube.com and search for X".
- Use read_clipboard when user says "fix this", "use what I copied", or "from clipboard".
- Use write_clipboard to deliver corrected code or results the user will paste elsewhere.
- Use take_screenshot when user says "look at my screen", "screenshot", or "what do I see".
- State what was produced and where it was saved when done.
"""

if _WORK_DIR:
    SYSTEM_PROMPT += f"\n\nDEFAULT OUTPUT DIRECTORY: {_WORK_DIR}\nSave all output files here unless told otherwise."


def _get_client():
    from openai import OpenAI
    from urllib.parse import urlparse, urlunparse

    # 1. Grab environment variables with clean default fallbacks
    base_url = os.environ.get("API_BASE", "https://openrouter.ai/api/v1").strip()
    api_key = os.environ.get("API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "CRITICAL: API_KEY environment variable is missing or blank.\n"
            "Double-check your configuration values."
        )

    # 2. Check if the target host is Google's OpenAI compatibility layer
    parsed_url = urlparse(base_url)
    is_google = "generativelanguage.googleapis.com" in (parsed_url.netloc or parsed_url.path)

    if is_google:
        # Google AI Studio OpenAI shim requires the key appended directly inside the URL query string.
        # Format string becomes: https://generativelanguage.googleapis.com/v1beta/openai?key=AIzaSy...
        
        # Clean the path to prevent double slashes before adding query params
        clean_path = parsed_url.path.rstrip("/")
        
        # Build the new URL injecting the key parameter cleanly
        new_query = f"key={api_key}"
        base_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            clean_path,
            parsed_url.params,
            new_query,
            parsed_url.fragment
        ))
        
        # The OpenAI SDK throws an validation error if api_key is empty. 
        # Pass a dummy string; Google ignores the Bearer header entirely when the query param is set.
        sdk_key = "ignored-by-google-via-query-param"
        extra_headers = {}
    else:
        # Standard OpenAI-compliant providers (OpenRouter, Groq, Together, Ollama)
        sdk_key = api_key
        extra_headers = {}
        
        # Add openrouter metadata helpers if matching
        if "openrouter.ai" in parsed_url.netloc:
            extra_headers = {
                "HTTP-Referer": "http://localhost:8765",
                "X-Title": "Forge Agent",
            }

    return OpenAI(
        base_url=base_url,
        api_key=sdk_key,
        default_headers=extra_headers,
    )


def _build_contents(messages: list, attached_files: dict) -> list:
    """Convert LangGraph messages to standard OpenAI/Gemma format.

    Gemma 4 enforces strict role alternation (system → user → assistant → user …).
    Consecutive messages with the same role are merged into one so the API
    never sees two user or two assistant turns back-to-back.
    """

    file_note = ""
    if attached_files:
        lines = ["[Attached files available via read_file tool:]"]
        for name, path in attached_files.items():
            lines.append(f"  {name} → {path}")
        file_note = "\n".join(lines) + "\n\n"

    raw = []

    # System prompt always goes first — Gemma honours it here
    raw.append({"role": "system", "content": SYSTEM_PROMPT})

    first_user = True
    for msg in messages:
        if isinstance(msg, HumanMessage):
            text = (file_note + msg.content) if first_user and file_note else msg.content
            first_user = False
            raw.append({"role": "user", "content": text})

        elif isinstance(msg, AIMessage):
            raw.append({"role": "assistant", "content": msg.content or " "})

        elif isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "tool")
            raw.append({"role": "user", "content": f"[TOOL RESULT: {name}]\n{msg.content}"})

    # ── Merge consecutive same-role turns (Gemma4 strict alternation) ──────
    contents: list = []
    for entry in raw:
        if contents and contents[-1]["role"] == entry["role"]:
            # Append to the previous message with a separator
            sep = "\n\n" if entry["role"] == "user" else "\n"
            contents[-1] = {
                "role": entry["role"],
                "content": contents[-1]["content"] + sep + entry["content"],
            }
        else:
            contents.append(dict(entry))

    # ── Gemma requires the turn sequence after system to start with "user" ─
    # If somehow the first non-system message is "assistant", prepend a dummy.
    non_sys = [m for m in contents if m["role"] != "system"]
    if non_sys and non_sys[0]["role"] == "assistant":
        sys_part = [m for m in contents if m["role"] == "system"]
        contents = sys_part + [{"role": "user", "content": "[start]"}] + non_sys

    return contents


def _call(messages: list, attached_files: dict) -> str:
    client   = _get_client()
    contents = _build_contents(messages, attached_files)
    try:
        response = client.chat.completions.create(
            model=os.environ.get("MODEL", "gemini-2.0-flash"),
            messages=contents
        )
        return _strip_thoughts(response.choices[0].message.content)
    except Exception as exc:
        return f"[API error]: {exc}"


def _stream(messages: list, attached_files: dict, stop_event=None):
    client   = _get_client()
    contents = _build_contents(messages, attached_files)
    full_text = ""
    stream = None
    try:
        # Buffer full response so <thought> blocks can be stripped cleanly
        stream = client.chat.completions.create(
            model=os.environ.get("MODEL", "gemini-2.0-flash"),
            messages=contents,
            stream=True
        )
        for chunk in stream:
            # Check for cancellation on every chunk, not just after the
            # whole response has already been downloaded — otherwise Stop
            # has no effect until the model finishes generating anyway.
            if stop_event and stop_event.is_set():
                try:
                    stream.close()
                except Exception:
                    pass
                break
            token = chunk.choices[0].delta.content
            if token:
                full_text += token
    except Exception as exc:
        yield f"[API error]: {exc}"
        return

    # Strip thought blocks then yield word-by-word for streaming feel
    words = _strip_thoughts(full_text).split(' ')
    for i, word in enumerate(words):
        if stop_event and stop_event.is_set():
            return
        yield word + ('' if i == len(words) - 1 else ' ')

# ─── Tool parsing ─────────────────────────────────────────────────────────────

_TOOL_RE = re.compile(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', re.DOTALL)

def _parse_tools(text: str) -> list[dict] | None:
    calls = []
    for m in _TOOL_RE.findall(text):
        try:
            calls.append(json.loads(m))
        except json.JSONDecodeError:
            pass
    return calls or None


def _run_tool(tc: dict) -> str:
    name     = tc.get("name", "")
    args     = tc.get("args", {})
    tool_map = {t.name: t for t in ALL_TOOLS}
    if name not in tool_map:
        return f"[Error]: Unknown tool '{name}'"
    try:
        return tool_map[name].invoke(args)
    except Exception as exc:
        return f"[Tool error in {name}]: {exc}"

# ─── Agent node ───────────────────────────────────────────────────────────────

def agent_node(state: AgentState) -> dict:
    messages = list(state["messages"])
    attached = state.get("attached_files", {})

    for _ in range(10):
        response = _call(messages, attached)
        tools    = _parse_tools(response)

        if not tools:
            return {"messages": [AIMessage(content=response)]}

        messages.append(AIMessage(content=response))
        for tc in tools:
            result = _run_tool(tc)
            messages.append(ToolMessage(
                content=result,
                tool_call_id=tc.get("name", "tool"),
                name=tc.get("name", "tool"),
            ))

    return {"messages": [AIMessage(content="[Agent] Max tool rounds reached.")]}

# ─── Graph ────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.set_entry_point("agent")
    graph.add_edge("agent", END)
    return graph.compile()

app = build_graph()

# ─── Streaming helper (used by main.py) ───────────────────────────────────────

def stream_final_response(state: dict, stop_event=None):
    """
    Runs tool loop, emits live status lines while tools execute,
    then streams the final answer token-by-token.

    Yields:
        ("status", str)     — live one-liner while waiting (replaces itself)
        ("tool_start", str) — tool about to run
        ("tool_done",  str) — tool finished with one-line result summary
        ("token",      str) — streaming token of final answer
        ("done",       list)— complete updated message list
    """
    import threading

    messages = list(state["messages"])
    attached = state.get("attached_files", {})

    for round_num in range(10):

        if stop_event and stop_event.is_set():
            yield ("cancelled", messages)
            return
        
        # ── Phase 1: call LLM (blocking) — show spinner while waiting ────────
        llm_result   = [None]
        llm_done_evt = threading.Event()

        def _call_llm():
            llm_result[0] = _call(messages, attached)
            llm_done_evt.set()

        t = threading.Thread(target=_call_llm, daemon=True)
        t.start()

        # Emit status ticks while LLM is thinking
        dots = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
        i = 0
        while not llm_done_evt.wait(timeout=0.12):
            if stop_event and stop_event.is_set():
                yield ("cancelled", messages)
                return
            yield ("status", f"\r\033[K{dots[i % len(dots)]}  Thinking…")
            i += 1
        yield ("status", "\r\033[K")   # clear the spinner line

        response = _strip_thoughts(llm_result[0]) if llm_result[0] else ""
        tools    = _parse_tools(response)

        if not tools:
            # ── Phase 2: stream final answer ─────────────────────────────────
            partial = ""
            for chunk in _stream(messages, attached, stop_event=stop_event):
                if stop_event and stop_event.is_set():
                    messages.append(AIMessage(content=partial.strip() or "[stopped before any output]"))
                    yield ("cancelled", messages)
                    return
                partial += chunk
                yield ("token", chunk)

            # _stream can also stop itself mid-way (closing the
            # network stream) and return early with no more chunks —
            # catch that case too so we don't fall through and treat a
            # cancelled response as a normal completed one.
            if stop_event and stop_event.is_set():
                messages.append(AIMessage(content=partial.strip() or "[stopped before any output]"))
                yield ("cancelled", messages)
                return
            messages.append(AIMessage(content=response))
            yield ("done", messages)
            return

        # ── Phase 3: execute tools with live status ───────────────────────────
        messages.append(AIMessage(content=response))
        for tc in tools:
            if stop_event and stop_event.is_set():
                yield ("cancelled", messages)
                return
            tool_name  = tc.get("name", "tool")
            args_short = _fmt_args(tc.get("args", {}))
            yield ("tool_start", f"⚙  {tool_name}({args_short})")

            # Run tool in thread, emit spinner ticks
            tool_result  = [None]
            tool_done    = threading.Event()

            def _run(tc=tc):
                tool_result[0] = _run_tool(tc)
                tool_done.set()

            tt = threading.Thread(target=_run, daemon=True)
            tt.start()

            i = 0
            while not tool_done.wait(timeout=0.15):
                if stop_event and stop_event.is_set():
                    yield ("cancelled", messages)
                    return
                yield ("status", f"\r\033[K  {dots[i % len(dots)]}  Running {tool_name}…")
                i += 1
            yield ("status", "\r\033[K")  # clear

            result = tool_result[0]
            # One-line summary: first non-empty line of result, max 80 chars
            summary = next(
                (ln.strip() for ln in result.splitlines() if ln.strip()), ""
            )[:80]
            yield ("tool_done", f"  ✓  {tool_name} → {summary}")

            messages.append(ToolMessage(
                content=result,
                tool_call_id=tool_name,
                name=tool_name,
            ))

    yield ("done", messages)


def _fmt_args(args: dict) -> str:
    parts = []
    for k, v in args.items():
        s = str(v)
        parts.append(f"{k}={s[:57] + '…' if len(s) > 60 else s!r}")
    return ", ".join(parts)


# ─── Token counter ────────────────────────────────────────────────────────────

def count_tokens(messages: list) -> int:
    """
    Rough token estimate for the current history.
    Uses ~4 chars per token as a conservative approximation.
    The real count includes the system prompt overhead (~500 tokens).
    """
    total_chars = len(SYSTEM_PROMPT)
    for msg in messages:
        total_chars += len(str(msg.content))
    return total_chars // 4


# ─── History summariser ───────────────────────────────────────────────────────

def summarise_history(messages: list, attached_files: dict) -> list:
    """
    Compress the conversation history into a single summary message.
    Keeps the last 2 turns verbatim for continuity.
    Returns a new shortened message list: [SummaryHuman, SummaryAI, *last_2_turns].
    """
    if len(messages) <= 4:
        return messages   # Nothing worth compressing

    # Keep last 2 full turns (up to 4 messages) verbatim
    keep_tail  = messages[-4:]
    to_compress = messages[:-4]

    # Build a plain-text transcript of the old turns
    transcript_lines = ["Summarise this conversation history concisely.\n",
                        "Capture: key tasks done, files created/edited, errors fixed, ",
                        "important outputs and paths. Be factual and brief.\n\n",
                        "HISTORY TO SUMMARISE:\n"]
    for msg in to_compress:
        if isinstance(msg, HumanMessage):
            transcript_lines.append(f"USER: {msg.content[:500]}")
        elif isinstance(msg, AIMessage):
            transcript_lines.append(f"ASSISTANT: {msg.content[:500]}")
        elif isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "tool")
            transcript_lines.append(f"TOOL({name}): {msg.content[:300]}")

    summary_prompt = "\n".join(transcript_lines)
    summary_text   = _call(
        [HumanMessage(content=summary_prompt)], attached_files
    )

    compressed = [
        HumanMessage(content="[Previous session summary — treat as background context]"),
        AIMessage(content=summary_text),
    ] + list(keep_tail)

    return compressed