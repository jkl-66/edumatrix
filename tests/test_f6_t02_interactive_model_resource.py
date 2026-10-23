from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBArtifact, DBArtifactVersion, DBLearningEvent, DBProfileSnapshot, DBSourceRef, DBUser
from app.interactive_lab import InteractiveLabError, apply_action, create_instance
from app.m5_resources import (
    ResourceVersionCreateRequest,
    create_resource_version,
    parse_interactive_model_content,
    resource_detail,
)
from app.resource_bundles import create_generation_job, execute_generation_job_demo


ROOT = Path(__file__).resolve().parents[1]
COURSE_ID = "demo-course-rag-trust-v1"
ROUTE_CONTRACT = ROOT / "frontend/src/router/routeMigrationContract.json"


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


def _resource(session, learner: DBUser, key: str = "f6-t02-resource-001") -> DBArtifact:
    source = session.get(DBSourceRef, "demo-ref-07")
    profile = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
    assert source is not None and profile is not None
    job = create_generation_job(
        session,
        learner,
        course_id=COURSE_ID,
        knowledge_point_id="demo-kp-07",
        profile_snapshot_id=profile.id,
        idempotency_key=key,
        scope="single",
        items=[{
            "type": "interactive_model",
            "title": "混合检索参数实验",
            "source_ref_ids": [source.id],
            "completion_rule": "运行实验并提交不少于 20 个字的观察结论",
        }],
        learning_goal="解释混合检索参数对召回、排序质量和延迟的影响",
    )
    session.commit()
    executed = execute_generation_job_demo(session, learner, job["job_id"])
    session.commit()
    item = executed["items"][0]
    assert item["state"] == "succeeded"
    return session.get(DBArtifact, item["resource"]["resource_id"])


def test_generation_creates_strict_interactive_model_resource_and_projection():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner)
        version = session.get(DBArtifactVersion, artifact.current_version_id)
        parsed = parse_interactive_model_content(version.content)
        detail = resource_detail(session, artifact)

        assert version.content_format == "json"
        assert parsed.schemaVersion == "f6.interactive-model.v1"
        assert parsed.templateId == "rag-hybrid-tuning"
        assert {item.key for item in parsed.parameters} == {
            "keyword_weight", "vector_weight", "top_k", "rerank_threshold",
        }
        assert parsed.dataset.sourceRefIds == parsed.sourceRefIds
        assert detail["catalog"]["route"] == f"/workspace/resources/models/{artifact.id}"
        projection = detail["interactive_model"]["current"]
        assert projection["mode"] == "structured"
        assert projection["source_readiness"]["publishable"] is True
        assert projection["structured"]["observationPrompt"]["minimumCharacters"] == 20
    finally:
        session.close()
        engine.dispose()


def test_only_valid_observation_submission_creates_learning_evidence():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "f6-t02-resource-evidence-001")
        state, version, _ = create_instance(
            session,
            owner=learner.public_id,
            template_id=None,
            title=None,
            parameters=None,
            linked_media_resource_id=None,
            source_resource_id=artifact.id,
            idempotency_key="f6-t02-instance-evidence-001",
        )
        session.flush()
        baseline = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()

        evaluated, _ = apply_action(
            session,
            instance_id=state.instance_id,
            owner=learner.public_id,
            action="run",
            parameters=None,
            observation=None,
            expected_version=version.version_number,
            idempotency_key="f6-t02-run-evidence-001",
        )
        assert evaluated["status"] == "evaluated"
        assert len(evaluated["computed_series"]) == 3
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() == baseline

        with pytest.raises(InteractiveLabError) as exc_info:
            apply_action(
                session,
                instance_id=state.instance_id,
                owner=learner.public_id,
                action="submit",
                parameters=None,
                observation="太短",
                expected_version=evaluated["version_number"],
                idempotency_key="f6-t02-short-observation-001",
            )
        assert exc_info.value.code == "lab_observation_required"
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() == baseline

        observation = "提高召回数量会改善召回率，但平均延迟也随之上升，因此需要结合排序质量选择平衡点。"
        submitted, created = apply_action(
            session,
            instance_id=state.instance_id,
            owner=learner.public_id,
            action="submit",
            parameters=None,
            observation=observation,
            expected_version=evaluated["version_number"],
            idempotency_key="f6-t02-submit-observation-001",
        )
        assert created is True
        assert submitted["status"] == "passed"
        assert submitted["submitted_observation"] == observation
        assert submitted["learning_evidence"]["created"] is True
        event = session.get(DBLearningEvent, submitted["learning_evidence"]["event_id"])
        assert event.event_type == "interactive_model_observation_submitted"
        assert event.object_id == artifact.id
        assert event.evidence_status == "accepted"
        assert event.mastery_eligible is True
        assert event.payload["observation"] == observation
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() == baseline + 1

        replay, replay_created = apply_action(
            session,
            instance_id=state.instance_id,
            owner=learner.public_id,
            action="submit",
            parameters=None,
            observation=observation,
            expected_version=evaluated["version_number"],
            idempotency_key="f6-t02-submit-observation-001",
        )
        assert replay_created is False
        assert replay["version_id"] == submitted["version_id"]
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() == baseline + 1
    finally:
        session.close()
        engine.dispose()


