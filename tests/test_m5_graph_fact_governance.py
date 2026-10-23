from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.utils.exceptions import GraphBuilderError
from app.utils.graph_builder import GraphBuilder, InMemoryGraphRepository
from app.utils.graph_models import GraphFact, GraphFactProvenance, Triplet
from course_catalog import (
    CURATED_COURSE_MANIFESTS,
    load_m0_course_bundle,
    load_versioned_course_bundle,
    upsert_course_bundle,
)
from ingestion import _seed_canonical_course_facts
import ingestion
from tests.api_test_helpers import auth_headers


def test_rule_extraction_is_candidate_and_never_a_verified_edge():
    repository = InMemoryGraphRepository()
    builder = GraphBuilder(repository=repository)
    report = builder.build_from_text(
        "损失函数是梯度下降的基础", source="unreviewed-upload.md"
    )

    assert report.raw_triplets >= 1
    assert report.written_edges == 0
    assert report.candidate_edges >= 1
    assert repository.count_edges() == 0
    assert repository.governance_counts()["candidate_relations"] >= 1
    assert all(
        fact.provenance.source_kind == "rule_candidate"
        and fact.provenance.verification_status == "candidate"
        for fact in repository.candidates
    )

    rejected = builder.build_from_text(
        "线性代数是向量表示的基础", source="unaligned-upload.md"
    )
    assert rejected.rejected_edges >= 1
    assert repository.count_edges() == 0


def test_co_occurrence_cannot_enter_verified_prerequisite_graph():
    repository = InMemoryGraphRepository()
    candidate = GraphFact(
        triplet=Triplet("document-a", "document-b", relation="CO_OCCUR", confidence=0.91),
        provenance=GraphFactProvenance(
            source_kind="co_occurrence",
            verification_status="candidate",
            extraction_method="embedding_similarity",
        ),
    )
    repository.record_candidate(candidate)

    assert repository.count_edges() == 0
    assert repository.query_prerequisites("document-b").prerequisites == ()
    assert repository.governance_counts()["co_occurrence_candidates"] == 1
    with pytest.raises(GraphBuilderError, match="only prerequisite"):
        repository.merge_edge("document-a", "document-b", "CO_OCCUR")


def test_canonical_course_fact_requires_complete_provenance():
    repository = InMemoryGraphRepository()
    incomplete = GraphFact(
        triplet=Triplet("基础", "进阶"),
        provenance=GraphFactProvenance(
            source_kind="canonical_course",
            verification_status="verified",
            course_id="course-1",
        ),
    )
    with pytest.raises(GraphBuilderError, match="complete source provenance"):
        repository.merge_fact(incomplete)


def test_canonical_course_prerequisites_are_verified_with_resolvable_sources():
    bundles = [
        load_m0_course_bundle(),
        load_versioned_course_bundle(CURATED_COURSE_MANIFESTS[0]),
    ]
    with SessionLocal() as session:
        for bundle in bundles:
            upsert_course_bundle(session, bundle)

    repository = InMemoryGraphRepository()
    builder = GraphBuilder(repository=repository)
    report = _seed_canonical_course_facts(builder)

    assert report["written_facts"] > 0
    assert report["rejected_facts"] == 0
    assert report["skipped_external_prerequisites"] == 2
    counts = repository.governance_counts()
    assert counts["canonical_course_facts"] == report["written_facts"]
    assert counts["candidate_relations"] == 0
    assert all(
        fact.provenance.course_id
        and fact.provenance.source_ref_id.startswith("ref-")
        and fact.provenance.evidence_id
        and len(fact.provenance.content_hash) == 64
        and len(fact.provenance.manifest_hash) == 64
        for fact in repository.facts
    )


def test_graph_stats_separates_verified_facts_and_candidates():
    with TestClient(app) as client:
        auth_headers(client, "m5_graph_governance_reader")
        response = client.get("/api/knowledge/graph/stats")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["governance"]["verified_facts"] > 0
        assert payload["governance"]["canonical_course_facts"] > 0
        assert payload["governance"]["candidate_relations"] >= 0
        assert payload["canonical_seed"]["rejected_facts"] == 0


def test_cached_graph_builder_refreshes_when_canonical_courses_arrive(monkeypatch):
    repository = InMemoryGraphRepository()
    builder = GraphBuilder(repository=repository)
    builder.canonical_seed_signature = ()
    monkeypatch.setattr(ingestion, "_graph_builder", builder)
    monkeypatch.setattr(ingestion, "_canonical_course_seed_signature", lambda: (("course-late", "hash"),))
    calls = []

    def seed(current):
        calls.append(current)
        current.canonical_seed_report = {"written_facts": 1, "rejected_facts": 0}
        return current.canonical_seed_report

    monkeypatch.setattr(ingestion, "_seed_canonical_course_facts", seed)

    assert ingestion._get_graph_builder() is builder
    assert calls == [builder]
    assert builder.canonical_seed_signature == (("course-late", "hash"),)
