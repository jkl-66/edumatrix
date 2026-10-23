from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.m5_api as m5_api
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBAssessmentAbilityState,
    Base,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBCourse,
    DBLearningEvent,
    DBLearningPath,
    DBProfileSnapshot,
    DBReviewPlan,
    DBUser,
)
from app.m5_assessment_core import AttemptInput
from app.profile_summary import build_profile_summary


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


def test_three_profile_summary_uses_existing_evidence_and_changes_after_diagnostic(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
        before = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=learner))
        assert before["schema_version"] == "r3.profile-summary.v1"
        assert [item["key"] for item in before["sections"]] == ["skill", "cognitive", "behavior"]
        assert before["summary"]["diagnostic_response_count"] == 0
        assert before["summary"]["diagnostic_attempt_count"] == 2
        assert before["summary"]["next_action"]["route"].startswith("/workspace")
        assert "课程总评" in before["boundary"]
        graph = before["knowledge_graph"]
        assert graph["schemaVersion"] == "f4.profile-knowledge-graph.v1"
        assert graph["summary"]["nodeCount"] == 12
        assert graph["summary"]["evidenceNodeCount"] >= 5
        assert graph["summary"]["unknownNodeCount"] >= 1
        assert {item["relation"] for item in graph["edges"]} == {"prerequisite"}
        assert any(item["source"] == "demo-kp-05" and item["target"] == "demo-kp-07" for item in graph["edges"])
        for node in graph["nodes"]:
            assert {
                "masteryBand", "evidenceCount", "lastEvidenceAt",
                "sourceEventIds", "confidence", "nextAction",
            } <= node.keys()
            assert node["masteryBand"] in {"mastered", "developing", "weak", "unknown", "conflict"}
            assert 0 <= node["confidence"] <= 1
        unknown = next(item for item in graph["nodes"] if item["masteryBand"] == "unknown")
        assert unknown["mastery"] is None
        assert unknown["evidenceCount"] == 0
        assert unknown["nextAction"]["title"] == "完成一次短诊断"
        # The frozen resource_opened/reading_started demo events are browsing only.
        assert all(not item["sourceEventIds"] for item in graph["nodes"])
        assert "浏览、搜索、展开和选择节点不改变掌握度" in graph["boundary"]
        for section in before["sections"]:
            assert section["headline"] and section["next_step"]["title"]
            assert section["evidence"]
            for evidence in section["evidence"]:
                assert evidence["source_type"] and evidence["source_id"]
                assert evidence["observed_at"]
                assert evidence["recommendation_impact"]

        question = session.query(DBAssessmentQuestion).filter_by(course_id=COURSE_ID).order_by(
            DBAssessmentQuestion.id,
        ).first()
        version = session.get(DBAssessmentQuestionVersion, question.current_version_id)
        payload = AttemptInput(
            question_version_id=version.id,
            idempotency_key="r3-profile-summary-attempt-001",
            mode="diagnostic",
            answer={"value": version.answer_key["value"]},
        )
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        result = _run(m5_api.submit_assessment_attempt(request, payload, current_user=learner))
        assert result["ability_update"]["applied"] is True

        after = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=learner))
        assert after["summary"]["diagnostic_response_count"] == 1
        assert after["summary"]["diagnostic_attempt_count"] == 3
        skill = next(item for item in after["sections"] if item["key"] == "skill")
        assert any(item["source_type"] == "assessment_ability_state" for item in skill["evidence"])
        assert any(item["source_type"] == "assessment_attempt" for item in skill["evidence"])
        assert after["summary"]["evidence_count"] > before["summary"]["evidence_count"]
        updated_node = next(
            item for item in after["knowledge_graph"]["nodes"]
            if item["id"] == version.primary_knowledge_point_id
        )
        assert updated_node["evidenceCount"] >= 1
        assert any(item["sourceId"] == result["id"] for item in updated_node["evidence"])
    finally:
        session.close()
        engine.dispose()


def test_skill_summary_prefers_named_course_weak_points_over_generic_ability_uncertainty():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        snapshot = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        snapshot_payload = dict(snapshot.snapshot or {})
        snapshot_payload.pop("weak_knowledge_point_ids", None)
        snapshot_payload["weak_points"] = [
            "Coding Agent、MCP 与 Skill",
            "优化算法、正则化与训练稳定性",
        ]
        snapshot.snapshot = snapshot_payload
        session.add(DBAssessmentAbilityState(
            owner_public_id=learner.public_id,
            course_scope=COURSE_ID,
            theta=[0.2, 0.1, -0.2],
            theta_std=[0.8, 0.8, 0.9],
            response_count=8,
        ))
        session.flush()

        result = build_profile_summary(session, current_user=learner, course_id=COURSE_ID)
        skill = next(item for item in result["sections"] if item["key"] == "skill")
        assert skill["difficulties"] == snapshot_payload["weak_points"]
        assert all("仍需更多证据确认" not in item for item in skill["difficulties"])
    finally:
        session.close()
        engine.dispose()


def test_profile_graph_reads_are_owner_scoped_and_do_not_mutate_learning_state(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)

        def counts():
            return {
                "events": session.query(DBLearningEvent).count(),
                "snapshots": session.query(DBProfileSnapshot).count(),
                "paths": session.query(DBLearningPath).count(),
                "reviews": session.query(DBReviewPlan).count(),
            }

        before = counts()
        first = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=learner))
        second = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=learner))
        assert counts() == before
        assert first["knowledge_graph"] == second["knowledge_graph"]
        assert first["owner"]["public_id"] == learner.public_id
        assert all(
            evidence["sourceId"]
            for node in first["knowledge_graph"]["nodes"]
            for evidence in node["evidence"]
        )
    finally:
        session.close()
        engine.dispose()


def test_profile_summary_allows_public_course_but_rejects_private_non_member_and_exposes_shared_panel(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        outsider = DBUser(
            public_id="usr-r3-profile-outsider",
            username="r3-profile-outsider",
            hashed_password="not-used",
            role="student",
        )
        session.add(outsider)
        session.commit()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
        public_summary = _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=outsider))
        assert public_summary["course"]["id"] == COURSE_ID
        course = session.get(DBCourse, COURSE_ID)
        course.visibility = "private"
        session.flush()
        with pytest.raises(HTTPException) as forbidden:
            _run(m5_api.get_profile_summary(course_id=COURSE_ID, current_user=outsider))
        assert forbidden.value.status_code == 409
        assert forbidden.value.detail["code"] == "course_unavailable"

        component = (ROOT / "frontend/src/components/ProfileSummaryPanel.vue").read_text(encoding="utf-8")
        assessment = (ROOT / "frontend/src/views/AssessmentWorkspace.vue").read_text(encoding="utf-8")
        profile = (ROOT / "frontend/src/views/StudentAnalysis.vue").read_text(encoding="utf-8")
        for marker in (
            'data-testid="profile-summary"',
            "profile-section-${section.key}",
            "查看来源、时间与推荐影响",
            "recommendation_impact",
        ):
            assert marker in component
        assert "summaryPanel.value?.refresh()" in assessment
        assert "ProfileSummaryPanel" in assessment
        assert "ProfileSummaryPanel" in profile
    finally:
        session.close()
        engine.dispose()
