"""
test_critical_config_race.py — Verifies that config values (API keys, model names)
are isolated per-async-task and don't leak via os.environ mutation.

Fix 2: server/dependencies.py uses contextvars for active config; engine/utils.py
reads from it instead of raw os.environ.
"""

import asyncio
import os
import pytest
from unittest.mock import patch


class TestConfigRaceCondition:
    """Config values must be isolated between concurrent requests."""

    @pytest.mark.asyncio
    async def test_concurrent_configs_isolated(self):
        """Two concurrent tasks applying different configs must each resolve their own API key."""
        from server.dependencies import set_active_config, get_active_config

        barrier = asyncio.Barrier(2)
        results = {}

        async def request_a():
            set_active_config({"API_KEY": "key_user_A", "MODEL": "model-a", "API_BASE": "https://a.example.com/"})
            await barrier.wait()
            await asyncio.sleep(0.05)
            cfg = get_active_config()
            results["a_key"] = cfg.get("API_KEY")
            results["a_model"] = cfg.get("MODEL")

        async def request_b():
            set_active_config({"API_KEY": "key_user_B", "MODEL": "model-b", "API_BASE": "https://b.example.com/"})
            await barrier.wait()
            await asyncio.sleep(0.05)
            cfg = get_active_config()
            results["b_key"] = cfg.get("API_KEY")
            results["b_model"] = cfg.get("MODEL")

        await asyncio.gather(request_a(), request_b())

        assert results["a_key"] == "key_user_A", f"Request A saw wrong key: {results['a_key']}"
        assert results["b_key"] == "key_user_B", f"Request B saw wrong key: {results['b_key']}"
        assert results["a_model"] == "model-a"
        assert results["b_model"] == "model-b"

    def test_get_active_config_falls_back_to_environ(self):
        """When no ContextVar is set, get_active_config reads from os.environ."""
        from server.dependencies import get_active_config

        os.environ["API_KEY"] = "env_fallback_key"
        os.environ["MODEL"] = "env_fallback_model"
        cfg = get_active_config()
        assert cfg.get("API_KEY") == "env_fallback_key"
        assert cfg.get("MODEL") == "env_fallback_model"

    def test_set_and_get_active_config(self):
        """Basic set/get active config works."""
        from server.dependencies import set_active_config, get_active_config

        set_active_config({"API_KEY": "explicit_key", "MODEL": "explicit_model"})
        cfg = get_active_config()
        assert cfg["API_KEY"] == "explicit_key"
        assert cfg["MODEL"] == "explicit_model"

    def test_openai_client_reads_active_config(self):
        """get_openai_client and get_async_openai_client use get_active_config, not raw os.environ."""
        from server.dependencies import set_active_config
        from engine.utils import get_openai_client, get_async_openai_client

        set_active_config({
            "API_KEY": "test_key_123",
            "MODEL": "test-model-v1",
            "API_BASE": "https://test.example.com/v1/"
        })

        client, model = get_openai_client(role="agent")
        assert model == "test-model-v1"

        async_client, async_model = get_async_openai_client(role="agent")
        assert async_model == "test-model-v1"

    def test_sync_client_cache(self):
        """get_openai_client should cache clients (not recreate each call)."""
        from server.dependencies import set_active_config
        from engine.utils import get_openai_client

        set_active_config({
            "API_KEY": "cache_test_key",
            "MODEL": "cache-model",
            "API_BASE": "https://cache.example.com/v1/"
        })

        client1, _ = get_openai_client(role="agent")
        client2, _ = get_openai_client(role="agent")
        assert client1 is client2, "Sync client should be cached across calls"

    @pytest.mark.asyncio
    async def test_concurrent_generation_tasks_isolated(self):
        """Simulate two concurrent generation coroutines spawned via asyncio.create_task with different configs."""
        from server.dependencies import set_active_config, get_active_config
        from engine.utils import get_async_openai_client

        barrier = asyncio.Barrier(2)
        observed = {}

        async def worker(worker_id: str, api_key: str, model: str):
            set_active_config({"API_KEY": api_key, "MODEL": model, "API_BASE": "https://api.openai.com/v1/"})

            async def sub_task():
                await barrier.wait()
                await asyncio.sleep(0.02)
                client, resolved_model = get_async_openai_client("agent")
                cfg = get_active_config()
                observed[worker_id] = {
                    "cfg_key": cfg.get("API_KEY"),
                    "model": resolved_model,
                    "client_key": client.api_key
                }

            task = asyncio.create_task(sub_task())
            await task

        await asyncio.gather(
            worker("ws1", "sk-ws1-key-1111111111111111", "model-ws1"),
            worker("ws2", "sk-ws2-key-2222222222222222", "model-ws2")
        )

        assert observed["ws1"]["cfg_key"] == "sk-ws1-key-1111111111111111"
        assert observed["ws1"]["model"] == "model-ws1"
        assert observed["ws1"]["client_key"] == "sk-ws1-key-1111111111111111"

        assert observed["ws2"]["cfg_key"] == "sk-ws2-key-2222222222222222"
        assert observed["ws2"]["model"] == "model-ws2"
        assert observed["ws2"]["client_key"] == "sk-ws2-key-2222222222222222"


