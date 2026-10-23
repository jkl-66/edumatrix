from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.database import DBSourceRef, SessionLocal, init_db
from course_catalog import (
    ingest_course_bundle,
    load_m0_course_bundle,
    load_versioned_course_bundle,
    upsert_course_bundle,
)
from course_retrieval_evaluation import (
    DEFAULT_DATASET_PATH,
    DEFAULT_MANIFEST_PATH,
    evaluate_course_retrieval,
    load_course_retrieval_dataset,
)
from models import Evidence, EvidenceModality, StudentProfile
from rag_engine import hybrid_rag


COURSE_ID = "course-machine-learning-foundations-v1"
M0_MANIFEST_PATH = Path("outputs/M0_阶段0基线与架构契约/datasets/course_manifest.json")
M0_DATASET_PATH = M0_MANIFEST_PATH.with_name("course_retrieval_evaluation.json")


def test_frozen_dataset_covers_every_curated_chapter_and_has_no_evidence_cases():
    dataset = load_course_retrieval_dataset()
    bundle = load_versioned_course_bundle(DEFAULT_MANIFEST_PATH)
    expected_documents = {item["filename"] for item in bundle["documents"]}
    covered_documents = {
        filename
        for case in dataset["answerable_cases"]
        for filename in case["relevant_documents"]
    }

    assert dataset["course_id"] == COURSE_ID
    assert dataset["course_manifest_version"] == bundle["course"]["version"]
    assert covered_documents == expected_documents
    assert len(dataset["answerable_cases"]) == 12
    assert len(dataset["no_evidence_cases"]) == 4


def test_course_retrieval_report_passes_recall_locators_and_no_evidence_gate():
    report = evaluate_course_retrieval()

    assert report["passed"] is True, report
    assert report["recall_at_k"] == 1.0
    assert report["no_evidence_rejection_rate"] == 1.0
    assert all(item["locatable"] for item in report["answerable_results"])
    assert all(not item["missing_documents"] for item in report["answerable_results"])


def test_m0_frozen_dataset_covers_all_documents_and_passes_retrieval_gates():
    dataset = load_course_retrieval_dataset(M0_DATASET_PATH)
    bundle = load_m0_course_bundle(M0_MANIFEST_PATH)
    expected_documents = {item["filename"] for item in bundle["documents"]}
    covered_documents = {
        filename
        for case in dataset["answerable_cases"]
        for filename in case["relevant_documents"]
    }

    assert dataset["course_id"] == bundle["course"]["id"]
    assert dataset["course_manifest_version"] == bundle["course"]["version"]
    assert covered_documents == expected_documents
    assert len(dataset["answerable_cases"]) >= len(expected_documents)
    assert len(dataset["no_evidence_cases"]) >= 4

    report = evaluate_course_retrieval(M0_DATASET_PATH, M0_MANIFEST_PATH)
    assert report["passed"] is True, report
    assert report["recall_at_k"] == 1.0
    assert report["no_evidence_rejection_rate"] == 1.0
    assert all(item["locatable"] for item in report["answerable_results"])
    assert all(not item["missing_documents"] for item in report["answerable_results"])


def test_retrieved_source_refs_resolve_to_canonical_database_objects():
    init_db()
    bundle = load_versioned_course_bundle(DEFAULT_MANIFEST_PATH)
    session = SessionLocal()
    try:
        upsert_course_bundle(session, bundle)
        ingest_course_bundle(bundle)
        result = hybrid_rag.retrieve(
            "PCA explained_variance_ratio_ 如何解释",
            course_id=COURSE_ID,
            disable_external=True,
            top_k=5,
        )
        assert result.evidence
        for item in result.evidence:
            source_ref = session.get(DBSourceRef, item.metadata["source_ref_id"])
            assert source_ref is not None
            assert source_ref.source_document_id == item.metadata["source_document_id"]
            assert source_ref.chapter_id == item.metadata["chapter_id"]
            assert source_ref.content_hash == item.metadata["source_ref_content_hash"]
    finally:
        session.close()


def test_course_scope_excludes_other_public_courses_until_explicitly_expanded():
    curated = load_versioned_course_bundle(DEFAULT_MANIFEST_PATH)
    baseline = load_m0_course_bundle()
    ingest_course_bundle(curated)
    ingest_course_bundle(baseline)
    query = "查询必须同时约束用户、组织、课程和版本范围"

    scoped = hybrid_rag.retrieve(
        query,
        course_id=COURSE_ID,
        disable_external=True,
        top_k=5,
    )
    expanded = hybrid_rag.retrieve(
        query,
        course_id=COURSE_ID,
        allow_cross_course=True,
        disable_external=True,
        top_k=5,
    )

    assert scoped.evidence
    assert all(item.metadata.get("course_id") == COURSE_ID for item in scoped.evidence)
    assert any(
        item.metadata.get("course_id") == baseline["course"]["id"]
        for item in expanded.evidence
    )


def test_course_scope_keeps_owner_private_material_but_rejects_other_owner():
    bundle = load_versioned_course_bundle(DEFAULT_MANIFEST_PATH)
    ingest_course_bundle(bundle)
    owner_id = "retrieval-owner"
    private = Evidence(
        id="private-course-note-owner",
        title="个人 PCA 学习笔记",
        content="PCA explained_variance_ratio_ 是个人复习重点",
        modality=EvidenceModality.TEXT,
        source="private-pca-note.md",
    )
    other = replace(private, id="private-course-note-other", source="other-private-note.md")
    hybrid_rag.ingest_user_documents((private,), owner_id=owner_id)
    hybrid_rag.ingest_user_documents((other,), owner_id="other-owner")
    try:
        result = hybrid_rag.retrieve(
            "PCA explained_variance_ratio_ 个人复习重点",
            profile=StudentProfile(student_id=owner_id),
            course_id=COURSE_ID,
            disable_external=True,
            top_k=8,
        )
        sources = {item.source for item in result.evidence}
        assert "private-pca-note.md" in sources
        assert "other-private-note.md" not in sources
    finally:
        hybrid_rag.remove_user_documents("private-pca-note.md", owner_id=owner_id)
        hybrid_rag.remove_user_documents("other-private-note.md", owner_id="other-owner")
