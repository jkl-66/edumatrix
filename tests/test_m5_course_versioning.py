from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import course_catalog
from app.database import Base, DBCourse, DBCourseDocument
from course_catalog import (
    CURATED_COURSE_MANIFESTS,
    CourseManifestConflict,
    CourseUpdateApprovalRequired,
    apply_course_bundle_update,
    load_versioned_course_bundle,
    preflight_course_bundle_update,
    seed_default_courses,
    upsert_course_bundle,
)
from scripts.preflight_course_update import inspect_course_update


COURSE_ID = "course-machine-learning-foundations-v1"
VERSION_1 = "course-ml-foundations-1.0.0"
VERSION_2 = "course-ml-foundations-1.1.0"


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    value = factory()
    try:
        yield value
    finally:
        value.close()
        engine.dispose()


def _bundle():
    return load_versioned_course_bundle(CURATED_COURSE_MANIFESTS[0])


def _version_2(bundle):
    updated = deepcopy(bundle)
    updated["course"]["version"] = VERSION_2
    updated["course"]["manifest_version"] = VERSION_2
    updated["course"]["title"] = "机器学习基础与实践（修订版）"
    updated["course"]["manifest_data"]["manifest_version"] = VERSION_2
    updated["course"]["manifest_data"]["title"] = "机器学习基础与实践（修订版）"
    return updated


def test_course_preflight_is_read_only_and_idempotent(session):
    bundle = _bundle()

    first = preflight_course_bundle_update(session, bundle)
    second = preflight_course_bundle_update(session, bundle)

    assert first == second
    assert first["status"] == "new_course"
    assert first["requires_approval"] is False
    assert session.query(DBCourse).count() == 0
    assert session.query(DBCourseDocument).count() == 0

    upsert_course_bundle(session, bundle)
    replay = preflight_course_bundle_update(session, bundle)
    assert replay["status"] == "unchanged"
    assert replay["current_manifest_sha256"] == replay["incoming_manifest_sha256"]


def test_same_version_manifest_change_fails_before_database_mutation(session):
    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    original_title = session.get(DBCourse, COURSE_ID).title
    original_hashes = [
        row.content_hash
        for row in session.query(DBCourseDocument)
        .filter_by(course_id=COURSE_ID)
        .order_by(DBCourseDocument.chapter_order)
        .all()
    ]
    conflict = deepcopy(bundle)
    conflict["course"]["title"] = "同版本静默替换"
    conflict["course"]["manifest_data"]["title"] = "同版本静默替换"

    report = preflight_course_bundle_update(session, conflict)
    assert report["status"] == "same_version_conflict"
    assert report["requires_approval"] is True
    assert report["diff"]["metadata_changed"] is True
    with pytest.raises(CourseManifestConflict) as raised:
        upsert_course_bundle(session, conflict)
    assert raised.value.report == report
    assert session.get(DBCourse, COURSE_ID).title == original_title
    assert [
        row.content_hash
        for row in session.query(DBCourseDocument)
        .filter_by(course_id=COURSE_ID)
        .order_by(DBCourseDocument.chapter_order)
        .all()
    ] == original_hashes


def test_version_change_requires_compare_and_set_approval(session):
    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    updated = _version_2(bundle)

    report = preflight_course_bundle_update(session, updated)
    assert report["status"] == "update_available"
    assert report["current_version"] == VERSION_1
    assert report["incoming_version"] == VERSION_2
    assert report["diff"]["metadata_changed"] is True
    with pytest.raises(CourseUpdateApprovalRequired):
        upsert_course_bundle(session, updated)
    assert session.get(DBCourse, COURSE_ID).version == VERSION_1

    with pytest.raises(ValueError, match="approval_expectation_mismatch"):
        apply_course_bundle_update(
            session,
            updated,
            expected_current_version="wrong-current-version",
            expected_incoming_version=VERSION_2,
        )
    assert session.get(DBCourse, COURSE_ID).version == VERSION_1

    result = apply_course_bundle_update(
        session,
        updated,
        expected_current_version=VERSION_1,
        expected_incoming_version=VERSION_2,
    )
    assert result == {"inserted": 0, "updated": 12, "removed": 0}
    assert session.get(DBCourse, COURSE_ID).version == VERSION_2
    assert session.get(DBCourse, COURSE_ID).title == "机器学习基础与实践（修订版）"
    assert preflight_course_bundle_update(session, updated)["status"] == "unchanged"


def test_preflight_reports_file_provenance_order_and_knowledge_differences(session):
    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    updated = _version_2(bundle)
    manifest = updated["course"]["manifest_data"]
    manifest["files"][0]["sha256"] = "1" * 64
    manifest["files"][0]["source_sha256"] = "2" * 64
    manifest["files"][0]["git_revision"] = "3" * 40
    manifest["files"][0]["chapter_order"] = 1
    manifest["files"][1]["chapter_order"] = 0
    manifest["files"][0]["knowledge_point_codes"] = ["ML-KP-01", "ML-KP-02"]
    manifest["knowledge_points"][0]["title"] = "Python 编程基础（修订）"

    report = preflight_course_bundle_update(session, updated)

    first_path = manifest["files"][0]["path"]
    assert first_path in report["diff"]["content_changed"]
    assert first_path in report["diff"]["provenance_changed"]
    assert first_path in report["diff"]["reordered_files"]
    assert first_path in report["diff"]["knowledge_mapping_changed"]
    assert report["diff"]["knowledge_points_changed"] is True


def test_startup_reports_update_available_without_database_or_rag_overwrite(session, monkeypatch):
    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    updated = _version_2(bundle)
    original_title = session.get(DBCourse, COURSE_ID).title
    ingested: list[str] = []

    monkeypatch.setattr(course_catalog, "load_versioned_course_bundle", lambda _path: updated)
    monkeypatch.setattr(
        course_catalog,
        "ingest_course_bundle",
        lambda candidate: ingested.append(candidate["course"]["id"]) or 0,
    )

    result = seed_default_courses(session)

    course_result = next(item for item in result["courses"] if item["course_id"] == COURSE_ID)
    assert course_result["status"] == "update_available"
    assert course_result["preflight"]["current_version"] == VERSION_1
    assert course_result["preflight"]["incoming_version"] == VERSION_2
    assert COURSE_ID not in ingested
    assert session.get(DBCourse, COURSE_ID).version == VERSION_1
    assert session.get(DBCourse, COURSE_ID).title == original_title


def test_cli_inspection_helper_does_not_write(session):
    _bundle_value, report = inspect_course_update(session, CURATED_COURSE_MANIFESTS[0])

    assert report["status"] == "new_course"
    assert session.query(DBCourse).count() == 0
    assert session.query(DBCourseDocument).count() == 0
