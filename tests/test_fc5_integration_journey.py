from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import get_password_hash
from app.database import (
    DBCompetitionJourneyRun, DBExternalIdentityMapping, DBHRFieldMappingVersion,
    DBHRSyncBatch, DBHRSyncRecord, DBIntegrationDelivery, DBIntegrationFaultDrill,
    DBIntegrationFaultDrillStep, DBIntegrationReconciliationRun,
    DBJobFamily, DBJobLevel, DBLMSAssignmentExchange, DBLocalLMSConnection,
    DBLocalLRSStatement, DBLocalSSOSession, DBLocalWebhookEndpoint,
    DBOrganization, DBOrganizationMembership, DBTrainingAssignment,
    DBTrainingCohort, DBTrainingProgram, DBUser, DBWebhookReceipt, SessionLocal,
)
from app.main import app
from tests.api_test_helpers import auth_headers
from tests.api_test_helpers import TEST_PASSWORD


@pytest.fixture()
def integration_context():
    suffix = datetime.utcnow().strftime("%H%M%S%f")
    admin_name = f"fc5_int_admin_{suffix}"
    learner_name = f"fc5_int_learner_{suffix}"
    outsider_name = f"fc5_int_outsider_{suffix}"
    org_id = f"org-fc5-int-{suffix}"
    with SessionLocal() as db:
        admin = DBUser(username=admin_name, display_name="集成评委管理员", hashed_password=get_password_hash(TEST_PASSWORD), role="admin")
        learner = DBUser(username=learner_name, display_name="冻结合成集成学员", hashed_password=get_password_hash(TEST_PASSWORD), role="student")
        outsider = DBUser(username=outsider_name, display_name="外部管理员", hashed_password=get_password_hash(TEST_PASSWORD), role="admin")
        org = DBOrganization(id=org_id, name="FC5 本地集成冻结组织", organization_type="enterprise")
        db.add_all([admin, learner, outsider, org]); db.flush()
        db.add_all([
            DBOrganizationMembership(organization_id=org.id, user_public_id=admin.public_id, role="admin", status="active"),
            DBOrganizationMembership(organization_id=org.id, user_public_id=learner.public_id, role="learner", status="active"),
        ])
        db.commit()
        result = {"admin_name": admin_name, "learner_name": learner_name, "outsider_name": outsider_name,
                  "admin_id": admin.public_id, "learner_id": learner.public_id, "org_id": org.id}
    yield result


