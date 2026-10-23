from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.dashboard_summary import build_dashboard_summary
from app.database import (
    Base,
    DBCourse,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningEventConsumption,
    DBProfileSnapshot,
    DBUser,
)
from app.m5_workspace import M5WorkspaceError


ROOT = Path(__file__).resolve().parents[1]


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _course(db, suffix: str = "main"):
    user = DBUser(
        public_id=f"usr-p1-b33-{suffix}",
        username=f"p1-b33-{suffix}",
        hashed_password="unused",
        role="student",
    )
    course = DBCourse(
        id=f"course-p1-b33-{suffix}",
        owner_public_id=user.public_id,
        title="机器学习导论",
        version="course-v3",
        subject="AI/ML",
        status="published",
        visibility="private",
        manifest_version="manifest-v3",
        content_origin="团队课程知识库",
    )
    point = DBKnowledgePoint(
        id=f"kp-p1-b33-{suffix}",
        domain_pack="ml",
        code=f"ML-{suffix}",
        version="kp-v1",
        title="梯度下降",
    )
    db.add_all([user, course, point])
    db.commit()
    return user, course, point


def _snapshot(db, user, course, point, *, complete: bool = True):
    body = {
        "kind": "continuous_profile_update",
        "course_id": course.id,
        "weak_knowledge_point_ids": [point.id],
        "profile_projection": {},
    }
    if complete:
        body.update({
            "mastery_by_knowledge_point": {
                point.id: {
                    "score": 0.42,
                    "status": "weak",
                    "source_ref_ids": ["source-p1-b33-1"],
                },
            },
            "dimension_states": {
                "knowledge_mastery": {
                    "label": "知识基础与掌握度",
                    "status": "需要巩固",
                    "score": 0.42,
                    "source_turn_id": "turn-p1-b33",
                },
            },
            "source_turn_id": "turn-p1-b33",
            "weak_point_attribution": [{
                "weakPoint": point.id,
                "reason": "最近作答中梯度方向判断不稳定",
                "evidence": "学生在诊断作答中混淆了梯度与参数更新方向",
                "dimension_keys": ["knowledge_mastery"],
            }],
        })
    snapshot = DBProfileSnapshot(
        id=f"ps-p1-b33-{course.id}",
        owner_public_id=user.public_id,
        legacy_student_id=user.username,
        profile_version="profile.continuous.v4",
        snapshot=body,
        content_hash="snapshot-content",
        trace_id="trace-p1-b33",
    )
    db.add(snapshot)
    db.commit()
    return snapshot


def test_dashboard_weak_summary_projects_evidence_event_and_context_without_writes():
    engine, db = _db()
    try:
        user, course, point = _course(db)
        snapshot = _snapshot(db, user, course, point)
        event = DBLearningEvent(
            owner_public_id=user.public_id,
            legacy_student_id=user.username,
            course_id=course.id,
            event_type="quiz_answered",
            source="test",
            trace_id="event-trace-p1-b33",
            object_type="knowledge_point",
            object_id=point.id,
            action="answer",
            context_ref={"knowledgePointId": point.id},
            evidence_strength=1.0,
            evidence_status="accepted",
            evidence_reason="真实作答证据",
            mastery_eligible=True,
            completion_effect="progress",
            payload={"score": 0.42},
        )
        db.add(event)
        db.flush()
        db.add(DBLearningEventConsumption(
            learning_event_id=event.id,
            consumer="learning_aggregation",
            processor_version="p1-b33-test",
            status="processed",
            result={},
        ))
        db.commit()
        before = {
            "snapshots": db.query(DBProfileSnapshot).count(),
            "events": db.query(DBLearningEvent).count(),
            "consumptions": db.query(DBLearningEventConsumption).count(),
        }

        summary = build_dashboard_summary(db, current_user=user, course_id=course.id)
        card = summary["weak_summary"][0]
        assert card["knowledge_point_id"] == point.id
        assert card["title"] == point.title
        assert card["mastery"] == 0.42
        assert card["mastery_status"] == "supported"
        assert card["weak_reason"] == "最近作答中梯度方向判断不稳定"
        assert card["profile_dimensions"][0]["key"] == "knowledge_mastery"
        assert card["course_snapshot"] == {
            "course_id": course.id,
            "course_title": course.title,
            "course_version": course.version,
            "snapshot_id": snapshot.id,
            "snapshot_version": snapshot.profile_version,
        }
        assert {ref["id"] for ref in card["source_refs"]} >= {snapshot.id, "source-p1-b33-1"}
        assert card["event_refs"][0]["id"] == event.id
        assert card["next_action"]["course_id"] == course.id
        assert card["next_action"]["knowledge_point_id"] == point.id
        assert f"course_id={course.id}" in card["next_action"]["route"]
        assert f"knowledge_point_id={point.id}" in card["next_action"]["route"]
        assert summary["read_only"] is True
        assert {
            "snapshots": db.query(DBProfileSnapshot).count(),
            "events": db.query(DBLearningEvent).count(),
            "consumptions": db.query(DBLearningEventConsumption).count(),
        } == before
    finally:
        db.close()
        engine.dispose()


def test_dashboard_weak_summary_unknown_fields_are_not_invented_and_course_isolation_holds():
    engine, db = _db()
    try:
        user, course, point = _course(db, "unknown")
        _snapshot(db, user, course, point, complete=False)
        summary = build_dashboard_summary(db, current_user=user, course_id=course.id)
        card = summary["weak_summary"][0]
        assert card["mastery"] is None
        assert card["mastery_status"] == "unknown"
        assert "待确认" in card["weak_reason"]
        assert card["weak_reason_status"] == "unknown"
        assert card["profile_dimensions"][0]["status"] == "待确认"
        assert card["event_refs"] == []
        assert card["next_action"]["available"] is True

        other_user, other_course, other_point = _course(db, "other")
        _snapshot(db, other_user, other_course, other_point)
        with pytest.raises(M5WorkspaceError):
            build_dashboard_summary(db, current_user=user, course_id=other_course.id)
    finally:
        db.close()
        engine.dispose()


def test_dashboard_weak_summary_empty_states_explain_missing_snapshot_or_weak_points():
    engine, db = _db()
    try:
        user, course, point = _course(db, "empty")
        no_snapshot = build_dashboard_summary(db, current_user=user, course_id=course.id)
        assert no_snapshot["weak_summary"] == []

        snapshot = _snapshot(db, user, course, point)
        snapshot.snapshot = {"course_id": course.id, "profile_projection": {}}
        db.commit()
        no_weak = build_dashboard_summary(db, current_user=user, course_id=course.id)
        assert no_weak["weak_summary"] == []
    finally:
        db.close()
        engine.dispose()


def test_dashboard_frontend_renders_weak_evidence_and_keeps_side_inset():
    source = (ROOT / "frontend/src/views/Dashboard.vue").read_text(encoding="utf-8")
    for token in (
        "item.weak_reason",
        "weakMasteryLabel(item)",
        "item.profile_dimensions",
        "weakSnapshotLabel(item)",
        "item.source_refs",
        "item.event_refs",
        "item.next_action?.route",
        "weakSummaryEmptyCopy",
        "dashboard-weak-item",
    ):
        assert token in source
    assert ".dashboard-side-summary > section { padding: 24px 18px;" in source
    assert "recommendation_score" not in source
