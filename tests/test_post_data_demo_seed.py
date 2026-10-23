from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_seed import (
    competition_demo_status,
    reset_competition_demo,
    seed_competition_demo,
)
from app.auth import get_current_user
from app import chat_api, m5_api, review_schedule_api
from app.crud import load_student_profile
from app.database import (
    Base,
    DBAssessmentExam,
    DBAssessmentExamSitting,
    DBArtifact,
    DBArtifactVersion,
    DBChatConversation,
    DBChatMessage,
    DBCourse,
    DBCourseMembership,
    DBLearningEvent,
    DBLearningPath,
    DBNote,
    DBNoteVersion,
    DBPathNode,
    DBProfileSnapshot,
    DBReviewPlan,
    DBStudentProfile,
    DBUser,
    DBWrongQuestion,
)
from app.m5_workspace import workspace_overview
from app.post_data_demo_seed import (
    CONVERSATION_ID,
    COURSE_ID,
    EXAM_ID,
    NOTE_ID,
    NOTE_VERSION_ID,
    PATH_ID,
    PROFILE_ID,
    RESOURCE_SPECS,
    SITTING_ID,
    post_data_demo_issues,
    post_data_stable_ids,
)


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _owner(session):
    return session.query(DBUser).filter_by(username="lzz").one()


def test_post_data_overlay_is_idempotent_and_complete():
    engine, session = _session()
    try:
        first = seed_competition_demo(session)
        owner = _owner(session)
        stable_ids = post_data_stable_ids(session, owner=owner)

        second = seed_competition_demo(session)

        assert first.status == "created"
        assert second.status == "unchanged"
        assert second.created_count == 0
        assert post_data_demo_issues(session, owner=owner) == []
        assert post_data_stable_ids(session, owner=owner) == stable_ids
        assert all(value is not None for key, value in stable_ids.items() if key != "resources")
        assert len(stable_ids["resources"]) == len(RESOURCE_SPECS) == 9

        profile = session.get(DBProfileSnapshot, PROFILE_ID)
        legacy_profile = session.get(DBStudentProfile, owner.username)
        path = session.get(DBLearningPath, PATH_ID)
        assert profile.owner_public_id == owner.public_id
        assert profile.snapshot["course_id"] == COURSE_ID
        assert legacy_profile.target_course == session.get(DBCourse, COURSE_ID).title
        assert len(legacy_profile.concept_mastery) == 8
        restored_profile = load_student_profile(session, owner.username)
        assert restored_profile is not None
        assert restored_profile.profile_evidence[-1].source.value == "performance_signal"
        assert legacy_profile.profile_evidence[-1]["origin"] == "frozen_synthetic_course_journey"
        assert path.status == "active"
        assert session.query(DBPathNode).filter_by(learning_path_id=PATH_ID).count() == 8

        artifacts = session.query(DBArtifact).filter_by(
            owner_public_id=owner.public_id, course_id=COURSE_ID,
        ).filter(DBArtifact.id.like("postdata-resource-eml-%")).all()
        assert {row.artifact_type for row in artifacts} == {item[0] for item in RESOURCE_SPECS}
        for artifact in artifacts:
            version = session.get(DBArtifactVersion, artifact.current_version_id)
            assert version is not None
            assert version.content.strip()
            if version.content_format == "json":
                assert json.loads(version.content)
        video = next(row for row in artifacts if row.artifact_type == "video")
        video_version = session.get(DBArtifactVersion, video.current_version_id)
        local_files = video_version.metadata_json["local_video_files"]
        assert len(local_files) == 1
        assert next(iter(local_files.values())).endswith(".mp4")

        assert session.get(DBNote, NOTE_ID) is not None
        assert session.get(DBNoteVersion, NOTE_VERSION_ID) is not None
        assert session.get(DBChatConversation, CONVERSATION_ID) is not None
        assert session.query(DBChatMessage).filter_by(conversation_id=CONVERSATION_ID).count() == 2
        assert session.get(DBAssessmentExam, EXAM_ID).status == "open"
        assert session.get(DBAssessmentExamSitting, SITTING_ID).status == "assigned"
        assert session.query(DBLearningEvent).filter_by(
            owner_public_id=owner.public_id, course_id=COURSE_ID,
        ).filter(DBLearningEvent.id.like("postdata-event-lzz-eml-%")).count() == 9
    finally:
        session.close()
        engine.dispose()


