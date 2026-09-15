"""
rest.py — REST API endpoints for health, configuration, sessions, and SSE streaming.
"""

import json
import asyncio
import base64
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from server.schemas.rest import ConfigModel, HealthResponseModel, SessionSummaryModel, ChatRequestModel, FileUploadModel
from server.dependencies import (
    load_config,
    save_config,
    apply_config_to_env,
    list_available_sessions,
    SESSION_DIR
)
from server.routes.ws import active_connections
from engine.graph import stream_graph_execution
from langchain_core.messages import HumanMessage

rest_router = APIRouter()


@rest_router.get("/health", response_model=HealthResponseModel)
async def health_check():
    """Health check endpoint for monitoring."""
    return HealthResponseModel(
        status="ok",
        service="Forge Agent Backend",
        version="1.1.0",
        active_connections=active_connections
    )


@rest_router.get("/api/config", response_model=dict)
async def get_configuration():
    """Retrieves active configuration."""
    return load_config()


@rest_router.post("/api/config", response_model=dict)
async def update_configuration(config: ConfigModel):
    """Updates configuration and applies values immediately to the environment."""
    data = config.model_dump()
    save_config(data)
    apply_config_to_env(data)
    return {"status": "success", "message": "Configuration saved and applied."}


@rest_router.get("/api/sessions", response_model=list[SessionSummaryModel])
async def get_sessions():
    """Lists saved non-empty sessions."""
    sessions = list_available_sessions()
    return [SessionSummaryModel(**s) for s in sessions]


@rest_router.post("/api/chat/stream")
async def chat_sse_stream(request: ChatRequestModel):
    """
    Server-Sent Events (SSE) streaming endpoint for external HTTP clients.
    Streams token events, tool execution status, and final answer.
    """
    cfg = load_config()
    if not cfg.get("API_KEY"):
        raise HTTPException(status_code=400, detail="API_KEY is not configured.")

    initial_state = {
        "messages": [HumanMessage(content=request.content)],
        "attached_files": request.attached_files,
        "plan": None,
        "iteration": 0,
        "is_streaming": True
    }

    queue: asyncio.Queue = asyncio.Queue()
    asyncio.create_task(stream_graph_execution(initial_state, queue))

    async def event_generator():
        while True:
            event_type, payload = await queue.get()
            if event_type == "__end__":
                yield "event: end\ndata: [DONE]\n\n"
                break
            elif event_type == "token":
                yield f"event: token\ndata: {json.dumps({'token': str(payload)})}\n\n"
            elif event_type in ("tool_start", "tool_done"):
                yield f"event: tool\ndata: {json.dumps({'type': event_type, 'content': str(payload)})}\n\n"
            elif event_type == "status":
                yield f"event: status\ndata: {json.dumps({'status': str(payload)})}\n\n"
            elif event_type == "error":
                yield f"event: error\ndata: {json.dumps({'error': str(payload)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


UPLOAD_DIR = Path.home() / ".forge" / "uploads"


@rest_router.post("/api/upload")
async def upload_file(payload: FileUploadModel):
    """Saves an uploaded file locally to ~/.forge/uploads and returns its absolute path."""
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = Path(payload.name).name or "attached_file"
        file_path = UPLOAD_DIR / safe_name
        data = base64.b64decode(payload.content_base64)
        with open(file_path, "wb") as f:
            f.write(data)
        return {
            "status": "success",
            "name": safe_name,
            "path": str(file_path.resolve())
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"File upload failed: {exc}")

