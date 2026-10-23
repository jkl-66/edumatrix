from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_context import build_competition_demo_context
from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBUser
from fastapi import HTTPException
from knowledge_api import build_canonical_course_source_detail


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "frontend" / "src" / "views" / "Knowledge.vue"
SHELF = ROOT / "frontend" / "src" / "components" / "KnowledgeCourseShelf.vue"
WORKSPACE = ROOT / "frontend" / "src" / "views" / "LearningWorkspace.vue"


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_demo_context_exposes_one_trusted_course_entry_and_recommended_chapter():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        context = build_competition_demo_context(session, learner)

        chapter = next(item for item in context["chapters"] if item["position"] == 7)
        assert context["entry"] == {
            "course_id": "demo-course-rag-trust-v1",
            "chapter_id": chapter["id"],
            "chapter_title": chapter["title"],
            "course_route": f"/knowledge?course_id=demo-course-rag-trust-v1&chapter_id={chapter['id']}",
            "workspace_route": f"/workspace?course_id=demo-course-rag-trust-v1&chapter_id={chapter['id']}",
            "data_label": "冻结合成演示数据",
        }
        assert context["page_contracts"]["dashboard"]["primary_action"]["route"] == context["entry"]["course_route"]
        assert context["page_contracts"]["knowledge"]["primary_action"]["route"] == context["entry"]["workspace_route"]
        assert len(context["sources"]) == 9
        assert all(item["license"] and item["content_hash"] and item["status"] == "ready" for item in context["sources"])
    finally:
        session.close()
        engine.dispose()


def test_course_resource_page_exposes_source_preview_and_workspace_action():
    source = KNOWLEDGE.read_text(encoding="utf-8")
    shelf = SHELF.read_text(encoding="utf-8")
    for marker in (
        "KnowledgeCourseShelf",
        '@open-source="openCourseSource"',
        '@open-search-result="openCourseSearchResult"',
        "openCourseSource",
        "openCourseSearchResult",
        "source_document_id",
        "/knowledge/documents/",
    ):
        assert marker in source
    for marker in (
        'data-testid="knowledge-course-shelf"',
        'data-testid="open-chapter-document"',
        'aria-labelledby="course-search-title"',
        "课程正文检索",
        "打开来源",
    ):
        assert marker in shelf
    for removed in (
        "openDemoSource",
        "openDemoWorkspace",
        "open-demo-workspace",
        "replaceKnowledgeQuery",
        "knowledge-advanced-tools",
    ):
        assert removed not in source


def test_canonical_demo_source_detail_reuses_source_facts_and_rejects_non_member():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        detail = build_canonical_course_source_detail(session, learner, "demo-src-00")
        assert detail["course_id"] == "demo-course-rag-trust-v1"
        assert detail["source_document_id"] == "demo-src-00"
        assert detail["source_ref_id"] == "demo-ref-01"
        assert detail["source_sha256"] == detail["content_hash"]
        assert detail["source_git_revision"] == "competition-demo-rag-1.0.0"
        assert detail["course_license"]
        assert "课程目标" in detail["content"]

        outsider = DBUser(
            public_id="usr-r3-outsider",
            username="r3-outsider",
            hashed_password="not-used",
            role="student",
        )
        session.add(outsider)
        session.commit()
        try:
            build_canonical_course_source_detail(session, outsider, "demo-src-00")
            raise AssertionError("non-member unexpectedly read the course source")
        except HTTPException as exc:
            assert exc.status_code == 403
    finally:
        session.close()
        engine.dispose()


def test_workspace_honors_and_preserves_course_and_chapter_query():
    source = WORKSPACE.read_text(encoding="utf-8")
    for marker in (
        "const requestedCourseId = currentQueryValue('course_id')",
        "const requestedChapterId = currentQueryValue('chapter_id')",
        "getM5WorkspaceOverview(requestedCourseId)",
        "`workspace-document:${requestedChapterId}`",
        "course_id: workspaceData.course?.id || requestedCourseId",
        "chapter_id: selectedChapterId",
        "course_id: workspaceCourse.value?.id || ''",
    ):
        assert marker in source
