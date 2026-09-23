"""
conftest.py — Shared fixtures for Forge backend tests.
"""

import sys
import os
import tempfile
import pathlib
import pytest

# Ensure python_backend is on sys.path
backend_dir = pathlib.Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Set a dummy API_KEY so imports don't fail on missing env
if not os.environ.get("API_KEY"):
    os.environ["API_KEY"] = "test-key-for-ci"


@pytest.fixture
def tmp_work_dir():
    """Provides a temporary workspace directory for security tests."""
    with tempfile.TemporaryDirectory() as d:
        yield pathlib.Path(d).resolve()


@pytest.fixture
def tmp_db_path():
    """Provides a temporary SQLite DB path for storage tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = pathlib.Path(f.name)
    yield path
    path.unlink(missing_ok=True)
