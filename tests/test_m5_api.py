from fastapi.testclient import TestClient

from app.auth import get_current_user
from sqlalchemy import create_engine
from datetime import datetime, timedelta
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import (
    Base, DBArtifact, DBChapter, DBCourse, DBCourseMembership, DBLearningEvent,
    DBLearningPath, DBPathNode, DBPlanDraft, DBPlanVersion, DBSourceDocument, DBSourceRef, DBUser,
    DBGenerationTask, DBTaskStep, DBWorkerLease,
)
from app.main import app
from app.m1_repository import create_artifact_with_version
from app.m5_capabilities import RuntimeAvailability
import app.m5_api as m5_api


def _catalog_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        DBCourse(id="public-course", version="1", title="Public", visibility="public", manifest_version="1"),
        DBCourse(id="member-course", version="1", title="Member", visibility="private", manifest_version="1"),
        DBCourse(id="hidden-course", version="1", title="Hidden", visibility="private", manifest_version="1"),
    ])
    session.add_all([
        DBSourceDocument(id="src-public", course_id="public-course", title="P", filename="p.md", file_format="md", content_hash="a" * 64),
        DBSourceDocument(id="src-member", course_id="member-course", title="M", filename="m.md", file_format="md", content_hash="b" * 64),
    ])
    session.add_all([
        DBChapter(id="chapter-public", course_id="public-course", source_document_id="src-public", stable_key="p", title="Public chapter", position=1),
        DBChapter(id="chapter-member", course_id="member-course", source_document_id="src-member", stable_key="m", title="Member chapter", position=1),
        DBCourseMembership(course_id="member-course", user_public_id="owner", role="student", status="active"),
        DBArtifact(id="artifact-owner", owner_public_id="owner", course_id="member-course", artifact_type="lesson", title="Owner artifact"),
        DBArtifact(id="artifact-other", owner_public_id="other", artifact_type="lesson", title="Other artifact"),
    ])
    session.flush()
    return session


def test_m5_planning_targets_enforce_course_and_artifact_visibility():
    session = _catalog_session()
    user = DBUser(public_id="owner", username="owner", role="student", is_active=True)
    payload = m5_api._planning_targets(session, user)
    assert [item["id"] for item in payload["courses"]] == ["member-course", "public-course"]
    assert [item["id"] for item in payload["artifacts"]] == ["artifact-owner"]
    assert payload["courses"][0]["chapters"][0]["id"] == "chapter-member"


