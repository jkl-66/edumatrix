from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import (
    Base,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseMembership,
    DBKnowledgePoint,
    DBOnboardingSession,
    DBProfileSnapshot,
    DBStudentProfile,
    DBUser,
)
from app.profile_onboarding import (
    confirm_continuous_turn,
    continuous_update_reminder,
    get_or_create_session,
    record_continuous_turn,
    start_continuous_update,
)
from app.profile_summary import _public_source, build_personal_activity, build_profile_summary
from profile_api import _load_current_course_knowledge_points


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = DBUser(
        public_id="usr-noc-t07",
        username="noc-t07",
        hashed_password="unused",
        role="student",
        display_name="画像上下文学生",
    )
    session.add_all([
        user,
        DBStudentProfile(
            student_id=user.username,
            target_course="课程 A",
            weak_points=["kp-a"],
            concept_mastery={"kp-a": 0.4},
        ),
        DBCourse(
            id="course-a",
            version="1",
            title="课程 A",
            status="published",
            visibility="public",
            manifest_version="1",
        ),
        DBCourse(
            id="course-b",
            version="1",
            title="课程 B",
            status="published",
            visibility="public",
            manifest_version="1",
        ),
    ])
    session.flush()
    for course_id, code, title in (
        ("course-a", "A-01", "课程 A 知识点"),
        ("course-b", "B-01", "课程 B 知识点"),
    ):
        source_id = f"source-{course_id}"
        chapter_id = f"chapter-{course_id}"
        point_id = f"kp-{course_id}"
        session.add(DBChapter(
            id=chapter_id,
            course_id=course_id,
            source_document_id=source_id,
            stable_key=chapter_id,
            title=f"{title}章节",
            position=1,
        ))
        session.add(DBKnowledgePoint(
            id=point_id,
            domain_pack="noc-t07",
            code=code,
            version="1",
            title=title,
            status="active",
        ))
        session.add(DBChapterKnowledgePoint(
            id=f"relation-{course_id}",
            chapter_id=chapter_id,
            knowledge_point_id=point_id,
        ))
    session.commit()
    return engine, session, user


def test_non_member_can_use_continuous_profile_context_without_membership_write():
    engine, session, user = _session()
    try:
        assert session.query(DBOnboardingSession).count() == 0
        initial = get_or_create_session(session, user)
        assert initial.course_context == {
            "courseId": "course-a",
            "title": "课程 A",
            "source": "课程知识库",
        }
        started = start_continuous_update(session, user, course_id="course-a")
        assert started["courseContext"] == {
            "courseId": "course-a",
            "title": "课程 A",
            "source": "课程知识库",
        }
        reminder = continuous_update_reminder(session, user, course_id="course-a")
        assert reminder["courseContext"]["courseId"] == "course-a"
        payload = record_continuous_turn(
            session,
            user,
            turn_id="turn-a",
            user_answer="最近课程 A 的公式推导还是不太熟。",
            course_id="course-a",
            extractor=lambda *_: {
                "mode": "continuous_profile_update",
                "fields": [],
                "dimensions": [],
                "weakPointAttribution": [],
                "uncertainties": [],
            },
        )
        assert payload["turns"][0]["status"] == "awaiting_confirmation"
        confirm_continuous_turn(
            session,
            user,
            turn_id="turn-a",
            fields={"focus_level": 0.6},
        )
        assert session.query(DBProfileSnapshot).count() == 1
        assert session.query(DBCourseMembership).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_profile_analysis_scope_and_summary_follow_selected_course_without_membership():
    engine, session, user = _session()
    try:
        course_a = _load_current_course_knowledge_points(
            session,
            student_id=user.username,
            current_user_public_id=user.public_id,
            course_id="course-a",
        )
        course_b = _load_current_course_knowledge_points(
            session,
            student_id=user.username,
            current_user_public_id=user.public_id,
            course_id="course-b",
        )
        assert course_a["course_id"] == "course-a"
        assert [item["title"] for item in course_a["points"]] == ["课程 A 知识点"]
        assert course_b["course_id"] == "course-b"
        assert [item["title"] for item in course_b["points"]] == ["课程 B 知识点"]

        summary = build_profile_summary(session, current_user=user, course_id="course-b")
        assert summary["course"]["id"] == "course-b"
        assert summary["owner"]["public_id"] == user.public_id
        activity = build_personal_activity(session, current_user=user, course_id="course-b", days=7)
        assert activity["course"]["id"] == "course-b"
        assert activity["owner"]["publicId"] == user.public_id
        assert session.query(DBCourseMembership).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_missing_profile_course_is_not_treated_as_available_context():
    engine, session, user = _session()
    try:
        scope = _load_current_course_knowledge_points(
            session,
            student_id=user.username,
            current_user_public_id=user.public_id,
            course_id="course-missing",
        )
        assert scope == {"course_id": "", "course_title": "", "points": []}
    finally:
        session.close()
        engine.dispose()


def test_profile_public_source_is_navigable_without_internal_identifier_projection():
    source = _public_source(
        label="查看相关测评记录",
        route="/workspace/assessment/exams?course_id=course-a",
        available=True,
        kind="assessment_attempt",
    )
    assert source == {
        "label": "查看相关测评记录",
        "route": "/workspace/assessment/exams?course_id=course-a",
        "available": True,
        "kind": "assessment_attempt",
        "occurredAt": None,
    }
