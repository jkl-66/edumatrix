from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBArtifactVersion, DBDecisionRecord, DBLearningEvent, DBProfileEvidence
from app.m3_decisions import build_m3_decision_comparison, persist_m3_decision_comparison
from app.m3_interactive import (
    InteractiveAction,
    M3InteractiveError,
    M3InteractiveManifest,
    TuningParameters,
    apply_m3_interactive_action,
    build_m3_interactive_manifest,
    create_m3_interactive_session,
    persist_m3_interactive_manifest,
    record_m3_interactive_evidence,
)
from app.m3_matching import build_m3_matching_report, persist_m3_matching_report
from tests.test_m3_matching import _prepare
from app.m3_baseline import seed_m3_profile_baselines


@pytest.fixture
def interactive_fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    fixture = seed_m3_profile_baselines(session).fixtures[1]
    task = _prepare(session, fixture)
    matching = build_m3_matching_report(session, task_id=task.id, owner_public_id=task.owner_public_id)
    persist_m3_matching_report(session, report=matching)
    decision = build_m3_decision_comparison(session, task_id=task.id, owner_public_id=task.owner_public_id)
    persist_m3_decision_comparison(session, comparison=decision)
    manifest = build_m3_interactive_manifest(session, task_id=task.id, owner_public_id=task.owner_public_id)
    manifest_artifact, manifest_version, _ = persist_m3_interactive_manifest(
        session, task_id=task.id, owner_public_id=task.owner_public_id, manifest=manifest
    )
    session_artifact, session_version, _ = create_m3_interactive_session(
        session,
        task_id=task.id,
        owner_public_id=task.owner_public_id,
        manifest_artifact_version_id=manifest_version.id,
    )
    try:
        yield session, fixture, task, manifest, manifest_artifact, session_artifact, session_version
    finally:
        session.close()
        engine.dispose()


def _action(session, artifact, owner, key, action, **kwargs):
    return apply_m3_interactive_action(
        session,
        session_artifact_id=artifact.id,
        owner_public_id=owner,
        request=InteractiveAction(idempotency_key=key, action=action, **kwargs),
    )


def _optimal_parameters():
    return TuningParameters(keyword_weight=0.4, vector_weight=0.6, top_k=5, rerank_threshold=0.55)


def test_manifest_is_restricted_versioned_and_has_no_remote_script_surface(interactive_fixture):
    session, fixture, task, manifest, manifest_artifact, _session_artifact, _version = interactive_fixture
    assert manifest.runtime_mode == "safe_deterministic_simulation"
    assert manifest.security_level == "no_external_code_or_network"
    assert len(manifest.public_query_scenarios) == 10
    assert manifest.hidden_acceptance.hidden_expected_values_exposed is False
    assert set(manifest.allowed_components) == {
        "parameter_controls", "metrics_table", "retrieval_log", "evidence_table",
        "fault_panel", "hint_panel", "acceptance_panel",
    }
    assert session.query(DBArtifactVersion).filter_by(artifact_id=manifest_artifact.id).count() == 1
    payload = manifest.model_dump(mode="json")
    payload["remote_script"] = "https://example.invalid/unsafe.js"
    with pytest.raises(ValidationError):
        M3InteractiveManifest.model_validate(payload)


def test_deterministic_happy_path_is_versioned_idempotent_and_resettable(interactive_fixture):
    session, fixture, task, _manifest, _manifest_artifact, artifact, initial_version = interactive_fixture
    owner = task.owner_public_id
    state, _, _, _ = _action(session, artifact, owner, "action-configure-1", "configure", parameters=_optimal_parameters())
    assert state.status == "configured"
    state, _, _, _ = _action(session, artifact, owner, "action-run-0001", "run")
    assert state.status == "running"
    state, _, _, _ = _action(session, artifact, owner, "action-evaluate-1", "evaluate")
    assert state.status == "evaluated"
    assert state.metrics.recall_at_k > state.metrics.baseline_recall_at_k
    assert state.metrics.ranking_score > state.metrics.baseline_ranking_score
    state, submit_version, submit_event, created = _action(session, artifact, owner, "action-submit-01", "submit")
    assert state.status == "passed"
    assert state.hidden_acceptance.passed is True
    assert set(state.hidden_acceptance.model_dump()) == {
        "passed_count", "total_count", "passed", "failure_categories",
        "checker_version", "hidden_expected_values_exposed",
    }
    version_count = session.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).count()
    replay = _action(session, artifact, owner, "action-submit-01", "submit")
    assert replay[1].id == submit_version.id and replay[2].id == submit_event.id and replay[3] is False
    assert session.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).count() == version_count
    state, _, _, _ = _action(session, artifact, owner, "action-reset-001", "reset")
    assert state.status == "not_started" and state.attempt == 2 and state.action_count == 5
    assert initial_version.id != artifact.current_version_id


