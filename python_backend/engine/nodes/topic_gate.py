"""
topic_gate.py — Analyzes topic continuity between user turns using a decoupled
lightweight LLM (MODEL_TOPIC_GATE / MODEL_PLANNER), detecting conversational shifts
and gating branch creation.
"""

import json
import re
from typing import Any, Optional
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from engine.state import AgentState
from engine.utils import get_async_openai_client


def extract_text_content(content: Any) -> str:
    """
    Extracts text from plain strings or multimodal list-of-dicts content.
    Handles LangChain content structures like [{'type': 'text', 'text': '...'}].
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if "text" in item and isinstance(item["text"], str):
                    parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        if parts:
            return " ".join(parts)
    return str(content) if content is not None else ""


def parse_topic_shift_response(raw_text: str) -> dict[str, Any]:
    """
    Robustly parses the LLM output JSON:
    - Strips markdown code fences (```json ... ```)
    - Extracts JSON from surrounding preamble/commentary
    - Removes trailing commas in objects and arrays
    - Normalizes string boolean values ("true" / "false")
    - Applies safe defaults for missing keys
    """
    cleaned = (raw_text or "").strip()
    if not cleaned:
        raise ValueError("Empty response from LLM")

    # Strip markdown fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.IGNORECASE).strip()

    # Extract JSON block between first { and last } if surrounded by commentary
    match = re.search(r"\{[\s\S]*\}", cleaned)
    json_candidate = match.group(0) if match else cleaned

    # Strip trailing commas before closing braces/brackets
    json_candidate = re.sub(r",\s*([\}\]])", r"\1", json_candidate)

    data = json.loads(json_candidate)

    raw_is_related = data.get("is_related", True)
    if isinstance(raw_is_related, str):
        is_related = raw_is_related.strip().lower() not in ("false", "0", "no")
    else:
        is_related = bool(raw_is_related)

    return {
        "is_related": is_related,
        "topic": str(data.get("topic", "New Topic")).strip(),
        "reason": str(data.get("reason", "")).strip()
    }


async def evaluate_topic_shift(
    new_query: Any,
    previous_messages: list[BaseMessage]
) -> dict[str, Any]:
    """
    Evaluates whether new_query is topically related to the previous completed turn.
    Returns:
    {
        "is_related": bool,
        "topic": str,
        "reason": str
    }
    """
    query = extract_text_content(new_query).strip()
    if not query:
        return {"is_related": True, "topic": "", "reason": "Empty query"}

    # Find previous completed turn: the last AIMessage and the HumanMessage before it
    prev_user_text = ""
    prev_agent_text = ""

    last_ai_idx = -1
    for i in range(len(previous_messages) - 1, -1, -1):
        if isinstance(previous_messages[i], AIMessage):
            last_ai_idx = i
            prev_agent_text = extract_text_content(previous_messages[i].content)
            break

    if last_ai_idx >= 0:
        for i in range(last_ai_idx - 1, -1, -1):
            if isinstance(previous_messages[i], HumanMessage):
                prev_user_text = extract_text_content(previous_messages[i].content)
                break

    # If no prior conversation exists (first turn), it's always related
    if not prev_user_text and not prev_agent_text:
        return {"is_related": True, "topic": "", "reason": "First turn in conversation"}

    # Decoupled lightweight model invocation
    try:
        client, model = get_async_openai_client("topic_gate")

        # Truncate prompt context for fast, economical inference (strictly last turn only)
        p_user = prev_user_text[:300]
        p_agent = prev_agent_text[:400]
        q_user = query[:300]

        system_prompt = (
            "You are an expert conversation continuity and topic coherence analyzer.\n"
            "Evaluate whether the user's NEW QUERY is topically related to the PREVIOUS TURN, "
            "or represents an abrupt shift to an entirely new, unrelated topic.\n\n"
            "Rules:\n"
            "- If the new query is a follow-up, requests changes/clarifications, continues the task, "
            "or stays in the same domain/subject matter: is_related = true.\n"
            "- If the new query switches to a completely different task, domain, or subject matter "
            "(e.g., from coding a Python script to asking about cooking recipes or movie recommendations): is_related = false.\n"
            "- Respond with ONLY a JSON object in this format:\n"
            "{\"is_related\": true, \"topic\": \"Brief topic (2-4 words)\", \"reason\": \"1-sentence reason\"}"
        )

        user_content = (
            f"Previous Turn:\nUser: {p_user}\nAssistant: {p_agent}\n\n"
            f"New Query:\nUser: {q_user}"
        )

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.0,
            max_tokens=150,
            timeout=8.0
        )

        content = response.choices[0].message.content or ""
        res = parse_topic_shift_response(content)
        print(f"[topic_gate] LLM evaluated: is_related={res['is_related']}, topic='{res['topic']}', reason='{res['reason']}'")
        return res
    except Exception as exc:
        print(f"[topic_gate] evaluate_topic_shift notice/error: {exc}")
        # Non-blocking fallback: on timeout or parse error, safely presume continuity
        return {
            "is_related": True,
            "topic": "",
            "reason": f"Fallback due to evaluator notice: {exc}"
        }


async def topic_gate_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """
    LangGraph entry node for topic analysis and state enrichment.
    Emits branch prompt if topic shift is detected and halts downstream generation.
    """
    if state.get("skip_topic_gate"):
        return {"topic_info": {"is_related": True, "topic": "", "reason": "Explicitly skipped"}}

    messages = state.get("messages", [])
    if not messages:
        return {"topic_info": None}

    # Find the latest HumanMessage by reverse traversal
    last_human_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_human_idx = i
            break

    if last_human_idx == -1:
        return {"topic_info": None}

    prior_messages = messages[:last_human_idx]
    if not prior_messages:
        return {"topic_info": None}

    new_query = messages[last_human_idx].content
    analysis = await evaluate_topic_shift(new_query, prior_messages)

    # If topic shifted and a streaming queue is configured, signal the client immediately
    if analysis.get("is_related") is False and config:
        configurable = config.get("configurable", {}) if isinstance(config, dict) else getattr(config, "configurable", {})
        queue = configurable.get("queue") if isinstance(configurable, dict) else None
        if queue is not None:
            try:
                await queue.put(("branch_prompt", analysis))
            except Exception:
                pass

    return {"topic_info": analysis}
