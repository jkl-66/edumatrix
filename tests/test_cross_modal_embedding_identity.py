"""Saved projections must never mix embedding models or vector spaces."""
import json

import pytest

import multimodal_alignment as alignment
from embedding_models import HashEmbeddingBackend


@pytest.fixture
def calibrated_pair_file(monkeypatch, tmp_path):
    monkeypatch.setattr(alignment, "_ALIGNMENT_DATA_DIR", tmp_path)
    monkeypatch.setattr(alignment, "_ALIGNMENT_FILE", tmp_path / "pairs.json")
    monkeypatch.setattr(alignment, "_CALIBRATION_EPOCHS", 2)
    monkeypatch.setattr(alignment, "EMBEDDINGS", HashEmbeddingBackend(dim=16, name="model-a"))
    original = alignment.CrossModalAligner()
    original.calibrate()
    original.save_to_disk()
    return original, alignment._ALIGNMENT_FILE


@pytest.mark.parametrize("backend", [
    HashEmbeddingBackend(dim=24, name="model-a"),
    HashEmbeddingBackend(dim=16, name="model-b"),
])
def test_changed_model_uses_one_raw_space_without_overwriting_pairs(calibrated_pair_file, monkeypatch, backend):
    original, path = calibrated_pair_file
    saved = path.read_bytes()
    monkeypatch.setattr(alignment, "EMBEDDINGS", backend)
    restored = alignment.CrossModalAligner()
    assert not restored.is_calibrated
    assert restored._pairs == original._pairs
    for mode in ("text", "formula", "image"):
        results = restored.search("最大池化", mode=mode)
        assert results and all(not row["calibrated"] for row in results)
    # Compare to a clean current-backend instance: both sides must be raw.
    monkeypatch.setattr(alignment, "_ALIGNMENT_FILE", path.with_name("absent.json"))
    fresh = alignment.CrossModalAligner(pairs=original._pairs)
    assert restored.search("最大池化") == fresh.search("最大池化")
    assert path.read_bytes() == saved


def test_same_model_restores_calibrated_search(calibrated_pair_file):
    original, _ = calibrated_pair_file
    restored = alignment.CrossModalAligner()
    assert restored.is_calibrated
    for mode in ("text", "formula", "image"):
        assert restored.search("最大池化", mode=mode) == original.search("最大池化", mode=mode)


def test_legacy_calibration_without_identity_keeps_content(calibrated_pair_file):
    original, path = calibrated_pair_file
    payload = json.loads(path.read_text(encoding="utf8"))
    payload.pop("embedding_identity")
    path.write_text(json.dumps(payload), encoding="utf8")
    restored = alignment.CrossModalAligner()
    assert restored.pair_count == original.pair_count
    assert not restored.is_calibrated
    assert restored.search("池化")


def test_live_backend_change_rebuilds_candidates_before_register_and_search(calibrated_pair_file, monkeypatch):
    original, _ = calibrated_pair_file
    monkeypatch.setattr(alignment, "EMBEDDINGS", HashEmbeddingBackend(dim=24, name="model-b"))
    original.register_pair("新增概念", formula="x=1")
    assert not original.is_calibrated
    assert len(original._text_embeddings) == original.pair_count
    assert all(len(v) == 24 for v in original._text_embeddings)
    assert original.search("新增概念")


def test_known_seed_corrections_keep_custom_pairs_and_do_not_write_on_load(calibrated_pair_file):
    original, path = calibrated_pair_file
    payload = json.loads(path.read_text(encoding="utf8"))
    legacy_pairs = [{**pair, **alignment._LEGACY_SEED_FIELDS.get(pair['text'], {})}
                    for pair in original._pairs]
    custom = {**legacy_pairs[2], 'image_desc': '用户自己补充的解释'}
    payload['pairs'] = legacy_pairs + [custom]
    path.write_text(json.dumps(payload), encoding="utf8")
    saved = path.read_bytes()
    restored = alignment.CrossModalAligner()
    assert restored._pairs[:-1] == original._pairs
    assert restored._pairs[-1] == custom
    assert not restored.is_calibrated  # Learned pair correspondence has changed.
    assert path.read_bytes() == saved
