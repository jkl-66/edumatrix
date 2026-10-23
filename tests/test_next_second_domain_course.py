from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import DBCourse, DBCourseDocument, DBKnowledgePoint, DBSourceDocument, SessionLocal
from course_catalog import CURATED_COURSE_MANIFESTS, load_versioned_course_bundle, upsert_course_bundle
from course_retrieval_evaluation import evaluate_course_retrieval
from scripts.build_curated_edge_course import MANIFEST_PATH, PROCESSING_REPORT_PATH, REVISION, build_course
from app.main import app
from tests.api_test_helpers import auth_headers


COURSE_ID = "course-embedded-edge-intelligence-v1"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_second_domain_builder_is_deterministic_and_preserves_license_chain():
    before_manifest = MANIFEST_PATH.read_bytes()
    before_report = PROCESSING_REPORT_PATH.read_bytes()
    before_files = {
        item["path"]: hashlib.sha256((MANIFEST_PATH.parent / item["path"]).read_bytes()).hexdigest()
        for item in _manifest()["files"]
    }

    rebuilt = build_course()

    assert MANIFEST_PATH.read_bytes() == before_manifest
    assert PROCESSING_REPORT_PATH.read_bytes() == before_report
    assert rebuilt["source_repository"]["git_revision"] == REVISION
    assert len(rebuilt["files"]) == 8
    assert {item["license_spdx"] for item in rebuilt["files"]} == {"CC-BY-NC-SA-4.0"}
    assert all(item["obligations"] == ["attribution", "noncommercial", "share_alike", "indicate_changes"] for item in rebuilt["files"])
    assert all("Edge Impulse" in item["attribution"] for item in rebuilt["files"])
    assert all(item["source_sha256"] == rebuilt["source_repository"]["source_sha256"] for item in rebuilt["files"])
    assert before_files == {
        item["path"]: hashlib.sha256((MANIFEST_PATH.parent / item["path"]).read_bytes()).hexdigest()
        for item in rebuilt["files"]
    }
    notice = (MANIFEST_PATH.parent / "LICENSE-AND-ATTRIBUTION.upstream.md").read_text(encoding="utf-8")
    assert "CC BY-NC-SA 4.0" in notice
    assert "Harvard University" in notice
    assert "does not redistribute linked videos or binary" in notice


def test_generic_loader_supports_two_domains_without_ml_identity_copy():
    ml_path, edge_path = CURATED_COURSE_MANIFESTS
    ml = load_versioned_course_bundle(ml_path)
    edge = load_versioned_course_bundle(edge_path)

    assert ml["course"]["id"] != edge["course"]["id"]
    assert ml["course"]["domain_pack"] != edge["course"]["domain_pack"]
    assert {point["code"] for point in ml["knowledge_points"]}.isdisjoint(
        {point["code"] for point in edge["knowledge_points"]}
    )
    assert all("ML-KP" not in code for item in edge["documents"] for code in item["knowledge_point_codes"])
    assert all("机器学习" not in item["tags"] for item in edge["documents"])
    assert all("边缘智能" in item["tags"] for item in edge["documents"])
    assert all(item["source_sha256"] == _manifest()["source_repository"]["source_sha256"] for item in edge["documents"])


def test_second_domain_bundle_rejects_license_tampering(tmp_path: Path):
    copied = tmp_path / "edge"
    shutil.copytree(MANIFEST_PATH.parent, copied)
    (copied / "LICENSE-AND-ATTRIBUTION.upstream.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="license mismatch"):
        load_versioned_course_bundle(copied / "course_manifest.json")


def test_second_domain_projects_through_canonical_course_path():
    bundle = load_versioned_course_bundle(CURATED_COURSE_MANIFESTS[1])
    session = SessionLocal()
    try:
        first = upsert_course_bundle(session, bundle)
        second = upsert_course_bundle(session, bundle)
        assert first["inserted"] in {0, 8}
        assert second == {"inserted": 0, "updated": 8, "removed": 0}
        assert session.query(DBCourse).filter_by(id=COURSE_ID).count() == 1
        assert session.query(DBCourseDocument).filter_by(course_id=COURSE_ID).count() == 8
        assert session.query(DBSourceDocument).filter_by(course_id=COURSE_ID).count() == 8
        assert session.query(DBKnowledgePoint).filter_by(
            domain_pack="domain-embedded-edge-intelligence-v1", version="edge-kp-1.0.0"
        ).count() == 8
        sources = session.query(DBSourceDocument).filter_by(course_id=COURSE_ID).all()
        assert all(source.source_sha256 == _manifest()["source_repository"]["source_sha256"] for source in sources)
        assert all(source.parser_metadata["origin"] == "versioned_course_bundle" for source in sources)
    finally:
        session.close()


def test_second_domain_frozen_retrieval_evaluation_passes():
    report = evaluate_course_retrieval(
        MANIFEST_PATH.with_name("retrieval_evaluation.json"), MANIFEST_PATH
    )
    assert report["answerable_passed"] == 8
    assert report["no_evidence_passed"] == 2
    assert report["passed"] is True


def test_second_domain_http_exposes_eight_chapters_and_full_provenance():
    with TestClient(app) as client:
        headers = auth_headers(client, "next_second_domain_reader")
        response = client.get(
            "/api/knowledge/list?student_id=next_second_domain_reader", headers=headers
        )
        assert response.status_code == 200, response.text
        rows = [item for item in response.json() if item.get("course_id") == COURSE_ID]
        assert len(rows) == 8
        assert [item["chapter_order"] for item in rows] == list(range(8))
        assert all(item["source_git_revision"] == REVISION for item in rows)
        assert all(item["source_license_spdx"] == "CC-BY-NC-SA-4.0" for item in rows)
        assert all(item["source_obligations"] == ["attribution", "noncommercial", "share_alike", "indicate_changes"] for item in rows)
        detail = client.get(
            f"/api/knowledge/{rows[0]['id']}?student_id=next_second_domain_reader",
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        assert payload["source_url"].endswith(f"/blob/{REVISION}/README.md")
        assert payload["source_sha256"] == _manifest()["source_repository"]["source_sha256"]
        assert payload["source_ref_id"]
