"""
test_phase4.py — Unit and integration tests for Phase 4:
Exact BPE tokenization, dynamic context pruning, hierarchical summarization,
tree search dead-end detection, and Gemma turn alternation safety.
"""

import asyncio
import unittest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from engine.tokenizer import count_tokens_exact, count_message_tokens, calculate_token_savings
from engine.pruner import DynamicContextPruner
from engine.summarizer import HierarchicalSubtreeSummarizer
from engine.tree_search import evaluate_turn_outcome, detect_dead_end_subtrees
from engine.utils import build_model_contents
from storage.metadata import metadata_store


class TestPhase4(unittest.TestCase):

    def setUp(self):
        asyncio.run(metadata_store.setup())

    def test_exact_tokenizer_and_fallback(self):
        """Tests exact BPE counter and pure-Python fallback calculations."""
        # Empty and whitespace
        self.assertEqual(count_tokens_exact(""), 0)
        self.assertEqual(count_tokens_exact("   "), 0)
        self.assertEqual(count_tokens_exact(None), 0)

        # Basic text
        text = "Hello world, this is a test of the token counter."
        toks = count_tokens_exact(text)
        self.assertGreater(toks, 5)
        self.assertLess(toks, 25)

        # Message token accounting
        h_msg = HumanMessage(content="Write a Python script to calculate fibonacci.")
        h_toks = count_message_tokens(h_msg)
        self.assertGreater(h_toks, 5)

        ai_msg = AIMessage(
            content="I will run the local script now.",
            tool_calls=[{"name": "run_local_python_script", "args": {"code": "print(42)"}, "id": "call_1"}]
        )
        ai_toks = count_message_tokens(ai_msg)
        self.assertGreater(ai_toks, h_toks)

        # Savings calculation
        raw = [h_msg, ai_msg, ai_msg]
        pruned = [h_msg, ai_msg]
        raw_t, pruned_t, savings = calculate_token_savings(raw, pruned)
        self.assertEqual(savings, raw_t - pruned_t)
        self.assertGreater(savings, 0)
        print("✓ test_exact_tokenizer_and_fallback passed")

    def test_dead_end_tool_tombstoning(self):
        """Verifies failed tool executions are compacted into tombstones when subsequent retries occur."""
        pruner = DynamicContextPruner(preserve_recent_turns=2)

        messages = [
            # Turn 0: Root Goal
            HumanMessage(content="Deploy the server on port 8080."),
            AIMessage(content="Starting server..."),
            # Turn 1: Dead-End Tool Failure
            HumanMessage(content="Checking port status..."),
            AIMessage(content="Running check script...", tool_calls=[{"name": "run_script", "args": {}, "id": "c1"}]),
            ToolMessage(
                content="Traceback (most recent call last):\nFileNotFoundError: [Errno 2] No such file or directory: 'server.py'\nError: execution failed",
                name="run_script",
                tool_call_id="c1"
            ),
            AIMessage(content="Failed to find server.py. Retrying with main.py."),
            # Turn 2: Successful Retry
            HumanMessage(content="Try main.py instead."),
            AIMessage(content="Running main.py...", tool_calls=[{"name": "run_script", "args": {}, "id": "c2"}]),
            ToolMessage(content="Server started successfully on port 8080.", name="run_script", tool_call_id="c2"),
            AIMessage(content="Server is running on port 8080."),
            # Turn 3: Recent turn (verbatim)
            HumanMessage(content="Verify health check."),
            AIMessage(content="Health check passed.")
        ]

        pruned = pruner.prune_context(messages)
        self.assertEqual(len(pruned), len(messages))

        # Check that the failed tool output was tombstoned
        failed_tool = [m for m in pruned if isinstance(m, ToolMessage) and m.tool_call_id == "c1"][0]
        self.assertIn("Tool retry succeeded", failed_tool.content)
        self.assertIn("earlier attempt failed", failed_tool.content)
        self.assertNotIn("Traceback (most recent call last)", failed_tool.content)

        # Check that the successful tool output was preserved verbatim
        success_tool = [m for m in pruned if isinstance(m, ToolMessage) and m.tool_call_id == "c2"][0]
        self.assertEqual(success_tool.content, "Server started successfully on port 8080.")
        print("✓ test_dead_end_tool_tombstoning passed")

    def test_bulky_tool_output_truncation(self):
        """Verifies stale bulky tool outputs from older turns are truncated."""
        pruner = DynamicContextPruner(max_tool_output_tokens=50, preserve_recent_turns=2)

        huge_listing = "\n".join([f"file_{i}.txt: rw-r--r-- size 4096 bytes" for i in range(100)])
        messages = [
            HumanMessage(content="List all files in repository."),
            AIMessage(content="Running ls..."),
            HumanMessage(content="Inspect directory structure."),
            ToolMessage(content=huge_listing, name="list_directory", tool_call_id="c0"),
            AIMessage(content="I see the files."),
            # Recent turns
            HumanMessage(content="Now open readme."),
            AIMessage(content="Readme opened."),
            HumanMessage(content="Done."),
            AIMessage(content="All finished.")
        ]

        pruned = pruner.prune_context(messages)
        tool_msg = [m for m in pruned if isinstance(m, ToolMessage) and m.name == "list_directory"][0]
        self.assertIn("pruned from earlier tool output", tool_msg.content)
        self.assertLess(len(tool_msg.content), len(huge_listing))
        print("✓ test_bulky_tool_output_truncation passed")

    def test_relevance_turn_filtering(self):
        """Verifies low-relevance intermediate assistant turns are condensed."""
        pruner = DynamicContextPruner(relevance_threshold=0.2, preserve_recent_turns=2)

        irrelevant_text = (
            "The weather in Tokyo is sunny today with mild humidity and a light breeze. "
            "Yesterday it rained heavily causing travel delays across various transit networks. "
            "Many tourists visited parks and enjoyed cherry blossom season throughout the afternoon."
        ) * 4

        messages = [
            HumanMessage(content="Setup PostgreSQL pgvector database."),
            AIMessage(content="Database initialized."),
            HumanMessage(content="What about unrelated regional weather patterns?"),
            AIMessage(content=irrelevant_text),
            # Recent turns
            HumanMessage(content="Now test the vector similarity search index."),
            AIMessage(content="Vector search test passed."),
            HumanMessage(content="Check database connection."),
            AIMessage(content="Connection active.")
        ]

        pruned = pruner.prune_context(messages)
        mid_ai = pruned[3]
        self.assertIsInstance(mid_ai, AIMessage)
        self.assertIn("Intermediate reasoning condensed", mid_ai.content)
        self.assertLess(len(mid_ai.content), len(irrelevant_text))
        print("✓ test_relevance_turn_filtering passed")

    def test_gemma_strict_alternation_after_pruning(self):
        """Verifies build_model_contents produces valid alternating turns after pruning."""
        pruner = DynamicContextPruner()

        messages = [
            HumanMessage(content="Task start: run script."),
            AIMessage(content="Executing..."),
            HumanMessage(content="Step 1"),
            ToolMessage(content="[Tool retry succeeded: error pruned]", name="run", tool_call_id="c1"),
            AIMessage(content="Step 1 done."),
            HumanMessage(content="Step 2"),
            ToolMessage(content="Result 2", name="run", tool_call_id="c2"),
            AIMessage(content="Step 2 done."),
            HumanMessage(content="Final step query."),
            AIMessage(content="Final completion.")
        ]

        pruned = pruner.prune_context(messages)
        contents = build_model_contents(pruned, {})

        # Verify non-system messages strictly alternate user and assistant
        non_sys = [m for m in contents if m["role"] != "system"]
        self.assertGreater(len(non_sys), 0)
        self.assertEqual(non_sys[0]["role"], "user")

        for i in range(1, len(non_sys)):
            prev_role = non_sys[i - 1]["role"]
            curr_role = non_sys[i]["role"]
            self.assertNotEqual(
                prev_role, curr_role,
                f"Consecutive same-role collision at index {i}: {prev_role} followed by {curr_role}"
            )
        print("✓ test_gemma_strict_alternation_after_pruning passed")

    def test_hierarchical_block_summarization(self):
        """Verifies multi-turn history is hierarchically compacted and cached."""
        summarizer = HierarchicalSubtreeSummarizer(block_size=2, activation_turn_depth=4)

        messages = []
        for i in range(6):
            messages.append(HumanMessage(content=f"User turn number {i} regarding feature {i}."))
            messages.append(AIMessage(content=f"Assistant response for feature {i} completed successfully."))

        compacted = asyncio.run(summarizer.compact_ancestor_history(
            messages, thread_id="test_thread_summary", attached_files={}
        ))

        self.assertLess(len(compacted), len(messages))
        # First message is preserved root
        self.assertEqual(compacted[0].content, messages[0].content)
        # Spliced hierarchical summary
        has_summary = any("[Hierarchical Summary]" in str(m.content) for m in compacted)
        self.assertTrue(has_summary)
        # Recent turns preserved at tail
        self.assertEqual(compacted[-1].content, messages[-1].content)
        self.assertEqual(compacted[-2].content, messages[-2].content)
        print("✓ test_hierarchical_block_summarization passed")

    def test_tree_search_evaluation_and_dead_ends(self):
        """Verifies turn scoring and dead-end branch identification."""
        # Success turn
        good_turn = [
            HumanMessage(content="Run test."),
            AIMessage(content="Executing...", tool_calls=[{"name": "test", "args": {}, "id": "c1"}]),
            ToolMessage(content="All 5 tests passed with exit code 0.", name="test", tool_call_id="c1"),
            AIMessage(content="Done.")
        ]
        score_good = evaluate_turn_outcome(good_turn)
        self.assertEqual(score_good, 1.0)

        # Failing turn with repetition
        bad_turn = [
            HumanMessage(content="Run command."),
            AIMessage(content="Retrying...", tool_calls=[
                {"name": "cmd", "args": {"opt": 1}, "id": "c1"},
                {"name": "cmd", "args": {"opt": 1}, "id": "c2"}
            ]),
            ToolMessage(content="Error: Command failed with exit code 1", name="cmd", tool_call_id="c1"),
            ToolMessage(content="Traceback (most recent call last): Fatal Error", name="cmd", tool_call_id="c2"),
        ]
        score_bad = evaluate_turn_outcome(bad_turn)
        self.assertLess(score_bad, 0.4)

        # Mock snapshot objects for dead-end subtree detection
        class MockConfig:
            def __init__(self, cid):
                self.config = {"configurable": {"checkpoint_id": cid}}
                self.next = ()
                self.values = {
                    "messages": [
                        ToolMessage(content="Error: connection failed", name="t", tool_call_id="1"),
                        ToolMessage(content="Error: retry failed", name="t", tool_call_id="2"),
                        ToolMessage(content="Traceback: terminal failure", name="t", tool_call_id="3")
                    ]
                }

        mock_snapshots = [MockConfig("chk_failing_branch")]
        dead_ends = detect_dead_end_subtrees(mock_snapshots, max_consecutive_failures=3)
        self.assertIn("chk_failing_branch", dead_ends)

        # Persist and retrieve via metadata_store
        asyncio.run(metadata_store.set_pruned("thread_1", "chk_failing_branch", True))
        meta = asyncio.run(metadata_store.get_metadata_map("thread_1"))
        self.assertTrue(meta.get("chk_failing_branch", {}).get("is_pruned"))

        # Revive branch
        asyncio.run(metadata_store.set_pruned("thread_1", "chk_failing_branch", False))
        meta_revived = asyncio.run(metadata_store.get_metadata_map("thread_1"))
        self.assertFalse(meta_revived.get("chk_failing_branch", {}).get("is_pruned"))
        print("✓ test_tree_search_evaluation_and_dead_ends passed")


if __name__ == "__main__":
    unittest.main()

