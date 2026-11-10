from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBArtifact,
    DBArtifactVersion,
    DBAssessmentAttempt,
    DBAssessmentQuestionVersion,
    DBLearningEvent,
    DBProfileSnapshot,
    DBSourceRef,
    DBUser,
)
from app.main import app
import app.m5_api as m5_api
from app.m1_repository import add_artifact_version
from app.m5_resources import (
    ResourceVersionCreateRequest,
    ResourceVersionRestoreRequest,
    compare_resource_versions,
    create_resource_version,
    resource_detail,
    restore_resource_version,
)
from app.resource_bundles import create_generation_job, execute_generation_job_demo


COURSE_ID = "demo-course-rag-trust-v1"


def test_new_quiz_api_keeps_old_work_and_starts_once(monkeypatch):
    import app.resource_bundles_api as bundle_api
    from app.resource_bundles import _generation_manifest, append_task_event
    from app.database import DBGenerationTask

    engine, session = _session()
    started = []
    identity = {"user": None}

    async def isolated_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(bundle_api, "run_db_op", isolated_run_db_op)
    original_submit = bundle_api.submit_resource_job
    def tracked_submit(db, actor, task_id):
        started.append(task_id)
        return original_submit(db, actor, task_id)
    monkeypatch.setattr(bundle_api, "submit_resource_job", tracked_submit)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    client = TestClient(app)
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        identity["user"] = learner
        resource_id = _quiz_resource(session, learner)
        artifact = session.get(DBArtifact, resource_id)
        original_version = artifact.current_version_id
        origin_manifest = _generation_manifest(session, artifact.creating_task_id)
        origin_manifest['context']['learning_goal'] = '必须恰好两句话'
        origin_manifest['context']['teaching_scope'] = {
            'title': '检索与来源', 'goal': '必须恰好两句话',
            'knowledge_points': [{'id': 'demo-kp-07', 'title': '检索与来源'}],
        }
        append_task_event(session, task_id=artifact.creating_task_id,
            event_type='resource_generation.revision.requested', payload={'manifest': origin_manifest})
        append_task_event(session, task_id=artifact.creating_task_id,
            event_type='resource_generation.review.amended', payload={
                'active_requirements': {'learning_goal': '解释检索结果与来源，以理由是否完整评价',
                                        'shared': ['不限句数'], 'by_resource': {}},
                'review_decisions': [],
            })
        before = session.query(DBLearningEvent).count()
        payload = {"resource_id": resource_id, "version_id": original_version}
        url = "/api/v1/resource-bundles/generation-jobs/from-quiz"
        response = client.post(url, json=payload)
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["created"] and started == [result["job_id"]]
        assert session.get(DBGenerationTask, result['job_id']).automation_state == 'queued'
        manifest = _generation_manifest(session, result["job_id"])
        assert manifest["scope"] == "single" and manifest["items"][0]["type"] == "quiz"
        assert manifest["items"][0]["source_ref_ids"] == ["demo-ref-07"]
        assert manifest["context_snapshot_id"] == original_version
        assert "previous_questions_and_work" in manifest["user_instruction"]
        assert '必须恰好两句话' not in manifest['user_instruction']
        assert manifest['context']['learning_goal'] == '解释检索结果与来源，以理由是否完整评价'
        assert manifest['context']['teaching_scope']['goal'] == manifest['context']['learning_goal']
        repeat = client.post(url, json=payload)
        assert repeat.status_code == 201 and repeat.json()["job_id"] == result["job_id"]
        assert not repeat.json()["created"] and len(started) == 1
        assert artifact.current_version_id == original_version and session.query(DBLearningEvent).count() == before
        assert session.get(DBGenerationTask, result["job_id"]).owner_public_id == learner.public_id
        identity["user"] = session.query(DBUser).filter(DBUser.public_id != learner.public_id).first()
        assert client.post(url, json=payload).status_code == 404
        assert len(started) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close(); engine.dispose()


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_new_practice_uses_selected_reviewed_version_during_later_revision():
    from app.database import DBGenerationTask
    from app.quiz_practice import create_quiz_practice
    from app.resource_bundles import ResourceBundleError, _generation_manifest, append_task_event
    import pytest

    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = session.get(DBArtifact, _quiz_resource(session, learner))
        reviewed = session.get(DBArtifactVersion, artifact.current_version_id)
        # The demo generator does not publish; model the real published-version
        # event explicitly before starting a later revision.
        append_task_event(session, task_id=artifact.creating_task_id, event_type="publish.completed",
            payload={"output_refs": [f"{artifact.id}:{reviewed.id}"]})
        pending = add_artifact_version(session, artifact=artifact, content=reviewed.content,
            content_format="json", metadata=reviewed.metadata_json, created_task_id=artifact.creating_task_id)
        session.get(DBGenerationTask, artifact.creating_task_id).status = "running"
        session.flush()
        detail = resource_detail(session, artifact)
        projections = {item["id"]: item["projection"] for item in detail["quiz"]["versions"]}
        assert detail["resource"]["learning_unavailable_reason"]
        assert projections[pending.id]["learning_unavailable_reason"]
        assert not projections[reviewed.id]["learning_unavailable_reason"]
        with pytest.raises(ResourceBundleError, match="仍在准备或核对"):
            create_quiz_practice(session, learner, resource_id=artifact.id, version_id=pending.id)
        job = create_quiz_practice(session, learner, resource_id=artifact.id, version_id=reviewed.id)
        assert _generation_manifest(session, job["job_id"])["context_snapshot_id"] == reviewed.id
        assert artifact.current_version_id == pending.id
    finally:
        session.close()
        engine.dispose()


