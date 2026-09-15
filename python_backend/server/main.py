"""
main.py — FastAPI application factory, lifespan management, and Uvicorn server runner.
"""

import sys
import threading
import subprocess
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from server.routes.ws import ws_router, set_server_instance
from server.routes.rest import rest_router
from server.dependencies import PLAYWRIGHT_BROWSERS_DIR


def _ensure_playwright_chromium() -> None:
    """Installs Playwright Chromium on first launch in the background."""
    marker = PLAYWRIGHT_BROWSERS_DIR / ".chromium_installed"
    if marker.exists():
        return
    try:
        print("[server] First run: downloading Chromium for browser automation...")
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True
        )
        marker.touch()
        print("[server] Chromium download complete.")
    except Exception as exc:
        print(f"[server] Chromium download failed, will retry next launch: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    threading.Thread(target=_ensure_playwright_chromium, daemon=True).start()
    print("[server] Initializing stateful checkpointer...")
    from storage import checkpoint_manager, metadata_store
    from engine.graph import build_graph, set_compiled_graph

    checkpointer = await checkpoint_manager.initialize()
    await metadata_store.setup()

    # Initialize RAG vector store
    from rag.vector_store import get_vector_store
    vs = get_vector_store()
    await vs.initialize()

    # Recompile graph with attached checkpointer
    graph_with_cp = build_graph(checkpointer=checkpointer)
    set_compiled_graph(graph_with_cp)

    print(f"[server] Forge FastAPI backend starting up with {checkpoint_manager.backend_type} checkpointer...")
    yield
    # Teardown actions
    print("[server] Forge FastAPI backend shutting down...")
    await checkpoint_manager.close()
    await vs.close()


def create_app() -> FastAPI:
    """Constructs and configures the FastAPI application."""
    app = FastAPI(
        title="Forge Agent API",
        version="1.1.0",
        description="Autonomous desktop AI agent backend with multi-node LangGraph engine.",
        lifespan=lifespan
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(ws_router)
    app.include_router(rest_router)

    return app


app = create_app()


def run_server(host: str = "localhost", port: int = 8765):
    """
    Launches Uvicorn using uvicorn.Server to allow clean should_exit shutdown
    coordinated with Tauri supervisor signals.
    """
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    set_server_instance(server)
    print(f"[server] Running Forge FastAPI Server on http://{host}:{port} and ws://{host}:{port}")
    server.run()


if __name__ == "__main__":
    run_server()

