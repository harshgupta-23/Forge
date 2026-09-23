import asyncio
import time
import pytest
from engine.nodes.agent import StreamingThoughtFilter


@pytest.mark.asyncio
async def test_streaming_thought_filter_10k_tokens_bounded_memory():
    queue = asyncio.Queue()
    filter_instance = StreamingThoughtFilter(queue=queue)

    tokens = ["Hello ", "world! ", "This ", "is ", "a ", "token. "] * 2000  # 12,000 tokens

    start_time = time.perf_counter()
    for tok in tokens:
        await filter_instance.feed(tok)
    await filter_instance.flush()
    duration = time.perf_counter() - start_time

    # Verify execution completes quickly (<1.5s for 12,000 tokens)
    assert duration < 1.5, f"Streaming filter took {duration:.2f}s, expected < 1.5s"

    # Verify buffer is cleared after flush
    assert len(filter_instance.buffer) == 0

    # Verify tokens were delivered to queue
    received = []
    while not queue.empty():
        item = await queue.get()
        if item[0] == "token":
            received.append(item[1])
    full_text = "".join(received)
    assert len(full_text) > 0


@pytest.mark.asyncio
async def test_streaming_thought_filter_suppresses_thoughts_without_memory_spike():
    queue = asyncio.Queue()
    filter_instance = StreamingThoughtFilter(queue=queue)

    # Stream a thought block with 5,000 tokens followed by clean answer
    await filter_instance.feed("<thought>")
    for _ in range(5000):
        await filter_instance.feed("reasoning step ")
        # Peak buffer inside thought must stay bounded to sliding window (<= 128 chars)
        assert len(filter_instance.buffer) <= 128
    await filter_instance.feed("</thought>")
    await filter_instance.feed("Final answer to the user.")
    await filter_instance.flush()

    received = []
    while not queue.empty():
        item = await queue.get()
        if item[0] == "token":
            received.append(item[1])
    output = "".join(received)
    assert "reasoning step" not in output
    assert "Final answer" in output

