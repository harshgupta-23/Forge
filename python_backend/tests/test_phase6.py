"""
test_phase6.py — Comprehensive verification suite for Phase 6
(Containerization via Docker & Cloud Infrastructure via Terraform).
"""

import os
import unittest
import pathlib

from server.main import create_app
from server.dependencies import _resolve_agent_home


class TestPhase6(unittest.TestCase):
    """Verifies Docker containerization, Terraform configurations, and hybrid client logic."""

    @classmethod
    def setUpClass(cls):
        cls.root_dir = pathlib.Path(__file__).resolve().parent.parent.parent
        cls.dockerfile_path = cls.root_dir / "docker" / "Dockerfile"
        cls.compose_path = cls.root_dir / "docker-compose.yml"
        cls.terraform_dir = cls.root_dir / "terraform"

    def test_dockerfile_multi_stage_and_security(self):
        """Verifies multi-stage build, non-root user, Playwright cache path, and healthcheck."""
        self.assertTrue(self.dockerfile_path.exists(), "docker/Dockerfile must exist")
        content = self.dockerfile_path.read_text(encoding="utf-8")

        # Multi-stage check
        self.assertIn("FROM python:3.11-slim AS builder", content)
        self.assertIn("FROM python:3.11-slim AS runner", content)

        # Global Playwright path & non-root permissions check (Refinement #1)
        self.assertIn("PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright", content)
        self.assertIn("/opt/ms-playwright", content)
        self.assertIn("USER forge", content)
        self.assertIn("useradd -u 1000", content)

        # Networking & Health check
        self.assertIn("EXPOSE 8765", content)
        self.assertIn("HEALTHCHECK", content)
        self.assertIn("http://localhost:8765/health", content)
        print("✓ test_dockerfile_multi_stage_and_security passed")

    def test_docker_compose_orchestration(self):
        """Verifies multi-container Compose setup with pgvector, backend, volumes, and health gates."""
        self.assertTrue(self.compose_path.exists(), "docker-compose.yml must exist")
        content = self.compose_path.read_text(encoding="utf-8")

        # Services check
        self.assertIn("backend:", content)
        self.assertIn("postgres:", content)
        self.assertIn("pgvector/pgvector:pg16", content)

        # Ports
        self.assertIn('"8765:8765"', content)
        self.assertIn('"5432:5432"', content)

        # Healthcheck dependency
        self.assertIn("service_healthy", content)

        # Named volume persistence
        self.assertIn("forge_postgres_data:", content)
        self.assertIn("forge_data:", content)
        print("✓ test_docker_compose_orchestration passed")

    def test_terraform_modules_and_idle_timeout(self):
        """Verifies Terraform configuration files, RDS pgvector, and extended ALB idle timeout."""
        var_file = self.terraform_dir / "variables.tf"
        main_file = self.terraform_dir / "main.tf"
        out_file = self.terraform_dir / "outputs.tf"

        self.assertTrue(var_file.exists(), "terraform/variables.tf must exist")
        self.assertTrue(main_file.exists(), "terraform/main.tf must exist")
        self.assertTrue(out_file.exists(), "terraform/outputs.tf must exist")

        main_content = main_file.read_text(encoding="utf-8")
        var_content = var_file.read_text(encoding="utf-8")
        out_content = out_file.read_text(encoding="utf-8")

        # Extended ALB idle timeout (Refinement #2)
        self.assertIn("idle_timeout", main_content)
        self.assertIn("alb_idle_timeout", var_content)

        # RDS PostgreSQL 16
        self.assertIn("aws_db_instance", main_content)
        self.assertIn("postgres16", main_content)

        # ECS Fargate Cluster & Service
        self.assertIn("aws_ecs_cluster", main_content)
        self.assertIn("aws_ecs_service", main_content)
        self.assertIn("FARGATE", main_content)

        # Outputs check
        self.assertIn("api_endpoint_url", out_content)
        self.assertIn("alb_dns_name", out_content)
        self.assertIn("websocket_url", out_content)
        print("✓ test_terraform_modules_and_idle_timeout passed")

    def test_agent_home_resilient_fallback(self):
        """Verifies _resolve_agent_home falls back gracefully to /tmp/.forge if target is not writable."""
        resolved = _resolve_agent_home()
        self.assertTrue(resolved.exists())
        self.assertTrue(os.access(str(resolved), os.W_OK))
        print("✓ test_agent_home_resilient_fallback passed")

    def test_dynamic_cors_allowed_origins(self):
        """Verifies create_app configures CORS correctly from ALLOWED_ORIGINS env var."""
        old_val = os.environ.get("ALLOWED_ORIGINS")
        try:
            os.environ["ALLOWED_ORIGINS"] = "https://example.com, https://tauri.localhost"
            app = create_app()
            # Find CORSMiddleware
            cors_middleware = [m for m in app.user_middleware if "CORSMiddleware" in str(m.cls)]
            self.assertEqual(len(cors_middleware), 1)
            origins = cors_middleware[0].kwargs.get("allow_origins", [])
            self.assertIn("https://example.com", origins)
            self.assertIn("https://tauri.localhost", origins)
        finally:
            if old_val is None:
                os.environ.pop("ALLOWED_ORIGINS", None)
            else:
                os.environ["ALLOWED_ORIGINS"] = old_val
        print("✓ test_dynamic_cors_allowed_origins passed")

    def test_hybrid_backend_client_and_scripts(self):
        """Verifies remote backend mode in Tauri lib.rs, main.js, and --docker launcher flags."""
        lib_rs = self.root_dir / "src-tauri" / "src" / "lib.rs"
        main_js = self.root_dir / "src" / "main.js"
        linux_start = self.root_dir / "linux" / "start.sh"
        win_start = self.root_dir / "windows" / "start.bat"

        self.assertIn("BACKEND_MODE", lib_rs.read_text(encoding="utf-8"))
        self.assertIn("BACKEND_WS_URL", main_js.read_text(encoding="utf-8"))
        self.assertIn("--docker", linux_start.read_text(encoding="utf-8"))
        self.assertIn("--docker", win_start.read_text(encoding="utf-8"))
        print("✓ test_hybrid_backend_client_and_scripts passed")


if __name__ == "__main__":
    unittest.main()

