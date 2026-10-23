from pathlib import Path

from scripts.audit_course_sources import build_audit


ROOT = Path(__file__).resolve().parents[1]


def test_course_source_audit_covers_manifest_and_local_revisions():
    report = build_audit(ROOT)

    assert report["schema_version"] == "edumatrix.course-source-audit.v1"
    assert report["source_count"] == 15
    assert report["local_git_source_count"] == 13
    git_entries = [item for item in report["sources"] if item["kind"] == "git"]
    assert all(len(item["git_revision"]) == 40 for item in git_entries)
    assert all(item["material_file_counts"] for item in git_entries)


def test_default_allowlist_requires_hashed_permissive_license():
    report = build_audit(ROOT)
    by_key = {item["key"]: item for item in report["sources"]}

    assert report["default_course_allowlist"]
    for key in report["default_course_allowlist"]:
        item = by_key[key]
        assert item["default_course_eligibility"] == "approved_default_course_candidate"
        assert item["license_files"]
        assert all(len(license_item["sha256"]) == 64 for license_item in item["license_files"])
        assert any(
            license_item["detected_spdx"] in {"MIT", "Clear-BSD"}
            for license_item in item["license_files"]
        )


def test_unclear_and_reciprocal_sources_are_not_silently_approved():
    report = build_audit(ROOT)
    by_key = {item["key"]: item for item in report["sources"]}

    assert by_key["compsci-589"]["default_course_eligibility"] == "manual_obligation_review_required"
    assert by_key["mlcourse-ai"]["default_course_eligibility"] == "manual_obligation_review_required"
    assert by_key["vay-keen-watermelon-notes"]["default_course_eligibility"] == "blocked_no_local_license"
    assert by_key["watermelonbook-training"]["default_course_eligibility"] == "blocked_no_local_license"
    assert by_key["uci-iris"]["default_course_eligibility"] == "external_reference_only"