def test_post_data_reset_repairs_in_place_and_preserves_unrelated_course():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        owner = _owner(session)
        stable_ids = post_data_stable_ids(session, owner=owner)
        session.add(DBCourse(
            id="course-user-owned", version="1", title="用户自建课程",
            owner_public_id=owner.public_id, visibility="private", status="published",
            manifest_version="1", manifest_data={"scope": "user-owned"},
        ))
        session.add(DBCourseMembership(
            id="membership-user-owned", course_id="course-user-owned",
            user_public_id=owner.public_id, role="student", status="active",
        ))
        artifact = session.get(DBArtifact, "postdata-resource-eml-handout")
        artifact.status = "archived"
        review = session.get(DBReviewPlan, stable_ids["review"])
        review.mastery = 0.99
        wrong = session.get(DBWrongQuestion, stable_ids["wrong_question"])
        wrong.notes = "用户修改后的错误内容"
        session.commit()

        degraded = competition_demo_status(session)
        assert degraded.status == "degraded"
        assert "postdata:resource_state" in degraded.issues

        reset = reset_competition_demo(session)

        assert reset.before_status == "degraded"
        assert reset.after_status == "ready"
        assert post_data_stable_ids(session, owner=owner) == stable_ids
        assert session.get(DBArtifact, artifact.id).status == "approved"
        assert session.get(DBReviewPlan, stable_ids["review"]).mastery == 0.42
        assert "先核查误报样本" in session.get(DBWrongQuestion, stable_ids["wrong_question"]).notes
        assert session.get(DBCourse, "course-user-owned").title == "用户自建课程"
        assert session.get(DBCourseMembership, "membership-user-owned").status == "active"

        unchanged = reset_competition_demo(session)
        assert unchanged.before_status == "ready"
        assert unchanged.after_status == "ready"
        assert unchanged.deleted_counts == {}
    finally:
        session.close()
        engine.dispose()


def test_post_data_course_is_default_workspace_and_browsing_is_not_mastery_evidence():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        owner = _owner(session)

        overview = workspace_overview(session, current_user=owner)
        browse = session.get(DBLearningEvent, "postdata-event-lzz-eml-browse")

        assert overview["state"] == "ready"
        assert overview["course"]["id"] == COURSE_ID
        assert overview["current_path"]["id"] == PATH_ID
        assert overview["profile"] is not None
        assert overview["recent_artifacts"]
        assert browse.evidence_status == "none"
        assert browse.mastery_eligible is False
        assert browse.completion_effect == "none"
        assert browse.payload["truthfulness"] == "frozen_synthetic_demo_data"
    finally:
        session.close()
        engine.dispose()


def test_post_data_learning_surfaces_are_readable_through_http(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        owner = _owner(session)
        app = FastAPI()
        app.include_router(m5_api.router)
        app.include_router(chat_api.router)
        app.include_router(review_schedule_api.router)
        app.dependency_overrides[get_current_user] = lambda: owner

        async def fake_run_db_op(func, *args, **kwargs):
            return func(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
        monkeypatch.setattr(chat_api, "run_db_op", fake_run_db_op)
        monkeypatch.setattr(review_schedule_api, "run_db_op", fake_run_db_op)
        client = TestClient(app)

        workspace = client.get("/api/v1/m5/workspace")
        profile = client.get("/api/v1/m5/profile-summary", params={"course_id": COURSE_ID})
        resources = client.get("/api/v1/m5/resources", params={"course_id": COURSE_ID, "limit": 25})
        exams = client.get("/api/v1/m5/assessment/exams")
        conversations = client.get("/api/v1/chat/conversations")
        conversation = client.get(f"/api/v1/chat/conversations/{CONVERSATION_ID}")
        review = client.get(
            "/api/v1/review-schedule",
            params={"month": "2026-08", "course_id": COURSE_ID},
        )

        assert workspace.status_code == 200
        assert workspace.json()["course"]["id"] == COURSE_ID
        assert workspace.json()["current_path"]["id"] == PATH_ID
        assert profile.status_code == 200
        assert profile.json()["course"]["id"] == COURSE_ID
        assert len(profile.json()["knowledge_graph"]["nodes"]) == 8
        assert resources.status_code == 200
        assert resources.json()["total"] == 9
        assert {item["artifact_type"] for item in resources.json()["items"]} == {
            item[0] for item in RESOURCE_SPECS
        }
        assert exams.status_code == 200
        assert any(item["id"] == EXAM_ID for item in exams.json()["items"])
        assert conversations.status_code == 200
        assert any(item["id"] == CONVERSATION_ID for item in conversations.json()["items"])
        assert conversation.status_code == 200
        assert len(conversation.json()["messages"]) == 2
        assert review.status_code == 200
        assert review.json()["selected_course_id"] == COURSE_ID
        assert review.json()["tasks"]
    finally:
        session.close()
        engine.dispose()
