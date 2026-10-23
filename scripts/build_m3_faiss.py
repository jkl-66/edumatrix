"""Build and verify the licensed M3 course index with real semantic embeddings."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models import Evidence
from scripts.ingest_to_faiss import extract_ipynb, extract_markdown, stable_id
from vector_store_faiss import FaissVectorIndex


REPO_ROOT = ROOT / "data" / "raw" / "github_repos" / "nyandwi-machine-learning-complete"
LICENSE_PATH = REPO_ROOT / "LICENSE"
SOURCE_URL = "https://github.com/Nyandwi/machine_learning_complete"
LICENSE_SPDX = "MIT"
OUTPUT_DIR = ROOT / "outputs" / "M3_三画像C加比赛闭环" / "evidence" / "faiss"
INDEX_PATH = OUTPUT_DIR / "licensed_ml_course"
SELECTED_FILES = (
    "docs/11_ml_fundamentals.md",
    "docs/12_intro_to_sklearn.ipynb",
    "docs/13_linear_models_for_regression.ipynb",
    "docs/14_linear_models_for_classification.ipynb",
    "docs/15_support_vector_machines_for_regression.ipynb",
    "docs/16_support_vector_machines_for_classification.ipynb",
    "docs/17_decision_trees_for_regression.ipynb",
    "docs/18_decision_trees_for_classification.ipynb",
    "docs/19_random_forests_for_regression.ipynb",
    "docs/20_random_forests_for_classification.ipynb",
    "docs/21_ensemble_models.ipynb",
    "docs/22_intro_to_unsupervised_learning_with_kmeans_clustering.ipynb",
    "docs/23_a_practical_intro_to_principal_components_analysis.ipynb",
    "docs/24_intro_to_neural_networks.ipynb",
)
QUERIES = (
    "How does a decision tree choose a split for classification?",
    "Explain linear regression loss and model fitting.",
    "What is K-means clustering and how are centroids updated?",
    "How do random forests reduce overfitting?",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_license() -> dict[str, str]:
    if not LICENSE_PATH.is_file():
        raise RuntimeError("selected course repository has no license file")
    text = LICENSE_PATH.read_text(encoding="utf-8")
    if "MIT License" not in text or "Permission is hereby granted" not in text:
        raise RuntimeError("selected repository license is not a recognizable MIT license")
    return {
        "spdx": LICENSE_SPDX,
        "path": str(LICENSE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "sha256": _sha256(LICENSE_PATH),
        "source_url": SOURCE_URL,
        "attribution": "Copyright (c) 2021 Jean de Dieu Nyandwi",
    }


def main() -> int:
    from embedding_models import EMBEDDINGS

    if "sentence-transformer" not in EMBEDDINGS.name:
        raise RuntimeError(f"real sentence-transformer backend required, got {EMBEDDINGS.name}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    license_record = _validate_license()
    index = FaissVectorIndex("m3-licensed-machine-learning-course")
    source_records = []
    all_evidence: list[Evidence] = []

    for relative in SELECTED_FILES:
        path = (REPO_ROOT / relative).resolve()
        if REPO_ROOT.resolve() not in path.parents or not path.is_file():
            raise RuntimeError(f"selected source is missing or outside repository: {relative}")
        extractor = extract_markdown if path.suffix.lower() == ".md" else extract_ipynb
        chunks = extractor(path)
        if not chunks:
            raise RuntimeError(f"selected source produced no chunks: {relative}")
        source_path = str(path.relative_to(ROOT)).replace("\\", "/")
        source_records.append(
            {
                "path": source_path,
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
                "chunks": len(chunks),
            }
        )
        for number, chunk in enumerate(chunks):
            all_evidence.append(
                Evidence(
                    id=stable_id(source_path, number),
                    title=chunk["title"],
                    content=chunk["content"],
                    modality=chunk["modality"],
                    source=source_path,
                    tags=tuple(chunk["tags"]) + ("licensed-course", "MIT"),
                    anchors=tuple(chunk["anchors"]),
                    metadata={
                        "course_id": "m3-licensed-ml-course-v1",
                        "repository": SOURCE_URL,
                        "license": LICENSE_SPDX,
                        "source_sha256": source_records[-1]["sha256"],
                    },
                )
            )

    started = time.perf_counter()
    index.upsert(tuple(all_evidence))
    index.save(INDEX_PATH)
    build_seconds = time.perf_counter() - started
    reloaded = FaissVectorIndex.load(INDEX_PATH)
    if reloaded.count() != len(all_evidence):
        raise RuntimeError("FAISS round-trip changed the evidence count")

    query_results = []
    for query in QUERIES:
        hits = reloaded.search(query, top_k=5)
        if not hits or max(hit.score for hit in hits) <= 0.0:
            raise RuntimeError(f"semantic query returned no scored evidence: {query}")
        query_results.append(
            {
                "query": query,
                "hits": [
                    {
                        "id": hit.id,
                        "title": hit.title,
                        "score": round(float(hit.score), 6),
                        "source": hit.source,
                        "license": (hit.metadata or {}).get("license"),
                    }
                    for hit in hits
                ],
            }
        )

    manifest = {
        "schema_version": "edumatrix.m3.faiss-evidence.v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "course_id": "m3-licensed-ml-course-v1",
        "course_title": "Machine Learning Complete - selected core course",
        "license": license_record,
        "embedding": {
            "provider": EMBEDDINGS.name,
            "model": os.getenv("EDUMATRIX_EMBEDDING_MODEL", ""),
            "dimension": reloaded.dim,
            "normalized": True,
        },
        "faiss": {
            "implementation": "faiss-cpu",
            "index_type": type(reloaded._index).__name__,
            "evidence_count": reloaded.count(),
            "build_seconds": round(build_seconds, 3),
            "faiss_sha256": _sha256(INDEX_PATH.with_suffix(".faiss")),
            "metadata_sha256": _sha256(INDEX_PATH.with_suffix(".json")),
        },
        "sources": source_records,
        "queries": query_results,
        "claim_boundary": "Real licensed files and real sentence-transformer/FAISS retrieval; no LLM quality claim.",
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
