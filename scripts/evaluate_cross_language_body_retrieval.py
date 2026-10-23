from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from embedding_models import HashEmbeddingBackend, cosine_similarity
from app.cross_language_retrieval import expand_ml_query, reciprocal_rank_fusion, tfidf_document_scores


DEFAULT_COURSE_DIR = ROOT / "data" / "curated" / "machine_learning_foundations_v1"
DEFAULT_DATASET = DEFAULT_COURSE_DIR / "cross_language_body_evaluation.json"


def _load_dataset(path: Path) -> dict[str, Any]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if dataset.get("schema_version") != "edumatrix.cross-language-body-evaluation.v1":
        raise ValueError("unsupported_cross_language_evaluation_schema")
    if not dataset.get("cases"):
        raise ValueError("cross_language_evaluation_cases_required")
    return dataset


def _body_chunks(course_dir: Path, dataset: dict[str, Any]) -> list[tuple[str, str]]:
    marker = str(dataset["body_marker"])
    size = int(dataset["chunk_chars"])
    overlap = int(dataset["chunk_overlap_chars"])
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("invalid_cross_language_chunk_window")
    chunks: list[tuple[str, str]] = []
    for path in sorted((course_dir / "chapters").glob("*.md")):
        content = path.read_text(encoding="utf-8")
        if marker not in content:
            raise ValueError(f"course_body_marker_missing:{path.name}")
        body = content.split(marker, 1)[1]
        for start in range(0, len(body), size - overlap):
            chunk = body[start : start + size]
            if chunk.strip():
                chunks.append((path.name, chunk))
    return chunks


def _body_documents(course_dir: Path, dataset: dict[str, Any]) -> dict[str, str]:
    marker = str(dataset["body_marker"])
    documents: dict[str, str] = {}
    for path in sorted((course_dir / "chapters").glob("*.md")):
        content = path.read_text(encoding="utf-8")
        if marker not in content:
            raise ValueError(f"course_body_marker_missing:{path.name}")
        documents[path.name] = content.split(marker, 1)[1]
    return documents


def evaluate(
    *,
    dataset_path: Path,
    course_dir: Path,
    backend: str,
    model_path: Path | None,
    e5_prefixes: bool,
    query_strategy: str = "baseline",
) -> dict[str, Any]:
    dataset = _load_dataset(dataset_path)
    chunks = _body_chunks(course_dir, dataset)
    body_documents = _body_documents(course_dir, dataset)
    known_documents = {name for name, _ in chunks}
    for case in dataset["cases"]:
        if case["relevant_document"] not in known_documents:
            raise ValueError(f"unknown_relevant_document:{case['relevant_document']}")

    if backend == "hash":
        embedder = HashEmbeddingBackend()
        chunk_vectors = [embedder.embed(text) for _, text in chunks]

        def query_vector(text: str):
            return embedder.embed(text)

        model_identity = embedder.name
    elif backend == "sentence-transformer":
        if model_path is None or not model_path.is_dir():
            raise ValueError("local_sentence_transformer_model_required")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(str(model_path), local_files_only=True)
        passages = [f"passage: {text}" if e5_prefixes else text for _, text in chunks]
        chunk_vectors = model.encode(passages, normalize_embeddings=True, show_progress_bar=False)

        def query_vector(text: str):
            value = f"query: {text}" if e5_prefixes else text
            return model.encode(value, normalize_embeddings=True)

        model_identity = model_path.name
    else:
        raise ValueError("unsupported_cross_language_backend")

    case_results = []
    threshold = int(dataset["pass_rank_threshold"])
    for case in dataset["cases"]:
        original_query = str(case["query"])
        if query_strategy == "baseline":
            expansion = None
            retrieval_query = original_query
        elif query_strategy in {"glossary-v1", "hybrid-glossary-v1"}:
            expansion = expand_ml_query(original_query)
            retrieval_query = expansion.expanded_query
        else:
            raise ValueError("unsupported_cross_language_query_strategy")
        vector = query_vector(retrieval_query)
        by_document: dict[str, float] = {}
        lexical_by_document: dict[str, float] = {}
        for (document, _), chunk_vector in zip(chunks, chunk_vectors):
            score = cosine_similarity(tuple(vector), tuple(chunk_vector))
            by_document[document] = max(by_document.get(document, -1.0), float(score))
        if query_strategy == "hybrid-glossary-v1" and expansion is not None:
            lexical_by_document = tfidf_document_scores(expansion, body_documents)
            ranking, fusion = reciprocal_rank_fusion(by_document, lexical_by_document)
        else:
            ranking = sorted(by_document, key=by_document.get, reverse=True)
            fusion = {}
        relevant = str(case["relevant_document"])
        rank = ranking.index(relevant) + 1
        case_results.append(
            {
                "id": case["id"],
                "relevant_document": relevant,
                "rank": rank,
                "passed": rank <= threshold,
                "relevant_score": round(by_document[relevant], 6),
                "top_document": ranking[0],
                "top_score": round(by_document[ranking[0]], 6),
                "query_strategy": query_strategy,
                "matched_concepts": list(expansion.matched_concepts) if expansion else [],
                "added_terms": list(expansion.added_terms) if expansion else [],
                "semantic_rank": int(fusion[relevant]["semantic_rank"]) if fusion else rank,
                "lexical_rank": int(fusion[relevant]["lexical_rank"]) if fusion else None,
                "lexical_score": round(float(fusion[relevant]["lexical_score"]), 6) if fusion else None,
                "fused_score": round(float(fusion[relevant]["fused_score"]), 8) if fusion else None,
            }
        )

    passed = sum(item["passed"] for item in case_results)
    return {
        "schema_version": "edumatrix.cross-language-body-report.v1",
        "dataset_version": dataset["dataset_version"],
        "course_id": dataset["course_id"],
        "backend": backend,
        "model": model_identity,
        "e5_prefixes": e5_prefixes,
        "query_strategy": query_strategy,
        "fusion": {
            "method": "reciprocal-rank-fusion" if query_strategy == "hybrid-glossary-v1" else "none",
            "rank_constant": 20 if query_strategy == "hybrid-glossary-v1" else None,
            "semantic_weight": 1.0 if query_strategy == "hybrid-glossary-v1" else None,
            "tfidf_weight": 2.0 if query_strategy == "hybrid-glossary-v1" else None,
        },
        "metadata_excluded": True,
        "case_count": len(case_results),
        "passed_at_rank_threshold": passed,
        "rank_threshold": threshold,
        "recall_at_rank_threshold": passed / len(case_results),
        "passed": passed == len(case_results),
        "case_results": case_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate pure Chinese queries against English course bodies without Chinese metadata."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--course-dir", type=Path, default=DEFAULT_COURSE_DIR)
    parser.add_argument("--backend", choices=("hash", "sentence-transformer"), required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--e5-prefixes", action="store_true")
    parser.add_argument(
        "--query-strategy",
        choices=("baseline", "glossary-v1", "hybrid-glossary-v1"),
        default="baseline",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(
        dataset_path=args.dataset,
        course_dir=args.course_dir,
        backend=args.backend,
        model_path=args.model_path,
        e5_prefixes=args.e5_prefixes,
        query_strategy=args.query_strategy,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
