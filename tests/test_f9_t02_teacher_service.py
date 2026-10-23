from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.teacher_api as teacher_api
from app.agent_audit import AGENT_AUDIT_EVENT
from app.auth import get_current_user, get_password_hash
from app.database import (
    Base,
    DBArtifact,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseDocument,
    DBCourseMembership,
    DBGenerationTask,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningPath,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBSourceDocument,
    DBStudentProfile,
    DBTaskEvent,
    DBTeachingClass,
    DBTeachingClassMember,
    DBTeachingTask,
    DBUser,
)
from app.main import app


def _fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    teacher = DBUser(
        public_id="f9-teacher",
        username="f9-teacher",
        hashed_password=get_password_hash("pw"),
        role="teacher",
        display_name="林老师",
    )
    outsider = DBUser(
        public_id="f9-outsider",
        username="f9-outsider",
        hashed_password=get_password_hash("pw"),
        role="teacher",
        display_name="外部教师",
    )
    assistant = DBUser(
        public_id="f9-assistant",
        username="f9-assistant",
        hashed_password=get_password_hash("pw"),
        role="assistant",
        display_name="助教",
    )
    admin = DBUser(
        public_id="f9-admin",
        username="f9-admin",
        hashed_password=get_password_hash("pw"),
        role="admin",
        display_name="管理员",
    )
    learners = [
        DBUser(
            public_id=f"f9-learner-{index}",
            username=f"f9-learner-{index}",
            hashed_password=get_password_hash("pw"),
            role="student",
            display_name=f"学员 {index}",
        )
        for index in (1, 2)
    ]
    course = DBCourse(
        id="f9-course",
        version="1",
        title="可信 RAG 工程",
        subject="人工智能",
        visibility="public",
        status="published",
        manifest_version="1",
        owner_public_id=teacher.public_id,
    )
    other_course = DBCourse(
        id="f9-other-course",
        version="1",
        title="其他课程",
        visibility="private",
        status="published",
        manifest_version="1",
        owner_public_id=outsider.public_id,
    )
    source = DBSourceDocument(
        id="f9-source",
        course_id=course.id,
        title="可信检索课程讲义",
        filename="retrieval.md",
        file_format="md",
        content_hash="a" * 64,
        processing_status="ready",
        license_text="CC BY 4.0",
    )
    chapters = [
        DBChapter(
            id=f"f9-chapter-{index}",
            course_id=course.id,
            source_document_id=source.id,
            stable_key=f"chapter-{index}",
            title=title,
            position=index,
        )
        for index, title in ((1, "混合检索"), (2, "引用校验"))
    ]
    points = [
        DBKnowledgePoint(
            id="f9-kp-retrieval",
            domain_pack="f9-rag",
            code="RAG-01",
            version="1",
            title="混合检索与重排",
        ),
        DBKnowledgePoint(
            id="f9-kp-citation",
            domain_pack="f9-rag",
            code="RAG-02",
            version="1",
            title="引用约束",
            prerequisites=["f9-kp-retrieval"],
        ),
    ]
    db.add_all([teacher, outsider, assistant, admin, *learners])
    db.flush()
    db.add_all([course, other_course])
    db.flush()
    other_content = "# 课程讲义\n检索先召回相关材料，再通过重排与引用校验提高回答的可追溯性。"
    db.add(DBCourseDocument(
        id="f9-other-material", course_id=other_course.id, chapter_order=1,
        filename="other-course.md", title="其他课程讲义", content=other_content,
        content_hash=hashlib.sha256(other_content.encode("utf-8")).hexdigest(),
        chunk_count=1, status="published",
    ))
    db.add(source)
    db.flush()
    db.add_all([*chapters, *points])
    db.flush()
    db.add_all([
        DBChapterKnowledgePoint(
            chapter_id=chapters[0].id,
            knowledge_point_id=points[0].id,
        ),
        DBChapterKnowledgePoint(
            chapter_id=chapters[1].id,
            knowledge_point_id=points[1].id,
        ),
        DBCourseMembership(
            course_id=course.id,
            user_public_id=teacher.public_id,
            role="teacher",
            status="active",
        ),
        DBCourseMembership(
            course_id=course.id,
            user_public_id=assistant.public_id,
            role="assistant",
            status="active",
        ),
        DBCourseMembership(
            course_id=other_course.id,
            user_public_id=outsider.public_id,
            role="teacher",
            status="active",
        ),
        *[
            DBCourseMembership(
                course_id=course.id,
                user_public_id=learner.public_id,
                role="student",
                status="active",
            )
            for learner in learners
        ],
    ])
    classroom = DBTeachingClass(
        id="f9-class",
        course_id=course.id,
        title="RAG 实训班",
        term="2026",
        owner_public_id=teacher.public_id,
    )
    db.add(classroom)
    db.flush()
    db.add_all([
        *[
            DBTeachingClassMember(
                class_id=classroom.id,
                user_public_id=learner.public_id,
                role="student",
            )
            for learner in learners
        ],
        DBTeachingTask(
            id="f9-task",
            class_id=classroom.id,
            title="检查本周学习证据",
            idempotency_key="f9-task-001",
            status="draft",
            created_by_public_id=teacher.public_id,
        ),
        DBArtifact(
            id="f9-resource",
            owner_public_id=learners[0].public_id,
            course_id=course.id,
            artifact_type="handout",
            title="个性化检索讲义",
            status="published",
        ),
        DBStudentProfile(
            student_id=learners[0].username,
            concept_mastery={"混合检索与重排": 0.28, "引用约束": 0.71},
        ),
        DBStudentProfile(
            student_id=learners[1].username,
            concept_mastery={"混合检索与重排": 0.76, "引用约束": 0.31},
        ),
    ])
    now = datetime.utcnow()
    for learner, weak_id, mastered_id, event_id in (
        (learners[0], points[0].id, points[1].id, "f9-event-1"),
        (learners[1], points[1].id, points[0].id, "f9-event-2"),
    ):
        db.add(DBProfileSnapshot(
            id=f"f9-snapshot-{learner.public_id}",
            owner_public_id=learner.public_id,
            legacy_student_id=learner.username,
            profile_version="1",
            snapshot={
                "course_id": course.id,
                "mastery": 0.5,
                "weak_knowledge_point_ids": [weak_id],
                "mastered_knowledge_point_ids": [mastered_id],
            },
            content_hash="b" * 64,
            trace_id=f"trace-{learner.public_id}",
        ))
        db.add(DBLearningEvent(
            id=event_id,
            owner_public_id=learner.public_id,
            course_id=course.id,
            event_type="assessment_submitted",
            trace_id=f"trace-{event_id}",
            object_type="knowledge_point",
            object_id=weak_id,
            evidence_status="accepted",
            evidence_strength=0.8,
            mastery_eligible=True,
            evidence_reason="正式测验证据",
            occurred_at=now,
        ))
    plan = DBPlanDraft(
        id="f9-plan",
        owner_public_id=learners[0].public_id,
        course_id=course.id,
        title="既有路径",
        status="confirmed",
        idempotency_key="f9-plan-001",
    )
    db.add(plan)
    db.flush()
    version = DBPlanVersion(
        id="f9-plan-version",
        plan_draft_id=plan.id,
        version_number=1,
        content={"goal": "完成可信检索", "nodes": []},
        content_hash="c" * 64,
        created_by_public_id=teacher.public_id,
    )
    db.add(version)
    db.flush()
    path = DBLearningPath(
        id="f9-path",
        owner_public_id=learners[0].public_id,
        course_id=course.id,
        source_plan_version_id=version.id,
    )
    db.add(path)
    db.flush()
    db.add_all([
        DBPathNode(
            id="f9-node-1",
            learning_path_id=path.id,
            node_key="f9-node-1",
            sequence=1,
            node_type="chapter",
            target_object_id=chapters[0].id,
            title="完成混合检索练习",
            status="completed",
            estimate_min_minutes=20,
            estimate_max_minutes=30,
        ),
        DBPathNode(
            id="f9-node-2",
            learning_path_id=path.id,
            node_key="f9-node-2",
            sequence=2,
            node_type="chapter",
            target_object_id=chapters[1].id,
            title="完成引用校验练习",
            status="pending",
            estimate_min_minutes=20,
            estimate_max_minutes=40,
        ),
    ])
    generation = DBGenerationTask(
        id="f9-generation",
        owner_public_id=learners[0].public_id,
        course_id=course.id,
        trace_id="private-trace-never-return",
        capability="resource_generation",
        idempotency_key="f9-generation-001",
        status="completed",
        progress=1.0,
    )
    db.add(generation)
    db.flush()
    db.add(DBTaskEvent(
        id="f9-agent-event",
        task_id=generation.id,
        sequence=1,
        event_type=AGENT_AUDIT_EVENT,
        payload={
            "runId": "f9-public-run",
            "role": "validation",
            "inputRefs": [points[0].id, source.id],
            "candidateSummary": "建议先完成混合检索对比实验",
            "disagreement": "候选难度存在分歧",
            "validation": "来源与学习事件一致",
            "revision": "降低任务跨度并补充引用检查",
            "decisionSummary": "发布针对性练习",
            "status": "completed",
            "system_prompt": "must be removed",
            "api_key": "must be removed",
        },
    ))
    db.commit()
    return db, engine, {
        "teacher": teacher,
        "outsider": outsider,
        "assistant": assistant,
        "admin": admin,
        "learners": learners,
        "course": course,
        "other_course": other_course,
    }


