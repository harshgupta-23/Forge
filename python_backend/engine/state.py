"""
state.py — LangGraph Agent State definition.
"""
from typing import Annotated, Optional, Any
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Core state tracked across LangGraph execution cycles."""
    messages: Annotated[list[BaseMessage], add_messages]
    attached_files: dict[str, str]
    plan: Optional[list[str]]
    iteration: int
    is_streaming: bool
    warned_signatures: Optional[list[str]]
    recovery_count: Optional[int]
    topic_info: Optional[dict[str, Any]]
    skip_topic_gate: Optional[bool]

