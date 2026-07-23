from __future__ import annotations

import hashlib
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.auth import get_password_hash
from app.database import (
    Base, DBAgentRun, DBArtifactVersion, DBAuditLog, DBClaimCheck,
    DBDebateRound, DBDecisionRecord, DBEvaluationRun, DBGenerationTask,
    DBJobLevel, DBLearningEvent, DBProfileSnapshot, DBQualityCheck,
    DBSkillStandard, DBTrainingCohort, DBCertification, DBUser,
)
from app.identity import new_public_id
from app.m1_enterprise import (
    add_organization_member, approve_exemption, assign_training,
    create_competency_standard, create_job_family, create_job_level,
    create_organization, create_training_cohort, create_training_program,
    issue_certification, publish_job_standard_version, record_skill_evidence,
    request_exemption, require_organization_access,
)
from app.m1_evidence import seed_rag_domain_pack, trace_bundle
from app.m1_repository import create_artifact_with_version, create_generation_task
from app.migrations import apply_registered_migrations


def _engine(path):
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def _user(session, prefix: str, *, role: str = "student") -> DBUser:
    user = DBUser(
        username=new_public_id(prefix),
        hashed_password=get_password_hash("stage-acceptance"),
        role=role,
    )
    session.add(user)
    session.flush()
    return user


