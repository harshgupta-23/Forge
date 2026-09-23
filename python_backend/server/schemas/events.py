"""
events.py — Pydantic discriminated union schemas for WebSocket message contracts.
"""

from typing import Literal, Union, Optional, Any, Annotated
from pydantic import BaseModel, Field


class BaseInboundEvent(BaseModel):
    model_config = {"extra": "ignore"}


class GetConfigEvent(BaseInboundEvent):
    type: Literal["get_config"]


class SaveConfigEvent(BaseInboundEvent):
    type: Literal["save_config"]
    data: dict[str, Any] = Field(default_factory=dict)


class UserMessageEvent(BaseInboundEvent):
    type: Literal["user_message"]
    content: str


class StopGenerationEvent(BaseInboundEvent):
    type: Literal["stop_generation"]


class SetActiveEvent(BaseInboundEvent):
    type: Literal["set_active"]
    content: Optional[str] = None
    data: Optional[str] = None


class SetLabelData(BaseModel):
    node_id: str
    label: Optional[str] = None


class SetLabelEvent(BaseInboundEvent):
    type: Literal["set_label"]
    data: SetLabelData


class UndoEvent(BaseInboundEvent):
    type: Literal["undo"]
    data: Optional[Union[dict[str, Any], str]] = None
    node_id: Optional[str] = None
    content: Optional[str] = None


class SummariseEvent(BaseInboundEvent):
    type: Literal["summarise"]


class ClearEvent(BaseInboundEvent):
    type: Literal["clear"]


class ListSessionsEvent(BaseInboundEvent):
    type: Literal["list_sessions"]


class LoadSessionEvent(BaseInboundEvent):
    type: Literal["load_session"]
    data: Optional[dict[str, Any]] = None
    content: Optional[str] = None


class SaveSessionEvent(BaseInboundEvent):
    type: Literal["save_session"]
    content: str = ""
    filename: Optional[str] = None


class AttachFileEvent(BaseInboundEvent):
    type: Literal["attach_file"]
    name: str
    path: str


class GetTokenUsageEvent(BaseInboundEvent):
    type: Literal["get_token_usage"]


class ShutdownEvent(BaseInboundEvent):
    type: Literal["shutdown"]


class BranchDecisionEvent(BaseInboundEvent):
    type: Literal["branch_decision"]
    decision: Literal["branch", "continue"]


class RenameSessionData(BaseModel):
    model_config = {"extra": "ignore"}
    session_id: str
    label: str = ""


class RenameSessionEvent(BaseInboundEvent):
    type: Literal["rename_session"]
    data: RenameSessionData


class DeleteSessionData(BaseModel):
    model_config = {"extra": "ignore"}
    session_id: str


class DeleteSessionEvent(BaseInboundEvent):
    type: Literal["delete_session"]
    data: DeleteSessionData


# Discriminated union for incoming WebSocket frames
InboundEvent = Annotated[
    Union[
        GetConfigEvent,
        SaveConfigEvent,
        UserMessageEvent,
        StopGenerationEvent,
        SetActiveEvent,
        SetLabelEvent,
        UndoEvent,
        SummariseEvent,
        ClearEvent,
        ListSessionsEvent,
        LoadSessionEvent,
        SaveSessionEvent,
        AttachFileEvent,
        GetTokenUsageEvent,
        ShutdownEvent,
        BranchDecisionEvent,
        RenameSessionEvent,
        DeleteSessionEvent,
    ],
    Field(discriminator="type")
]


# ── Outbound payload models (exact legacy frontend keys) ──────────────────────

class BranchPromptOutbound(BaseModel):
    model_config = {"extra": "ignore"}
    type: Literal["branch_prompt"] = "branch_prompt"
    topic: str = ""
    reason: str = ""
    user_text: str = ""


class ConfigOutbound(BaseModel):
    type: Literal["config"] = "config"
    data: dict[str, Any]


class ChatHistoryOutbound(BaseModel):
    type: Literal["chat_history"] = "chat_history"
    messages: list[dict[str, Any]]
    active_node_id: str


class TreeDataOutbound(BaseModel):
    type: Literal["tree_data"] = "tree_data"
    session_id: str
    root_id: str
    active_node_id: str
    nodes: dict[str, Any]


class NodeAddedOutbound(BaseModel):
    model_config = {"extra": "ignore"}
    type: Literal["node_added"] = "node_added"
    session_id: str
    node: dict[str, Any]
    active_node_id: str


class StatusOutbound(BaseModel):
    type: Literal["status"] = "status"
    content: str


class TokenOutbound(BaseModel):
    type: Literal["token"] = "token"
    content: str


class ToolStartOutbound(BaseModel):
    type: Literal["tool_start"] = "tool_start"
    content: str


class ToolDoneOutbound(BaseModel):
    model_config = {"extra": "ignore"}
    type: Literal["tool_done"] = "tool_done"
    content: str
    tokens: Optional[int] = None


class DoneOutbound(BaseModel):
    type: Literal["done"] = "done"


class ErrorOutbound(BaseModel):
    type: Literal["error"] = "error"
    content: str


class TokenBreakdown(BaseModel):
    model_config = {"extra": "ignore"}
    user: int = 0
    tools: int = 0
    agent: int = 0
    turn_total: int = 0
    context_total: int = 0
    pruned_savings: int = 0


class TokenCountOutbound(BaseModel):
    model_config = {"extra": "ignore"}
    type: Literal["token_count"] = "token_count"
    content: int
    breakdown: Optional[TokenBreakdown] = None


class TokenUsageWindowsOutbound(BaseModel):
    type: Literal["token_usage_windows"] = "token_usage_windows"
    last_5h: int
    last_24h: int


class SessionListOutbound(BaseModel):
    type: Literal["session_list"] = "session_list"
    sessions: list[dict[str, Any]]


class SummarisedOutbound(BaseModel):
    type: Literal["summarised"] = "summarised"
    content: str


class IndexingProgressOutbound(BaseModel):
    model_config = {"extra": "ignore"}
    type: Literal["indexing_progress"] = "indexing_progress"
    filename: str
    step: Literal["parsing", "embedding", "indexed", "error"]
    progress_pct: int
    chunks_count: int
    message: str

