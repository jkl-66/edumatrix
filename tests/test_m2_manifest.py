from __future__ import annotations

import json

from app.database import DBArtifact, DBArtifactRelation, DBArtifactVersion
from app.m2_manifest import M2BundleManifest, build_m2_manifest
from app.m2_quality import run_m2_quality_checks
from app.m2_tasks import start_task_step
from tests.test_m2_artifacts import _seeded_session
from tests.test_m2_quality import _generate_three


def test_manifest_is_formal_idempotent_and_contains_only_lineage_not_answers():
    engine, session, baseline, task = _seeded_session()
    context = baseline.generation_context
    try:
        _generate_three(session, baseline, task)
        start_task_step(
            session, task_id=task.id, owner_public_id=context.owner_public_id, sequence=4
        )
        assert run_m2_quality_checks(session, task_id=task.id, context=context).passed
        artifact, version, created = build_m2_manifest(
            session, task_id=task.id, context=context
        )
        replay_artifact, replay_version, replay_created = build_m2_manifest(
            session, task_id=task.id, context=context
        )
        assert created is True
        assert replay_created is False
        assert replay_artifact.id == artifact.id
        assert replay_version.id == version.id
        assert artifact.artifact_type == "m2_bundle_manifest"
        manifest = M2BundleManifest.model_validate(json.loads(version.content))
        assert manifest.status == "quality_passed"
        assert [item.artifact_type for item in manifest.artifacts] == [
            "lesson", "lab_guide", "tiered_quiz"
        ]
        assert all(len(item.quality_check_ids) == 3 for item in manifest.artifacts)
        assert "answer_key" not in version.content
        assert "explanation" not in version.content
        assert session.query(DBArtifactRelation).filter_by(
            source_artifact_id=artifact.id, relation_type="contains"
        ).count() == 3
        assert session.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).count() == 1

        assert run_m2_quality_checks(session, task_id=task.id, context=context).passed
    finally:
        session.close()
        engine.dispose()


def test_manifest_refuses_unchecked_current_artifact_version():
    engine, session, baseline, task = _seeded_session()
    context = baseline.generation_context
    try:
        _generate_three(session, baseline, task)
        lesson = session.query(DBArtifact).filter_by(
            creating_task_id=task.id, artifact_type="lesson"
        ).one()
        assert lesson.current_version_id
        try:
            build_m2_manifest(session, task_id=task.id, context=context)
        except ValueError as exc:
            assert getattr(exc, "code", "") == "quality_checks_incomplete"
        else:
            raise AssertionError("unchecked artifact versions must not enter the M2 manifest")
    finally:
        session.close()
        engine.dispose()