def _create_run(client, headers, context, key="integration-journey"):
    response = client.post("/api/v1/competition-journeys/integration/runs", headers=headers, json={
        "organization_id": context["org_id"], "learner_public_id": context["learner_id"], "run_key": key,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _seed_evidence(context, started_at):
    now = max(datetime.utcnow(), started_at + timedelta(seconds=1))
    h = "a" * 64
    with SessionLocal() as db:
        identity = DBExternalIdentityMapping(organization_id=context["org_id"], user_public_id=context["learner_id"], provider="fc5-local-idp", external_subject=f"synthetic:{context['learner_id']}", status="active")
        db.add(identity); db.flush()
        db.add(DBLocalSSOSession(organization_id=context["org_id"], mapping_id=identity.id, user_public_id=context["learner_id"], assertion_id="fc5-assertion", assertion_hash=h, resolved_organization_role="learner", login_mode="simulated_sso", status="active", issued_at=now, expires_at=now + timedelta(hours=1)))
        mapping = DBHRFieldMappingVersion(organization_id=context["org_id"], source_key="fc5-hr", version_number=1, field_map={}, mapping_hash=h, created_by_public_id=context["admin_id"], created_at=now)
        db.add(mapping); db.flush()
        batch = DBHRSyncBatch(organization_id=context["org_id"], source_key="fc5-hr", source_snapshot_id="fc5-snapshot", source_sequence=1, mapping_version_id=mapping.id, source_snapshot={}, preview_snapshot={}, source_hash=h, status="applied", created_by_public_id=context["admin_id"], created_at=now, applied_at=now)
        db.add(batch); db.flush()
        db.add(DBHRSyncRecord(batch_id=batch.id, organization_id=context["org_id"], external_employee_id="SYN-FC5", action="create", outcome="created", user_public_id=context["learner_id"], evidence_snapshot={}, evidence_hash=h, created_at=now))
        family = DBJobFamily(organization_id=context["org_id"], code="FC5", title="集成演示岗位")
        db.add(family); db.flush()
        level = DBJobLevel(job_family_id=family.id, level_code="L1", version="1", title="集成演示岗位", status="active")
        db.add(level); db.flush()
        program = DBTrainingProgram(organization_id=context["org_id"], target_job_level_id=level.id, title="集成演示培训", version="1", status="active")
        db.add(program); db.flush()
        cohort = DBTrainingCohort(organization_id=context["org_id"], training_program_id=program.id, standard_snapshot={"synthetic": True}, status="active")
        db.add(cohort); db.flush()
        assignment = DBTrainingAssignment(organization_id=context["org_id"], cohort_id=cohort.id, learner_public_id=context["learner_id"], assignment_source="transfer_plan", status="assigned", assigned_at=now)
        db.add(assignment); db.flush()
        lms = DBLocalLMSConnection(organization_id=context["org_id"], connection_key="fc5-lms", display_name="本地 LMS", created_by_public_id=context["admin_id"], created_at=now)
        db.add(lms); db.flush()
        db.add(DBLMSAssignmentExchange(organization_id=context["org_id"], connection_id=lms.id, training_assignment_id=assignment.id, external_assignment_key="fc5-assignment", payload={}, payload_hash=h, status="assigned", synced_at=now))
        xapi = DBIntegrationDelivery(organization_id=context["org_id"], adapter_type="xapi", adapter_version="1", destination_key="fc5-lrs", idempotency_key="fc5-xapi", source_object_type="learning_event", source_object_id="fc5-event", payload={}, payload_hash=h, status="delivered", attempt_count=1, delivered_at=now, created_at=now)
        db.add(xapi); db.flush()
        db.add(DBLocalLRSStatement(organization_id=context["org_id"], destination_key="fc5-lrs", statement_id="fc5-event", delivery_id=xapi.id, actor_public_id=context["learner_id"], verb_id="completed", object_id="fc5-object", statement={}, statement_hash=h, received_at=now))
        endpoint = DBLocalWebhookEndpoint(organization_id=context["org_id"], name="FC5 接收端", destination_key="fc5-webhook", signing_secret="local-secret", secret_fingerprint=h, created_by_public_id=context["admin_id"], created_at=now)
        db.add(endpoint); db.flush()
        db.add(DBWebhookReceipt(endpoint_id=endpoint.id, organization_id=context["org_id"], event_id="fc5-webhook-event", nonce="fc5-nonce", timestamp_value=1, signature_prefix="v1=abc", payload_hash=h, outcome="accepted", reason_code="accepted", received_at=now))
        drill = DBIntegrationFaultDrill(organization_id=context["org_id"], run_key="fc5-drill", status="passed", current_scenario=7, lock_version=8, authority_before_hash=h, authority_after_hash=h, scenario_plan=[], created_by_public_id=context["admin_id"], created_at=now, completed_at=now + timedelta(seconds=1))
        db.add(drill); db.flush()
        keys = ["duplicate", "out_of_order", "revocation", "conflict", "disconnect", "timeout", "dead_letter"]
        for index, key in enumerate(keys, 1):
            after = {"status": "dead_letter"} if key == "dead_letter" else {}
            recovery = {"action": "explicit_requeue", "status": "delivered"} if key == "dead_letter" else {"action": "recovered"}
            db.add(DBIntegrationFaultDrillStep(drill_id=drill.id, organization_id=context["org_id"], scenario_index=index, scenario_key=key, outcome="passed", fault_code=f"fc5_{key}", before_snapshot={}, after_snapshot=after, recovery_snapshot=recovery, authority_hash=h, evidence_hash=h, created_at=now + timedelta(seconds=1)))
        db.add(DBIntegrationReconciliationRun(organization_id=context["org_id"], run_key="fc5-recon", mapping_versions={}, source_preview={}, count_snapshot={}, discrepancies=[], status="resolved", snapshot_hash=h, created_by_public_id=context["admin_id"], created_at=now + timedelta(seconds=2), closed_at=now + timedelta(seconds=2)))
        db.commit()


def test_integration_journey_visits_scope_and_run_key(integration_context):
    with TestClient(app) as client:
        admin = auth_headers(client, integration_context["admin_name"])
        outsider = auth_headers(client, integration_context["outsider_name"])
        learner = auth_headers(client, integration_context["learner_name"])
        run = _create_run(client, admin, integration_context)
        assert run["progress"] == {"completed": 0, "total": 6, "percent": 0}
        assert run["integration_context"]["network_sent"] is False
        for step in run["steps"]:
            response = client.post(f"/api/v1/competition-journeys/integration/runs/{run['id']}/visits", headers=admin, json={"step_key": step["key"], "route": step["route"]})
            assert response.status_code == 201, response.text
        current = client.get(f"/api/v1/competition-journeys/integration/runs/{run['id']}", headers=admin).json()
        assert current["progress"]["completed"] == 0 and len(current["visits"]) == 6
        assert _create_run(client, admin, integration_context)["created"] is False
        assert client.get(f"/api/v1/competition-journeys/integration/runs/{run['id']}", headers=outsider).status_code == 403
        assert client.get("/api/v1/competition-journeys/integration", headers=learner).status_code == 403


def test_integration_journey_requires_same_context_and_ordered_recovery(integration_context):
    with TestClient(app) as client:
        admin = auth_headers(client, integration_context["admin_name"])
        run = _create_run(client, admin, integration_context, "integration-lifecycle")
        started = datetime.fromisoformat(run["created_at"])
        _seed_evidence(integration_context, started)
        final = client.get(f"/api/v1/competition-journeys/integration/runs/{run['id']}", headers=admin)
        assert final.status_code == 200, final.text
        body = final.json()
        assert body["status"] == "completed"
        assert body["progress"] == {"completed": 6, "total": 6, "percent": 100}
        assert all(step["complete"] for step in body["steps"])


def test_migration_061_preserves_all_six_journey_types_and_marketplace_fk():
    with SessionLocal() as db:
        assert db.execute(text("select count(*) from schema_migrations where version='20260805_061'")).scalar_one() == 1
        owner = db.query(DBUser).first()
        rows = [DBCompetitionJourneyRun(owner_public_id=owner.public_id, journey_type=kind, run_key=f"fc5-061-{kind}", baseline_snapshot={"kind": kind}, baseline_hash=str(index) * 64) for index, kind in enumerate(("student", "media", "teacher", "enterprise", "marketplace", "integration"), 1)]
        db.add_all(rows); db.commit()
        assert {row.journey_type for row in rows} == {"student", "media", "teacher", "enterprise", "marketplace", "integration"}
        fk = db.execute(text("pragma foreign_key_list(marketplace_journey_search_verifications)")).all()
        assert next(row[2] for row in fk if row[3] == "run_id") == "competition_journey_runs"
