from pathlib import Path

from models import Evidence, EvidenceModality
from knowledge_base import load_evidence_from_file
from rag_engine import VisRAG


def _image_evidence(raw_image_ref: str, *, source: str = "verified-textbook.pdf:p1") -> Evidence:
    return Evidence(
        id="verified-image",
        title="Verified image",
        content="Verified local image evidence",
        modality=EvidenceModality.IMAGE,
        source=source,
        metadata={"raw_image_ref": raw_image_ref},
    )


def test_visrag_does_not_create_builtin_evidence_when_seed_is_empty(monkeypatch):
    monkeypatch.setattr("rag_engine.load_seed_evidence", lambda: ())

    visrag = VisRAG()

    assert visrag.patch_db == ()
    assert visrag.index.count() == 0


def test_visrag_rejects_missing_untraced_and_out_of_scope_images(monkeypatch, tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    missing = _image_evidence("data/patches/missing.png")
    untraced = _image_evidence("data/patches/missing.png", source="")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"real but outside governed patch storage")
    out_of_scope = _image_evidence(str(outside))
    monkeypatch.setattr("rag_engine.load_seed_evidence", lambda: (missing, untraced, out_of_scope))

    visrag = VisRAG()

    assert project_root not in outside.parents
    assert visrag.patch_db == ()


def test_visrag_accepts_existing_traced_patch(monkeypatch, tmp_path):
    existing = tmp_path / "verified.png"
    existing.write_bytes(b"verified local image")
    evidence = _image_evidence(str(existing))
    monkeypatch.setattr("rag_engine.PATCHES_ROOT", tmp_path)
    monkeypatch.setattr("rag_engine.load_seed_evidence", lambda: (evidence,))

    visrag = VisRAG()

    assert existing.is_file()
    assert visrag.patch_db == (evidence,)
    assert visrag.index.count() == 1


def test_packaged_visual_seed_manifest_loads_all_verified_images():
    evidence = load_evidence_from_file("data/evidences.json")
    visrag = VisRAG()

    assert len(evidence) == 7
    assert len(visrag.patch_db) == 7
    assert {item.id for item in visrag.patch_db} == {item.id for item in evidence}
    assert all(item.metadata.get("license") for item in visrag.patch_db)
