from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import (
    DBEvaluationRun, DBExternalIdentityMapping, DBOrganization,
    DBOrganizationMembership, DBUser, SessionLocal,
)
from app.identity import new_public_id
from app.main import app
from app.m1_object_service import OBJECT_SPECS
from tests.api_test_helpers import TEST_PASSWORD, auth_headers


def _user_for_headers(headers: dict[str, str]) -> DBUser:
    token = headers["Authorization"].split(" ", 1)[1]
    from jose import jwt
    from config import CONFIG
    payload = jwt.decode(token, CONFIG.auth_secret_key, algorithms=[CONFIG.auth_algorithm])
    with SessionLocal() as session:
        user = session.query(DBUser).filter_by(public_id=payload["uid"]).one()
        session.expunge(user)
        return user


def _promote_and_login(client: TestClient, username: str) -> dict[str, str]:
    with SessionLocal() as session:
        user = session.query(DBUser).filter_by(username=username).one()
        user.role = "teacher"
        session.commit()
    response = client.post("/api/auth/login", data={"username": username, "password": TEST_PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_object_gateway_registry_and_openapi_schema_cover_m1_core_types():
    expected = {
        "course", "source_document", "knowledge_point", "source_ref",
        "generation_task", "artifact", "artifact_version", "plan_draft",
        "memory_item", "domain_pack", "profile_snapshot", "profile_evidence", "agent_run",
        "quality_check", "claim_check", "evaluation_case", "organization",
        "job_level", "competency_standard", "training_cohort", "training_assignment",
        "exemption_request", "skill_evidence", "certification", "external_identity_mapping",
    }
    assert expected <= set(OBJECT_SPECS)
    assert all(hasattr(spec.model, "id") for spec in OBJECT_SPECS.values())
    schema = app.openapi()
    assert "/api/v1/objects/{object_type}" in schema["paths"]
    assert "/api/v1/objects/{object_type}/{object_id}" in schema["paths"]
    assert "CanonicalObjectDetail" in schema["components"]["schemas"]


def test_object_gateway_enforces_owner_public_course_and_hides_content():
    with TestClient(app) as client:
        owner_headers = auth_headers(client, new_public_id("gateway-owner"))
        other_headers = auth_headers(client, new_public_id("gateway-other"))
        course = client.get(
            "/api/v1/objects/course/course-rag-engineering-m0", headers=other_headers
        )
        assert course.status_code == 200
        assert course.json()["access"] == "owner_or_scope_member"

        artifact = client.post(
            "/api/v1/artifacts", headers=owner_headers,
            json={"artifact_type": "gateway-test", "title": "Private gateway artifact", "content": "SECRET BODY"},
        )
        assert artifact.status_code == 201
        artifact_id = artifact.json()["id"]
        version_id = artifact.json()["current_version_id"]
        detail = client.get(f"/api/v1/objects/artifact/{artifact_id}", headers=owner_headers)
        assert detail.status_code == 200
        assert "SECRET BODY" not in detail.text
        assert detail.json()["owner_public_id"]
        version = client.get(f"/api/v1/objects/artifact_version/{version_id}", headers=owner_headers)
        assert version.status_code == 200
        assert version.json()["source_ids"]["artifact_id"] == artifact_id
        assert client.get(
            f"/api/v1/objects/artifact/{artifact_id}", headers=other_headers
        ).status_code == 403


def test_object_gateway_enforces_organization_and_internal_boundaries():
    with TestClient(app) as client:
        member_username = new_public_id("gateway-member")
        outsider_username = new_public_id("gateway-outsider")
        operator_username = new_public_id("gateway-operator")
        member_headers = auth_headers(client, member_username)
        outsider_headers = auth_headers(client, outsider_username)
        auth_headers(client, operator_username)
        member = _user_for_headers(member_headers)

        with SessionLocal() as session:
            org = DBOrganization(name="Gateway organization")
            session.add(org)
            session.flush()
            session.add(DBOrganizationMembership(
                organization_id=org.id, user_public_id=member.public_id, role="learner"
            ))
            session.flush()
            mapping = DBExternalIdentityMapping(
                organization_id=org.id, user_public_id=member.public_id,
                provider="test-sso", external_subject=new_public_id("external-secret"),
            )
            run = DBEvaluationRun(
                trace_id=new_public_id("gateway-trace"), code_version="test",
                data_version="test", model_version="test",
            )
            session.add_all([mapping, run])
            session.commit()
            mapping_id, run_id, org_id = mapping.id, run.id, org.id

        organization = client.get(f"/api/v1/objects/organization/{org_id}", headers=member_headers)
        assert organization.status_code == 200
        assert client.get(
            f"/api/v1/objects/organization/{org_id}", headers=outsider_headers
        ).status_code == 403
        mapping = client.get(
            f"/api/v1/objects/external_identity_mapping/{mapping_id}", headers=member_headers
        )
        assert mapping.status_code == 200
        assert "external-secret" not in mapping.text
        assert client.get(
            f"/api/v1/objects/evaluation_run/{run_id}", headers=member_headers
        ).status_code == 403
        operator_headers = _promote_and_login(client, operator_username)
        assert client.get(
            f"/api/v1/objects/evaluation_run/{run_id}", headers=operator_headers
        ).status_code == 200


def test_generic_object_lists_apply_permission_filter_and_stable_cursor():
    with TestClient(app) as client:
        owner_headers = auth_headers(client, new_public_id("gateway-list-owner"))
        other_headers = auth_headers(client, new_public_id("gateway-list-other"))
        created = []
        for suffix in ("one", "two"):
            artifact = client.post(
                "/api/v1/artifacts", headers=owner_headers,
                json={"artifact_type": "gateway-list", "title": f"Gateway filter {suffix}", "content": suffix},
            )
            assert artifact.status_code == 201
            created.append(artifact.json()["id"])
        first = client.get(
            "/api/v1/objects/artifact", headers=owner_headers,
            params={"status": "draft", "q": "Gateway filter", "limit": 1},
        )
        assert first.status_code == 200
        assert len(first.json()["items"]) == 1
        assert first.json()["has_more"] is True
        second = client.get(
            "/api/v1/objects/artifact", headers=owner_headers,
            params={"status": "draft", "q": "Gateway filter", "limit": 1,
                    "cursor": first.json()["next_cursor"]},
        )
        assert second.status_code == 200
        assert second.json()["items"][0]["id"] != first.json()["items"][0]["id"]
        invisible = client.get(
            "/api/v1/objects/artifact", headers=other_headers,
            params={"q": "Gateway filter"},
        )
        assert invisible.status_code == 200
        assert invisible.json()["items"] == []
