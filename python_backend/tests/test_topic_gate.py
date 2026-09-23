"""
test_topic_gate.py — Comprehensive test suite for topic gate routing, evaluation,
robust JSON parsing, edge-case sanitization, and context window truncation.
Addresses Flaws 1 through 6.
"""

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

# Add python_backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import END
from engine.nodes.topic_gate import (
    evaluate_topic_shift,
    topic_gate_node,
    parse_topic_shift_response,
    extract_text_content,
)
from engine.graph import route_topic_gate


class TestTopicGateSuite(unittest.IsolatedAsyncioTestCase):
    """
    Test suite for topic continuity and branch gating.
    """

    def create_mock_llm_client(self, content_str: str = "", side_effect: Exception | None = None):
        """Reusable parameterized mock factory (Flaw 3: Eliminates redundant mock boilerplate)."""
        mock_client = MagicMock()
        if side_effect:
            mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)
        else:
            mock_response = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = content_str
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        return mock_client

    # =========================================================================
    # FLAW 1: Core Business Actions & Graph Routing
    # =========================================================================

    async def test_route_topic_gate_unrelated_routes_to_end(self):
        """Verify routing function routes to END when topic shift is detected."""
        state = {
            "topic_info": {
                "is_related": False,
                "topic": "French Cuisine",
                "reason": "Shift from Python to cooking"
            }
        }
        destination = route_topic_gate(state)
        self.assertEqual(destination, END, "Unrelated topic must route to END to wait for user branch choice")

    async def test_route_topic_gate_related_routes_to_planner(self):
        """Verify routing function routes to planner when topic continues."""
        state = {
            "topic_info": {
                "is_related": True,
                "topic": "Python Optimization",
                "reason": "Follow-up question"
            }
        }
        destination = route_topic_gate(state)
        self.assertEqual(destination, "planner", "Related topic must continue to planner")

    async def test_route_topic_gate_none_or_missing_routes_to_planner(self):
        """Verify default routing when topic_info is None or empty."""
        self.assertEqual(route_topic_gate({}), "planner")
        self.assertEqual(route_topic_gate({"topic_info": None}), "planner")

    async def test_topic_gate_node_emits_branch_prompt_to_queue_on_unrelated(self):
        """Verify topic_gate_node emits ('branch_prompt', analysis) to streaming queue when unrelated."""
        mock_client = self.create_mock_llm_client(
            '{"is_related": false, "topic": "Astrophysics", "reason": "Shift to space"}'
        )
        queue = asyncio.Queue()
        config = {"configurable": {"queue": queue}}

        state = {
            "messages": [
                HumanMessage(content="Explain python generators"),
                AIMessage(content="Generators yield values lazily..."),
                HumanMessage(content="How far is Proxima Centauri?")
            ]
        }

        with patch("engine.nodes.topic_gate.get_async_openai_client", return_value=(mock_client, "gpt-4o-mini")):
            res = await topic_gate_node(state, config)
            self.assertIsNotNone(res["topic_info"])
            self.assertFalse(res["topic_info"]["is_related"])

            # Verify queue received branch prompt event
            self.assertFalse(queue.empty())
            ev_type, payload = queue.get_nowait()
            self.assertEqual(ev_type, "branch_prompt")
            self.assertFalse(payload["is_related"])
            self.assertEqual(payload["topic"], "Astrophysics")

    async def test_topic_gate_node_skips_when_skip_topic_gate_flag_is_set(self):
        """Verify topic_gate_node bypasses evaluation when skip_topic_gate is True."""
        state = {
            "messages": [
                HumanMessage(content="Explain python generators"),
                AIMessage(content="Generators yield values lazily..."),
                HumanMessage(content="How far is Proxima Centauri?")
            ],
            "skip_topic_gate": True
        }
        res = await topic_gate_node(state, {})
        self.assertTrue(res["topic_info"]["is_related"])
        self.assertEqual(route_topic_gate(res), "planner")

    # =========================================================================
    # FLAW 2: Realistic LLM Output Parsing & Failure Modes
    # =========================================================================

    def test_parse_markdown_code_fences(self):
        """Verify parser handles ```json code blocks with newlines."""
        raw = "```json\n{\n  \"is_related\": false,\n  \"topic\": \"Gardening\",\n  \"reason\": \"Different field\"\n}\n```"
        parsed = parse_topic_shift_response(raw)
        self.assertFalse(parsed["is_related"])
        self.assertEqual(parsed["topic"], "Gardening")

    def test_parse_preamble_and_conversational_chatter(self):
        """Verify parser handles surrounding conversational commentary."""
        raw = "Sure! Here is my analysis:\n{\"is_related\": false, \"topic\": \"Space Exploration\", \"reason\": \"Topic shifted\"}\nLet me know if you need more!"
        parsed = parse_topic_shift_response(raw)
        self.assertFalse(parsed["is_related"])
        self.assertEqual(parsed["topic"], "Space Exploration")

    def test_parse_trailing_commas(self):
        """Verify parser handles trailing commas in JSON."""
        raw = '{"is_related": true, "topic": "Algorithms", "reason": "Follow-up",}'
        parsed = parse_topic_shift_response(raw)
        self.assertTrue(parsed["is_related"])
        self.assertEqual(parsed["topic"], "Algorithms")

    def test_parse_string_booleans(self):
        """Verify parser handles string booleans 'false' and 'true'."""
        parsed_false = parse_topic_shift_response('{"is_related": "false", "topic": "Music"}')
        self.assertFalse(parsed_false["is_related"])

        parsed_true = parse_topic_shift_response('{"is_related": "true", "topic": "Tech"}')
        self.assertTrue(parsed_true["is_related"])

    def test_parse_missing_keys_safe_defaults(self):
        """Verify parser provides safe defaults when keys are missing."""
        raw = '{"topic": "Quantum Computing"}'
        parsed = parse_topic_shift_response(raw)
        self.assertTrue(parsed["is_related"])
        self.assertEqual(parsed["topic"], "Quantum Computing")

    # =========================================================================
    # FLAW 4: Robust Contract-Based Fallback Assertions
    # =========================================================================

    async def test_evaluator_network_error_contract_fallback(self):
        """Verify resilient fallback preserves business contract (continuity) without string assertions."""
        mock_client = self.create_mock_llm_client(side_effect=TimeoutError("Model endpoint timed out"))
        messages = [HumanMessage(content="Hello"), AIMessage(content="Hi there")]

        with patch("engine.nodes.topic_gate.get_async_openai_client", return_value=(mock_client, "gpt-4o-mini")):
            res = await evaluate_topic_shift("Next query", messages)
            # Must satisfy contract: returns dict with is_related=True and valid string fields
            self.assertIsInstance(res, dict)
            self.assertIs(res["is_related"], True)
            self.assertIsInstance(res["topic"], str)
            self.assertIsInstance(res["reason"], str)

    async def test_evaluator_unparseable_garbage_contract_fallback(self):
        """Verify unparseable gibberish from LLM safely falls back to continuity."""
        mock_client = self.create_mock_llm_client("I am unable to answer in JSON format.")
        messages = [HumanMessage(content="Hello"), AIMessage(content="Hi there")]

        with patch("engine.nodes.topic_gate.get_async_openai_client", return_value=(mock_client, "gpt-4o-mini")):
            res = await evaluate_topic_shift("Next query", messages)
            self.assertIs(res["is_related"], True)

    # =========================================================================
    # FLAW 5: Edge Cases in Query Content and State Shape
    # =========================================================================

    async def test_whitespace_only_query_bypasses_llm(self):
        """Verify queries with only spaces, tabs, or newlines do not trigger LLM calls."""
        mock_client = self.create_mock_llm_client()
        messages = [HumanMessage(content="Prior task"), AIMessage(content="Result")]

        with patch("engine.nodes.topic_gate.get_async_openai_client", return_value=(mock_client, "gpt-4o-mini")):
            for ws_query in ["   ", "\t\t", "\n\r\n", "   \t \n "]:
                res = await evaluate_topic_shift(ws_query, messages)
                self.assertTrue(res["is_related"])
                self.assertEqual(res["reason"], "Empty query")

        # Zero calls made to LLM
        mock_client.chat.completions.create.assert_not_called()

    async def test_multimodal_list_content_support(self):
        """Verify message content formatted as list of dicts (multimodal) is correctly extracted."""
        self.assertEqual(extract_text_content("Simple string"), "Simple string")
        self.assertEqual(
            extract_text_content([{"type": "text", "text": "Describe this code"}, {"type": "image_url"}]),
            "Describe this code"
        )
        self.assertEqual(
            extract_text_content([{"text": "Part 1"}, {"text": "Part 2"}]),
            "Part 1 Part 2"
        )

        mock_client = self.create_mock_llm_client('{"is_related": true, "topic": "Image query", "reason": "Continuation"}')
        messages = [
            HumanMessage(content=[{"type": "text", "text": "Look at this diagram"}]),
            AIMessage(content=[{"type": "text", "text": "It is an architecture diagram"}])
        ]
        with patch("engine.nodes.topic_gate.get_async_openai_client", return_value=(mock_client, "gpt-4o-mini")):
            res = await evaluate_topic_shift([{"type": "text", "text": "What does component A do?"}], messages)
            self.assertTrue(res["is_related"])

    async def test_last_message_not_human_message_traversal(self):
        """Verify topic_gate_node locates latest HumanMessage even if last message is AIMessage or SystemMessage."""
        mock_client = self.create_mock_llm_client('{"is_related": false, "topic": "Animals", "reason": "Shift"}')
        state = {
            "messages": [
                HumanMessage(content="Who is Alan Turing?"),
                AIMessage(content="Alan Turing was a mathematician..."),
                HumanMessage(content="Tell me about Siberian tigers"),
                AIMessage(content="Internal scratchpad or intermediate message"),
            ]
        }
        with patch("engine.nodes.topic_gate.get_async_openai_client", return_value=(mock_client, "gpt-4o-mini")):
            res = await topic_gate_node(state, {})
            self.assertIsNotNone(res["topic_info"])
            self.assertFalse(res["topic_info"]["is_related"])
            self.assertEqual(res["topic_info"]["topic"], "Animals")

    # =========================================================================
    # FLAW 6: Context Window Slicing and Token Truncation
    # =========================================================================

    async def test_50_turn_history_truncation_limits_prompt_context(self):
        """Verify that passing 50 conversation turns only feeds the last turn into the prompt and bounds token size."""
        mock_client = self.create_mock_llm_client('{"is_related": true, "topic": "Turn 50", "reason": "Continuation"}')

        # Generate 50 turns (100 messages) with very long text in early turns
        messages = []
        for i in range(1, 51):
            messages.append(HumanMessage(content=f"Turn {i} question: " + "verbose info " * 50))
            messages.append(AIMessage(content=f"Turn {i} answer: " + "verbose response " * 50))

        with patch("engine.nodes.topic_gate.get_async_openai_client", return_value=(mock_client, "gpt-4o-mini")):
            res = await evaluate_topic_shift("Turn 51 question follow-up", messages)
            self.assertTrue(res["is_related"])

            # Verify prompt contents in call arguments
            mock_client.chat.completions.create.assert_called_once()
            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            sent_messages = call_kwargs["messages"]
            prompt_user_content = sent_messages[1]["content"]

            # Early turns (e.g. Turn 1, Turn 2) must NOT be present in prompt
            self.assertNotIn("Turn 1 question", prompt_user_content)
            self.assertNotIn("Turn 25 question", prompt_user_content)

            # Only Turn 50 should be present
            self.assertIn("Turn 50 question", prompt_user_content)
            self.assertIn("Turn 50 answer", prompt_user_content)

            # Total prompt characters must be strictly bounded (< 1500 chars)
            self.assertLess(len(prompt_user_content), 1500)


if __name__ == "__main__":
    unittest.main()
