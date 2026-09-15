"""
rest.py — Pydantic schemas for FastAPI REST endpoints.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class ConfigModel(BaseModel):
    API_KEY: str = ""
    MODEL: str = "gemma-4-26b-a4b-it"
    API_BASE: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
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

