from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from config import CONFIG
from models import Evidence, EvidenceModality


def load_evidence_from_file(path: str | Path) -> tuple[Evidence, ...]:
    path = Path(path)
    if not path.exists():
        return ()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        items = data.get("evidences", data.get("evidence", []))
    elif isinstance(data, list):
        items = data
    else:
        return ()
    return tuple(_parse_evidence(item) for item in items)


def _parse_evidence(item: dict) -> Evidence:
    raw_modality = str(item.get("modality", "text")).lower()
    modality_map = {
        "text": EvidenceModality.TEXT,
        "image": EvidenceModality.IMAGE,
        "graph": EvidenceModality.GRAPH,
        "code": EvidenceModality.CODE,
    }
    modality = modality_map.get(raw_modality, EvidenceModality.TEXT)
    return Evidence(
        id=str(item["id"]),
        title=str(item.get("title", "")),
        content=str(item.get("content", "")),
        modality=modality,
        source=str(item.get("source", "")),
        tags=tuple(str(t) for t in item.get("tags", [])),
        anchors=tuple(str(a) for a in item.get("anchors", [])),
        score=float(item.get("score", 0.0)),
        metadata=item.get("metadata", {}),
    )


def load_seed_evidence() -> tuple[Evidence, ...]:
    files = [
        Path("data") / "knowledge_base.json",
        Path("data") / "evidences.json",
    ]
    for f in files:
        evidence = load_evidence_from_file(f)
        if evidence:
            return evidence
    return ()


def save_evidence_to_file(evidence: Sequence[Evidence], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = []
    for item in evidence:
        data.append({
            "id": item.id,
            "title": item.title,
            "content": item.content,
            "modality": item.modality.value,
            "source": item.source,
            "tags": list(item.tags),
            "anchors": list(item.anchors),
            "score": item.score,
            "metadata": item.metadata,
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
