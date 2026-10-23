from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseDocument,
    DBKnowledgePoint,
    DBSourceDocument,
    DBSourceRef,
    SessionLocal,
)
from app.legacy_repositories import LegacyReadRepository
from app.main import app
from course_catalog import (
    CURATED_COURSE_MANIFESTS,
    load_versioned_course_bundle,
    upsert_course_bundle,
)
from scripts.build_curated_ml_course import MANIFEST_PATH, build_course
from tests.api_test_helpers import auth_headers


COURSE_ID = "course-machine-learning-foundations-v1"
REPOSITORY_KEY = "nyandwi-machine-learning-complete"
REVISION = "8aabb071866027dd5c83de6de0c82a17f2ebe79e"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _copied_bundle(tmp_path: Path) -> Path:
    source = CURATED_COURSE_MANIFESTS[0].parent
    destination = tmp_path / "course"
    shutil.copytree(source, destination)
    return destination / "course_manifest.json"


def test_curated_manifest_is_file_level_allowlist_with_complete_provenance():
    manifest = _manifest()

    assert manifest["schema_version"] == "edumatrix.course-version-manifest.v1"
    assert manifest["course_id"] == COURSE_ID
    assert len(manifest["reviewed_candidates"]) == 7
    assert len(manifest["files"]) == 12
    assert len(manifest["knowledge_points"]) == 13
    assert [item["chapter_order"] for item in manifest["files"]] == list(range(12))
    assert sum(item["conversion"]["stripped_output_count"] for item in manifest["files"]) == 624
    assert {item["repository_key"] for item in manifest["files"]} == {REPOSITORY_KEY}
    assert {item["git_revision"] for item in manifest["files"]} == {REVISION}
    assert {item["license_spdx"] for item in manifest["files"]} == {"MIT"}
    assert all(len(item["source_sha256"]) == 64 for item in manifest["files"])
    assert all(item["knowledge_point_codes"] for item in manifest["files"])
    assert all(item["selection_reason"] for item in manifest["files"])


def test_curated_course_builder_is_reproducible_and_strips_notebook_outputs():
    before = MANIFEST_PATH.read_bytes()
    before_hashes = {
        item["path"]: hashlib.sha256((MANIFEST_PATH.parent / item["path"]).read_bytes()).hexdigest()
        for item in _manifest()["files"]
    }

    rebuilt = build_course()

    assert MANIFEST_PATH.read_bytes() == before
    assert rebuilt["course_id"] == COURSE_ID
    after_hashes = {
        item["path"]: hashlib.sha256((MANIFEST_PATH.parent / item["path"]).read_bytes()).hexdigest()
        for item in rebuilt["files"]
    }
    assert after_hashes == before_hashes
    for item in rebuilt["files"]:
        content = (MANIFEST_PATH.parent / item["path"]).read_text(encoding="utf-8")
        assert "data:image" not in content.lower()
        assert '"outputs":' not in content
        assert "Notebook 未执行" in content


def test_curated_bundle_loads_only_manifest_files_and_keeps_source_locations(tmp_path: Path):
    manifest_path = _copied_bundle(tmp_path)
    extra = manifest_path.parent / "chapters" / "not_allowlisted.md"
    extra.write_text("this file must never enter the course", encoding="utf-8")

    bundle = load_versioned_course_bundle(manifest_path)

    assert bundle["course"]["id"] == COURSE_ID
    assert len(bundle["documents"]) == 12
    assert len(bundle["knowledge_points"]) == 13
    assert not any("not_allowlisted" in item["filename"] for item in bundle["documents"])
    assert all(item["source_path"].startswith(f"{REPOSITORY_KEY}@{REVISION}:") for item in bundle["documents"])
    assert all(f"/blob/{REVISION}/" in item["source_url"] for item in bundle["documents"])
    assert all(item["parser_version"] == "edumatrix-notebook-to-markdown-v1" for item in bundle["documents"])


