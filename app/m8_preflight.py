"""Truthful deployment/demo readiness report without secret disclosure."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.database import engine
from app.m5_api import runtime_availability
from app.migrations import MIGRATIONS
from config import CONFIG


ROOT = Path(__file__).resolve().parents[1]


def deployment_preflight() -> dict[str, Any]:
    """Return capabilities and blockers, never configuration values."""
    latest_schema = MIGRATIONS[-1].version if MIGRATIONS else None
    database_available = False
    applied_schema: str | None = None
    initialized_users = 0
    initialized_domains = 0
    database_error_code: str | None = None
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            database_available = True
            applied_schema = connection.execute(
                text("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1")
            ).scalar()
            initialized_users = int(connection.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0)
            initialized_domains = int(connection.execute(text("SELECT COUNT(*) FROM domain_packs")).scalar() or 0)
    except Exception as exc:
        database_error_code = type(exc).__name__

    runtime = runtime_availability()
    frontend_dist = ROOT / "frontend" / "dist" / "index.html"
    schema_current = database_available and applied_schema == latest_schema
    data_initialized = initialized_users > 0 and initialized_domains > 0

    checks = {
        "database": {"available": database_available, "required": True, "error_code": database_error_code},
        "schema": {"current": schema_current, "applied": applied_schema, "expected": latest_schema, "required": True},
        "data_initialization": {"ready": data_initialized, "users": initialized_users, "domain_packs": initialized_domains, "required": True},
        "frontend_build": {"available": frontend_dist.is_file(), "required": True},
        "text_model": {"available": runtime.text_model, "required": True},
        "vision_model": {"available": runtime.vision_model, "required": False},
        "retrieval": {"available": runtime.retrieval, "required": True},
        "sandbox": {"available": runtime.sandbox_mode != "disabled", "mode": runtime.sandbox_mode, "required": False},
        "media_pipeline": {"available": runtime.media_pipeline, "required": False},
    }

    blockers: list[dict[str, str]] = []
    if not database_available:
        blockers.append({"code": "database_unavailable", "remediation": "start the backend and initialize the SQLite database"})
    if database_available and not schema_current:
        blockers.append({"code": "schema_not_current", "remediation": "run the registered database migrations"})
    if database_available and not data_initialized:
        blockers.append({"code": "demo_data_missing", "remediation": "run python scripts/seed_students.py and initialize the domain pack"})
    if not frontend_dist.is_file():
        blockers.append({"code": "frontend_build_missing", "remediation": "run npm --prefix frontend run build"})
    if not runtime.text_model:
        blockers.append({"code": "text_model_unavailable", "remediation": "configure a real model in backend environment variables"})
    if not runtime.retrieval:
        blockers.append({"code": "retrieval_index_missing", "remediation": "download course data and run scripts/ingest_to_faiss.py"})

    return {
        "schema_version": "m8.deployment-preflight.v1",
        "status": "ready" if not blockers else "not_ready",
        "generation_allowed": not blockers,
        "checks": checks,
        "blockers": blockers,
        "configuration": {
            "backend_model_key_configured": bool(CONFIG.llm_api_key),
            "client_keys_accepted": False,
            "secret_values_included": False,
        },
    }
