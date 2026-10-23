from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.m5_api as m5_api
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBLearningPath,
    DBPlanDraft,
    DBPlanVersion,
    DBUser,
)


ROOT = Path(__file__).resolve().parents[1]
COURSE_ID = "demo-course-rag-trust-v1"


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _run(awaitable):
    return asyncio.run(awaitable)


def test_textbook_draft_is_explainable_idempotent_and_confirmed_through_existing_lifecycle(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
        before = _run(m5_api.get_textbook_path_draft(
            course_id=COURSE_ID, current_user=learner,
        ))
        assert before["state"] == "confirmed"
        assert before["plan"]["confirmed_version_id"] == before["plan"]["current_version_id"]
        active_before = session.query(DBLearningPath).filter_by(
            owner_public_id=learner.public_id, course_id=COURSE_ID, status="active",
        ).one()

        generated = _run(m5_api.generate_textbook_path_draft_api(
            m5_api.TextbookPathDraftRequest(course_id=COURSE_ID, time_budget_minutes=90),
            current_user=learner,
        ))
        assert generated["state"] == "draft_ready"
        assert generated["changed"] is True
        assert generated["plan"]["status"] == "replan_pending"
        assert generated["plan"]["current_version_id"] != generated["plan"]["confirmed_version_id"]
        assert generated["diff"] and generated["diff"]["summary"]
        assert generated["evidence"]["weak_knowledge_point_ids"] == ["demo-kp-06", "demo-kp-07"]
        assert len(generated["nodes"]) >= 4
        assert all(item["chapter"] and item["source"]["document_id"] for item in generated["nodes"])
        assert all(item["source"]["content_hash"] for item in generated["nodes"])
        assert any(
            kp["is_weak"] for item in generated["nodes"] for kp in item["knowledge_points"]
        )
        assert any("先修" in item["reason"] for item in generated["nodes"])

        version_count = session.query(DBPlanVersion).filter_by(
            plan_draft_id=generated["plan"]["id"],
        ).count()
        replay = _run(m5_api.generate_textbook_path_draft_api(
            m5_api.TextbookPathDraftRequest(course_id=COURSE_ID, time_budget_minutes=90),
            current_user=learner,
        ))
        assert replay["changed"] is False
        assert session.query(DBPlanVersion).filter_by(
            plan_draft_id=generated["plan"]["id"],
        ).count() == version_count

        rebuilt = _run(m5_api.generate_textbook_path_draft_api(
            m5_api.TextbookPathDraftRequest(course_id=COURSE_ID, time_budget_minutes=60),
            current_user=learner,
        ))
        assert rebuilt["changed"] is True
        assert rebuilt["plan"]["status"] == "replan_pending"
        assert rebuilt["plan"]["confirmed_version_id"] == generated["plan"]["confirmed_version_id"]
        assert rebuilt["plan"]["current_version_id"] != generated["plan"]["current_version_id"]
        assert rebuilt["plan"]["total_minutes"] <= 60
        assert session.query(DBLearningPath).filter_by(
            owner_public_id=learner.public_id, course_id=COURSE_ID, status="active",
        ).one().id == active_before.id
        assert session.query(DBPlanVersion).filter_by(
            plan_draft_id=generated["plan"]["id"],
        ).count() == version_count + 1

        rebuilt_replay = _run(m5_api.generate_textbook_path_draft_api(
            m5_api.TextbookPathDraftRequest(course_id=COURSE_ID, time_budget_minutes=60),
            current_user=learner,
        ))
        assert rebuilt_replay["changed"] is False
        assert rebuilt_replay["plan"]["current_version_id"] == rebuilt["plan"]["current_version_id"]
        assert session.query(DBPlanVersion).filter_by(
            plan_draft_id=generated["plan"]["id"],
        ).count() == version_count + 1

        confirmed = _run(m5_api.confirm_learning_plan(
            rebuilt["plan"]["id"],
            m5_api.PlanConfirmRequest(expected_lock_version=rebuilt_replay["plan"]["lock_version"]),
            current_user=learner,
        ))
        assert confirmed["plan"]["status"] == "confirmed"
        assert confirmed["plan"]["confirmed_version_id"] == confirmed["plan"]["current_version_id"]
        assert confirmed["path"]["supersedes_path_id"] == active_before.id
        session.refresh(active_before)
        assert active_before.status == "archived"
        assert all(item["node_type"] == "chapter" for item in confirmed["path"]["nodes"])
        after = _run(m5_api.get_textbook_path_draft(
            course_id=COURSE_ID, current_user=learner,
        ))
        assert after["state"] == "confirmed"
        assert after["diff"] is None
    finally:
        session.close()
        engine.dispose()


def test_textbook_draft_rejects_non_member_and_frontend_has_confirmation_contract(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        outsider = DBUser(
            public_id="usr-r3-path-outsider",
            username="r3-path-outsider",
            hashed_password="not-used",
            role="student",
        )
        session.add(outsider)
        session.commit()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
        with pytest.raises(HTTPException) as forbidden:
            _run(m5_api.get_textbook_path_draft(
                course_id=COURSE_ID, current_user=outsider,
            ))
        assert forbidden.value.status_code == 403

        api = (ROOT / "frontend/src/api/m5.js").read_text(encoding="utf-8")
        view = (ROOT / "frontend/src/views/LearningPathGraph.vue").read_text(encoding="utf-8")
        assert "getM5TextbookPathDraft" in api
        assert "generateM5TextbookPathDraft" in api
        for marker in (
            'data-testid="textbook-path-draft"',
            'data-testid="generate-textbook-path-draft"',
            'data-testid="confirm-textbook-path-draft"',
            "教材锚定路径草稿",
            "版本变化",
            "用户确认前仅为草稿",
        ):
            assert marker in view
    finally:
        session.close()
        engine.dispose()
