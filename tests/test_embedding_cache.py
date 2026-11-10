from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import sys

import pytest

from embedding_models import CachingEmbeddingBackend
from embedding_models import SentenceTransformerEmbedding


def test_cached_documents_do_not_skip_query_encoder_warmup(tmp_path):
    backend = CountingEmbedding('sentence-transformer', 'existing-model', 2.0)
    ready = []
    backend.prepare = lambda: ready.append(True)
    cache = CachingEmbeddingBackend(backend, cache_path=str(tmp_path / 'prepared.db'))
    cache.embed('cached course passage')
    cache.prepare()
    cache.embed_many(['cached course passage'])
    assert ready == [True]
    assert backend.calls == 1


@pytest.mark.parametrize('missing_local', [False, True])
def test_local_encoder_uses_installed_files_and_downloads_only_when_missing(monkeypatch, missing_local):
    loads = []
    model = SimpleNamespace(encode=lambda texts, **kwargs: [(1.0, 2.0) for _ in texts])
    def construct(name, **kwargs):
        loads.append((name, kwargs))
        if missing_local and kwargs.get('local_files_only'):
            raise FileNotFoundError('synthetic missing model files')
        return model
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(set_num_threads=lambda n: None))
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=construct))
    encoder = SentenceTransformerEmbedding('selected-model')
    encoder.prepare()
    assert encoder.embed('new question') == (1.0, 2.0)
    encoder.prepare()
    assert loads[0] == ('selected-model', {'device': 'cpu', 'local_files_only': True})
    assert len(loads) == (2 if missing_local else 1)
    if missing_local:
        assert loads[1] == ('selected-model', {'device': 'cpu'})


def test_encoder_configuration_failure_is_not_hidden_by_download_fallback(monkeypatch):
    loads = []
    def construct(name, **kwargs):
        loads.append(name)
        raise ValueError('synthetic unsupported model configuration')
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(set_num_threads=lambda n: None))
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=construct))
    with pytest.raises(ValueError, match='unsupported'):
        SentenceTransformerEmbedding('selected-model').prepare()
    assert loads == ['selected-model']


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


def test_batch_cache_reuses_existing_vectors_and_deduplicates_missing_text(tmp_path):
    cache_path = str(tmp_path / 'batch.db')
    original = CountingEmbedding('test', 'batch', 3.0)
    cached = CachingEmbeddingBackend(original, cache_path=cache_path)
    cached.embed('already cached')
    values = cached.embed_many(['new', 'already cached', 'new', 'other'])
    assert values == [(3.0, 3.0), (3.0, 14.0), (3.0, 3.0), (3.0, 5.0)]
    assert original.calls == 3
    restarted = CountingEmbedding('test', 'batch', 99.0)
    assert CachingEmbeddingBackend(restarted, cache_path=cache_path).embed_many(['other', 'new']) == [values[3], values[0]]
    assert restarted.calls == 0


def test_vector_index_keeps_batch_vectors_paired_with_the_right_content(tmp_path):
    from vector_store import InMemoryVectorIndex
    from models import Evidence, EvidenceModality
    backend = CachingEmbeddingBackend(CountingEmbedding('test', 'index-batch', 3.0), cache_path=str(tmp_path/'index.db'))
    index = InMemoryVectorIndex('synthetic', embedding_backend=backend)
    items = tuple(Evidence(id=str(i), title='', content=text, source='', modality=EvidenceModality.TEXT)
                  for i, text in enumerate(['short', 'a longer paragraph']))
    index.upsert(items)
    assert index.count() == 2
    assert index._vectors['0'][1] < index._vectors['1'][1]
