from __future__ import annotations

from dataclasses import dataclass

from embedding_models import CachingEmbeddingBackend


@dataclass
class CountingEmbedding:
    name: str
    model_name: str
    value: float
    calls: int = 0

    def embed(self, text: str) -> tuple[float, ...]:
        self.calls += 1
        return (self.value, float(len(text)))


def test_persistent_embedding_cache_isolated_by_backend_identity(tmp_path):
    cache_path = str(tmp_path / "embedding-cache.db")
    first_backend = CountingEmbedding("sentence-transformer", "model-a", 1.0)
    second_backend = CountingEmbedding("sentence-transformer", "model-b", 2.0)

    first = CachingEmbeddingBackend(first_backend, cache_path=cache_path)
    second = CachingEmbeddingBackend(second_backend, cache_path=cache_path)

    assert first.embed("same text") == (1.0, 9.0)
    assert first.embed("same text") == (1.0, 9.0)
    assert second.embed("same text") == (2.0, 9.0)
    assert first_backend.calls == 1
    assert second_backend.calls == 1


def test_persistent_embedding_cache_reused_for_same_backend(tmp_path):
    cache_path = str(tmp_path / "embedding-cache.db")
    original_backend = CountingEmbedding("hash-embedding", "", 3.0)
    original = CachingEmbeddingBackend(original_backend, cache_path=cache_path)
    assert original.embed("course material") == (3.0, 15.0)

    restarted_backend = CountingEmbedding("hash-embedding", "", 99.0)
    restarted = CachingEmbeddingBackend(restarted_backend, cache_path=cache_path)
    assert restarted.embed("course material") == (3.0, 15.0)
    assert restarted_backend.calls == 0
