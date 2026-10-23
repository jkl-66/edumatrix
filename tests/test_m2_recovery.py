from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import (
    Base,
    DBArtifact,
    DBArtifactVersion,
    DBGenerationTask,
    DBLearningEvent,
    DBTaskEvent,
)
from app.m2_artifacts import (
    M2ArtifactGenerationError,
    M2StructuredArtifactGenerator,
    persist_generated_artifact,
)
from app.m2_baseline import seed_m2_baseline
from app.m2_contracts import GenerationContext, M2Capability
from app.m2_feedback import M2LearningFeedback, record_m2_feedback
from app.m2_manifest import build_m2_manifest
from app.m2_quality import run_m2_quality_checks
from app.m2_tasks import (
    create_golden_task,
    fail_task_step,
    resume_golden_task,
    retry_task_step,
    start_golden_task,
    start_task_step,
)
from tests.test_m2_artifacts import FakeStructuredLLM, _payloads


class MarkdownFailureLLM:
    async def generate(self, system_prompt, user_prompt, *, role):
        return "```json\n{}\n```"


def _open_database(path: Path):
    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _close_database(engine, session):
    session.close()
    engine.dispose()


def test_refresh_reconnect_restart_duplicate_submit_and_local_failure_recovery():
    path = Path.cwd() / f"m2_recovery_{uuid4().hex}.db"
    sidecars = [Path(f"{path}-wal"), Path(f"{path}-shm")]
    try:
        engine, session = _open_database(path)
        baseline = seed_m2_baseline(session)
        context = baseline.generation_context
        task, created = create_golden_task(
            session,
            context=context,
            idempotency_key="m2-recovery-golden-request",
            model="deterministic-test-double",
        )
        session.commit()
        task_id = task.id
        task_trace_id = task.trace_id
        owner = context.owner_public_id
        context_payload = context.model_dump(mode="json")
        initial = resume_golden_task(session, task_id=task_id, owner_public_id=owner)
        initial_cursor = initial["last_event_sequence"]
        assert created is True
        _close_database(engine, session)

        engine, session = _open_database(path)
        context = GenerationContext.model_validate(context_payload)
        assert resume_golden_task(
            session,
            task_id=task_id,
            owner_public_id=owner,
            after_event_sequence=initial_cursor,
        )["events"] == []
        start_golden_task(session, task_id=task_id, owner_public_id=owner)
        start_task_step(session, task_id=task_id, owner_public_id=owner, sequence=1)
        with pytest.raises(M2ArtifactGenerationError) as raised:
            asyncio.run(
                M2StructuredArtifactGenerator(MarkdownFailureLLM()).generate(
                    session, capability=M2Capability.LESSON, context=context
                )
            )
        assert raised.value.code == "artifact_schema_invalid"
        fail_task_step(
            session,
            task_id=task_id,
            owner_public_id=owner,
            sequence=1,
            error_code=raised.value.code,
            error_message=str(raised.value),
            retryable=True,
        )
        session.commit()
        failed_cursor = resume_golden_task(
            session, task_id=task_id, owner_public_id=owner
        )["last_event_sequence"]
        assert session.query(DBArtifact).filter_by(creating_task_id=task_id).count() == 0
        _close_database(engine, session)

        engine, session = _open_database(path)
        context = GenerationContext.model_validate(context_payload)
        failed_state = resume_golden_task(session, task_id=task_id, owner_public_id=owner)
        assert failed_state["latest_steps"][0]["status"] == "failed"
        retry_task_step(session, task_id=task_id, owner_public_id=owner, sequence=1)
        start_task_step(session, task_id=task_id, owner_public_id=owner, sequence=1)
        generator = M2StructuredArtifactGenerator(FakeStructuredLLM(_payloads(context)))
        lesson = asyncio.run(
            generator.generate(session, capability=M2Capability.LESSON, context=context)
        )
        lesson_artifact, lesson_version, lesson_created = persist_generated_artifact(
            session,
            task_id=task_id,
            context=context,
            capability=M2Capability.LESSON,
            artifact=lesson,
        )
        session.commit()
        assert lesson_created is True
        lesson_artifact_id = lesson_artifact.id

        replay_artifact, replay_version, replay_created = persist_generated_artifact(
            session,
            task_id=task_id,
            context=context,
            capability=M2Capability.LESSON,
            artifact=lesson,
        )
        assert replay_created is False
        assert replay_artifact.id == lesson_artifact.id
        assert replay_version.id == lesson_version.id
        for sequence, capability in (
            (2, M2Capability.LAB_GUIDE),
            (3, M2Capability.TIERED_QUIZ),
        ):
            start_task_step(session, task_id=task_id, owner_public_id=owner, sequence=sequence)
            artifact = asyncio.run(generator.generate(session, capability=capability, context=context))
            persist_generated_artifact(
                session,
                task_id=task_id,
                context=context,
                capability=capability,
                artifact=artifact,
            )
        start_task_step(session, task_id=task_id, owner_public_id=owner, sequence=4)
        assert run_m2_quality_checks(session, task_id=task_id, context=context).passed
        manifest, pre_feedback_manifest, _ = build_m2_manifest(
            session, task_id=task_id, context=context
        )
        quiz = session.query(DBArtifact).filter_by(
            creating_task_id=task_id, artifact_type="tiered_quiz"
        ).one()
        feedback = M2LearningFeedback(
            idempotency_key="m2-recovery-feedback-001",
            artifact_version_id=quiz.current_version_id,
            activity_type="quiz_attempt",
            completed=True,
            accuracy=0.72,
            help_requests=1,
            self_reported_difficulty=3,
            observed_seconds=600,
            occurred_at=datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc),
        )
        feedback_result = record_m2_feedback(
            session, task_id=task_id, context=context, feedback=feedback
        )
        session.commit()
        assert feedback_result.task_status == "completed"
        assert feedback_result.manifest_version_id != pre_feedback_manifest.id
        manifest_id = manifest.id
        _close_database(engine, session)

        engine, session = _open_database(path)
        context = GenerationContext.model_validate(context_payload)
        duplicate_task, duplicate_created = create_golden_task(
            session,
            context=context,
            idempotency_key="m2-recovery-golden-request",
            model="deterministic-test-double",
        )
        duplicate_feedback = record_m2_feedback(
            session, task_id=task_id, context=context, feedback=feedback
        )
        final_state = resume_golden_task(session, task_id=task_id, owner_public_id=owner)
        reconnect = resume_golden_task(
            session,
            task_id=task_id,
            owner_public_id=owner,
            after_event_sequence=failed_cursor,
        )
        assert duplicate_created is False
        assert duplicate_task.id == task_id
        assert duplicate_feedback.created is False
        assert final_state["status"] == "completed"
        assert [event["sequence"] for event in final_state["events"]] == list(
            range(1, final_state["last_event_sequence"] + 1)
        )
        assert reconnect["events"]
        assert reconnect["events"][0]["sequence"] == failed_cursor + 1
        assert session.query(DBGenerationTask).filter_by(id=task_id).count() == 1
        assert session.query(DBArtifact).filter_by(creating_task_id=task_id).count() == 4
        assert session.query(DBArtifact).filter_by(
            creating_task_id=task_id, artifact_type="lesson"
        ).count() == 1
        assert session.query(DBArtifactVersion).filter_by(artifact_id=lesson_artifact_id).count() == 1
        assert session.query(DBArtifactVersion).filter_by(artifact_id=manifest_id).count() == 2
        assert session.query(DBLearningEvent).filter_by(trace_id=task_trace_id).count() == 1
        assert session.query(DBTaskEvent).filter_by(task_id=task_id).count() == final_state[
            "last_event_sequence"
        ]
        _close_database(engine, session)
    finally:
        try:
            session.close()
            engine.dispose()
        except UnboundLocalError:
            pass
        for candidate in [path, *sidecars]:
            candidate.unlink(missing_ok=True)