def test_resource_binding_enforces_owner_type_and_frozen_version():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        other = session.query(DBUser).filter(DBUser.public_id != learner.public_id).first()
        artifact = _resource(session, learner, "f6-t02-resource-owner-001")
        source_version_id = artifact.current_version_id

        with pytest.raises(InteractiveLabError) as exc_info:
            create_instance(
                session,
                owner=other.public_id,
                template_id=None,
                title=None,
                parameters=None,
                linked_media_resource_id=None,
                source_resource_id=artifact.id,
                idempotency_key="f6-t02-foreign-instance-001",
            )
        assert exc_info.value.code == "lab_source_resource_forbidden"

        state, _, _ = create_instance(
            session,
            owner=learner.public_id,
            template_id=None,
            title=None,
            parameters=None,
            linked_media_resource_id=None,
            source_resource_id=artifact.id,
            idempotency_key="f6-t02-owned-instance-001",
        )
        assert state.source_resource_version_id == source_version_id
        assert state.course_id == COURSE_ID
        assert state.knowledge_point_id == "demo-kp-07"
        assert state.profile_snapshot_id
        assert state.source_ref_ids
    finally:
        session.close()
        engine.dispose()


def test_structured_resource_revision_is_validated_and_frontend_has_dedicated_contract():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        artifact = _resource(session, learner, "f6-t02-resource-revision-001")
        current = session.get(DBArtifactVersion, artifact.current_version_id)
        revised = json.loads(current.content)
        revised["summary"] = "修订后的参数实验说明，仍保留原课程、来源、参数和观察规则。"
        detail = create_resource_version(
            session,
            artifact=artifact,
            actor_public_id=learner.public_id,
            request=ResourceVersionCreateRequest(
                expected_lock_version=artifact.lock_version,
                source_version_id=current.id,
                content=json.dumps(revised, ensure_ascii=False),
                content_format="json",
            ),
        )
        assert len(detail["interactive_model"]["versions"]) == 2

        view = (ROOT / "frontend/src/views/InteractiveLabWorkspace.vue").read_text(encoding="utf-8")
        router = (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")
        assert "source_resource_id" in view
        assert "观察结论" in view
        assert "computed_series" in view
        assert "name: 'InteractiveModelResource', component: InteractiveLabWorkspace" in router
        assert "component: InteractiveLabWorkspace" in router
        migration = next(
            record
            for record in json.loads(ROUTE_CONTRACT.read_text(encoding="utf-8"))
            if record["sourcePath"] == "/interactive-lab"
        )
        assert migration["disposition"] == "merged"
        assert migration["destination"] == "/workspace/resources/models/legacy"
        assert migration["rollbackRoute"] == "/interactive-lab"
        assert migration["roles"] == ["student", "teacher"]
    finally:
        session.close()
        engine.dispose()
