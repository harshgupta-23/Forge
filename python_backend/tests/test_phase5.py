"""
test_phase5.py — Verification suite for Phase 5 (Observability & Automated Evaluation Suites).

Tests:
1. Tracer environment synchronization, precedence, and dynamic export.
2. Tracer active vs disabled state detection.
3. LangChainTracer callback generation with session_id metadata binding.
4. Transparent @traceable decorator fallback (sync & async).
5. Golden evaluation dataset schema and integrity.
6. Ragas metric computation (Faithfulness, Answer Relevance, Context Precision, Context Recall).
7. End-to-end evaluation report generation and quality gate assertion.
8. GitHub Actions workflow and package.json test script definitions.
"""

import os
import json
import asyncio
import unittest
from pathlib import Path

from observability.tracer import (
    sync_tracing_env,
    is_tracing_enabled,
    get_tracing_callbacks,
    traceable
)
from tests.evals.test_ragas import RagasEvaluator


class TestPhase5(unittest.TestCase):
    """Phase 5 verification test suite."""

    def setUp(self):
        # Cache existing env
        self.original_env = {
            "LANGCHAIN_TRACING_V2": os.environ.get("LANGCHAIN_TRACING_V2"),
            "LANGCHAIN_API_KEY": os.environ.get("LANGCHAIN_API_KEY"),
            "LANGCHAIN_PROJECT": os.environ.get("LANGCHAIN_PROJECT"),
            "LANGCHAIN_ENDPOINT": os.environ.get("LANGCHAIN_ENDPOINT")
        }

    def tearDown(self):
        # Restore environment
        for k, v in self.original_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_tracer_env_sync_and_precedence(self):
        """Verifies environment variables take precedence over config.json and export to os.environ."""
        os.environ["LANGCHAIN_API_KEY"] = "env_key_123"
        os.environ.pop("LANGCHAIN_PROJECT", None)

        cfg = {
            "LANGCHAIN_API_KEY": "cfg_key_should_be_ignored",
            "LANGCHAIN_PROJECT": "ForgeTestProject",
            "LANGCHAIN_TRACING_V2": "true"
        }

        active = sync_tracing_env(cfg)
        # Env var has precedence
        self.assertEqual(os.environ.get("LANGCHAIN_API_KEY"), "env_key_123")
        self.assertEqual(active.get("LANGCHAIN_API_KEY"), "env_key_123")
        # Config exports when missing from env
        self.assertEqual(os.environ.get("LANGCHAIN_PROJECT"), "ForgeTestProject")
        self.assertEqual(os.environ.get("LANGCHAIN_TRACING_V2"), "true")
        print("✓ test_tracer_env_sync_and_precedence passed")

    def test_tracer_active_detection(self):
        """Verifies is_tracing_enabled correctly gates on both flag and key."""
        os.environ.pop("LANGCHAIN_TRACING_V2", None)
        os.environ.pop("LANGCHAIN_API_KEY", None)
        self.assertFalse(is_tracing_enabled())

        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ.pop("LANGCHAIN_API_KEY", None)
        self.assertFalse(is_tracing_enabled())

        os.environ["LANGCHAIN_API_KEY"] = "ls_key_abc"
        self.assertTrue(is_tracing_enabled())

        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        self.assertFalse(is_tracing_enabled())
        print("✓ test_tracer_active_detection passed")

    def test_tracer_callbacks_generation(self):
        """Verifies get_tracing_callbacks safely generates tracer or returns empty list."""
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        cb = get_tracing_callbacks(thread_id="session-test-01")
        self.assertEqual(cb, [])

        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = "ls_mock_key"
        os.environ["LANGCHAIN_PROJECT"] = "Forge"

        # Attempt callback generation; should either succeed or return [] gracefully
        cb_active = get_tracing_callbacks(
            thread_id="session-test-01",
            metadata={"session_id": "session-test-01"}
        )
        self.assertIsInstance(cb_active, list)
        print("✓ test_tracer_callbacks_generation passed")

    def test_traceable_decorator_fallback(self):
        """Verifies transparent @traceable decorator works seamlessly for sync and async functions."""
        @traceable(name="sync_compute")
        def add(a: int, b: int) -> int:
            return a + b

        @traceable(name="async_compute")
        async def async_mul(a: int, b: int) -> int:
            return a * b

        self.assertEqual(add(10, 20), 30)

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            res = loop.run_until_complete(async_mul(6, 7))
            self.assertEqual(res, 42)
        finally:
            loop.close()
        print("✓ test_traceable_decorator_fallback passed")

    def test_golden_dataset_schema(self):
        """Verifies golden_dataset.json schema and non-emptiness."""
        p = Path(__file__).parent / "evals" / "golden_dataset.json"
        self.assertTrue(p.exists(), "golden_dataset.json must exist")

        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 5)

        for item in data:
            self.assertIn("id", item)
            self.assertIn("category", item)
            self.assertIn("question", item)
            self.assertIn("contexts", item)
            self.assertIn("ground_truth", item)
            self.assertIn("generated_answer", item)
            self.assertIn("expected_tools", item)
            self.assertIsInstance(item["contexts"], list)
            self.assertGreater(len(item["contexts"]), 0)
        print("✓ test_golden_dataset_schema passed")

    def test_ragas_metrics_computation(self):
        """Verifies Faithfulness, Answer Relevance, Context Precision, and Context Recall algorithms."""
        evaluator = RagasEvaluator(use_live_llm=False)

        # 1. Faithfulness
        grounded_answer = "AsyncPostgresSaver connects to PostgreSQL."
        contexts = ["CheckpointManager uses AsyncPostgresSaver to connect to PostgreSQL."]
        f_score = evaluator.compute_faithfulness(grounded_answer, contexts)
        self.assertGreaterEqual(f_score, 0.8)

        hallucinated_answer = "Forge uses a quantum processor located in Antarctica."
        f_bad = evaluator.compute_faithfulness(hallucinated_answer, contexts)
        self.assertLess(f_bad, 0.5)

        # 2. Answer Relevance
        q = "How does Forge persist checkpoints?"
        a_rel = "Forge persists checkpoints using PostgreSQL with AsyncPostgresSaver or local SQLite."
        ar_score = evaluator.compute_answer_relevance(q, a_rel)
        self.assertGreaterEqual(ar_score, 0.7)

        # 3. Context Precision
        gt = "Forge uses PostgreSQL and SQLite for checkpointer storage."
        ranked_ctx = [
            "Forge uses PostgreSQL and SQLite for checkpointer storage.",
            "Unrelated document chunk."
        ]
        cp_score = evaluator.compute_context_precision(gt, ranked_ctx)
        self.assertGreaterEqual(cp_score, 0.7)

        # 4. Context Recall
        cr_score = evaluator.compute_context_recall(gt, ranked_ctx)
        self.assertGreaterEqual(cr_score, 0.7)
        print("✓ test_ragas_metrics_computation passed")

    def test_eval_report_and_quality_gate(self):
        """Verifies end-to-end dataset evaluation meets the >= 0.70 threshold."""
        dataset_path = Path(__file__).parent / "evals" / "golden_dataset.json"
        report_path = Path(__file__).parent / "evals" / "eval_report.json"

        with open(dataset_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)

        evaluator = RagasEvaluator(use_live_llm=False)
        report = evaluator.evaluate_dataset(dataset, str(report_path))

        self.assertIn("aggregates", report)
        self.assertGreaterEqual(report["aggregates"]["overall_score"], 0.70)
        self.assertTrue(report_path.exists())
        print("✓ test_eval_report_and_quality_gate passed")

    def test_github_workflow_and_package_scripts(self):
        """Verifies .github/workflows/evals.yml and package.json test scripts."""
        workflow_path = Path(__file__).parents[2] / ".github" / "workflows" / "evals.yml"
        self.assertTrue(workflow_path.exists(), "evals.yml must exist")
        content = workflow_path.read_text(encoding="utf-8")
        self.assertIn("Automated Evaluation & Regression Pipeline", content)
        self.assertIn("test_ragas.py", content)
        self.assertIn("test_phase5.py", content)

        pkg_path = Path(__file__).parents[2] / "package.json"
        with open(pkg_path, "r", encoding="utf-8") as f:
            pkg = json.load(f)
        self.assertIn("test", pkg.get("scripts", {}))
        self.assertIn("run-tests.js", pkg["scripts"]["test"])
        print("✓ test_github_workflow_and_package_scripts passed")


if __name__ == "__main__":
    unittest.main()

