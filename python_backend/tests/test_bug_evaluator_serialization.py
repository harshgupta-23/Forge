import pytest
from langchain_core.messages import AIMessage, ToolMessage
from engine.nodes.evaluator import get_failing_tool_signatures, is_stuck_in_repetition_loop, _normalize_args


class CustomUnserializable:
    def __init__(self, val):
        self.val = val

    def __repr__(self):
        return f"CustomUnserializable({self.val})"


def test_normalize_args_handles_non_serializable():
    args = {"obj": CustomUnserializable(42), "set_val": {1, 2, 3}}
    norm = _normalize_args(args)
    assert isinstance(norm, str)
    assert "CustomUnserializable(42)" in norm


def test_evaluator_loop_detection_with_unserializable_args():
    obj = CustomUnserializable(99)
    # Turn 1: AI calls tool with unserializable arg
    ai_msg_1 = AIMessage(
        content="calling tool",
        tool_calls=[{"id": "call_1", "name": "run_custom", "args": {"key": obj}}]
    )
    # Turn 1: Tool returns error
    tool_msg_1 = ToolMessage(
        content="Error: connection refused",
        name="run_custom",
        tool_call_id="call_1"
    )
    # Turn 2: AI repeats the same tool call with same unserializable arg
    ai_msg_2 = AIMessage(
        content="retrying same tool",
        tool_calls=[{"id": "call_2", "name": "run_custom", "args": {"key": obj}}]
    )

    messages = [ai_msg_1, tool_msg_1, ai_msg_2]

    # Must not raise TypeError
    sigs = get_failing_tool_signatures(messages)
    assert len(sigs) == 1
    assert "run_custom" in sigs[0]

    is_loop, reason = is_stuck_in_repetition_loop(messages)
    assert is_loop is True
    assert "run_custom" in reason

