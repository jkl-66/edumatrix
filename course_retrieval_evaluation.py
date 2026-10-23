from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from course_catalog import ingest_course_bundle, load_m0_course_bundle, load_versioned_course_bundle, upsert_course_bundle
from app.database import SessionLocal
from models import StudentProfile
from rag_engine import hybrid_rag


ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET_PATH = (
    ROOT
    / "data"
    / "curated"
    / "machine_learning_foundations_v1"
    / "retrieval_evaluation.json"
)
DEFAULT_MANIFEST_PATH = DEFAULT_DATASET_PATH.with_name("course_manifest.json")
EVALUATION_SCHEMA = "edumatrix.course-retrieval-evaluation.v1"


def load_course_retrieval_dataset(path: Path = DEFAULT_DATASET_PATH) -> dict[str, Any]:
    dataset = json.loads(Path(path).read_text(encoding="utf-8"))
    if dataset.get("schema_version") != EVALUATION_SCHEMA:
        raise ValueError("unsupported_course_retrieval_evaluation_schema")
    if not dataset.get("answerable_cases") or not dataset.get("no_evidence_cases"):
        raise ValueError("course_retrieval_evaluation_cases_required")
    case_ids = [
        item["id"]
        for group in ("answerable_cases", "no_evidence_cases")
        for item in dataset[group]
    ]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate_course_retrieval_case_id")
    return dataset


def _load_evaluated_course_bundle(manifest_path: Path) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version"):
        return load_versioned_course_bundle(manifest_path)
    if manifest.get("course_id") and manifest.get("manifest_version") and manifest.get("files"):
        return load_m0_course_bundle(manifest_path)
    raise ValueError("unsupported_course_manifest_schema")


def evaluate_course_retrieval(
    dataset_path: Path = DEFAULT_DATASET_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    dataset = load_course_retrieval_dataset(dataset_path)
    bundle = _load_evaluated_course_bundle(manifest_path)
    course = bundle["course"]
    if dataset["course_id"] != course["id"]:
        raise ValueError("retrieval_dataset_course_mismatch")
    if dataset["course_manifest_version"] != course["version"]:
        raise ValueError("retrieval_dataset_manifest_version_mismatch")

    # The evaluator runs in an isolated database as well as against the
    # in-memory index.  Register the evaluated bundle through the same
    # canonical source path first; otherwise a fresh database would correctly
    # reject every query as having no ready DBSourceDocument/DBSourceRef.
    with SessionLocal() as session:
        upsert_course_bundle(session, bundle)
    ingest_course_bundle(bundle)
    profile = StudentProfile(student_id="course-retrieval-evaluator")
    top_k = int(dataset["top_k"])
    answerable_results = []
    for case in dataset["answerable_cases"]:
        retrieval = hybrid_rag.retrieve(
            case["query"],
            top_k=top_k,
            profile=profile,
            disable_external=True,
            course_id=course["id"],
        )
        expected = set(case["relevant_documents"])
        relevant_hits = [
            item
            for item in retrieval.evidence
            if Path(item.source).name in expected
        ]
        recalled_documents = {
            Path(item.source).name
            for item in relevant_hits
        }
        missing_documents = expected - recalled_documents
        searchable_text = "\n".join(item.content for item in relevant_hits).lower()
        term_hits = [
            term
            for term in case["allowed_answer_terms"]
            if term.lower() in searchable_text
        ]
        locatable = bool(relevant_hits) and all(
            item.metadata.get("source_ref_id")
            and item.metadata.get("source_document_id")
            and item.metadata.get("chapter_id")
            and item.metadata.get("source_ref_content_hash")
            for item in relevant_hits
        )
        answerable_results.append(
            {
                "id": case["id"],
                "passed": bool(
                    not missing_documents
                    and term_hits
                    and locatable
                    and not retrieval.low_confidence
                ),
                "relevant_document_recalled": not missing_documents,
                "recalled_documents": sorted(recalled_documents),
                "missing_documents": sorted(missing_documents),
                "allowed_answer_term_hits": term_hits,
                "locatable": locatable,
                "low_confidence": retrieval.low_confidence,
                "top_sources": [item.source for item in retrieval.evidence],
                "top_scores": [round(item.score, 6) for item in retrieval.evidence],
            }
        )

    no_evidence_results = []
    for case in dataset["no_evidence_cases"]:
        retrieval = hybrid_rag.retrieve(
            case["query"],
            top_k=top_k,
            profile=profile,
            disable_external=True,
            course_id=course["id"],
        )
        no_evidence_results.append(
            {
                "id": case["id"],
                "passed": retrieval.low_confidence,
                "expected_reason": case["expected_reason"],
                "low_confidence": retrieval.low_confidence,
                "top_sources": [item.source for item in retrieval.evidence],
                "top_scores": [round(item.score, 6) for item in retrieval.evidence],
            }
        )

    answerable_passed = sum(item["passed"] for item in answerable_results)
    no_evidence_passed = sum(item["passed"] for item in no_evidence_results)
    return {
        "schema_version": "edumatrix.course-retrieval-report.v1",
        "dataset_version": dataset["dataset_version"],
        "course_id": course["id"],
        "course_manifest_version": course["version"],
        "top_k": top_k,
        "answerable_case_count": len(answerable_results),
        "answerable_passed": answerable_passed,
        "recall_at_k": answerable_passed / len(answerable_results),
        "no_evidence_case_count": len(no_evidence_results),
        "no_evidence_passed": no_evidence_passed,
        "no_evidence_rejection_rate": no_evidence_passed / len(no_evidence_results),
        "passed": answerable_passed == len(answerable_results)
        and no_evidence_passed == len(no_evidence_results),
        "answerable_results": answerable_results,
        "no_evidence_results": no_evidence_results,
    }
