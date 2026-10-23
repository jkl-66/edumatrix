from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from app.database import DBCourse, DBCourseDocument, DBSourceDocument, DBSourceRef, SessionLocal
from app.m5_source_locator import build_evidence_locations
from app.main import app
from course_catalog import (
    CURATED_COURSE_MANIFESTS,
    ingest_course_bundle,
    load_m0_course_bundle,
    load_versioned_course_bundle,
    upsert_course_bundle,
)
from tests.api_test_helpers import auth_headers


CURATED_COURSE_ID = "course-machine-learning-foundations-v1"


def _curated_bundle():
    return load_versioned_course_bundle(CURATED_COURSE_MANIFESTS[0])


def _source_ref_for_document(session, document_id: str) -> DBSourceRef:
    source = session.query(DBSourceDocument).filter_by(
        legacy_document_id=document_id
    ).one()
    return session.query(DBSourceRef).filter_by(source_document_id=source.id).one()


def test_all_packaged_course_evidence_has_original_character_location():
    bundles = [load_m0_course_bundle(), _curated_bundle()]
    total = 0
    for bundle in bundles:
        for document in bundle["documents"]:
            locations = build_evidence_locations(
                document["content"], document["chunks"]
            )
            assert set(locations) == {item.id for item in document["chunks"]}
            for location in locations.values():
                fragment = document["content"][location.char_start:location.char_end]
                assert fragment
                assert hashlib.sha256(fragment.encode("utf-8")).hexdigest() == location.fragment_hash
                assert location.quote == fragment[:500]
                total += 1
    assert total == 582


def test_course_ingestion_exposes_trusted_fragment_metadata():
    bundle = _curated_bundle()
    expected_chunks = sum(len(document["chunks"]) for document in bundle["documents"])
    assert expected_chunks == 569
    assert ingest_course_bundle(bundle) == expected_chunks
    first = bundle["documents"][0]["chunks"][0]
    indexed = next(
        item
        for item in __import__("rag_engine").hybrid_rag.user_index._items.values()
        if item.id == first.id and item.metadata.get("course_id") == CURATED_COURSE_ID
    )
    assert indexed.metadata["evidence_char_start"] == 0
    assert indexed.metadata["evidence_char_end"] > 0
    assert len(indexed.metadata["evidence_fragment_hash"]) == 64
    assert indexed.metadata["source_ref_id"]


def test_source_evidence_api_returns_server_verified_document_location():
    bundle = _curated_bundle()
    first_document = bundle["documents"][0]
    first_evidence = first_document["chunks"][0]
    with SessionLocal() as session:
        upsert_course_bundle(session, bundle)
        source_ref = _source_ref_for_document(session, first_document["id"])
        source_ref_id = source_ref.id

    with TestClient(app) as client:
        headers = auth_headers(client, "m5_source_location_reader")
        response = client.get(
            f"/api/v1/source-refs/{source_ref_id}/evidence/{first_evidence.id}",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["schema_version"] == "m5.source-evidence-location.v1"
        assert payload["knowledge_document_id"] == first_document["id"]
        assert payload["course_id"] == CURATED_COURSE_ID
        assert payload["source_ref_id"] == source_ref_id
        assert payload["evidence_id"] == first_evidence.id
        assert payload["char_start"] == 0
        assert payload["char_end"] > payload["char_start"]
        assert payload["quote"] == first_document["content"][:500]
        assert len(payload["fragment_hash"]) == 64

        assert client.get(
            f"/api/v1/source-refs/{source_ref_id}/evidence/{first_evidence.id}"
        ).status_code == 401


def test_source_evidence_api_rejects_mismatched_and_unknown_evidence():
    curated = _curated_bundle()
    m0 = load_m0_course_bundle()
    with SessionLocal() as session:
        upsert_course_bundle(session, curated)
        upsert_course_bundle(session, m0)
        curated_ref = _source_ref_for_document(session, curated["documents"][0]["id"])
        curated_ref_id = curated_ref.id
    wrong_evidence_id = m0["documents"][0]["chunks"][0].id

    with TestClient(app) as client:
        headers = auth_headers(client, "m5_source_location_mismatch")
        mismatch = client.get(
            f"/api/v1/source-refs/{curated_ref_id}/evidence/{wrong_evidence_id}",
            headers=headers,
        )
        assert mismatch.status_code == 404
        assert mismatch.json()["detail"]["code"] == "evidence_not_found"
        unknown = client.get(
            "/api/v1/source-refs/ref-does-not-exist/evidence/evidence-does-not-exist",
            headers=headers,
        )
        assert unknown.status_code == 404


def test_source_evidence_api_enforces_private_course_access():
    bundle = _curated_bundle()
    document = bundle["documents"][0]
    evidence = document["chunks"][0]
    with TestClient(app) as client:
        headers = auth_headers(client, "m5_source_location_private_denied")
        with SessionLocal() as session:
            upsert_course_bundle(session, bundle)
            course = session.query(DBCourse).filter_by(id=CURATED_COURSE_ID).one()
            original_visibility = course.visibility
            course.visibility = "private"
            source_ref_id = _source_ref_for_document(session, document["id"]).id
            session.commit()
        try:
            response = client.get(
                f"/api/v1/source-refs/{source_ref_id}/evidence/{evidence.id}",
                headers=headers,
            )
            assert response.status_code == 403
        finally:
            with SessionLocal() as session:
                course = session.query(DBCourse).filter_by(id=CURATED_COURSE_ID).one()
                course.visibility = original_visibility
                session.commit()


def test_source_evidence_api_fails_closed_on_content_hash_drift():
    bundle = _curated_bundle()
    document = bundle["documents"][0]
    evidence = document["chunks"][0]
    with TestClient(app) as client:
        headers = auth_headers(client, "m5_source_location_drift")
        with SessionLocal() as session:
            upsert_course_bundle(session, bundle)
            source_ref = _source_ref_for_document(session, document["id"])
            source_ref_id = source_ref.id
            original_hash = source_ref.content_hash
            source_ref.content_hash = "0" * 64
            session.commit()
        try:
            response = client.get(
                f"/api/v1/source-refs/{source_ref_id}/evidence/{evidence.id}",
                headers=headers,
            )
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "source_content_drift"
        finally:
            with SessionLocal() as session:
                source_ref = session.query(DBSourceRef).filter_by(id=source_ref_id).one()
                source_ref.content_hash = original_hash
                session.commit()
