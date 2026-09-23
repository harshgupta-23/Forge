"""
test_critical_async_summarise.py — Verifies that summarise_history is fully async
and executes without blocking concurrent event-loop tasks.
"""

import asyncio
import inspect
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from engine.utils import summarise_history


class TestAsyncSummariseHistory:
    def test_summarise_history_is_coroutine_function(self):
        """summarise_history must be an async coroutine function."""
        assert inspect.iscoroutinefunction(summarise_history)

    @pytest.mark.asyncio
    async def test_async_summarise_execution_and_concurrency(self):
        """Verify summarise_history awaits AsyncOpenAI and doesn't block concurrent tasks."""
        mock_choice = MagicMock()
        mock_choice.message.content = "Summary: User asked for assistance, tasks performed."
        mock_response = MagicMock(choices=[mock_choice])

        # Mock client whose completions.create yields control with asyncio.sleep
        async def mock_create(*args, **kwargs):
            await asyncio.sleep(0.05)
            return mock_response

        messages = [
            HumanMessage(content="Hello 1"),
            AIMessage(content="Response 1"),
            HumanMessage(content="Task 2"),
            ToolMessage(content="Result 2", name="bash", tool_call_id="call_1"),
            AIMessage(content="Response 2"),
            HumanMessage(content="Follow up 3"),
            AIMessage(content="Final 3")
        ]

        # Concurrently run a background heartbeat task
        heartbeat_ticks = 0

        async def heartbeat():
            nonlocal heartbeat_ticks
            for _ in range(5):
                await asyncio.sleep(0.01)
                heartbeat_ticks += 1

        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(side_effect=mock_create)

        with patch("engine.utils.get_async_openai_client", return_value=(mock_async_client, "mock-model")):
            summarise_task = asyncio.create_task(summarise_history(messages, {}))
            heartbeat_task = asyncio.create_task(heartbeat())

            res, _ = await asyncio.gather(summarise_task, heartbeat_task)

        # Heartbeat task was able to advance while summarise was awaiting response
        assert heartbeat_ticks >= 3, f"Heartbeat was starved! Ticks: {heartbeat_ticks}"
        assert len(res) == 6  # 2 compressed prefix messages + 4 retained tail messages
        assert "[Previous session summary" in res[0].content
        assert "Summary: User asked" in res[1].content

