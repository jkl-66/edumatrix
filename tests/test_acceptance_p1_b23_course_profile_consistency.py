from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.dashboard_summary import _profile_alignment
from app.database import Base, DBCourse, DBProfileSnapshot, DBStudentProfile, DBUser


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _user_course(db, suffix: str = "main"):
    user = DBUser(public_id=f"usr-p1-b23-{suffix}", username=f"p1-b23-{suffix}", hashed_password="unused", role="student")
    course = DBCourse(
        id=f"course-p1-b23-{suffix}", version="v2", title="机器学习工程", subject="AI/ML",
        status="published", manifest_version="manifest-v2", content_origin="团队课程知识库",
    )
    profile = DBStudentProfile(
        student_id=user.username,
        target_course=course.title,
        knowledge_base="向量检索与评估",
        cognitive_style="图示+代码",
        motivation_type="岗位转型",
        learning_state_causes={"focus": "recent evidence"},
    )
    db.add_all([user, course, profile])
    db.commit()
    return user, course


def test_dashboard_profile_alignment_exposes_same_course_and_legacy_fields_without_writing():
    engine, db = _db()
    try:
        user, course = _user_course(db)
        db.add(DBProfileSnapshot(
            id="ps-p1-b23-current",
            owner_public_id=user.public_id,
            legacy_student_id=user.username,
            profile_version="profile.continuous.v3",
            snapshot={"kind": "continuous_profile_update", "course_id": course.id, "profile_projection": {"cognitive_style": "图示+代码"}},
            content_hash="p1-b23-current",
            trace_id="p1-b23-trace",
        ))
        db.commit()
        before = (db.query(DBProfileSnapshot).count(), db.query(DBStudentProfile).count())
        result = _profile_alignment(db, current_user=user, course=course)
        assert result["course"]["id"] == course.id
        assert result["course"]["version"] == course.version
        assert result["course"]["source"] == course.content_origin
        assert result["profile_snapshot"]["version"] == "profile.continuous.v3"
        fields = {item["field"]: item for item in result["legacy_migration"]["fields"]}
        assert {"knowledge_base", "learning_state_causes", "cognitive_style", "motivation_type"}.issubset(fields)
        assert all(item["algorithm_version"] for item in fields.values())
        assert result["read_only"] is True
        assert (db.query(DBProfileSnapshot).count(), db.query(DBStudentProfile).count()) == before
    finally:
        db.close()
        engine.dispose()


def test_missing_legacy_profile_is_unknown_not_a_default_conclusion():
    engine, db = _db()
    try:
        user = DBUser(public_id="usr-p1-b23-empty", username="p1-b23-empty", hashed_password="unused", role="student")
        course = DBCourse(id="course-p1-b23-empty", version="v1", title="空课程", status="published", manifest_version="manifest-v1")
        db.add_all([user, course])
        db.commit()
        result = _profile_alignment(db, current_user=user, course=course)
        assert result["status"] == "unknown"
        assert result["profile_snapshot"]["status"] == "unknown"
        assert result["legacy_migration"]["status"] == "not_available"
        assert result["legacy_migration"]["fields"] == []
    finally:
        db.close()
        engine.dispose()


def test_frontend_uses_course_context_and_no_demo_course_override():
    root = Path(__file__).resolve().parents[1]
    dashboard = (root / "frontend/src/views/Dashboard.vue").read_text(encoding="utf-8")
    profile = (root / "frontend/src/views/StudentAnalysis.vue").read_text(encoding="utf-8")
    router = (root / "frontend/src/router/index.js").read_text(encoding="utf-8")
    assert "useCourseContextStore" in dashboard
    assert "profile_alignment" in dashboard
    assert "useCourseContextStore" in profile
    assert "getCompetitionDemoContext" not in profile
    assert "demo-course-rag-trust-v1" not in profile
    assert "name: 'Dashboard'" in router and "courseScoped: true" in router