def _client(monkeypatch, db, identity):
    async def isolated_run_db_op(operation):
        return operation(db)

    monkeypatch.setattr(teacher_api, "run_db_op", isolated_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    return TestClient(app)


def _counts(db):
    return {
        "events": db.query(DBLearningEvent).count(),
        "snapshots": db.query(DBProfileSnapshot).count(),
        "paths": db.query(DBLearningPath).count(),
        "nodes": db.query(DBPathNode).count(),
        "profiles": db.query(DBStudentProfile).count(),
    }


def test_teacher_api_enforces_formal_role_and_course_scope(monkeypatch):
    db, engine, users = _fixture()
    identity = {"user": users["teacher"]}
    client = _client(monkeypatch, db, identity)
    try:
        courses = client.get("/api/v1/teacher/courses")
        assert courses.status_code == 200
        assert [item["id"] for item in courses.json()["items"]] == ["f9-course"]

        assert client.get("/api/v1/teacher/courses/f9-other-course").status_code == 404
        identity["user"] = users["outsider"]
        assert client.get("/api/v1/teacher/courses/f9-course").status_code == 404

        for forbidden in (users["assistant"], users["learners"][0]):
            identity["user"] = forbidden
            assert client.get("/api/v1/teacher/courses").status_code == 403

        identity["user"] = users["admin"]
        admin_courses = client.get("/api/v1/teacher/courses")
        assert {item["id"] for item in admin_courses.json()["items"]} == {
            "f9-course", "f9-other-course",
        }
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()


def test_teacher_reads_are_evidence_based_sanitized_and_read_only(monkeypatch):
    db, engine, users = _fixture()
    identity = {"user": users["teacher"]}
    client = _client(monkeypatch, db, identity)
    before = _counts(db)
    try:
        overview = client.get("/api/v1/teacher/overview", params={"course_id": "f9-course"})
        assert overview.status_code == 200, overview.text
        assert overview.json()["summary"] == {
            "courseCount": 1,
            "studentCount": 2,
            "attentionCount": 2,
            "pendingTaskCount": 1,
        }
        assert {item["title"] for item in overview.json()["weakPoints"]} == {
            "混合检索与重排", "引用约束",
        }

        course = client.get("/api/v1/teacher/courses/f9-course")
        assert course.status_code == 200, course.text
        assert len(course.json()["chapters"]) == 2
        assert len(course.json()["sources"]) == 1
        assert len(course.json()["resources"]) == 1
        assert len(course.json()["classes"]) == 1

        students = client.get("/api/v1/teacher/students", params={"course_id": "f9-course"})
        assert students.status_code == 200, students.text
        items = students.json()["items"]
        assert len(items) == 2
        assert {item["weakestPoint"]["title"] for item in items} == {
            "混合检索与重排", "引用约束",
        }
        assert all(item["sourceEventIds"] for item in items)

        detail = client.get(
            "/api/v1/teacher/students/f9-learner-1",
            params={"course_id": "f9-course"},
        )
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["actions"] == {
            "canCreateIntervention": True,
            "canEditMastery": False,
        }
        assert body["profile"]["evidenceState"] == "sufficient"
        assert body["profile"]["weakPoints"][0]["sourceEventIds"] == ["f9-event-1"]
        assert body["evidenceTimeline"][0]["sourceEventId"] == "f9-event-1"
        audit = body["agentAudit"]
        assert audit["state"] == "complete"
        assert set(audit["items"][0]) == {
            "role", "inputRefs", "candidateSummary", "disagreement",
            "validation", "revision", "decisionSummary", "status",
        }
        encoded = json.dumps(body, ensure_ascii=False).lower()
        for forbidden in (
            "system_prompt", "api_key", "chain_of_thought", "raw_log",
            "private-trace-never-return",
        ):
            assert forbidden not in encoded
        assert _counts(db) == before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()


def test_teacher_intervention_is_idempotent_and_never_writes_mastery(monkeypatch):
    db, engine, users = _fixture()
    identity = {"user": users["teacher"]}
    client = _client(monkeypatch, db, identity)
    learner = users["learners"][0]
    before = _counts(db)
    mastery_before = dict(
        db.query(DBStudentProfile).filter_by(student_id=learner.username).one().concept_mastery
    )
    payload = {
        "course_id": "f9-course",
        "learner_public_id": learner.public_id,
        "idempotency_key": "f9-teacher-intervention-001",
    }
    try:
        first = client.post("/api/v1/teacher/interventions", json=payload)
        second = client.post("/api/v1/teacher/interventions", json=payload)
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["path_id"] == second.json()["path_id"]
        assert first.json()["created"] is True
        assert second.json()["created"] is False
        after = _counts(db)
        assert after["events"] == before["events"]
        assert after["snapshots"] == before["snapshots"]
        assert after["profiles"] == before["profiles"]
        assert after["paths"] == before["paths"] + 1
        assert after["nodes"] == before["nodes"] + 1
        mastery_after = dict(
            db.query(DBStudentProfile).filter_by(student_id=learner.username).one().concept_mastery
        )
        assert mastery_after == mastery_before

        identity["user"] = users["assistant"]
        assert client.post("/api/v1/teacher/interventions", json=payload).status_code == 403
        identity["user"] = users["outsider"]
        assert client.post("/api/v1/teacher/interventions", json=payload).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()
