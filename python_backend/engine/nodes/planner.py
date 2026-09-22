import re
import json
import asyncio
from typing import Any
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import HumanMessage
from engine.state import AgentState
from engine.utils import get_async_openai_client


def _decompose_prompt_to_plan(prompt: str, attached_files: dict[str, str] = None) -> list[str] | None:
    """
    Deconstructs user prompt into actionable steps dynamically without static stubbing.
    Detects numbered lists, bullet points, and sequential conjunctions.
    """
    text = prompt.strip()
    if not text:
        return None

    # Check for numbered list (e.g. 1. ... 2. ...)
    numbered_items = re.findall(r'(?:^|\n)\s*\d+[\.\)]\s*([^\n]+)', text)
    if len(numbered_items) >= 2:
        return [item.strip() for item in numbered_items if item.strip()]

    # Check for bullet items (- ... or * ...)
    bullet_items = re.findall(r'(?:^|\n)\s*[\-\*]\s*([^\n]+)', text)
    if len(bullet_items) >= 2:
        return [item.strip() for item in bullet_items if item.strip()]

    # Check for sequential conjunctions
    pattern = re.compile(
        r'\b(?:and\s+then|after\s+that|then|next|first|finally|secondly|thirdly)\b',
        re.IGNORECASE
    )
    if pattern.search(text):
        raw_parts = pattern.split(text)
        cleaned = []
        for part in raw_parts:
            s = part.strip().strip(",;:-")
            s = re.sub(r'^(?:and|also|now|then|afterwards)\s+', '', s, flags=re.IGNORECASE).strip()
            if len(s) > 3 and not s.lower().startswith("please"):
                cleaned.append(s[0].upper() + s[1:])
        if len(cleaned) >= 2:
            return cleaned

    # If documents are attached and query is analytical/research
    if attached_files and any(w in text.lower() for w in ("analyze", "review", "summarize", "find", "check")):
        filenames = ", ".join(list(attached_files.keys())[:3])
        return [
            f"Search relevant passages in attached files ({filenames})",
            "Evaluate extracted context and formulate solution",
            "Synthesize verified response"
        ]

    return None


async def _generate_llm_plan(prompt: str, attached_files: dict[str, str] = None) -> list[str] | None:
    """
    Invokes the decoupled lightweight planner model (MODEL_PLANNER) to deconstruct
    complex user objectives into actionable milestones.
    """
    text = prompt.strip()
    if not text or len(text) < 15:
        return None

    try:
        client, model = get_async_openai_client(role="planner")

        system_prompt = (
            "You are a fast task-planning module for an autonomous desktop agent. "
            "Analyze the user's objective and any referenced files. "
            "If the request is a multi-step objective or involves actions/tools, decompose it into 2 to 5 concise sequential milestones. "
            "Return ONLY a valid JSON array of step descriptions, for example: [\"1. Search files\", \"2. Analyze findings\"]. "
            "If the request is a simple, direct conversational question (e.g. 'hi', 'what is 2+2?'), return []."
        )

        user_content = text
        if attached_files:
            file_list = ", ".join(list(attached_files.keys())[:5])
            user_content += f"\n\n[Attached Knowledge Files: {file_list}]"

        # Cap timeout to avoid blocking turn start
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.0,
                max_tokens=256,
            ),
            timeout=3.0
        )
        content = (response.choices[0].message.content or "").strip()
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed) and len(parsed) >= 2:
                return [s.strip() for s in parsed if s.strip()]
    except Exception:
        pass
    return None


async def planner_node(state: AgentState, config: RunnableConfig = None) -> dict[str, Any]:
    """
    Initializes execution cycle with minimal context slicing:
    - Slices root user prompt & current user query
    - Generates dynamic plan milestones without unnecessary LLM latency
    - Sets state iteration to 0
    """
    cfg = (config or {}).get("configurable", {})
    queue = cfg.get("queue")
    stop_event = cfg.get("stop_event")

    if stop_event and stop_event.is_set():
        return {"iteration": 0, "is_streaming": False}

    messages = state.get("messages", [])
    attached = state.get("attached_files") or {}

    # Context Slicing: Only inspect latest user prompt
    last_user_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_msg = str(msg.content)
            break

    # 1. Fast heuristic: If user already provided an explicit numbered or bulleted list
    plan = _decompose_prompt_to_plan(last_user_msg, attached)

    # 2. If no explicit list in prompt, invoke decoupled planner model (MODEL_PLANNER)
    if not plan and last_user_msg:
        plan = await _generate_llm_plan(last_user_msg, attached)

    if queue:
        if plan:
            summary_preview = " -> ".join(plan[:3])
            if len(plan) > 3:
                summary_preview += f" (+{len(plan) - 3} more)"
            await queue.put(("status", f"Plan ({len(plan)} steps): {summary_preview}"))
        else:
            await queue.put(("status", "Analyzing request..."))

    return {
        "iteration": state.get("iteration", 0),
        "plan": plan,
        "is_streaming": False
    }