def test_curated_bundle_rejects_path_escape_and_license_tampering(tmp_path: Path):
    traversal_manifest = _copied_bundle(tmp_path / "traversal")
    traversal = json.loads(traversal_manifest.read_text(encoding="utf-8"))
    traversal["files"][0]["path"] = "../outside.md"
    traversal_manifest.write_text(json.dumps(traversal, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes its bundle"):
        load_versioned_course_bundle(traversal_manifest)

    license_manifest = _copied_bundle(tmp_path / "license")
    license_file = license_manifest.parent / "LICENSE.upstream.txt"
    license_file.write_text("tampered license", encoding="utf-8")
    with pytest.raises(ValueError, match="license mismatch"):
        load_versioned_course_bundle(license_manifest)


def test_curated_course_upsert_is_idempotent_and_projects_canonical_sources():
    bundle = load_versioned_course_bundle(CURATED_COURSE_MANIFESTS[0])
    session = SessionLocal()
    try:
        upsert_course_bundle(session, bundle)
        second = upsert_course_bundle(session, bundle)

        assert second == {"inserted": 0, "updated": 12, "removed": 0}
        assert session.query(DBCourse).filter_by(id=COURSE_ID).count() == 1
        assert session.query(DBCourseDocument).filter_by(course_id=COURSE_ID).count() == 12
        assert session.query(DBSourceDocument).filter_by(course_id=COURSE_ID).count() == 12
        assert session.query(DBChapter).filter_by(course_id=COURSE_ID).count() == 12
        assert session.query(DBKnowledgePoint).filter_by(
            domain_pack="domain-machine-learning-foundations-v1",
            version="ml-kp-1.0.0",
        ).count() == 13
        refs = (
            session.query(DBSourceRef, DBSourceDocument)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .filter(DBSourceDocument.course_id == COURSE_ID)
            .all()
        )
        assert len(refs) == 12
        assert all(source.source_url and f"/blob/{REVISION}/" in source.source_url for _ref, source in refs)
        assert all(ref.parser_version == "edumatrix-notebook-to-markdown-v1" for ref, _source in refs)
        assert session.query(DBChapterKnowledgePoint).join(
            DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id
        ).filter(DBChapter.course_id == COURSE_ID).count() >= 13

        _legacy, course_rows = LegacyReadRepository(session).knowledge_library_rows("any-student")
        visible = [row for row in course_rows if row[1].id == COURSE_ID]
        assert len(visible) == 12
        assert [row[0].chapter_order for row in visible] == list(range(12))
        assert all(row[1].title == "机器学习基础与实践" for row in visible)
        assert all(row[2] is not None and row[3] is not None and row[4] is not None for row in visible)
    finally:
        session.close()


def test_curated_course_http_detail_exposes_clickable_canonical_provenance():
    with TestClient(app) as client:
        headers = auth_headers(client, "m5_curated_course_reader")
        listed = client.get(
            "/api/knowledge/list?student_id=m5_curated_course_reader",
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        course_rows = [item for item in listed.json() if item.get("course_id") == COURSE_ID]
        assert len(course_rows) == 12
        first = course_rows[0]
        assert first["source_url"].startswith("https://github.com/Nyandwi/machine_learning_complete/blob/")
        assert first["source_git_revision"] == REVISION
        assert first["source_license_spdx"] == "MIT"
        assert first["source_license_file"] == "LICENSE.upstream.txt"
        assert first["source_ref_id"]

        detail = client.get(
            f"/api/knowledge/{first['id']}?student_id=m5_curated_course_reader",
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        assert payload["source_url"] == first["source_url"]
        assert payload["source_ref_id"] == first["source_ref_id"]
        assert payload["source_document_id"]
        assert payload["source_chapter_id"]
        assert payload["source_chapter_title"] == payload["title"]
        assert payload["source_ref_char_start"] == 0
        assert payload["source_ref_char_end"] == len(payload["content"])
        assert payload["source_sha256"] != payload["content_hash"].lower()
