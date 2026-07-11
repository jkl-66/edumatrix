from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Protocol
from urllib import request

from config import CONFIG


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

    def _load_model(self):
        if self._model is None:
            import sentence_transformers
            self._model = sentence_transformers.SentenceTransformer(
                self.model_name,
                device="cpu",
            )

    def embed(self, text: str) -> tuple[float, ...]:
        self._load_model()
        vec = self._model.encode(text, normalize_embeddings=True)
        return tuple(float(v) for v in vec)

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
        payload = json.dumps({"model": self.model, "input": text}, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        req = request.Request(self.endpoint, data=payload, headers=headers, method="POST")
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        return tuple(float(value) for value in data["data"][0]["embedding"])

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
    def __init__(self, backend: EmbeddingBackend):
        self._backend = backend
        self._cache: dict[str, tuple[float, ...]] = {}
        self.name = f"cached-{backend.name}"
        
        # Initialize SQLite DB in workspace root
        import os
        import sqlite3
        self._db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "embeddings_cache.db")
        try:
            conn = sqlite3.connect(self._db_path, timeout=10.0)
            with conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS embedding_cache (text TEXT PRIMARY KEY, vector_json TEXT)"
                )
            conn.close()
        except Exception:
            pass

    def embed(self, text: str) -> tuple[float, ...]:
        if text in self._cache:
            return self._cache[text]
            
        import sqlite3
        import json
        
        # Try retrieving from SQLite
        try:
            conn = sqlite3.connect(self._db_path, timeout=10.0)
            cursor = conn.cursor()
            cursor.execute("SELECT vector_json FROM embedding_cache WHERE text = ?", (text,))
            row = cursor.fetchone()
            conn.close()
            if row:
                vec = tuple(float(x) for x in json.loads(row[0]))
                self._cache[text] = vec
                return vec
        except Exception:
            pass
            
        # Fallback to computing embedding
        vec = self._backend.embed(text)
        self._cache[text] = vec
        
        # Persist to SQLite
        try:
            conn = sqlite3.connect(self._db_path, timeout=10.0)
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO embedding_cache (text, vector_json) VALUES (?, ?)",
                    (text, json.dumps(vec)),
                )
            conn.close()
        except Exception:
            pass
            
        return vec

    def score(self, query: str, document: str) -> float:
        q_vec = self.embed(query)
        d_vec = self.embed(document)
        return cosine_similarity(q_vec, d_vec)


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