def _hash(value) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_m1_stage_gate_survives_tenant_attacks_version_upgrade_and_reopen(tmp_path):
    database_path = tmp_path / "m1-stage-acceptance.db"
    engine = _engine(database_path)
    Base.metadata.create_all(engine)
    apply_registered_migrations(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as session:
        domain = seed_rag_domain_pack(session)
        skill = session.query(DBSkillStandard).filter_by(
            domain_version_id=domain["domain_version_id"]
        ).first()
        assert skill is not None

        admin_a = _user(session, "admin-a", role="admin")
        admin_b = _user(session, "admin-b", role="admin")
        learner_a = _user(session, "learner-a")
        learner_b = _user(session, "learner-b")
        org_a = create_organization(session, name="Enterprise A", actor=admin_a)
        org_b = create_organization(session, name="Enterprise B", actor=admin_b)
        add_organization_member(
            session, organization_id=org_a.id,
            user_public_id=learner_a.public_id, role="learner",
            actor_public_id=admin_a.public_id,
        )
        add_organization_member(
            session, organization_id=org_b.id,
            user_public_id=learner_b.public_id, role="learner",
            actor_public_id=admin_b.public_id,
        )

        family_a = create_job_family(
            session, organization_id=org_a.id, code="RAG-A",
            title="RAG Engineer A", actor_public_id=admin_a.public_id,
        )
        level_a = create_job_level(
            session, job_family=family_a, level_code="L2", version="2026.1",
            title="Independent RAG Engineer", actor_public_id=admin_a.public_id,
        )
        standard_a = create_competency_standard(
            session, job_level=level_a, skill_standard=skill,
            requirement_level="independent", version="2026.1",
            actor_public_id=admin_a.public_id,
            evidence_requirements=["hidden_test"],
            acceptance_rules=["all_required_pass"],
        )
        family_b = create_job_family(
            session, organization_id=org_b.id, code="RAG-B",
            title="RAG Engineer B", actor_public_id=admin_b.public_id,
        )
        create_job_level(
            session, job_family=family_b, level_code="L1", version="2026.1",
            title="Junior RAG Engineer", actor_public_id=admin_b.public_id,
        )
        program = create_training_program(
            session, organization_id=org_a.id, target_job_level=level_a,
            title="RAG transfer program", version="1",
            actor_public_id=admin_a.public_id,
        )
        cohort = create_training_cohort(
            session, program=program, actor_public_id=admin_a.public_id,
            course_versions=["course-rag-engineering-m0@0.1"],
            resource_version_ids=["resource-v1"],
            assessment_versions=["assessment-v1"],
        )
        assignment = assign_training(
            session, cohort=cohort, learner_public_id=learner_a.public_id,
            assignment_source="transfer_plan", actor_public_id=admin_a.public_id,
        )
        exemption = request_exemption(
            session, assignment_id=assignment.id,
            competency_standard_id=standard_a.id,
            requester_public_id=learner_a.public_id,
            evidence_ids=["prior-evidence"],
        )

        with pytest.raises(HTTPException) as read_denied:
            require_organization_access(
                session, organization_id=org_a.id,
                user_public_id=admin_b.public_id, action="read",
            )
        assert read_denied.value.status_code == 403
        with pytest.raises(HTTPException) as modify_denied:
            publish_job_standard_version(
                session, source_job_level=level_a, new_version="attack-version",
                actor_public_id=admin_b.public_id,
            )
        assert modify_denied.value.status_code == 403
        with pytest.raises(HTTPException) as approval_denied:
            approve_exemption(
                session, request=exemption, approver_public_id=admin_b.public_id
            )
        assert approval_denied.value.status_code == 403

        evidence = record_skill_evidence(
            session, organization_id=org_a.id,
            learner_public_id=learner_a.public_id,
            competency_standard=standard_a, evidence_type="hidden_test",
            source_object_id="artifact-version-1", result="passed",
            actor_public_id=admin_a.public_id,
            hidden_test_result={"passed": 8, "total": 8},
        )
        certification = issue_certification(
            session, organization_id=org_a.id,
            learner_public_id=learner_a.public_id, job_level=level_a,
            evidence_ids=[evidence.id], issuer_public_id=admin_a.public_id,
            retraining_rule={"months": 12},
        )

        trace_id = new_public_id("stage-trace")
        snapshot_data = {
            "job_level_id": level_a.id,
            "job_level_version": level_a.version,
            "competency_standard_id": standard_a.id,
            "competency_version": standard_a.version,
        }
        snapshot = DBProfileSnapshot(
            owner_public_id=learner_a.public_id,
            profile_version="profile-stage-v1", snapshot=snapshot_data,
            content_hash=_hash(snapshot_data), trace_id=trace_id,
        )
        session.add(snapshot)
        session.flush()
        task, _ = create_generation_task(
            session, owner_public_id=learner_a.public_id,
            capability="enterprise.training.evidence",
            idempotency_key=new_public_id("stage-idem"), trace_id=trace_id,
        )
        artifact, artifact_version = create_artifact_with_version(
            session, owner_public_id=learner_a.public_id,
            artifact_type="skill_evidence", title="Stage acceptance evidence",
            content="Evidence bound to the original standard snapshot",
            creating_task_id=task.id,
        )
        run = DBAgentRun(
            task_id=task.id, trace_id=trace_id, role="evidence-verifier",
            agent_version="1", input_summary=json.dumps(snapshot_data),
            output_artifact_version_id=artifact_version.id,
            status="completed",
        )
        session.add(run)
        session.flush()
        session.add_all([
            DBLearningEvent(
                owner_public_id=learner_a.public_id,
                event_type="skill_evidence.completed", trace_id=trace_id,
                object_type="skill_evidence", object_id=evidence.id,
                payload={"result": "passed"},
            ),
            DBQualityCheck(
                artifact_version_id=artifact_version.id, agent_run_id=run.id,
                trace_id=trace_id, check_type="hidden_test",
                checker_version="1", status="passed",
            ),
            DBClaimCheck(
                artifact_version_id=artifact_version.id, trace_id=trace_id,
                atomic_claim="All required hidden tests passed",
                support_status="supported", verdict="keep",
            ),
            DBDebateRound(
                task_id=task.id, artifact_version_id=artifact_version.id,
                trace_id=trace_id, round_number=1, max_rounds=1,
                prover_claim="evidence sufficient",
                challenger_response="verified against hidden tests",
                judge_decision="keep",
            ),
            DBDecisionRecord(
                owner_public_id=learner_a.public_id, task_id=task.id,
                profile_snapshot_id=snapshot.id, trace_id=trace_id,
                decision_type="certify", candidates=["retrain", "certify"],
                rules=["all_required_pass"], evidence_ids=[evidence.id],
                confidence=1.0,
            ),
            DBEvaluationRun(
                trace_id=trace_id, code_version="stage-acceptance",
                data_version="evaluation-m0-0.1", model_version="deterministic",
            ),
        ])

        new_level, new_standards = publish_job_standard_version(
            session, source_job_level=level_a, new_version="2026.2",
            actor_public_id=admin_a.public_id,
        )
        with pytest.raises(HTTPException) as duplicate_version:
            publish_job_standard_version(
                session, source_job_level=level_a, new_version="2026.2",
                actor_public_id=admin_a.public_id,
            )
        assert duplicate_version.value.status_code == 409
        session.commit()

        ids = {
            "cohort": cohort.id,
            "certification": certification.id,
            "old_level": level_a.id,
            "old_standard": standard_a.id,
            "new_level": new_level.id,
            "new_standard": new_standards[0].id,
            "trace": trace_id,
        }

    engine.dispose()

    reopened_engine = _engine(database_path)
    ReopenedSession = sessionmaker(bind=reopened_engine)
    with ReopenedSession() as session:
        cohort = session.query(DBTrainingCohort).filter_by(id=ids["cohort"]).one()
        certification = session.query(DBCertification).filter_by(
            id=ids["certification"]
        ).one()
        old_level = session.query(DBJobLevel).filter_by(id=ids["old_level"]).one()
        new_level = session.query(DBJobLevel).filter_by(id=ids["new_level"]).one()
        assert old_level.version == "2026.1"
        assert new_level.version == "2026.2"
        assert cohort.standard_snapshot["job_level_version"] == "2026.1"
        assert certification.standard_snapshot["job_level_version"] == "2026.1"
        assert cohort.standard_snapshot["competencies"][0]["id"] == ids["old_standard"]
        assert certification.standard_snapshot["competencies"][0]["id"] == ids["old_standard"]

        bundle = trace_bundle(session, ids["trace"])
        expected = {
            "profile_snapshots", "tasks", "agent_runs", "artifacts",
            "artifact_versions", "learning_events", "quality_checks",
            "claim_checks", "debate_rounds", "decisions", "evaluation_runs",
        }
        assert expected <= bundle.keys()
        assert all(len(bundle[key]) == 1 for key in expected)
        assert json.loads(bundle["agent_runs"][0].input_summary)[
            "job_level_version"
        ] == "2026.1"
        version_actions = {
            row.action for row in session.query(DBAuditLog).filter(
                DBAuditLog.object_id.in_([
                    ids["new_level"], ids["new_standard"]
                ])
            ).all()
        }
        assert version_actions == {
            "job_standard_version.publish",
            "competency_standard_version.publish",
        }
    reopened_engine.dispose()
