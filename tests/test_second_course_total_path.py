from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBCourse, DBCourseMembership, DBUser, SessionLocal
from app.path_code_task import run_code_task
from app.second_course_total_path import build_total_path_baseline
from rag_engine import hybrid_rag
from app.auth import get_password_hash
from course_catalog import (
    CANONICAL_BUILTIN_COURSE_MANIFESTS,
    FOUNDATIONS_COURSE_ID,
    MASTER_COURSE_ID,
    SECONDARY_COURSE_ID,
    ensure_primary_course_memberships,
    ingest_course_bundle,
    load_versioned_course_bundle,
    upsert_course_bundle,
)


SECONDARY_MANIFEST = Path("data/curated/data_structures_algorithms_v1/course_manifest.json")


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def test_second_course_bundle_is_real_chinese_content_and_deterministic():
    manifest_before = SECONDARY_MANIFEST.read_bytes()
    bundle = load_versioned_course_bundle(SECONDARY_MANIFEST)
    assert manifest_before == SECONDARY_MANIFEST.read_bytes()
    assert bundle["course"]["id"] == SECONDARY_COURSE_ID
    assert bundle["course"]["language"] == "zh-CN"
    assert len(bundle["documents"]) == 14
    assert len(bundle["knowledge_points"]) == 25
    assert sum(document["chunk_count"] for document in bundle["documents"]) >= 500
    assert all(document["git_revision"] if "git_revision" in document else True for document in bundle["documents"])
    assert all(document["source_role"] == "中文主教材" for document in bundle["documents"])
    assert all("数据结构" in document["tags"] or "算法" in document["tags"] for document in bundle["documents"])


def test_all_active_accounts_receive_both_builtin_courses_idempotently():
    engine, db = _session()
    try:
        users = [
            DBUser(public_id="usr-lzz", username="lzz", hashed_password=get_password_hash("x"), role="student", is_active=True),
            DBUser(public_id="usr-demo", username="demo-student", hashed_password=get_password_hash("x"), role="student", is_active=True),
        ]
        db.add_all(users)
        for path in CANONICAL_BUILTIN_COURSE_MANIFESTS:
            upsert_course_bundle(db, load_versioned_course_bundle(path))
        db.commit()
        first = ensure_primary_course_memberships(db)
        second = ensure_primary_course_memberships(db)
        assert first["active_users"] == 2
        assert first["builtin_memberships_created_or_repaired"] == 4
        assert second["builtin_memberships_created_or_repaired"] == 0
        for user in users:
            ids = {
                row.course_id
                for row in db.query(DBCourseMembership).filter_by(user_public_id=user.public_id, status="active").all()
            }
            assert ids == {FOUNDATIONS_COURSE_ID, MASTER_COURSE_ID}
    finally:
        db.close()
        engine.dispose()


def test_total_path_has_cross_course_bridges_and_valid_schedule():
    report = build_total_path_baseline()
    assert report["status"] == "ready"
    validation = report["validation"]
    assert validation["status"] == "valid"
    assert validation["read_only"] is True
    assert validation["learning_state_written"] is False
    assert set(validation["course_ids"]) == {MASTER_COURSE_ID, SECONDARY_COURSE_ID}
    assert len(report["bridge_edges"]) == 3
    assert validation["issues"] == []
    assert len(validation["days"]) == 33
    assert validation["scheduled_minutes"] == validation["total_minutes"]


def test_path_generated_code_passes_runtime_and_theory_contract():
    report = asyncio.run(run_code_task())
    assert report["passed"] is True
    assert report["runtime"]["status"] == "success"
    assert "binary_search: PASS" in report["runtime"]["stdout"]
    assert report["theory"]["status"] == "passed"
    assert report["theory"]["complexity"] == {"time": "O(log n)", "space": "O(1)"}
    assert all(item["passed"] for item in report["theory"]["checks"])


def test_second_course_canonical_retrieval_returns_scoped_evidence():
    bundle = load_versioned_course_bundle(SECONDARY_MANIFEST)
    db = SessionLocal()
    try:
        upsert_course_bundle(db, bundle)
        ingest_course_bundle(bundle)
        db.commit()
    finally:
        db.close()
    result = hybrid_rag.retrieve(
        "二分查找 边界",
        course_id=SECONDARY_COURSE_ID,
        disable_external=True,
        top_k=3,
    )
    assert result.evidence
    assert all(item.metadata.get("course_id") == SECONDARY_COURSE_ID for item in result.evidence)
    assert any("二分" in item.title or "查找" in item.title for item in result.evidence)