def _quiz_resource(session, learner: DBUser):
    source = session.get(DBSourceRef, "demo-ref-07")
    profile = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
    assert source is not None and profile is not None
    job = create_generation_job(
        session,
        learner,
        course_id=COURSE_ID,
        knowledge_point_id="demo-kp-07",
        profile_snapshot_id=profile.id,
        idempotency_key="f6-t01-quiz-resource-test-001",
        scope="single",
        items=[{
            "type": "quiz",
            "title": "课程上下文即时练习",
            "source_ref_ids": [source.id],
            "completion_rule": "三道必做题均至少正确一次",
        }],
        learning_goal="依据当前课程来源完成一次可追溯即时练习",
    )
    session.commit()
    executed = execute_generation_job_demo(session, learner, job["job_id"])
    session.commit()
    item = executed["items"][0]
    assert item["state"] == "succeeded"
    return item["resource"]["resource_id"]


def test_quiz_resource_generation_attempt_history_and_evidence(monkeypatch):
    engine, session = _session()
    identity = {"user": None}

    async def isolated_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    client = TestClient(app)
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        identity["user"] = learner
        resource_id = _quiz_resource(session, learner)
        artifact = session.get(DBArtifact, resource_id)

        before_browse = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()
        detail = resource_detail(session, artifact)
        after_browse = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()
        assert after_browse == before_browse
        assert detail["catalog"]["type"] == "quiz"
        projection = detail["quiz"]["current"]
        assert projection["mode"] == "structured"
        assert projection["structured"]["knowledgePoint"]["id"]
        assert len(projection["questions"]) == 3
        assert projection["progress"] == {
            "question_count": 3,
            "attempted_count": 0,
            "correct_count": 0,
            "required_count": 3,
            "required_correct_count": 0,
            "completed": False,
        }
        question = projection["questions"][0]
        assert "answer_key" not in question

        version = session.get(DBAssessmentQuestionVersion, question["id"])
        correct_choice = version.answer_key["choice"]
        wrong_choice = next(label for label in ("A", "B", "C", "D") if label != correct_choice)
        wrong = client.post("/api/v1/m5/assessment/attempts", json={
            "question_version_id": question["id"],
            "idempotency_key": "f6-t01-wrong-attempt-001",
            "mode": "practice",
            "answer": {"choice": wrong_choice},
        })
        assert wrong.status_code == 201, wrong.text
        wrong_payload = wrong.json()
        assert wrong_payload["correct"] is False
        assert wrong_payload["correct_answer"] == {"choice": correct_choice}
        assert wrong_payload["answer_explanation"]
        assert wrong_payload["learning_evidence"]["created"] is True

        correct = client.post("/api/v1/m5/assessment/attempts", json={
            "question_version_id": question["id"],
            "idempotency_key": "f6-t01-correct-attempt-002",
            "mode": "practice",
            "answer": {"choice": correct_choice},
        })
        assert correct.status_code == 201, correct.text
        correct_payload = correct.json()
        assert correct_payload["correct"] is True
        assert correct_payload["id"] != wrong_payload["id"]
        assert session.query(DBAssessmentAttempt).filter_by(
            owner_public_id=learner.public_id,
            question_version_id=question["id"],
            mode="practice",
        ).count() == 2

        refreshed = resource_detail(session, artifact)["quiz"]["current"]
        refreshed_question = refreshed["questions"][0]
        assert len(refreshed_question["attempts"]) == 2
        assert refreshed_question["latest_attempt"]["correct"] is True
        assert refreshed["progress"]["attempted_count"] == 1
        assert refreshed["progress"]["correct_count"] == 1
        assert session.query(DBLearningEvent).filter_by(
            owner_public_id=learner.public_id,
            event_type="quiz_answered",
        ).count() >= 2
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_quiz_resource_completes_after_all_required_questions_are_correct(monkeypatch):
    engine, session = _session()
    identity = {"user": None}

    async def isolated_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    client = TestClient(app)
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        identity["user"] = learner
        resource_id = _quiz_resource(session, learner)
        artifact = session.get(DBArtifact, resource_id)
        questions = resource_detail(session, artifact)["quiz"]["current"]["questions"]

        for index, question in enumerate(questions, start=1):
            version = session.get(DBAssessmentQuestionVersion, question["id"])
            response = client.post("/api/v1/m5/assessment/attempts", json={
                "question_version_id": question["id"],
                "idempotency_key": f"f6-t01-complete-{index:02d}",
                "mode": "practice",
                "answer": {"choice": version.answer_key["choice"]},
            })
            assert response.status_code == 201, response.text
            assert response.json()["correct"] is True

        progress = resource_detail(session, artifact)["quiz"]["current"]["progress"]
        assert progress == {
            "question_count": 3,
            "attempted_count": 3,
            "correct_count": 3,
            "required_count": 3,
            "required_correct_count": 3,
            "completed": True,
        }
        assert session.query(DBLearningEvent).filter_by(
            owner_public_id=learner.public_id,
            event_type="quiz_answered",
        ).count() == 3
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()
        engine.dispose()


