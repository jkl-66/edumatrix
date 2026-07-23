from __future__ import annotations

import hashlib
import json

from app.auth import get_password_hash
from app.database import (
    DBAgentRun, DBArtifactVersion, DBClaimCheck, DBDebateRound, DBDecisionRecord,
    DBDomainPack, DBDomainVersion, DBEvaluationCase, DBEvaluationRun, DBGenerationTask,
    DBJobTask, DBLearningEvent, DBProfileSnapshot, DBQualityCheck, DBSkillStandard, DBSourceRef, DBUser, SessionLocal, init_db
)
from app.identity import new_public_id
from app.m1_evidence import seed_m0_evaluation_cases, seed_rag_domain_pack, trace_bundle
from app.m1_repository import create_artifact_with_version, create_generation_task


init_db()


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def test_domain_pack_and_60_cases_seed_idempotently():
    with SessionLocal() as session:
        result = seed_rag_domain_pack(session)
        assert result["jobs"] == 12
        assert result["skills"] == 3
        assert seed_m0_evaluation_cases(session, result["domain_version_id"]) == 60
        assert seed_m0_evaluation_cases(session, result["domain_version_id"]) == 60
        assert session.query(DBDomainPack).filter_by(domain_key="domain-rag-0.1").count() == 1
        assert session.query(DBJobTask).filter_by(domain_version_id=result["domain_version_id"]).count() == 12
        assert session.query(DBSkillStandard).filter_by(domain_version_id=result["domain_version_id"]).count() == 3
        assert session.query(DBEvaluationCase).filter_by(domain_version_id=result["domain_version_id"]).count() == 60


def test_trace_bundle_reconstructs_full_competition_evidence_chain():
    with SessionLocal() as session:
        domain = seed_rag_domain_pack(session)
        user = DBUser(username=new_public_id("trace-user"), hashed_password=get_password_hash("pw"))
        session.add(user); session.flush()
        trace_id = new_public_id("trace")
        snapshot_data = {"level": "beginner", "weak_points": ["KP-11"]}
        snapshot = DBProfileSnapshot(
            owner_public_id=user.public_id, profile_version="profile-v1", snapshot=snapshot_data,
            content_hash=_hash(snapshot_data), trace_id=trace_id
        )
        session.add(snapshot); session.flush()
        task, _ = create_generation_task(
            session, owner_public_id=user.public_id, capability="lesson.generate",
            idempotency_key=new_public_id("idem"), trace_id=trace_id
        )
        artifact, version = create_artifact_with_version(
            session, owner_public_id=user.public_id, artifact_type="lesson", title="Trace lesson",
            content="Atomic claim with source", creating_task_id=task.id
        )
        source_ref = session.query(DBSourceRef).first()
        run = DBAgentRun(task_id=task.id, trace_id=trace_id, role="generator", agent_version="1", status="completed", output_artifact_version_id=version.id)
        session.add(run); session.flush()
        session.add(DBLearningEvent(
            owner_public_id=user.public_id, event_type="feedback.submitted",
            trace_id=trace_id, object_type="artifact_version", object_id=version.id,
            payload={"rating": 4},
        ))
        session.add(DBQualityCheck(artifact_version_id=version.id, agent_run_id=run.id, trace_id=trace_id, check_type="citation", checker_version="1", status="passed", source_ref_ids=[source_ref.id]))
        session.add(DBClaimCheck(artifact_version_id=version.id, trace_id=trace_id, atomic_claim="Atomic claim", source_ref_id=source_ref.id, support_status="supported", verdict="keep"))
        session.add(DBDebateRound(task_id=task.id, artifact_version_id=version.id, trace_id=trace_id, round_number=1, max_rounds=2, prover_claim="supported", challenger_response="checked", judge_decision="keep", evidence_ref_ids=[source_ref.id]))
        session.add(DBDecisionRecord(owner_public_id=user.public_id, task_id=task.id, profile_snapshot_id=snapshot.id, trace_id=trace_id, decision_type="advance", candidates=["review","advance"], rules=["quality_passed"], evidence_ids=[version.id], confidence=0.9))
        session.add(DBEvaluationRun(trace_id=trace_id, code_version="test", data_version="evaluation-m0-0.1", model_version="deterministic"))
        session.commit()
        bundle = trace_bundle(session, trace_id)
        for key in ("profile_snapshots","tasks","agent_runs","artifacts","artifact_versions","learning_events","quality_checks","claim_checks","debate_rounds","decisions","evaluation_runs"):
            assert len(bundle[key]) == 1, key
