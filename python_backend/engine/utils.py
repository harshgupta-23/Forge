"""
utils.py — Helper functions for message conversion, prompt formatting,
token counting, thinking-block sanitization, and model clients.
"""

import os
import re
from urllib.parse import urlparse, urlunparse
from typing import Any
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from openai import OpenAI

_THOUGHT_RE = re.compile(
    r'<thought>.*?</thought>|<thinking>.*?</thinking>',
    re.DOTALL | re.IGNORECASE
)


def _strip_thoughts(text: str) -> str:
    """Removes model thinking/reasoning tags before streaming or display."""
    if not text:
        return ""
    return _THOUGHT_RE.sub('', text).strip()


SYSTEM_PROMPT = """You are an autonomous local-PC execution agent with full Python code execution and file management powers.

For simple factual questions just answer directly. Only call tools when the task genuinely requires running code or touching files.

Available capabilities:
- run_local_python_script(script_code: str): Executes Python script strings locally via subprocess.
- pip_install(packages: str): Installs Python packages into isolated user environment at runtime.
- read_file(file_path: str): Reads a file from disk and returns its contents (path protected).
- write_file(file_path: str, content: str): Writes content to a file on disk (path protected).
- copy_file(source_path: str, destination_path: str): Copies a file from one path to another.
- list_directory(directory_path: str): Lists files and folders in a directory.
- get_environment_info(query: str): Returns system info — OS, Python version, environment variables.
- web_search(query: str, max_results: int): DuckDuckGo search, returns titles/URLs/snippets.
- semantic_search(query: str, top_k: int): Hybrid vector + full-text search with cross-encoder reranking over attached knowledge files.
- read_clipboard(): Reads the current clipboard contents.
- write_clipboard(text: str): Writes text to the clipboard.
- take_screenshot(filename: str): Captures a screenshot and saves it to the working directory.
- browser_action(instructions: str): Full browser automation via Playwright.

Rules:
- Scripts must be complete with all imports. Use absolute paths inside scripts.
- If STDERR has ModuleNotFoundError: pip_install then re-run immediately.
- Before editing any file: copy_file to .bak first.
- For ANY web search, online research, looking up articles, documentation, facts, current events, weather, or news: ALWAYS use web_search. It is fast, direct, and executes in the background. Do NOT use browser_action for web search queries.
- Use browser_action ONLY when genuine browser DOM interaction is required (filling forms, clicking website buttons, downloading files). It runs headlessly in the background and terminates automatically when done.
- When documents or code files are attached, prioritize semantic_search to retrieve relevant snippets, functions, or sections instead of reading entire files with read_file.
- Use read_clipboard when user says "fix this", "use what I copied", or "from clipboard".
- Use write_clipboard to deliver corrected code or results the user will paste elsewhere.
- Use take_screenshot when user says "look at my screen", "screenshot", or "what do I see".
- State what was produced and where it was saved when done.
"""

_WORK_DIR = os.environ.get("AGENT_WORK_DIR", "")
if _WORK_DIR:
    SYSTEM_PROMPT += f"\n\nDEFAULT OUTPUT DIRECTORY: {_WORK_DIR}\nSave all output files here unless told otherwise."


def get_openai_client() -> tuple[OpenAI, str]:
    """
    Constructs OpenAI client configuring Google AI Studio query param keys,
    OpenRouter metadata, or standard OpenAI-compatible endpoints.
    Returns (client, model_name).
    """
    base_url = os.environ.get("API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai/").strip()
    api_key = os.environ.get("API_KEY", "").strip()
    model = os.environ.get("MODEL", "gemma-4-26b-a4b-it").strip()

    if not api_key:
        raise RuntimeError(
            "CRITICAL: API_KEY is missing or blank. Please open Settings in the UI to add your API key."
        )

    parsed_url = urlparse(base_url)
    is_google = "generativelanguage.googleapis.com" in (parsed_url.netloc or parsed_url.path)

    if is_google:
        clean_path = parsed_url.path.rstrip("/")
        new_query = f"key={api_key}"
        base_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            clean_path,
            parsed_url.params,
            new_query,
            parsed_url.fragment
        ))
        sdk_key = "ignored-by-google-via-query-param"
        extra_headers = {}
    else:
        sdk_key = api_key
        extra_headers = {}
        if "openrouter.ai" in parsed_url.netloc:
            extra_headers = {
                "HTTP-Referer": "http://localhost:8765",
                "X-Title": "Forge Agent",
            }

    client = OpenAI(
        base_url=base_url,
        api_key=sdk_key,
        default_headers=extra_headers,
    )
    return client, model


