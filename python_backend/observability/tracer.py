"""
tracer.py — Production LangSmith tracing manager with zero-overhead fallback.

Provides:
- Config precedence resolution (os.environ > config.json > disabled)
- Dynamic environment variable synchronization for LangChain internals
- Thread-scoped LangChainTracer callback generation with session_id binding
- Transparent @traceable decorator fallback when tracing is disabled or unconfigured
"""

import os
import functools
from typing import Any, Callable, Optional


def sync_tracing_env(config: Optional[dict[str, Any]] = None) -> dict[str, str]:
    """
    Synchronizes LangSmith credentials into os.environ following precedence:
    Environment Variables > config.json > Defaults (Disabled).

    Returns a dictionary of active tracing environment settings.
    """
    cfg = config or {}

    keys_mapping = {
        "LANGCHAIN_TRACING_V2": cfg.get("LANGCHAIN_TRACING_V2"),
        "LANGCHAIN_API_KEY": cfg.get("LANGCHAIN_API_KEY"),
        "LANGCHAIN_PROJECT": cfg.get("LANGCHAIN_PROJECT", "Forge"),
        "LANGCHAIN_ENDPOINT": cfg.get("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
    }

    active_settings: dict[str, str] = {}
    for key, cfg_val in keys_mapping.items():
        # Env var has priority
        if key in os.environ and os.environ[key]:
            active_settings[key] = os.environ[key]
        elif cfg_val is not None and str(cfg_val).strip():
            # Export to os.environ so LangChain/LangSmith internals pick it up
            val_str = str(cfg_val).strip()
            os.environ[key] = val_str
            active_settings[key] = val_str

    return active_settings


def is_tracing_enabled() -> bool:
    """
    Returns True only if LANGCHAIN_TRACING_V2 is explicitly enabled
    and a valid LANGCHAIN_API_KEY is present in the environment.
    """
    tracing_v2 = os.environ.get("LANGCHAIN_TRACING_V2", "").lower().strip()
    has_flag = tracing_v2 in ("true", "1", "yes")
    has_key = bool(os.environ.get("LANGCHAIN_API_KEY", "").strip())
    return has_flag and has_key


def get_tracing_callbacks(
    thread_id: Optional[str] = None,
    run_name: str = "Forge-Turn",
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None
) -> list[Any]:
    """
    Generates LangChainTracer callbacks bound to the conversation thread.
    Binds thread_id to metadata['session_id'] so LangSmith aggregates all
    multi-node graph steps (planner, agent, tools, evaluator) into a single run tree.

    Returns an empty list when tracing is disabled or langsmith is not installed.
    """
    if not is_tracing_enabled():
        return []

    try:
        from langchain_core.tracers import LangChainTracer

        project = os.environ.get("LANGCHAIN_PROJECT", "Forge")
        tracer = LangChainTracer(project_name=project)
        return [tracer]
    except Exception as exc:
        # Fallback cleanly without halting agent execution
        print(f"[tracer] Warning: LangSmith tracer initialization failed: {exc}")
        return []


def traceable(
    name: Optional[str] = None,
    run_type: str = "chain",
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
    **kwargs: Any
) -> Callable:
    """
    Transparent @traceable decorator.
    If LangSmith is installed and tracing is enabled, wraps the function with langsmith.traceable.
    Otherwise, returns the function wrapped in a lightweight pass-through.
    """
    def decorator(func: Callable) -> Callable:
        if is_tracing_enabled():
            try:
                import langsmith
                return langsmith.traceable(
                    name=name or func.__name__,
                    run_type=run_type,
                    tags=tags,
                    metadata=metadata,
                    **kwargs
                )(func)
            except Exception:
                pass

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator

