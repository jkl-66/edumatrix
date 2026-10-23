from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import (
    Base,
    DBCourse,
    DBCourseMembership,
    DBChapter,
    DBChapterKnowledgePoint,
    DBKnowledgePoint,
    DBSourceDocument,
    DBStudentProfile,
    DBUser,
)
from models import KnowledgeTrace, ProfileEvidence, ProfileEvidenceSource
from profile_api import _build_weak_point_analysis, _load_current_course_knowledge_points


def test_profile_analysis_requests_carry_the_current_course_context():
    profile_api = ("frontend/src/api/profile.js")
    profile_view = ("frontend/src/views/StudentAnalysis.vue")
    dashboard = ("frontend/src/views/Dashboard.vue")
    root = Path(__file__).resolve().parents[1]
    api_source = (root / profile_api).read_text(encoding="utf-8")
    view_source = (root / profile_view).read_text(encoding="utf-8")
    dashboard_source = (root / dashboard).read_text(encoding="utf-8")
    assert "params = courseId ? { course_id: courseId } : undefined" in api_source
    assert view_source.count("getProfileAnalysis(studentId.value, profileCourseId.value)") == 5
    assert "getProfileAnalysis(studentId.value, courseId)" in view_source
    assert "refreshProfileAnalysis(courseId)" in view_source
    assert "getProfileAnalysis(sid, courseId)" in dashboard_source


def _profile(*, weak_points, concept_mastery=None, traces=None, evidence=None, causes=None):
    return SimpleNamespace(
        weak_points=list(weak_points),
        concept_mastery=dict(concept_mastery or {}),
        knowledge_traces=dict(traces or {}),
        profile_evidence=list(evidence or []),
        learning_state_causes=dict(causes or {}),
    )


def test_weak_analysis_only_keeps_current_course_canonical_points_and_normalizes_title():
    profile = _profile(
        weak_points=["我什么都不会", "kp-current", "外部课程知识点", "KP-CURRENT"],
        concept_mastery={"kp-current": 0.32},
        traces={"kp-current": KnowledgeTrace("当前课程知识点", mastery=0.32, attempts=2, correct_attempts=0)},
    )
    result = _build_weak_point_analysis(profile, [{"id": "kp-current", "title": "当前课程知识点", "code": "CUR-01"}])

    assert [item["concept"] for item in result] == ["当前课程知识点"]
    assert result[0]["mastery"] == 0.32
    assert "我什么都不会" not in str(result)
    assert "外部课程知识点" not in str(result)


def test_weak_analysis_accepts_canonical_title_or_code_but_not_ambiguous_keys():
    profile = _profile(
        weak_points=["当前课程知识点", "CUR-01", "通用标题"],
        concept_mastery={"CUR-01": {"score": 0.41}},
    )
    points = [
        {"id": "kp-current", "title": "当前课程知识点", "code": "CUR-01"},
        {"id": "kp-a", "title": "通用标题", "code": "A-01"},
        {"id": "kp-b", "title": "通用标题", "code": "B-01"},
    ]

    result = _build_weak_point_analysis(profile, points)

    assert [item["concept"] for item in result] == ["当前课程知识点"]
    assert result[0]["mastery"] == 0.41


def test_weak_analysis_does_not_copy_global_causes_without_point_evidence():
    profile = _profile(
        weak_points=["当前课程知识点"],
        concept_mastery={"当前课程知识点": 0.35},
        causes={
            "prerequisite_gap": SimpleNamespace(
                key="prerequisite_gap", label="前置知识缺口", percentage=90.0,
            )
        },
        evidence=[
            ProfileEvidence(
                source=ProfileEvidenceSource.STUDENT_MESSAGE,
                text="我在另一个概念上遇到困难",
                features=("prerequisite_gap",),
                weight=1.0,
                confidence=1.0,
            )
        ],
    )

    result = _build_weak_point_analysis(profile, [{"id": "kp-current", "title": "当前课程知识点", "code": "CUR-01"}])

    assert result[0]["root_causes"] == [
        {"cause": "待诊断", "detail": "需要更多交互数据来准确诊断根因", "percentage": 0}
    ]


def _course_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    user = DBUser(public_id="noc-t06-user", username="noc-t06-user", hashed_password="unused", role="student")
    session.add(user)
    for course_id, title, code in (
        ("course-current", "当前课程", "CUR-01"),
        ("course-other", "其他课程", "OTHER-01"),
    ):
        session.add(DBCourse(id=course_id, version="v1", title=title, manifest_version="noc-t06"))
        source_id = f"source-{course_id}"
        chapter_id = f"chapter-{course_id}"
        point_id = f"kp-{course_id}"
        session.add(DBSourceDocument(
            id=source_id, course_id=course_id, title=title, filename=f"{course_id}.md",
            file_format="md", content_hash=f"hash-{course_id}", processing_status="ready",
        ))
        session.add(DBChapter(
            id=chapter_id, course_id=course_id, source_document_id=source_id,
            stable_key=f"chapter-{course_id}", title=f"{title}章节", position=1,
        ))
        session.add(DBKnowledgePoint(
            id=point_id, domain_pack="test", code=code, version="v1", title=f"{title}知识点",
            status="active",
        ))
        session.add(DBChapterKnowledgePoint(
            id=f"ckp-{course_id}", chapter_id=chapter_id, knowledge_point_id=point_id,
        ))
    session.add(DBCourseMembership(
        id="membership-current", course_id="course-current", user_public_id=user.public_id,
        role="student", status="active",
    ))
    session.commit()
    return session


def test_current_course_scope_reads_selected_course_points_without_membership_gate():
    session = _course_fixture()
    try:
        scope = _load_current_course_knowledge_points(
            session,
            student_id="noc-t06-user",
            current_user_public_id="noc-t06-user",
            course_id="course-current",
        )
        assert scope["course_id"] == "course-current"
        assert scope["course_title"] == "当前课程"
        assert [item["title"] for item in scope["points"]] == ["当前课程知识点"]

        other = _load_current_course_knowledge_points(
            session,
            student_id="noc-t06-user",
            current_user_public_id="noc-t06-user",
            course_id="course-other",
        )
        assert other["course_id"] == "course-other"
        assert [item["title"] for item in other["points"]] == ["其他课程知识点"]
    finally:
        session.close()


def test_no_course_scope_returns_empty_instead_of_fabricated_weak_point():
    profile = DBStudentProfile(student_id="noc-t06-empty")
    assert _build_weak_point_analysis(profile, []) == []