def test_m5_plan_and_path_list_queries_are_owner_scoped(monkeypatch):
    session = _catalog_session()
    owner_plan = DBPlanDraft(owner_public_id="owner", course_id="member-course", title="Owner", status="confirmed", idempotency_key="owner-plan")
    other_plan = DBPlanDraft(owner_public_id="other", title="Other", status="draft", idempotency_key="other-plan")
    session.add_all([owner_plan, other_plan])
    session.flush()
    version = DBPlanVersion(plan_draft_id=owner_plan.id, version_number=1, content={"schema_version": "m5.plan.v1", "goal": "g", "assumptions": [], "nodes": []}, content_hash="c" * 64)
    session.add(version)
    session.flush()
    owner_plan.current_version_id = owner_plan.confirmed_version_id = version.id
    session.add(DBLearningPath(owner_public_id="owner", course_id="member-course", source_plan_version_id=version.id, status="active"))
    session.commit()

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: DBUser(public_id="owner", username="owner", role="student", is_active=True)
    try:
        plans = client.get("/api/v1/m5/plans").json()["items"]
        paths = client.get("/api/v1/m5/paths").json()["items"]
        assert [item["id"] for item in plans] == [owner_plan.id]
        assert len(paths) == 1 and paths[0]["course_id"] == "member-course"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_m5_resource_catalog_http_is_owner_scoped_source_filterable_and_read_only(monkeypatch):
    session = _catalog_session()
    session.add_all([
        DBSourceDocument(
            id="src-failed", course_id="member-course", title="Failed source",
            filename="failed.md", file_format="md", content_hash="d" * 64,
            processing_status="failed",
        ),
        DBChapter(
            id="chapter-failed", course_id="member-course", source_document_id="src-failed",
            stable_key="failed", title="Failed chapter", position=2,
        ),
        DBSourceRef(
            id="ref-ready", source_document_id="src-member", chapter_id="chapter-member",
            parser_version="test-parser-ready", location_label="第 1 节", content_hash="e" * 64,
        ),
        DBSourceRef(
            id="ref-failed", source_document_id="src-failed", chapter_id="chapter-failed",
            parser_version="test-parser-failed", location_label="第 2 节", content_hash="f" * 64,
        ),
    ])
    session.flush()
    available, _ = create_artifact_with_version(
        session,
        owner_public_id="owner",
        course_id="member-course",
        artifact_type="lesson",
        title="Available resource",
        content="# Available",
        metadata={"source_ref_ids": ["ref-ready"]},
    )
    unavailable, _ = create_artifact_with_version(
        session,
        owner_public_id="owner",
        course_id="member-course",
        artifact_type="lab_guide",
        title="Unavailable resource",
        content="# Unavailable",
        metadata={"source_ref_ids": ["ref-failed"]},
    )
    no_source, _ = create_artifact_with_version(
        session,
        owner_public_id="owner",
        course_id="member-course",
        artifact_type="mind_map",
        title="No source resource",
        content="# No source",
    )
    other, _ = create_artifact_with_version(
        session,
        owner_public_id="other",
        artifact_type="lesson",
        title="Other private resource",
        content="# Private",
    )
    session.commit()

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: DBUser(
        public_id="owner", username="owner", role="student", is_active=True,
    )
    event_count = session.query(DBLearningEvent).count()
    try:
        catalog = client.get("/api/v1/m5/resources?limit=100")
        assert catalog.status_code == 200
        ids = {item["id"] for item in catalog.json()["items"]}
        assert {available.id, unavailable.id, no_source.id}.issubset(ids)
        assert other.id not in ids

        assert [item["id"] for item in client.get(
            "/api/v1/m5/resources?source_status=available&limit=100"
        ).json()["items"]] == [available.id]
        assert [item["id"] for item in client.get(
            "/api/v1/m5/resources?source_status=unavailable&limit=100"
        ).json()["items"]] == [unavailable.id]
        assert no_source.id in {
            item["id"] for item in client.get(
                "/api/v1/m5/resources?source_status=not_recorded&limit=100"
            ).json()["items"]
        }

        detail = client.get(f"/api/v1/m5/resources/{available.id}")
        assert detail.status_code == 200
        assert detail.json()["catalog"]["route"].endswith(available.id)
        assert client.get(f"/api/v1/m5/resources/{available.id}/export").status_code == 200
        assert client.get(f"/api/v1/m5/resources/{other.id}").status_code == 403
        assert client.get(f"/api/v1/m5/resources/{other.id}/export").status_code == 403
        assert session.query(DBLearningEvent).count() == event_count
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_m5_assessment_http_contract_hides_answers_and_requires_confirmed_misconception(monkeypatch):
    session = _catalog_session()
    public_course = session.query(DBCourse).filter_by(id="public-course").one()
    public_course.owner_public_id = "teacher"
    session.add(
        DBUser(
            public_id="learner",
            username="learner",
            hashed_password="hash",
            role="student",
            is_active=True,
        )
    )
    session.commit()

    async def fake_run_db_op(operation):
        return operation(session)

    identity = {"user": DBUser(public_id="teacher", username="teacher", role="teacher", is_active=True)}
    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    try:
        created = client.post("/api/v1/m5/assessment/questions", json={
            "course_id": "public-course",
            "question_type": "single_choice",
            "origin": "manual",
            "version": {
                "prompt": "Which option is correct?",
                "options": ["A", "B"],
                "answer_key": {"choice": "B"},
                "scoring_rule": {"type": "exact"},
                "explanation": "B is correct",
            },
        })
        assert created.status_code == 201, created.text
        question = created.json()["question_version"]
        assert "answer_key" not in question and "explanation" not in question

        approved = client.post(
            f"/api/v1/m5/assessment/questions/{question['question_id']}/status",
            json={"expected_current_version_id": question["id"], "status": "approved"},
        )
        assert approved.status_code == 200, approved.text

        identity["user"] = DBUser(public_id="learner", username="learner", role="student", is_active=True)
        fetched = client.get(f"/api/v1/m5/assessment/questions/{question['id']}")
        assert fetched.status_code == 200
        assert "answer_key" not in fetched.json()

        injected = client.post("/api/v1/m5/assessment/attempts", json={
            "question_version_id": question["id"], "idempotency_key": "http-attempt-001",
            "answer": {"choice": "A"}, "score": 1, "correct": True,
        })
        assert injected.status_code == 422
        attempt = client.post("/api/v1/m5/assessment/attempts", json={
            "question_version_id": question["id"], "idempotency_key": "http-attempt-001",
            "answer": {"choice": "A"}, "mode": "practice",
        })
        assert attempt.status_code == 201, attempt.text
        assert attempt.json()["score"] == 0 and attempt.json()["correct"] is False
        proposed = attempt.json()["misconception_review"]
        assert proposed["status"] == "proposed"
        assert client.get("/api/v1/m5/review-queue").json()["items"] == []
        decision = client.post(
            f"/api/v1/m5/assessment/misconceptions/{proposed['id']}/decision",
            json={"decision": "modify", "category": "knowledge_gap", "note": "learner correction"},
        )
        assert decision.status_code == 200
        assert decision.json()["retest_task_created"] is True
        assert decision.json()["retest_task"]["status"] == "scheduled"
        assert decision.json()["retest_task"]["stable_mastery"] is False
        queue = client.get("/api/v1/m5/review-queue").json()["items"]
        assert len(queue) == 1 and queue[0]["category"] == "knowledge_gap"
        assert queue[0]["stable_mastery"] is False
        assert queue[0]["retest_task"]["id"] == decision.json()["retest_task"]["id"]
        task_id = decision.json()["retest_task"]["id"]
        from app.database import DBAssessmentRetestTask
        retest_task = session.query(DBAssessmentRetestTask).filter_by(id=task_id).one()
        retest_task.due_at = retest_task.due_at - timedelta(hours=25)

        from app.m5_learning import PlanNodeSpec, PlanSpec, confirm_plan, create_plan_draft
        node = PlanNodeSpec(
            node_key="retest-assessment", node_type="assessment",
            target_object_id=question["id"], title="Delayed assessment retest",
            resource_status="existing", estimate_min_minutes=5, estimate_max_minutes=10,
        )
        from app.database import DBAssessmentQuestion
        session.query(DBAssessmentQuestion).filter_by(id=question["question_id"]).one().status = "approved"
        plan, _, _ = create_plan_draft(
            session, owner_public_id="learner", course_id="public-course",
            title="Retest plan", idempotency_key="http-retest-plan",
            spec=PlanSpec(goal="Close the misconception", nodes=(node,)),
        )
        path = confirm_plan(session, plan=plan, owner_public_id="learner", expected_lock_version=1)
        session.commit()

        retest = client.get(f"/api/v1/m5/assessment/retests/{task_id}")
        assert retest.status_code == 200
        assert "answer_key" not in retest.json()["question"]
        passed = client.post(f"/api/v1/m5/assessment/retests/{task_id}/attempts", json={
            "idempotency_key": "http-retest-pass-001", "answer": {"choice": "B"},
            "confidence": 0.8, "duration_seconds": 15,
        })
        assert passed.status_code == 200, passed.text
        assert passed.json()["task"]["status"] == "completed"
        assert passed.json()["attempt"]["mode"] == "retest"
        assert passed.json()["path_evidence"]["event_type"] == "delayed_retest_passed"
        assert session.query(DBPathNode).filter_by(learning_path_id=path.id).one().status == "completed"
        assert session.query(DBLearningEvent).filter_by(event_type="delayed_retest_passed").count() == 1
        assert client.get("/api/v1/m5/review-queue").json()["items"] == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_m5_capability_api_is_authenticated_and_does_not_claim_missing_models(monkeypatch):
    monkeypatch.setattr(m5_api, "runtime_availability", lambda: RuntimeAvailability())
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: DBUser(
        public_id="usr-m5-student", username="m5-student", role="student", is_active=True,
    )
    try:
        status = client.get("/api/v1/m5/capabilities")
        assert status.status_code == 200
        body = status.json()
        assert body["user_configurable_secrets"] is False
        assert body["runtime"]["text_model"] is False
        assert body["runtime"]["deterministic_text_model"] is False
        assert body["generation_mode"] == "unavailable"

        route = client.post("/api/v1/m5/route", json={
            "contract": {"idempotency_key": "api-m5-001"},
            "message": "普通问答",
        })
        assert route.status_code == 200
        assert route.json()["status"] == "unavailable"
        assert route.json()["capability"] == "answer"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_model_operations_http_roles_pricing_worker_and_owner_cancel(monkeypatch):
    session = _catalog_session()
    task = DBGenerationTask(
        owner_public_id="owner", trace_id="trace-http-ops", status="queued",
        capability="m5.capability.lecture", idempotency_key="http-ops-task",
        created_at=datetime(2026, 8, 3, 8, 0),
    )
    other_task = DBGenerationTask(
        owner_public_id="other", trace_id="trace-http-other", status="queued",
        capability="m5.capability.lecture", idempotency_key="http-other-task",
        created_at=datetime(2026, 8, 3, 8, 1),
    )
    session.add_all([task, other_task])
    session.commit()

    async def fake_run_db_op(operation):
        return operation(session)

    identity = {"user": DBUser(public_id="student", username="student", role="student", is_active=True)}
    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    try:
        assert client.get("/api/v1/m5/model-operations").status_code == 403
        identity["user"] = DBUser(public_id="teacher", username="teacher", role="teacher", is_active=True)
        assert client.get("/api/v1/m5/model-operations").status_code == 200
        price_payload = {
            "provider": "demo", "model": "edu-model", "version": "http-v1",
            "currency": "USD", "input_cost_per_million": 1,
            "output_cost_per_million": 2,
            "source_url": "https://example.invalid/pricing",
            "source_label": "Frozen demo pricing",
            "effective_at": "2026-08-03T08:00:00Z",
        }
        assert client.post("/api/v1/m5/model-operations/prices", json=price_payload).status_code == 403

        identity["user"] = DBUser(public_id="admin", username="admin", role="admin", is_active=True)
        price = client.post("/api/v1/m5/model-operations/prices", json=price_payload)
        assert price.status_code == 201 and price.json()["created"] is True
        claim = client.post("/api/v1/m5/model-operations/workers/claim", json={"worker_id": "http-worker"})
        assert claim.status_code == 200 and claim.json()["claim"]["task_id"] == task.id
        assert session.query(DBWorkerLease).filter_by(task_id=task.id, status="active").count() == 1

        identity["user"] = DBUser(public_id="other", username="other", role="student", is_active=True)
        assert client.post(f"/api/v1/m5/tasks/{task.id}/cancel").status_code == 403
        identity["user"] = DBUser(public_id="owner", username="owner", role="student", is_active=True)
        cancelled = client.post(f"/api/v1/m5/tasks/{task.id}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_m5_task_rework_http_is_owner_scoped_and_refreshable(monkeypatch):
    session = _catalog_session()
    task = DBGenerationTask(
        owner_public_id="owner", trace_id="trace-http-rework",
        status="running", progress=0.5, capability="m5.capability.lecture",
        idempotency_key="http-task-rework",
    )
    session.add(task)
    session.flush()
    completed = DBTaskStep(
        task_id=task.id, sequence=1, attempt=1, agent_role="capability_agent",
        tool_name="m5.lecture.generate", status="completed",
    )
    pending = DBTaskStep(
        task_id=task.id, sequence=2, attempt=1, agent_role="validation_agent",
        tool_name="m5.lecture.validate", status="pending",
    )
    session.add_all([completed, pending])
    session.commit()

    async def fake_run_db_op(operation):
        return operation(session)

    identity = {"user": DBUser(public_id="other", username="other", role="student", is_active=True)}
    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    try:
        denied = client.post(
            f"/api/v1/m5/tasks/{task.id}/steps/1/rework",
            json={"reason_code": "review_requires_revision"},
        )
        assert denied.status_code == 403

        identity["user"] = DBUser(public_id="owner", username="owner", role="student", is_active=True)
        scheduled = client.post(
            f"/api/v1/m5/tasks/{task.id}/steps/1/rework",
            json={"reason_code": "review_requires_revision"},
        )
        assert scheduled.status_code == 200, scheduled.text
        assert scheduled.json()["attempt"] == 2

        recovered = client.get(f"/api/v1/m5/tasks/{task.id}")
        assert recovered.status_code == 200
        assert recovered.json()["latest_steps"][0]["attempt"] == 2
        assert recovered.json()["latest_steps"][0]["status"] == "pending"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_m5_tutor_context_http_contract_enforces_owner_sources_recovery_and_archive(monkeypatch):
    session = _catalog_session()
    session.add_all([
        DBSourceRef(
            id="ref-public", source_document_id="src-public", chapter_id="chapter-public",
            parser_version="test-parser-v1", page_number=2, char_start=10, char_end=48,
            quote="Public source quotation", content_hash="c" * 64,
        ),
        DBSourceRef(
            id="ref-member", source_document_id="src-member", chapter_id="chapter-member",
            parser_version="test-parser-v1", page_number=4, char_start=20, char_end=64,
            quote="Member source quotation", content_hash="d" * 64,
        ),
    ])
    session.commit()

    async def fake_run_db_op(operation):
        return operation(session)

    identity = {"user": DBUser(public_id="owner", username="owner", role="student", is_active=True)}
    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    monkeypatch.setattr(m5_api, "runtime_availability", lambda: RuntimeAvailability())
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    try:
        created = client.post("/api/v1/m5/tutor-contexts", json={
            "schema_version": "m5.tutor-context.v1",
            "idempotency_key": "http-tutor-context-001",
            "course_id": "public-course",
            "context_mode": "current_resource",
            "primary_object_type": "chapter",
            "primary_object_id": "chapter-public",
            "selected_source_ref_ids": ["ref-public"],
            "teaching_style": "close_reading",
            "explanation_depth": "deep",
            "guidance_mode": "socratic",
        })
        assert created.status_code == 201, created.text
        context = created.json()
        assert context["created"] is True
        assert context["context"]["sources"][0]["quote"] == "Public source quotation"
        assert context["context"]["sources"][0]["content_hash"] == "c" * 64

        recovered = client.get("/api/v1/m5/tutor-contexts")
        assert recovered.status_code == 200
        assert [item["id"] for item in recovered.json()["items"]] == [context["id"]]

        checked = client.post(f"/api/v1/m5/tutor-contexts/{context['id']}/preflight", json={
            "question": "Explain the quoted section", "intent": "explain",
        })
        assert checked.status_code == 200, checked.text
        assert checked.json()["generation_started"] is False
        assert checked.json()["blockers"] == ["text_model_unavailable"]

        cross_course = client.post("/api/v1/m5/tutor-contexts", json={
            "schema_version": "m5.tutor-context.v1",
            "idempotency_key": "http-tutor-context-002",
            "course_id": "public-course",
            "context_mode": "current_resource",
            "primary_object_type": "chapter",
            "primary_object_id": "chapter-public",
            "selected_source_ref_ids": ["ref-member"],
        })
        assert cross_course.status_code == 404
        assert cross_course.json()["detail"]["code"] == "tutor_source_ref_invalid"

        identity["user"] = DBUser(public_id="other", username="other", role="student", is_active=True)
        assert client.get("/api/v1/m5/tutor-contexts").json()["items"] == []
        assert client.get(f"/api/v1/m5/tutor-contexts/{context['id']}").status_code == 403
        assert client.post(
            f"/api/v1/m5/tutor-contexts/{context['id']}/preflight",
            json={"question": "Read another user's context"},
        ).status_code == 403
        assert client.post(
            f"/api/v1/m5/tutor-contexts/{context['id']}/archive",
            json={"expected_lock_version": context["lock_version"]},
        ).status_code == 403

        identity["user"] = DBUser(public_id="owner", username="owner", role="student", is_active=True)
        archived = client.post(
            f"/api/v1/m5/tutor-contexts/{context['id']}/archive",
            json={"expected_lock_version": context["lock_version"]},
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"
        assert client.get("/api/v1/m5/tutor-contexts").json()["items"] == []
        assert len(client.get("/api/v1/m5/tutor-contexts?include_archived=true").json()["items"]) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
