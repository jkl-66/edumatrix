from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import (
    Base,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningPath,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.m5_learning import multi_course_schedule, transition_path
from app.main import app
import app.m5_api as m5_api


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _course(session, course_id: str, title: str, prefix: str):
    session.add(DBCourse(id=course_id, version="1", title=title, subject=title, manifest_version="1"))
    source_id = f"source-{prefix}"
    session.add(DBSourceDocument(
        id=source_id, course_id=course_id, title=f"{title}教材", filename=f"{prefix}.md",
        file_format="md", content_hash=(prefix * 64)[:64], processing_status="ready",
    ))
    chapters = [
        DBChapter(id=f"{prefix}-chapter-1", course_id=course_id, source_document_id=source_id, stable_key="one", title=f"{title}基础", position=1),
        DBChapter(id=f"{prefix}-chapter-2", course_id=course_id, source_document_id=source_id, stable_key="two", title=f"{title}分支A", position=2),
        DBChapter(id=f"{prefix}-chapter-3", course_id=course_id, source_document_id=source_id, stable_key="three", title=f"{title}分支B", position=3),
    ]
    points = [
        DBKnowledgePoint(id=f"{prefix}-kp-1", domain_pack=prefix, code="one", version="1", title=f"{title}基础点"),
        DBKnowledgePoint(id=f"{prefix}-kp-2", domain_pack=prefix, code="two", version="1", title=f"{title}分支点A", prerequisites=[f"{prefix}-kp-1"]),
        DBKnowledgePoint(id=f"{prefix}-kp-3", domain_pack=prefix, code="three", version="1", title=f"{title}分支点B", prerequisites=[f"{prefix}-kp-1"]),
    ]
    session.add_all(chapters + points)
    session.flush()
    for index, chapter in enumerate(chapters, start=1):
        session.add(DBChapterKnowledgePoint(
            chapter_id=chapter.id, knowledge_point_id=f"{prefix}-kp-{index}", relation_type="teaches",
        ))
        session.add(DBSourceRef(
            id=f"{prefix}-ref-{index}", source_document_id=source_id, chapter_id=chapter.id,
            parser_version="test", location_label=f"第 {index} 节", content_hash=(f"{prefix}-{index}" * 20)[:64],
        ))
    session.flush()


def _path(session, owner: str, course_id: str, prefix: str, *, node_prefix: str | None = None) -> DBLearningPath:
    node_prefix = node_prefix or prefix
    plan = DBPlanDraft(
        id=f"{prefix}-plan", owner_public_id=owner, course_id=course_id,
        title=f"{prefix} plan", status="confirmed", idempotency_key=f"{prefix}-idem",
    )
    session.add(plan)
    session.flush()
    version = DBPlanVersion(
        id=f"{prefix}-version", plan_draft_id=plan.id, version_number=1,
        content={"schema_version": "m5.plan.v1", "goal": "test", "nodes": []}, content_hash=f"{prefix}-hash",
    )
    session.add(version)
    session.flush()
    path = DBLearningPath(
        id=f"{prefix}-path", owner_public_id=owner, course_id=course_id,
        source_plan_version_id=version.id, status="active",
    )
    session.add(path)
    session.flush()
    chapters = [f"{node_prefix}-chapter-1", f"{node_prefix}-chapter-2", f"{node_prefix}-chapter-3"]
    session.add_all([
        DBPathNode(
            id=f"{prefix}-node-1", learning_path_id=path.id, node_key=f"{prefix}-root", sequence=1,
            node_type="chapter", target_object_id=chapters[0], title="root", prerequisites=[],
            resource_status="existing", estimate_min_minutes=20, estimate_max_minutes=30,
        ),
        DBPathNode(
            id=f"{prefix}-node-2", learning_path_id=path.id, node_key=f"{prefix}-branch-a", sequence=2,
            node_type="chapter", target_object_id=chapters[1], title="branch-a", prerequisites=[f"{prefix}-root"],
            resource_status="existing", estimate_min_minutes=15, estimate_max_minutes=25,
        ),
        DBPathNode(
            id=f"{prefix}-node-3", learning_path_id=path.id, node_key=f"{prefix}-branch-b", sequence=3,
            node_type="chapter", target_object_id=chapters[2], title="branch-b", prerequisites=[f"{prefix}-root"],
            resource_status="existing", estimate_min_minutes=15, estimate_max_minutes=25,
        ),
    ])
    session.flush()
    return path


def _profile(session, owner: str, course_id: str, suffix: str, *, weak: list[str], mastered: list[str], unknown: list[str]):
    row = DBProfileSnapshot(
        id=f"{owner}-{suffix}", owner_public_id=owner, profile_version=f"b14-{suffix}",
        snapshot={
            "course_id": course_id,
            "time_budget_minutes": 35,
            "learning_preferences": {"mode": "代码实操" if weak else "图示讲解"},
            "mastery_by_knowledge_point": {
                item: {"status": "known", "score": 0.9, "evidence_item_count": 2}
                for item in mastered
            },
            "weak_knowledge_point_ids": weak,
            "mastered_knowledge_point_ids": mastered,
            "unknown_knowledge_point_ids": unknown,
        },
        content_hash=f"{suffix}-hash", trace_id=f"{suffix}-trace",
    )
    session.add(row)
    session.flush()
    return row


def test_multicourse_schedule_keeps_topology_and_profile_driven_differences():
    engine, session = _session()
    try:
        owner = "b14-owner"
        session.add(DBUser(public_id=owner, username=owner, hashed_password="hash", role="student", is_active=True))
        _course(session, "course-a", "数据结构", "a")
        _course(session, "course-b", "机器学习", "b")
        path_a = _path(session, owner, "course-a", "a")
        _path(session, owner, "course-b", "b")
        profile = _profile(
            session, owner, "course-a", "profile-a",
            weak=["a-kp-2"], mastered=["a-kp-1"], unknown=["a-kp-3"],
        )
        session.commit()

        before_events = session.query(DBLearningEvent).count()
        before_profile = dict(session.get(DBProfileSnapshot, profile.id).snapshot)
        result = multi_course_schedule(session, owner_public_id=owner)

        assert result["read_only"] is True
        assert result["learning_state_written"] is False
        assert {item["course_id"] for item in result["courses"]} == {"course-a", "course-b"}
        course_a = next(item for item in result["courses"] if item["course_id"] == "course-a")
        assert {edge["type"] for edge in course_a["topology"]["edges"]} >= {"path_prerequisite", "knowledge_prerequisite"}
        assert len(course_a["topology"]["modules"]) == 3
        assert next(item for item in course_a["nodes"] if item["node_key"] == "a-root")["status"] == "skipped"
        assert next(item for item in course_a["nodes"] if item["node_key"] == "a-branch-a")["priority"] > next(
            item for item in course_a["nodes"] if item["node_key"] == "a-branch-b"
        )["priority"]
        selected = result["selected"]
        assert selected["tasks"]
        task = next(item for item in selected["tasks"] if item["course_id"] == "course-a")
        assert {item["type"] for item in task["resources"]} == {"learning", "practice", "extension"}
        assert task["generation_context"]["profile_snapshot_id"] == profile.id
        assert task["generation_context"]["schedule_day"] == selected["day"]
        assert session.query(DBLearningEvent).count() == before_events
        assert dict(session.get(DBProfileSnapshot, profile.id).snapshot) == before_profile

        second_day = multi_course_schedule(session, owner_public_id=owner, selected_day=2)
        assert second_day["selected"]["day"] == 2
        assert second_day["selected"]["date"] != selected["date"]
        assert path_a.status == "active"
    finally:
        session.close()
        engine.dispose()


def test_schedule_changes_for_three_profiles_and_pause_removes_only_subject_work():
    engine, session = _session()
    try:
        _course(session, "course-a", "数据结构", "a")
        for index, owner in enumerate(("profile-low", "profile-mid", "profile-high")):
            session.add(DBUser(public_id=owner, username=owner, hashed_password="hash", role="student", is_active=True))
            _path(session, owner, "course-a", f"a{index}", node_prefix="a")
            if index == 0:
                weak, mastered, unknown = [f"a-kp-2"], [], [f"a-kp-1", f"a-kp-3"]
            elif index == 1:
                weak, mastered, unknown = [], [f"a-kp-1"], [f"a-kp-2", f"a-kp-3"]
            else:
                weak, mastered, unknown = [], [f"a-kp-1", f"a-kp-2"], [f"a-kp-3"]
            _profile(session, owner, "course-a", f"profile-{index}", weak=weak, mastered=mastered, unknown=unknown)
        session.commit()

        schedules = [multi_course_schedule(session, owner_public_id=owner) for owner in ("profile-low", "profile-mid", "profile-high")]
        first_tasks = [schedule["selected"]["tasks"][0]["node_key"] for schedule in schedules]
        assert len(set(first_tasks)) >= 2
        assert schedules[2]["courses"][0]["nodes"][0]["status"] == "skipped"

        paused_owner = "profile-low"
        paused_path = session.query(DBLearningPath).filter_by(owner_public_id=paused_owner).one()
        transition_path(session, path=paused_path, owner_public_id=paused_owner, target_status="paused", expected_lock_version=1)
        session.commit()
        paused_schedule = multi_course_schedule(session, owner_public_id=paused_owner)
        assert paused_schedule["courses"][0]["status"] == "paused"
        assert paused_schedule["selected"]["tasks"] == []
    finally:
        session.close()
        engine.dispose()


def test_schedule_is_owner_scoped_and_does_not_restore_legacy_path_surfaces():
    engine, session = _session()
    try:
        _course(session, "course-a", "数据结构", "a")
        session.add(DBUser(public_id="owner-a", username="owner-a", hashed_password="hash", role="student", is_active=True))
        session.add(DBUser(public_id="owner-b", username="owner-b", hashed_password="hash", role="student", is_active=True))
        _path(session, "owner-a", "course-a", "owner-a", node_prefix="a")
        _path(session, "owner-b", "course-a", "owner-b", node_prefix="a")
        session.commit()
        assert len(multi_course_schedule(session, owner_public_id="owner-a")["courses"]) == 1
        assert len(multi_course_schedule(session, owner_public_id="missing")["courses"]) == 0
    finally:
        session.close()
        engine.dispose()


def test_schedule_api_is_read_only_and_respects_authenticated_owner(monkeypatch):
    engine, session = _session()
    user = DBUser(public_id="api-owner", username="api-owner", hashed_password="hash", role="student", is_active=True)
    try:
        session.add(user)
        _course(session, "course-a", "数据结构", "a")
        _path(session, user.public_id, "course-a", "api", node_prefix="a")
        session.commit()

        async def fake_run_db_op(operation):
            return operation(session)

        monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
        app.dependency_overrides[get_current_user] = lambda: user
        events_before = session.query(DBLearningEvent).count()
        response = TestClient(app).get("/api/v1/m5/schedule?day=2")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["schema_version"] == "m5.multi-course-schedule.v1"
        assert body["read_only"] is True
        assert body["selected_day"] == 2
        assert session.query(DBLearningEvent).count() == events_before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()
