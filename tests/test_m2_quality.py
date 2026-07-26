from __future__ import annotations

import asyncio

from app.database import DBArtifact, DBArtifactVersion, DBClaimCheck, DBQualityCheck
from app.m2_artifacts import M2StructuredArtifactGenerator, persist_generated_artifact
from app.m2_contracts import M2Capability, validate_m2_artifact
from app.m2_quality import run_m2_quality_checks
from app.m2_tasks import (
    complete_golden_task,
    resume_golden_task,
    retry_task_step,
    start_task_step,
)
from tests.test_m2_artifacts import FakeStructuredLLM, _payloads, _seeded_session


def _generate_three(session, baseline, task):
    context = baseline.generation_context
    generator = M2StructuredArtifactGenerator(FakeStructuredLLM(_payloads(context)))
    for sequence, capability in enumerate(M2Capability, start=1):
        start_task_step(
            session,
            task_id=task.id,
            owner_public_id=context.owner_public_id,
            sequence=sequence,
        )
        artifact = asyncio.run(generator.generate(session, capability=capability, context=context))
        persist_generated_artifact(
            session,
            task_id=task.id,
            context=context,
            capability=capability,
            artifact=artifact,
        )


def test_quality_checks_are_versioned_separate_and_idempotent():
    engine, session, baseline, task = _seeded_session()
    context = baseline.generation_context
    try:
        _generate_three(session, baseline, task)
        start_task_step(
            session, task_id=task.id, owner_public_id=context.owner_public_id, sequence=4
        )
        result = run_m2_quality_checks(session, task_id=task.id, context=context)
        assert result.passed is True
        assert result.failed_artifact_types == []
        assert session.query(DBQualityCheck).count() == 9
        assert {row.check_type for row in session.query(DBQualityCheck).all()} == {
            "schema", "source_binding", "cross_artifact_binding"
        }
        assert all(row.score in {0.0, 1.0} for row in session.query(DBQualityCheck).all())
        assert session.query(DBClaimCheck).count() >= 3
        assert all(
            "does not claim semantic truth support" in row.rationale
            for row in session.query(DBClaimCheck).all()
        )

        repeated = run_m2_quality_checks(session, task_id=task.id, context=context)
        assert repeated.passed is True
        assert session.query(DBQualityCheck).count() == 9
        assert resume_golden_task(
            session, task_id=task.id, owner_public_id=context.owner_public_id
        )["status"] == "running"
    finally:
        session.close()
        engine.dispose()


def test_quality_failure_reworks_only_failed_artifact_and_keeps_old_version():
    engine, session, baseline, task = _seeded_session()
    context = baseline.generation_context
    try:
        _generate_three(session, baseline, task)
        lesson = session.query(DBArtifact).filter_by(
            creating_task_id=task.id, artifact_type="lesson"
        ).one()
        old_version_id = lesson.current_version_id
        old_version = session.query(DBArtifactVersion).filter_by(id=old_version_id).one()
        old_version.metadata_json = {**old_version.metadata_json, "domain_version_id": "dv-tampered"}
        start_task_step(
            session, task_id=task.id, owner_public_id=context.owner_public_id, sequence=4
        )
        failed = run_m2_quality_checks(session, task_id=task.id, context=context)
        assert failed.passed is False
        assert failed.failed_artifact_types == ["lesson"]
        state = resume_golden_task(
            session, task_id=task.id, owner_public_id=context.owner_public_id
        )
        assert state["latest_steps"][0]["attempt"] == 2
        assert state["latest_steps"][0]["status"] == "pending"
        assert state["latest_steps"][1]["attempt"] == 1
        assert state["latest_steps"][2]["attempt"] == 1

        start_task_step(
            session, task_id=task.id, owner_public_id=context.owner_public_id, sequence=1
        )
        revised_payload = _payloads(context)["理论教授"]
        revised_payload["sections"][0]["body_markdown"] += " 修订版本补充逐项核验。"
        revised = validate_m2_artifact(M2Capability.LESSON, revised_payload)
        _artifact, new_version, created = persist_generated_artifact(
            session,
            task_id=task.id,
            context=context,
            capability=M2Capability.LESSON,
            artifact=revised,
        )
        assert created is True
        assert new_version.id != old_version_id
        assert session.query(DBArtifactVersion).filter_by(artifact_id=lesson.id).count() == 2

        retry_task_step(
            session, task_id=task.id, owner_public_id=context.owner_public_id, sequence=4
        )
        start_task_step(
            session, task_id=task.id, owner_public_id=context.owner_public_id, sequence=4
        )
        passed = run_m2_quality_checks(session, task_id=task.id, context=context)
        assert passed.passed is True
        assert session.query(DBArtifactVersion).filter_by(artifact_id=lesson.id).count() == 2
        assert session.query(DBArtifactVersion).filter_by(id=old_version_id).one().id == old_version_id
    finally:
        session.close()
        engine.dispose()
