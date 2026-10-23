"""Process-wide test isolation configured before application modules import."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import shutil
import tempfile


_TEST_RUNTIME = Path(tempfile.mkdtemp(prefix="edumatrix-pytest-"))
_TEST_DATABASE = _TEST_RUNTIME / "edumatrix-test.sqlite3"

os.environ["EDUMATRIX_ENV"] = "test"
os.environ["TESTING"] = "true"
os.environ["EDUMATRIX_DB_PATH"] = str(_TEST_DATABASE)

# Runtime-oriented tests use the application's global SessionLocal rather than
# a per-test in-memory fixture. Build the isolated process database before test
# modules are collected so audited model calls and other shared services see
# the same complete schema as a real application startup.
from app.database import init_db

init_db()


def _cleanup_test_runtime() -> None:
    shutil.rmtree(_TEST_RUNTIME, ignore_errors=True)


atexit.register(_cleanup_test_runtime)
