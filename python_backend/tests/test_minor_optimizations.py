import pytest
from pathlib import Path
from langchain_core.messages import AIMessage, ToolMessage
from engine.tree_search import evaluate_turn_outcome
from tools.list_directory import list_directory


def test_tree_search_repetition_penalty():
    ai_msg_1 = AIMessage(
        content="call 1",
        tool_calls=[{"id": "c1", "name": "fetch", "args": {"url": "https://example.com"}}]
    )
    ai_msg_2 = AIMessage(
        content="call 2",
        tool_calls=[{"id": "c2", "name": "fetch", "args": {"url": "https://example.com"}}]
    )

    # Both call the identical tool with identical args
    score = evaluate_turn_outcome([ai_msg_1, ai_msg_2])
    # Initial score 1.0 - 0.3 = 0.7
    assert score == pytest.approx(0.7)


def test_list_directory_scandir(tmp_path: Path):
    d = tmp_path / "subdir"
    d.mkdir()
    f1 = d / "file1.txt"
    f1.write_text("hello")
    f2 = d / "file2.txt"
    f2.write_text("world 12345")
    sub = d / "nested_dir"
    sub.mkdir()

    from unittest.mock import patch
    with patch("server.dependencies.get_active_config", return_value={"AGENT_WORK_DIR": str(tmp_path)}):
        res = list_directory.invoke({"directory_path": str(d)})
        assert "[DIR ]  nested_dir" in res
        assert "[FILE]  file1.txt" in res
        assert "[FILE]  file2.txt" in res
        assert "bytes" in res
