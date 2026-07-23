from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import get_password_hash
from app.crud import save_student_profile
from app.database import DBProfileEvidence, DBStudentProfile, DBUser, SessionLocal
from app.identity import new_public_id
from app.m1_evidence import trace_bundle_summary
from app.m1_profile_evidence import profile_evidence_compat_view, sync_legacy_profile_evidence
from app.main import app
from models import ProfileEvidence, ProfileEvidenceSource, StudentProfile
from tests.api_test_helpers import TEST_PASSWORD, auth_headers


def test_legacy_profile_evidence_sync_is_idempotent_and_preserves_json():
    username = new_public_id("profile-evidence-user")
    legacy = [{
        "source": "student_feedback",
        "text": "Sensitive evidence body",
        "features": ["strategy_gap"],
        "weight": 0.76,
        "confidence": 0.82,
        "timestamp": "2026-07-23T08:00:00Z",
        "trace_id": new_public_id("trace"),
    }]
    with SessionLocal() as session:
        user = DBUser(username=username, hashed_password=get_password_hash(TEST_PASSWORD))
        session.add(user)
        session.flush()
        profile = DBStudentProfile(student_id=username, profile_evidence=legacy)
        session.add(profile)
        session.flush()
        first = sync_legacy_profile_evidence(session, profile)
        second = sync_legacy_profile_evidence(session, profile)
        session.commit()
        assert first[0].id == second[0].id
        assert session.query(DBProfileEvidence).filter_by(legacy_student_id=username).count() == 1
        assert session.query(DBStudentProfile).filter_by(student_id=username).one().profile_evidence == legacy
        view = profile_evidence_compat_view(session, username)
        assert view[0]["source"] == "student_feedback"
        assert view[0]["features"] == ["strategy_gap"]


def test_existing_profile_save_path_writes_normalized_evidence():
    username = new_public_id("profile-save-user")
    with SessionLocal() as session:
        session.add(DBUser(username=username, hashed_password=get_password_hash(TEST_PASSWORD)))
        session.commit()
        profile = StudentProfile(student_id=username)
        profile.profile_evidence.append(ProfileEvidence(
            source=ProfileEvidenceSource.STUDENT_MESSAGE,
            text="save-path evidence",
            features=("cognitive_load",),
            weight=0.5,
            confidence=0.7,
        ))
        save_student_profile(session, profile)
        row = session.query(DBProfileEvidence).filter_by(legacy_student_id=username).one()
        assert row.owner_public_id
        assert row.source_type == "student_message"
        assert row.features == ["cognitive_load"]
        assert session.query(DBStudentProfile).filter_by(student_id=username).one().profile_evidence[0]["text"] == "save-path evidence"


def test_profile_evidence_gateway_and_trace_hide_evidence_body():
    with TestClient(app) as client:
        owner_username = new_public_id("profile-evidence-owner")
        other_username = new_public_id("profile-evidence-other")
        owner_headers = auth_headers(client, owner_username)
        other_headers = auth_headers(client, other_username)
        with SessionLocal() as session:
            owner = session.query(DBUser).filter_by(username=owner_username).one()
            trace_id = new_public_id("profile-evidence-trace")
            row = DBProfileEvidence(
                owner_public_id=owner.public_id,
                legacy_student_id=owner_username,
                legacy_key=new_public_id("legacy-key"),
                source_type="performance_signal",
                source_object_id=new_public_id("assessment-run"),
                features=["prerequisite_gap"],
                weight=0.8,
                confidence=0.9,
                evidence_summary="DO NOT EXPOSE THIS EVIDENCE BODY",
                status="active",
                evidence_version="1",
                trace_id=trace_id,
            )
            session.add(row)
            session.commit()
            row_id = row.id
            summary = trace_bundle_summary(session, trace_id)
            assert summary["counts"]["profile_evidence"] == 1
            assert "DO NOT EXPOSE" not in str(summary)
            assert summary["groups"]["profile_evidence"][0]["source_type"] == "performance_signal"

        detail = client.get(f"/api/v1/objects/profile_evidence/{row_id}", headers=owner_headers)
        assert detail.status_code == 200
        assert detail.json()["source_ids"]["source_object_id"]
        assert "DO NOT EXPOSE" not in detail.text
        assert client.get(
            f"/api/v1/objects/profile_evidence/{row_id}", headers=other_headers
        ).status_code == 403


def test_unresolved_legacy_evidence_remains_readable_without_fabricated_owner():
    student_id = new_public_id("legacy-only-profile")
    legacy = [{"source": "student_message", "text": "legacy", "features": [], "weight": 0.4, "confidence": 0.5}]
    with SessionLocal() as session:
        profile = DBStudentProfile(student_id=student_id, profile_evidence=legacy)
        session.add(profile)
        session.flush()
        rows = sync_legacy_profile_evidence(session, profile)
        session.commit()
        assert rows[0].owner_public_id is None
        assert rows[0].status == "legacy_unresolved"
        assert profile_evidence_compat_view(session, student_id)[0]["text"] == "legacy"
