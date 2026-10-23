from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
import app.competition_demo_api as demo_api
from app.competition_demo_context import build_competition_demo_context
from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBReviewPlan, DBUser


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_context_composes_one_canonical_nonempty_demo_scope():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        student = session.query(DBUser).filter_by(username="lzz").one()
        context = build_competition_demo_context(session, student)

        assert context["initialized"] is True
        assert context["issues"] == []
        assert context["course"]["id"] == "demo-course-rag-trust-v1"
        assert context["course"]["source_count"] == 9
        assert context["course"]["chapter_count"] == 12
        assert context["course"]["knowledge_point_count"] == 12
        assert [item["title"] for item in context["path"]["tasks"]] == [
            "精读混合检索来源", "调优 Recall@K 交互实验", "完成混合检索短测",
        ]
        assert [item["knowledge_point_title"] for item in context["reviews"]] == [
            "混合检索与重排", "引用约束与拒答",
        ]
        assert context["focus_student"]["mastery"] == 0.58
        assert [item["title"] for item in context["focus_student"]["weak_knowledge_points"]] == [
            "向量检索", "混合检索与重排",
        ]
        assert context["cohort"] == {
            "id": "demo-cohort-rag-2026-a",
            "class_id": "demo-class-rag-2026-a",
            "title": "RAG 可信应用实训 2026 演示班",
            "student_count": 15,
            "participated_count": 12,
            "participation_rate": 0.8,
            "attention_count": 4,
            "average_mastery": 0.7,
            "metric_source": "15 份冻结合成画像快照的确定性聚合",
            "time_window": "frozen_demo_window_v1",
        }
        assert set(context["page_contracts"]) == {
            "dashboard", "knowledge", "path", "profile", "review", "teacher", "showcase",
        }
        assert all(item["status"] and item["next_step"] and item["primary_action"] for item in context["page_contracts"].values())
    finally:
        session.close()
        engine.dispose()


def test_context_excludes_unrelated_focus_student_review_history():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        session.add(DBReviewPlan(
            student_id="lzz",
            concept="unrelated-personal-history",
            interval_days=7,
            mastery=0.8,
            review_count=4,
            easiness_factor=2.5,
            last_quality=4,
            similar_quiz_ids=["personal-quiz-001"],
            priority=0.9,
        ))
        session.commit()

        admin = session.query(DBUser).filter_by(username="demo-admin").one()
        context = build_competition_demo_context(session, admin)

        assert context["initialized"] is True
        assert context["issues"] == []
        assert len(context["reviews"]) == 2
        assert {item["knowledge_point_id"] for item in context["reviews"]} == {
            "demo-kp-07",
            "demo-kp-08",
        }
        assert session.query(DBReviewPlan).filter_by(
            student_id="lzz", concept="unrelated-personal-history",
        ).count() == 1
    finally:
        session.close()
        engine.dispose()


def test_context_is_role_aware_and_rejects_outside_accounts():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        visitor = session.query(DBUser).filter_by(username="demo-visitor").one()
        visitor_context = build_competition_demo_context(session, visitor)
        assert visitor_context["focus_student"] is None
        assert visitor_context["path"] is None
        assert visitor_context["reviews"] == []

        outside = DBUser(public_id="usr-outside-r1", username="outside-r1", hashed_password="x", role="student")
        session.add(outside)
        session.commit()

        app = FastAPI()
        app.include_router(demo_api.router)

        async def fake_run_db_op(func, *args, **kwargs):
            return func(session, *args, **kwargs)

        original = demo_api.run_db_op
        demo_api.run_db_op = fake_run_db_op
        app.dependency_overrides[get_current_user] = lambda: outside
        client = TestClient(app)
        try:
            response = client.get("/api/v1/competition-demo/context")
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "competition_demo_scope_required"
        finally:
            client.close()
            demo_api.run_db_op = original
    finally:
        session.close()
        engine.dispose()


def test_context_reports_recovery_state_before_admin_initialization():
    engine, session = _session()
    try:
        admin = DBUser(public_id="usr-admin-r1", username="admin-r1", hashed_password="x", role="admin")
        session.add(admin)
        session.commit()
        context = build_competition_demo_context(session, admin)
        assert context["initialized"] is False
        assert context["issues"] == ["course_missing"]
        assert context["page_contracts"]["showcase"]["primary_action"]["route"] == "/competition-showcase"
    finally:
        session.close()
        engine.dispose()


def test_main_application_registers_competition_demo_context_route():
    from app.main import app

    assert set(app.openapi()["paths"]["/api/v1/competition-demo/context"]) == {"get"}
