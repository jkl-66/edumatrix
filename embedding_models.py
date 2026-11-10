from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from threading import RLock
from typing import Protocol
from urllib import request

from config import CONFIG
from cache_utils import TTLBoundedCache


class EmbeddingBackend(Protocol):
    name: str

    def embed(self, text: str) -> tuple[float, ...]:
        ...

    def score(self, query: str, document: str) -> float:
        query_vector = self.embed(query)
        doc_vector = self.embed(document)
        return cosine_similarity(query_vector, doc_vector)


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(0.0, min(1.0, (dot / (left_norm * right_norm) + 1.0) / 2.0))


@dataclass
class SentenceTransformerEmbedding:
    model_name: str = "BAAI/bge-small-zh-v1.5"
    name: str = "sentence-transformer"

    def __post_init__(self):
        self._model = None
        self._lock = RLock()

    def _load_model(self):
        if self._model is None:
            import torch
            # Small CPU encoders slow down markedly when every request fans out
            # to all machine cores. Keep a configurable throughput setting.
            torch.set_num_threads(max(1, CONFIG.embedding_cpu_threads))
            import sentence_transformers
            try:
                self._model = sentence_transformers.SentenceTransformer(
                    self.model_name, device="cpu", local_files_only=True,
                )
            except OSError:
                # A first installation still downloads the configured model.
                # An already-installed encoder needs no Hub metadata requests.
                self._model = sentence_transformers.SentenceTransformer(
                    self.model_name, device="cpu",
                )

    def prepare(self) -> None:
        with self._lock:
            self._load_model()

    def embed(self, text: str) -> tuple[float, ...]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        with self._lock:
            self._load_model()
            vectors = self._model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        return [tuple(float(v) for v in vector) for vector in vectors]

    def score(self, query: str, document: str) -> float:
        q_vec = self.embed(query)
        d_vec = self.embed(document)
        return cosine_similarity(q_vec, d_vec)


