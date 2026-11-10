"""Process-wide test isolation configured before application modules import."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import shutil
import tempfile
from functools import lru_cache

import pytest


_TEST_RUNTIME = Path(tempfile.mkdtemp(prefix="edumatrix-pytest-"))
_TEST_DATABASE = _TEST_RUNTIME / "edumatrix-test.sqlite3"

os.environ["EDUMATRIX_ENV"] = "test"
os.environ["TESTING"] = "true"
os.environ["EDUMATRIX_GENERATION_WORKER"] = "false"
os.environ["EDUMATRIX_DB_PATH"] = str(_TEST_DATABASE)
os.environ["EDUMATRIX_ALIGNMENT_DATA_DIR"] = str(_TEST_RUNTIME / "alignment")

# Runtime-oriented tests use the application's global SessionLocal rather than
# a per-test in-memory fixture. Build the isolated process database before test
# modules are collected so audited model calls and other shared services see
# the same complete schema as a real application startup.
from app.database import init_db

init_db()


def _cleanup_test_runtime() -> None:
    shutil.rmtree(_TEST_RUNTIME, ignore_errors=True)


atexit.register(_cleanup_test_runtime)


@pytest.fixture(scope="session", autouse=True)
def reuse_demo_seed_password_hashes():
    """Reuse fixed fixture credentials across isolated demo databases.

    Seed-heavy tests otherwise repeat the same expensive bcrypt hashes for
    every database. Registration, login verification and production hashing
    retain their real implementations and cost parameters.
    """
    import app.competition_demo_seed as demo_seed

    original = demo_seed.get_password_hash
    demo_seed.get_password_hash = lru_cache(maxsize=8)(original)
    try:
        yield
    finally:
        demo_seed.get_password_hash = original