def test_fault_requires_correct_diagnosis_and_recovery(interactive_fixture):
    session, fixture, task, _manifest, _manifest_artifact, artifact, _version = interactive_fixture
    owner = task.owner_public_id
    _action(session, artifact, owner, "fault-config-001", "configure", parameters=_optimal_parameters())
    _action(session, artifact, owner, "fault-inject-001", "inject_fault", fault_type="index_version_mismatch")
    _action(session, artifact, owner, "fault-run-00001", "run")
    state, _, _, _ = _action(session, artifact, owner, "fault-eval-0001", "evaluate")
    assert state.status == "failed"
    state, _, _, _ = _action(
        session, artifact, owner, "fault-diag-wrong", "diagnose",
        diagnosis="索引版本不一致", recovery_action="retry_without_change",
    )
    assert state.status == "diagnosed" and state.recovery_verified is False
    with pytest.raises(M3InteractiveError) as raised:
        _action(session, artifact, owner, "fault-rerun-bad", "rerun")
    assert raised.value.code == "recovery_not_verified"
    # Reset and reproduce the fault before choosing the verified recovery.
    _action(session, artifact, owner, "fault-reset-001", "reset")
    _action(session, artifact, owner, "fault-config-002", "configure", parameters=_optimal_parameters())
    _action(session, artifact, owner, "fault-inject-002", "inject_fault", fault_type="index_version_mismatch")
    _action(session, artifact, owner, "fault-run-00002", "run")
    _action(session, artifact, owner, "fault-eval-0002", "evaluate")
    state, _, _, _ = _action(
        session, artifact, owner, "fault-diag-right", "diagnose",
        diagnosis="当前索引版本与课程版本不一致", recovery_action="select_matching_index_version",
    )
    assert state.recovery_verified is True
    state, _, _, _ = _action(session, artifact, owner, "fault-rerun-ok1", "rerun")
    assert state.status == "running" and state.injected_fault == "none"
    state, _, _, _ = _action(session, artifact, owner, "fault-eval-0003", "evaluate")
    assert state.status == "evaluated"


def test_hidden_acceptance_flows_to_skill_evidence_report_and_proposed_decision(interactive_fixture):
    session, fixture, task, _manifest, _manifest_artifact, artifact, _version = interactive_fixture
    owner = task.owner_public_id
    _action(session, artifact, owner, "evidence-config1", "configure", parameters=_optimal_parameters())
    _action(session, artifact, owner, "evidence-run-001", "run")
    _action(session, artifact, owner, "evidence-eval-01", "evaluate")
    state, _, submit_event, _ = _action(session, artifact, owner, "evidence-submit", "submit")
    assert state.status == "passed" and state.hint_count == 0
    result = record_m3_interactive_evidence(
        session, session_artifact_id=artifact.id, owner_public_id=owner
    )
    replay = record_m3_interactive_evidence(
        session, session_artifact_id=artifact.id, owner_public_id=owner
    )
    assert replay == result
    assert result.learning_event_id == submit_event.id
    assert result.skill_evidence_level == "SE-4"
    evidence = session.query(DBProfileEvidence).filter_by(id=result.profile_evidence_id).one()
    assert "mastery_update:none" in evidence.features
    assert "不代表长期掌握或岗位胜任" in evidence.evidence_summary
    decision = session.query(DBDecisionRecord).filter_by(id=result.decision_record_id).one()
    assert decision.status == "proposed" and decision.user_confirmed is False
    assert decision.execution_impact["mastery_update"] == "none"
    assert session.query(DBLearningEvent).filter_by(id=submit_event.id).count() == 1
    assert (submit_event.payload or {})["hidden_result"]["hidden_expected_values_exposed"] is False


def test_hints_cap_evidence_at_se2_and_do_not_reveal_hidden_answers(interactive_fixture):
    session, fixture, task, _manifest, _manifest_artifact, artifact, _version = interactive_fixture
    owner = task.owner_public_id
    _action(session, artifact, owner, "hint-config-001", "configure", parameters=_optimal_parameters())
    _action(session, artifact, owner, "hint-run-00001", "run")
    _action(session, artifact, owner, "hint-eval-0001", "evaluate")
    state, _, _, _ = _action(session, artifact, owner, "hint-request-01", "request_hint")
    assert state.hint_level == 1 and state.hint_count == 1
    _action(session, artifact, owner, "hint-submit-001", "submit")
    result = record_m3_interactive_evidence(session, session_artifact_id=artifact.id, owner_public_id=owner)
    assert result.skill_evidence_level == "SE-2"
    evidence = session.query(DBProfileEvidence).filter_by(id=result.profile_evidence_id).one()
    assert evidence.weight < 0.85
    assert all("answer" not in feature.lower() for feature in evidence.features)