@dataclass(frozen=True)
class HashEmbeddingBackend:
    dim: int = 384
    name: str = "hash-embedding"

    def embed(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self.dim
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + min(3, len(token) // 4) * 0.15
            vector[index] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return tuple(vector)
        return tuple(value / norm for value in vector)

    def score(self, query: str, document: str) -> float:
        return cosine_similarity(self.embed(query), self.embed(document))


@dataclass(frozen=True)
class OpenAICompatibleEmbeddingBackend:
    endpoint: str
    api_key: str
    model: str
    timeout_seconds: int = 30
    name: str = "openai-compatible-embedding"

    def embed(self, text: str) -> tuple[float, ...]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        payload = json.dumps({"model": self.model, "input": texts}, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        req = request.Request(self.endpoint, data=payload, headers=headers, method="POST")
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        ordered = sorted(data['data'], key=lambda row: row['index'])
        if len(ordered) != len(texts) or [row['index'] for row in ordered] != list(range(len(texts))):
            raise ValueError('embedding_batch_incomplete')
        return [tuple(float(value) for value in row['embedding']) for row in ordered]

    def score(self, query: str, document: str) -> float:
        return cosine_similarity(self.embed(query), self.embed(document))


def _tokens(text: str) -> tuple[str, ...]:
    import re
    lower = text.lower()
    tokens = re.findall(r"[a-zA-Z0-9_+\-.]+|[\u4e00-\u9fff]{2,}", lower)
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.extend("".join(chinese[i : i + 2]) for i in range(max(0, len(chinese) - 1)))
    return tuple(token for token in tokens if token.strip())


class CachingEmbeddingBackend:
    def __init__(self, backend: EmbeddingBackend, *, cache_path: str | None = None):
        self._backend = backend
        self._cache: TTLBoundedCache[str, tuple[float, ...]] = TTLBoundedCache(
            maxsize=CONFIG.cache_max_entries,
            ttl_seconds=CONFIG.cache_ttl_seconds,
        )
        self.name = f"cached-{backend.name}"
        
        # Initialize SQLite DB in workspace root
        import os
        import sqlite3
        self._db_path = cache_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "embeddings_cache.db")
        try:
            conn = sqlite3.connect(self._db_path, timeout=10.0)
            with conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS embedding_cache (text TEXT PRIMARY KEY, vector_json TEXT)"
                )
            conn.close()
        except Exception:
            pass

    def _cache_key(self, text: str) -> str:
        identity = {
            "name": str(getattr(self._backend, "name", type(self._backend).__name__)),
            "model": str(getattr(self._backend, "model_name", getattr(self._backend, "model", ""))),
            "dim": int(getattr(self._backend, "dim", 0) or 0),
            "text": text,
        }
        canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def embed(self, text: str) -> tuple[float, ...]:
        cache_key = self._cache_key(text)
        if cache_key in self._cache:
            return self._cache[cache_key]
            
        import sqlite3
        import json
        
        # Try retrieving from SQLite
        try:
            conn = sqlite3.connect(self._db_path, timeout=10.0)
            cursor = conn.cursor()
            cursor.execute("SELECT vector_json FROM embedding_cache WHERE text = ?", (cache_key,))
            row = cursor.fetchone()
            conn.close()
            if row:
                vec = tuple(float(x) for x in json.loads(row[0]))
                self._cache[cache_key] = vec
                return vec
        except Exception:
            pass
            
        # Fallback to computing embedding
        vec = self._backend.embed(text)
        self._cache[cache_key] = vec
        
        # Persist to SQLite
        try:
            conn = sqlite3.connect(self._db_path, timeout=10.0)
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO embedding_cache (text, vector_json) VALUES (?, ?)",
                    (cache_key, json.dumps(vec)),
                )
            conn.close()
        except Exception:
            pass
            
        return vec

    def score(self, query: str, document: str) -> float:
        q_vec = self.embed(query)
        d_vec = self.embed(document)
        return cosine_similarity(q_vec, d_vec)

    def identity(self) -> dict[str, str | int]:
        return {
            "name": str(getattr(self._backend, "name", type(self._backend).__name__)),
            "model": str(getattr(self._backend, "model_name", getattr(self._backend, "model", ""))),
            "dim": int(getattr(self._backend, "dim", 0) or 0),
        }

    @property
    def semantic_capable(self) -> bool:
        return self.identity()['name'] in {'sentence-transformer', 'openai-compatible-embedding'}

    def prepare(self) -> None:
        # Cached document vectors alone do not load the query encoder. Warm it
        # even when every document is already cached after a server restart.
        prepare = getattr(self._backend, 'prepare', None)
        if prepare is not None:
            prepare()

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Read/write the existing cache in batches; encode each missing text once."""
        if not texts:
            return []
        import sqlite3
        keys = [self._cache_key(text) for text in texts]
        found = {key: value for key in set(keys) if (value := self._cache.get(key)) is not None}
        pending = list(dict.fromkeys(key for key in keys if key not in found))
        try:
            with sqlite3.connect(self._db_path, timeout=10.0) as db:
                for start in range(0, len(pending), 400):
                    batch = pending[start:start+400]
                    rows = db.execute('SELECT text,vector_json FROM embedding_cache WHERE text IN (' + ','.join('?' for _ in batch) + ')', batch)
                    for key, encoded in rows:
                        found[key] = tuple(float(value) for value in json.loads(encoded))
        except (sqlite3.Error, ValueError, TypeError):
            pass
        missing = {key: text for key, text in zip(keys, texts) if key not in found}
        pairs = list(missing.items())
        for start in range(0, len(pairs), 64):
            batch = pairs[start:start+64]
            encode_many = getattr(self._backend, 'embed_many', None)
            vectors = encode_many([text for _, text in batch]) if encode_many else [self._backend.embed(text) for _, text in batch]
            if len(vectors) != len(batch):
                raise ValueError('embedding_batch_incomplete')
            found.update((key, tuple(vector)) for (key, _), vector in zip(batch, vectors))
            try:
                with sqlite3.connect(self._db_path, timeout=10.0) as db:
                    db.executemany('INSERT OR REPLACE INTO embedding_cache (text,vector_json) VALUES (?,?)',
                                   [(key, json.dumps(found[key])) for key, _ in batch])
            except sqlite3.Error:
                pass
        for key, value in found.items():
            self._cache[key] = value
        return [found[key] for key in keys]


def build_embedding_backend() -> EmbeddingBackend:
    provider = CONFIG.embedding_provider.lower().strip()
    if provider == "sentence_transformer":
        try:
            return SentenceTransformerEmbedding(model_name=CONFIG.embedding_model)
        except Exception:
            pass
    if provider in {"openai", "openai_compatible", "compatible"}:
        if CONFIG.embedding_endpoint and CONFIG.embedding_api_key:
            return OpenAICompatibleEmbeddingBackend(
                endpoint=CONFIG.embedding_endpoint,
                api_key=CONFIG.embedding_api_key,
                model=CONFIG.embedding_model,
            )
    return HashEmbeddingBackend(dim=CONFIG.embedding_dim)


EMBEDDINGS = CachingEmbeddingBackend(build_embedding_backend())
