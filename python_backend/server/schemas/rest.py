"""
rest.py — Pydantic schemas for FastAPI REST endpoints.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class ConfigModel(BaseModel):
    API_KEY: str = ""
    MODEL: str = "gemma-4-26b-a4b-it"
    MODEL_PLANNER: Optional[str] = ""
    MODEL_SUMMARIZER: Optional[str] = ""
    MODEL_RERANKER: Optional[str] = ""
    API_BASE: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    API_KEY_PLANNER: Optional[str] = ""
    API_KEY_SUMMARIZER: Optional[str] = ""
    API_KEY_RERANKER: Optional[str] = ""
    API_BASE_PLANNER: Optional[str] = ""
    API_BASE_SUMMARIZER: Optional[str] = ""
    API_BASE_RERANKER: Optional[str] = ""
    AGENT_WORK_DIR: str = ""
    DATABASE_URL: Optional[str] = ""
    THEME: str = "dark"


class SessionSummaryModel(BaseModel):
    session_id: str
    created_at: Optional[str] = None
    node_count: int = 0
    preview: str = ""
    label: Optional[str] = None


class ChatRequestModel(BaseModel):
    content: str
    session_id: Optional[str] = None
    attached_files: dict[str, str] = Field(default_factory=dict)


class HealthResponseModel(BaseModel):
    status: str = "ok"
    service: str = "Forge Agent Backend"
    version: str = "1.1.0"
    active_connections: int = 0


class FileUploadModel(BaseModel):
    name: str
    content_base64: str