def test_quiz_resource_metadata_edit_compare_and_restore_preserve_question_ids():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        resource_id = _quiz_resource(session, learner)
        artifact = session.get(DBArtifact, resource_id)
        first = session.get(DBArtifactVersion, artifact.current_version_id)
        original_ids = [
            item["id"] for item in resource_detail(session, artifact)["quiz"]["current"]["questions"]
        ]
        revised = json.loads(first.content)
        revised["title"] = "课程上下文即时练习（修订）"
        revised["summary"] = "只修订资源说明，不改变题目身份和既有作答历史。"
        revised["questions"][0]["hints"] = ["先找题目的已知条件。", "按依赖顺序计算每一步。"]

        edited = create_resource_version(
            session,
            artifact=artifact,
            actor_public_id=learner.public_id,
            request=ResourceVersionCreateRequest(
                expected_lock_version=artifact.lock_version,
                source_version_id=first.id,
                content=json.dumps(revised, ensure_ascii=False),
                content_format="json",
            ),
        )
        second = session.get(DBArtifactVersion, artifact.current_version_id)
        assert [item["id"] for item in edited["quiz"]["current"]["questions"]] == original_ids
        assert edited["quiz"]["current"]["questions"][0]["hints"] == revised["questions"][0]["hints"]

        comparison = compare_resource_versions(
            session,
            artifact=artifact,
            left_version=first.version_number,
            right_version=second.version_number,
        )
        assert comparison["changed"] is True
        assert "课程上下文即时练习（修订）" in comparison["diff"]

        restored = restore_resource_version(
            session,
            artifact=artifact,
            actor_public_id=learner.public_id,
            request=ResourceVersionRestoreRequest(
                expected_lock_version=artifact.lock_version,
                version_id=first.id,
            ),
        )
        assert restored["quiz"]["current_version_id"] not in {first.id, second.id}
        assert [item["id"] for item in restored["quiz"]["current"]["questions"]] == original_ids
        assert len(restored["quiz"]["versions"]) == 3
    finally:
        session.close()
        engine.dispose()


def test_quiz_resource_projects_legacy_invalid_and_unavailable_versions_honestly():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        resource_id = _quiz_resource(session, learner)
        artifact = session.get(DBArtifact, resource_id)
        first = session.get(DBArtifactVersion, artifact.current_version_id)

        legacy = add_artifact_version(
            session,
            artifact=artifact,
            content="旧版测验题文本",
            content_format="markdown",
            created_by_public_id=learner.public_id,
            metadata=first.metadata_json,
        )
        invalid = add_artifact_version(
            session,
            artifact=artifact,
            content='{"schemaVersion":"f6.quiz-resource.v1"}',
            content_format="json",
            created_by_public_id=learner.public_id,
            metadata=first.metadata_json,
        )
        unavailable_content = json.loads(first.content)
        unavailable_content["questions"][0]["questionVersionId"] = "missing-question-version"
        unavailable = add_artifact_version(
            session,
            artifact=artifact,
            content=json.dumps(unavailable_content, ensure_ascii=False),
            content_format="json",
            created_by_public_id=learner.public_id,
            metadata=first.metadata_json,
        )
        session.commit()

        versions = {
            item["id"]: item["projection"]
            for item in resource_detail(session, artifact)["quiz"]["versions"]
        }
        assert versions[legacy.id]["mode"] == "legacy_readonly"
        assert versions[legacy.id]["questions"] == []
        assert versions[invalid.id]["mode"] == "invalid_structured"
        assert versions[invalid.id]["raw_content"] == invalid.content
        assert versions[unavailable.id]["mode"] == "structured"
        assert versions[unavailable.id]["questions"][0]["status"] == "unavailable"
        assert versions[unavailable.id]["progress"]["completed"] is False
    finally:
        session.close()
        engine.dispose()