def build_model_contents(messages: list[BaseMessage], attached_files: dict[str, str]) -> list[dict[str, Any]]:
    """
    Converts LangChain messages to OpenAI/Gemma message sequence.
    
    Critical Gemma / Google AI Studio rule:
    Enforces strict role alternation (system -> user -> assistant -> user ...).
    Consecutive messages of the same role (including multiple ToolMessages)
    are merged into a single turn so the API never sees two back-to-back same-role messages.
    """
    file_note = ""
    if attached_files:
        lines = ["[Attached files indexed in vector store (use semantic_search for targeted retrieval):]"]
        for name, path in attached_files.items():
            lines.append(f"  {name} → {path}")
        file_note = "\n".join(lines) + "\n\n"

    raw: list[dict[str, Any]] = []
    raw.append({"role": "system", "content": SYSTEM_PROMPT})

    first_user = True
    for msg in messages:
        if isinstance(msg, HumanMessage):
            text = (file_note + msg.content) if first_user and file_note else msg.content
            first_user = False
            raw.append({"role": "user", "content": text})

        elif isinstance(msg, AIMessage):
            content = msg.content or ""
            # If tool calls were generated, preserve them or content
            raw.append({"role": "assistant", "content": content or " "})

        elif isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "tool")
            content = str(msg.content)
            # Map tool results to user role with informative prefix
            raw.append({
                "role": "user",
                "content": f"[TOOL RESULT: {name}]\n{content}"
            })

    # Coalesce consecutive same-role turns
    contents: list[dict[str, Any]] = []
    for entry in raw:
        if contents and contents[-1]["role"] == entry["role"]:
            sep = "\n\n" if entry["role"] == "user" else "\n"
            contents[-1] = {
                "role": entry["role"],
                "content": contents[-1]["content"] + sep + entry["content"],
            }
        else:
            contents.append(dict(entry))

    # Ensure sequence after system starts with "user"
    non_sys = [m for m in contents if m["role"] != "system"]
    if non_sys and non_sys[0]["role"] == "assistant":
        sys_part = [m for m in contents if m["role"] == "system"]
        contents = sys_part + [{"role": "user", "content": "[start]"}] + non_sys

    return contents


def estimate_tokens(text: Any) -> int:
    """Estimates tokens for text (~4 chars/token, min 1 if not empty)."""
    if text is None:
        return 0
    s = str(text).strip()
    return max(1, len(s) // 4) if s else 0


def message_tokens(msg: BaseMessage) -> int:
    """Estimates tokens for a single BaseMessage including content and tool calls."""
    tokens = estimate_tokens(getattr(msg, "content", ""))
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            tokens += estimate_tokens(tc.get("name", "")) + estimate_tokens(str(tc.get("args", "")))
    return tokens


def count_tokens(messages: list[BaseMessage]) -> int:
    """Token estimation across system prompt and active messages (~4 chars/token)."""
    total_chars = len(SYSTEM_PROMPT)
    for msg in messages:
        total_chars += len(str(getattr(msg, "content", "")))
    return total_chars // 4


def summarise_history(messages: list[BaseMessage], attached_files: dict[str, str]) -> list[BaseMessage]:
    """
    Compresses conversation history into a concise summary while retaining
    the last 2 turns verbatim.
    """
    if len(messages) <= 4:
        return messages

    keep_tail = messages[-4:]
    to_compress = messages[:-4]

    transcript_lines = [
        "Summarise this conversation history concisely.\n",
        "Capture: key tasks done, files created/edited, errors fixed, ",
        "important outputs and paths. Be factual and brief.\n\n",
        "HISTORY TO SUMMARISE:\n"
    ]
    for msg in to_compress:
        if isinstance(msg, HumanMessage):
            transcript_lines.append(f"USER: {msg.content[:500]}")
        elif isinstance(msg, AIMessage):
            transcript_lines.append(f"ASSISTANT: {msg.content[:500]}")
        elif isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "tool")
            transcript_lines.append(f"TOOL({name}): {str(msg.content)[:300]}")

    summary_prompt = "\n".join(transcript_lines)
    client, model = get_openai_client()
    contents = build_model_contents([HumanMessage(content=summary_prompt)], attached_files)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=contents
        )
        summary_text = _strip_thoughts(response.choices[0].message.content or "")
    except Exception as exc:
        summary_text = f"[Summary generation error: {exc}]"

    compressed = [
        HumanMessage(content="[Previous session summary — treat as background context]"),
        AIMessage(content=summary_text),
    ] + list(keep_tail)

    return compressed


def convert_tools_to_openai_specs(tools: list) -> list[dict[str, Any]]:
    """
    Converts LangChain tool instances into OpenAI function calling schemas.
    """
    specs = []
    for t in tools:
        schema: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": t.name,
                "description": (t.description or "").strip(),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
        if hasattr(t, "args") and isinstance(t.args, dict):
            props = {}
            required = []
            for arg_name, arg_info in t.args.items():
                arg_type = arg_info.get("type", "string")
                arg_desc = arg_info.get("description", "")
                props[arg_name] = {"type": arg_type, "description": arg_desc}
                if arg_info.get("required", False):
                    required.append(arg_name)
            schema["function"]["parameters"]["properties"] = props
            schema["function"]["parameters"]["required"] = required
        elif hasattr(t, "get_input_schema"):
            try:
                schema["function"]["parameters"] = t.get_input_schema().model_json_schema()
            except Exception:
                pass

        specs.append(schema)
    return specs

