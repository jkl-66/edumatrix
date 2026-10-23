from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.m5_api as m5_api
from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBLearningEvent, DBUser


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


def test_graph_projects_human_behaviors_and_public_sources_without_mutation(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        session.add(DBLearningEvent(
            id="le-b12-human-label",
            owner_public_id=learner.public_id,
            legacy_student_id=learner.username,
            course_id=COURSE_ID,
            event_type="internal_custom_learning_event",
            schema_version="1.0",
            idempotency_key="b12-human-label-001",
            source="test",
            trace_id="trace-b12-human-label",
            object_type="knowledge_point",
            object_id="demo-kp-01",
            action="complete",
            context_ref={"knowledge_point_id": "demo-kp-01"},
            evidence_strength=0.8,
            evidence_status="accepted",
            evidence_reason="完成一次可回溯的课程练习",
            mastery_eligible=True,
            completion_effect="progress",
            payload={"actual_minutes": 8},
        ))
        session.commit()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
        before = session.query(DBLearningEvent).count()
        summary = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=learner))
        after = session.query(DBLearningEvent).count()
        node = next(item for item in summary["knowledge_graph"]["nodes"] if item["id"] == "demo-kp-01")

        assert before == after
        assert node["behaviors"]
        behavior = next(item for item in node["behaviors"] if item["source"]["kind"] == "learning_event")
        assert behavior["label"]
        assert behavior["label"] != "internal_custom_learning_event"
        assert behavior["source"]["available"] is True
        assert "/profile/history" in behavior["source"]["route"]
        assert all("internal_custom_learning_event" not in item["value"] for item in node["evidence"])
        assert all(item["source"].get("label") for item in node["evidence"])
        assert node["nextAction"]["title"]
    finally:
        session.close()
        engine.dispose()


def test_graph_ui_uses_public_labels_and_exposes_behavior_relation_states():
    student = (ROOT / "frontend/src/views/StudentAnalysis.vue").read_text(encoding="utf-8")
    workspace = (ROOT / "frontend/src/views/KnowledgeGraphWorkspace.vue").read_text(encoding="utf-8")
    explorer = (ROOT / "frontend/src/components/KnowledgeGraphExplorer.vue").read_text(encoding="utf-8")

    assert 'data-testid="profile-node-behaviors"' in student
    assert 'data-testid="profile-node-relations"' in student
    assert "behavior.source.label" in student
    assert "item.source.label" in student
    assert "item.sourceType" not in student.split("<template>", 1)[1]
    assert "item.sourceId" not in student.split("<template>", 1)[1]
    assert 'data-testid="course-graph-node-behaviors"' in workspace
    assert "selectedProfileNode" in workspace
    assert "behavior.source.label" in workspace
    assert "defineEmits(['node-select', 'reset'])" in explorer
