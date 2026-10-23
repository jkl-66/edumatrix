from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import (
    Base,
    DBArtifact,
    DBCourse,
    DBLearningEvent,
    DBLearningEventConsumption,
    DBStudentProfile,
    DBUser,
)
from app.main import app
from app.profile_summary import ProfileSummaryError, build_personal_activity
import app.m5_api as m5_api


DISPLAY_TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _utc_at(day: date, hour: int = 10) -> datetime:
    return datetime.combine(day, time(hour=hour), tzinfo=DISPLAY_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    owner = DBUser(
        public_id="usr-f8-profile-owner",
        username="f8-profile-owner",
        hashed_password="unused",
        role="student",
        display_name="画像学生",
    )
    other = DBUser(
        public_id="usr-f8-profile-other",
        username="f8-profile-other",
        hashed_password="unused",
        role="student",
        display_name="其他学生",
    )
    session.add_all([
        owner,
        other,
        DBStudentProfile(student_id=owner.username, major="人工智能", favorites=["artifact-a"]),
        DBStudentProfile(student_id=other.username),
    ])
    session.commit()
    courses = [
        DBCourse(
            id="course-f8-profile-a",
            version="1",
            title="人工智能导论",
            manifest_version="1",
            owner_public_id=owner.public_id,
        ),
        DBCourse(
            id="course-f8-profile-b",
            version="1",
            title="数据结构",
            manifest_version="1",
            owner_public_id=owner.public_id,
        ),
        DBCourse(
            id="course-f8-profile-private",
            version="1",
            title="未授权课程",
            manifest_version="1",
            owner_public_id=other.public_id,
        ),
    ]
    session.add_all(courses)
    session.commit()
    return engine, session, owner, other


def _event(
    session,
    *,
    event_id: str,
    owner: DBUser,
    day: date,
    course_id: str = "course-f8-profile-a",
    event_type: str = "resource_completed",
    object_type: str = "artifact",
    object_id: str = "",
    payload: dict | None = None,
    mastery: bool = False,
    completion: str = "none",
    hour: int = 10,
) -> DBLearningEvent:
    row = DBLearningEvent(
        id=event_id,
        owner_public_id=owner.public_id,
        course_id=course_id,
        event_type=event_type,
        source="test",
        trace_id=f"trace-{event_id}",
        object_type=object_type,
        object_id=object_id,
        action="read",
        evidence_strength=0.8 if mastery else 0.0,
        evidence_status="accepted" if mastery else "none",
        evidence_reason="固定测试证据" if mastery else "普通学习记录",
        mastery_eligible=mastery,
        completion_effect=completion,
        payload=payload or {},
        occurred_at=_utc_at(day, hour),
    )
    session.add(row)
    session.flush()
    return row


def _consumption(
    session,
    event: DBLearningEvent,
    *,
    status: str,
    mastery_average: float | None,
    suffix: str,
) -> None:
    summary = {} if mastery_average is None else {"mastery_average": mastery_average}
    session.add(DBLearningEventConsumption(
        id=f"lec-{suffix}",
        learning_event_id=event.id,
        consumer="learning_aggregation",
        processor_version=f"test-{suffix}",
        status=status,
        result={"steps": {"dashboard": {"summary": summary}}},
        created_at=event.occurred_at + timedelta(minutes=1),
        processed_at=event.occurred_at + timedelta(minutes=2) if status == "processed" else None,
    ))


def _counts(session) -> dict[str, int]:
    return {
        "events": session.query(DBLearningEvent).count(),
        "consumptions": session.query(DBLearningEventConsumption).count(),
        "profiles": session.query(DBStudentProfile).count(),
    }


def test_duration_heatmap_streak_and_processed_trend_use_only_real_evidence():
    engine, session, owner, _ = _session()
    try:
        today = NOW.astimezone(DISPLAY_TZ).date()
        yesterday = today - timedelta(days=1)
        three_days_ago = today - timedelta(days=3)
        duration_rows = [
            _event(session, event_id="le-duration-actual", owner=owner, day=today, payload={"actual_minutes": 12}),
            _event(session, event_id="le-duration-generic", owner=owner, day=today, payload={"duration_minutes": 8}),
            _event(session, event_id="le-duration-seconds", owner=owner, day=yesterday, payload={"active_seconds": 300}),
        ]
        _event(
            session,
            event_id="le-invalid-duration",
            owner=owner,
            day=today,
            event_type="resource_opened",
            payload={"actual_minutes": -10, "active_seconds": 0},
        )
        _event(
            session,
            event_id="le-browser-only",
            owner=owner,
            day=today,
            event_type="resource_opened",
            payload={"page": 4},
        )
        accepted = _event(
            session,
            event_id="le-accepted-evidence",
            owner=owner,
            day=yesterday,
            event_type="assessment_correct",
            object_type="assessment_question",
            object_id="question-1",
            mastery=True,
        )
        older = _event(
            session,
            event_id="le-trend-older",
            owner=owner,
            day=today,
            event_type="assessment_correct",
            object_type="assessment_question",
            object_id="question-2",
            mastery=True,
            hour=8,
        )
        newest = _event(
            session,
            event_id="le-trend-newest",
            owner=owner,
            day=today,
            event_type="assessment_correct",
            object_type="assessment_question",
            object_id="question-3",
            mastery=True,
            hour=11,
        )
        prior = _event(
            session,
            event_id="le-trend-prior",
            owner=owner,
            day=three_days_ago,
            event_type="assessment_correct",
            object_type="assessment_question",
            object_id="question-4",
            mastery=True,
        )
        pending = _event(
            session,
            event_id="le-trend-pending",
            owner=owner,
            day=yesterday,
            event_type="assessment_correct",
        )
        failed = _event(
            session,
            event_id="le-trend-failed",
            owner=owner,
            day=today - timedelta(days=2),
            event_type="assessment_correct",
        )
        _consumption(session, older, status="processed", mastery_average=0.51, suffix="older")
        _consumption(session, newest, status="processed", mastery_average=0.62, suffix="newest")
        _consumption(session, prior, status="processed", mastery_average=0.45, suffix="prior")
        _consumption(session, pending, status="pending", mastery_average=0.71, suffix="pending")
        _consumption(session, failed, status="failed", mastery_average=0.81, suffix="failed")
        session.commit()

        before = _counts(session)
        result = build_personal_activity(
            session,
            current_user=owner,
            course_id="course-f8-profile-a",
            days=30,
            now=NOW,
        )
        assert _counts(session) == before
        assert result["readOnly"] is True
        assert result["metrics"]["todayMinutes"]["value"] == 20
        assert result["metrics"]["weekMinutes"]["value"] == 25
        assert result["metrics"]["periodMinutes"]["value"] == 25
        assert set(result["metrics"]["periodMinutes"]["sourceEventIds"]) == {row.id for row in duration_rows}
        assert result["metrics"]["streakDays"]["value"] == 2

        by_day = {item["date"]: item for item in result["heatmap"]["days"]}
        assert len(by_day) == 30
        assert "le-browser-only" not in by_day[today.isoformat()]["sourceEventIds"]
        assert "le-invalid-duration" not in by_day[today.isoformat()]["sourceEventIds"]
        assert accepted.id in by_day[yesterday.isoformat()]["sourceEventIds"]
        assert by_day[today.isoformat()]["activeMinutes"] == 20
        assert by_day[yesterday.isoformat()]["activeMinutes"] == 5

        assert [(item["sourceEventId"], item["value"]) for item in result["trend"]["points"]] == [
            (prior.id, 45),
            (newest.id, 62),
        ]
        assert pending.id not in result["trend"]["sourceEventIds"]
        assert failed.id not in result["trend"]["sourceEventIds"]
        assert "页面停留和普通点击不计时" in result["calculation"]["duration"]
    finally:
        session.close()
        engine.dispose()


def test_empty_owner_course_scope_filters_and_pagination_are_honest():
    engine, session, owner, other = _session()
    try:
        today = NOW.astimezone(DISPLAY_TZ).date()
        for index in range(5):
            _event(
                session,
                event_id=f"le-course-a-{index}",
                owner=owner,
                day=today - timedelta(days=index),
                event_type="note_version_saved",
                object_type="note",
                object_id=f"note-{index}",
                course_id="course-f8-profile-a",
                hour=10 + index,
            )
        _event(
            session,
            event_id="le-course-b",
            owner=owner,
            day=today,
            event_type="code_tests_passed",
            object_type="code_run_attempt",
            object_id="run-b",
            course_id="course-f8-profile-b",
        )
        _event(
            session,
            event_id="le-other-owner",
            owner=other,
            day=today,
            event_type="note_created",
            object_type="note",
            object_id="other-note",
            course_id="course-f8-profile-a",
        )
        session.commit()

        first = build_personal_activity(
            session,
            current_user=owner,
            course_id="course-f8-profile-a",
            days=7,
            offset=0,
            limit=2,
            kind="note",
            now=NOW,
        )
        second = build_personal_activity(
            session,
            current_user=owner,
            course_id="course-f8-profile-a",
            days=7,
            offset=2,
            limit=2,
            kind="note",
            now=NOW,
        )
        assert first["activity"]["total"] == 5
        assert first["activity"]["hasMore"] is True
        assert second["activity"]["hasMore"] is True
        first_ids = [item["id"] for item in first["activity"]["items"]]
        second_ids = [item["id"] for item in second["activity"]["items"]]
        assert len(first_ids) == len(second_ids) == 2
        assert set(first_ids).isdisjoint(second_ids)
        assert all(item["course"]["id"] == "course-f8-profile-a" for item in first["activity"]["items"])
        assert all(item["kind"] == "note" for item in first["activity"]["items"])

        empty_owner = DBUser(
            public_id="usr-f8-profile-empty",
            username="f8-profile-empty",
            hashed_password="unused",
            role="student",
            display_name="空账号学生",
        )
        session.add(empty_owner)
        session.add(DBStudentProfile(student_id=empty_owner.username))
        session.commit()
        empty = build_personal_activity(session, current_user=empty_owner, days=90, now=NOW)
        assert empty["metrics"]["todayMinutes"]["value"] == 0
        assert empty["metrics"]["periodMinutes"]["value"] == 0
        assert empty["metrics"]["streakDays"]["value"] == 0
        assert empty["trend"]["points"] == []
        assert empty["activity"]["items"] == []
        assert all(item["eventCount"] == 0 and item["activeMinutes"] == 0 for item in empty["heatmap"]["days"])
        assert "0分钟" in empty["report"]["summary"]

        with pytest.raises(ProfileSummaryError) as invalid_period:
            build_personal_activity(session, current_user=owner, days=14, now=NOW)
        assert invalid_period.value.code == "activity_period_invalid"
        unrestricted = build_personal_activity(
            session,
            current_user=owner,
            course_id="course-f8-profile-private",
            now=NOW,
        )
        assert unrestricted["course"]["id"] == "course-f8-profile-private"
        assert unrestricted["activity"]["items"] == []
    finally:
        session.close()
        engine.dispose()


def test_activity_deep_links_are_controlled_and_withdrawn_artifacts_stay_auditable():
    engine, session, owner, _ = _session()
    try:
        today = NOW.astimezone(DISPLAY_TZ).date()
        session.add_all([
            DBArtifact(
                id="artifact-f8-published",
                owner_public_id=owner.public_id,
                course_id="course-f8-profile-a",
                artifact_type="handout",
                title="梯度下降讲义",
                status="published",
            ),
            DBArtifact(
                id="artifact-f8-withdrawn",
                owner_public_id=owner.public_id,
                course_id="course-f8-profile-a",
                artifact_type="quiz",
                title="已撤回测验",
                status="withdrawn",
            ),
        ])
        session.commit()
        _event(
            session,
            event_id="le-artifact-published",
            owner=owner,
            day=today,
            object_id="artifact-f8-published",
            payload={"target_url": "https://malicious.example"},
        )
        _event(
            session,
            event_id="le-artifact-withdrawn",
            owner=owner,
            day=today,
            object_id="artifact-f8-withdrawn",
        )
        _event(
            session,
            event_id="le-unknown-object",
            owner=owner,
            day=today,
            event_type="custom_event",
            object_type="external_url",
            object_id="https://malicious.example",
            payload={"route": "javascript:alert(1)"},
        )
        session.commit()

        before = _counts(session)
        result = build_personal_activity(
            session,
            current_user=owner,
            course_id="course-f8-profile-a",
            now=NOW,
        )
        assert _counts(session) == before
        items = {item["id"]: item for item in result["activity"]["items"]}
        published = items["le-artifact-published"]["target"]
        withdrawn = items["le-artifact-withdrawn"]["target"]
        unknown = items["le-unknown-object"]["target"]
        assert published["available"] is True
        assert published["route"].startswith("/workspace/resources/handouts/artifact-f8-published")
        assert "malicious.example" not in published["route"]
        assert withdrawn == {"label": "原资源已不可用", "route": "", "available": False}
        assert unknown == {"label": "仅保留历史记录", "route": "", "available": False}
        assert items["le-unknown-object"]["evidence"]["label"] == "学习记录，不直接改变掌握度"
        assert result["report"]["historyRoute"].startswith("/profile/history")
        assert result["profile"]["fullProfileRoute"].startswith("/profile/learning")
    finally:
        session.close()
        engine.dispose()


def test_personal_activity_http_accepts_numeric_period_query(monkeypatch):
    engine, session, owner, _ = _session()

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: owner
    client = TestClient(app)
    try:
        for days in (7, 30, 90):
            response = client.get("/api/v1/m5/personal-activity", params={"days": days, "limit": 5})
            assert response.status_code == 200, response.text
            assert response.json()["period"]["days"] == days

        invalid = client.get("/api/v1/m5/personal-activity", params={"days": 14})
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "activity_period_invalid"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()
