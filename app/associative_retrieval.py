"""HippoRAG 2 over already-authorized, versioned canonical passages.

The optional upstream dependency owns OpenIE, the fact filter, phrase/passage
graph, synonym edges and PPR. This module adapts existing providers and records
the retrieval trace; canonical_retrieval still owns permissions and citations.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from filelock import FileLock

UPSTREAM_COMMIT = "d5c8329422e0a0b834a15874545cb6a74b4f9b26"
ADAPTER_VERSION = "edumatrix-hipporag2-v1"


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def scope_identity(chunks, *, course_id, embedding_identity, model):
    return _digest({"adapter": ADAPTER_VERSION, "upstream": UPSTREAM_COMMIT,
                    "course_id": course_id, "embedding": embedding_identity, "model": model,
                    "passages": sorted((chunk.id, _digest(chunk.content)) for chunk in chunks)})


def _build_engine(directory, embeddings, model, identity):
    import numpy as np
    from hipporag import HippoRAG
    from hipporag.embedding_model.base import BaseEmbeddingModel
    from hipporag.llm.base import BaseLLM, LLMConfig
    from hipporag.utils.config_utils import BaseConfig
    from config import CONFIG
    from llm_client import OpenAIChatLLM

    config = BaseConfig(save_dir=str(directory), llm_name=model,
                        embedding_model_name="edumatrix-bge", openie_mode="online",
                        force_index_from_scratch=not (directory / "ready.json").exists(),
                        openie_max_workers=2, openie_ner_max_tokens=16384,
                        openie_triple_max_tokens=16384, linking_top_k=10,
                        retrieval_top_k=len(identity["passages"]), response_format=None)

    class ExistingLLM(BaseLLM):
        def __init__(self):
            super().__init__(config)
            self._init_llm_config()
            self.backend = OpenAIChatLLM(CONFIG.llm_endpoint, CONFIG.llm_api_key, model=model,
                                         temperature=0, max_tokens=16384,
                                         timeout_seconds=CONFIG.llm_timeout,
                                         thinking_mode="enabled", reasoning_effort="low")

        def _init_llm_config(self):
            self.llm_config = LLMConfig()

        def infer(self, messages=None, **kwargs):
            request = {"messages": messages, "model": model, "reasoning_effort": "low",
                       "max_tokens": max(16384, int(kwargs.get("max_new_tokens", 0)))}
            key = _digest(request)
            path = directory / "model-calls" / f"{key}.json"
            system = messages[0]['content'].lower()
            expected_field = ('named_entities' if 'extract named entities' in system else
                              'triples' if 'triple' in system and 'fact_after_filter' not in system else None)
            def validate(response):
                if not expected_field:
                    return
                from hipporag.information_extraction.openie_openai import _extract_json_list_field, _extract_ner_from_response
                values = (_extract_ner_from_response(response) if expected_field == 'named_entities' else
                          _extract_json_list_field(response, expected_field))
                if expected_field == 'triples' and any(not isinstance(v, list) or len(v) != 3 or
                    not all(isinstance(s, str) and s.strip() for s in v) for v in values):
                    raise ValueError('Invalid OpenIE triple')
            with FileLock(str(path) + ".lock"):
                if path.exists():
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    try:
                        validate(saved['response'])
                    except ValueError:
                        _save(directory / 'rejected-model-calls' / path.name, saved)
                    else:
                        return saved["response"], saved["metadata"], True
                sent_messages = [dict(message) for message in messages]
                if expected_field:
                    schema = ('{"named_entities":["实体或概念"]}' if expected_field == 'named_entities' else
                              '{"triples":[["主体","关系","客体"]]}')
                    sent_messages[-1]['content'] += ('\n\n以上是待抽取的资料。执行系统指定的信息抽取任务，'
                        '学科概念和数据角色也属于实体。只返回JSON，结构为' + schema + '。')
                    if list((directory / 'failures').glob(f'{key}-*.json')):
                        sent_messages[-1]['content'] += ('\n核对每条关系恰好包含主体、关系、客体三个非空字符串。'
                            '保持原文比较方向、否定与成立条件；可能发生不能改成必然。')
                started = time.monotonic()
                try:
                    response, metadata = self.backend.infer_messages(sent_messages, max_tokens=request["max_tokens"],
                        response_format={"type": "json_object"} if expected_field else None)
                    validate(response)
                except Exception as exc:
                    _save(directory / "failures" / f"{key}-{time.time_ns()}.json",
                          {"request": request, "error_type": type(exc).__name__,
                           "sent_messages": sent_messages, "response": locals().get('response'),
                           "elapsed_seconds": time.monotonic() - started})
                    raise
                metadata["elapsed_seconds"] = time.monotonic() - started
                _save(path, {"request": request, "sent_messages": sent_messages, "response": response, "metadata": metadata})
                return response, metadata, False

    class ExistingEmbedding(BaseEmbeddingModel):
        def __init__(self):
            super().__init__(config)
            self.embedding_dim = len(embeddings.embed("模型选择与泛化"))

        def batch_encode(self, texts, **kwargs):
            values = np.asarray(embeddings.embed_many([texts] if isinstance(texts, str) else list(texts)), dtype=np.float32)
            return self._normalize_embeddings(values, kwargs.get("normalize"))

    class TracedHippoRAG(HippoRAG):
        def rerank_facts(self, query, query_fact_scores):
            result = super().rerank_facts(query, query_fact_scores)
            self.trace["fact_filter"] = result[2]
            self.trace["selected_fact_scores"] = [float(query_fact_scores[i]) for i in result[0]]
            return result

        def run_ppr(self, reset_prob, damping=.5):
            self.trace["ppr"] = {"damping": damping, "passage_node_weight": self.global_config.passage_node_weight,
                                 "seeds": [{"node": self.graph.vs[i]["name"], "weight": float(value)}
                                           for i, value in enumerate(reset_prob) if value > 0]}
            return super().run_ppr(reset_prob, damping)

    (directory / "model-calls").mkdir(parents=True, exist_ok=True)
    llm = ExistingLLM()
    engine = TracedHippoRAG(global_config=config, extraction_llm=llm, qa_llm=llm,
                           embedding_model=ExistingEmbedding(), index_identity=_digest(identity))
    engine.trace = {}
    return engine


def rank_associative_chunks(chunks, *, query, embeddings, course_id):
    """Return the canonical rank contract, using only this call's allowed scope."""
    from config import CONFIG
    if not embeddings.semantic_capable:
        raise ValueError("关联检索需要配置语义嵌入模型")
    if CONFIG.llm_provider not in {"openai", "vllm"} or not CONFIG.llm_api_key:
        raise ValueError("关联检索需要已配置的模型连接")
    from hipporag import Chunk

    started = time.monotonic()
    model = os.getenv("EDUMATRIX_HIPPORAG_MODEL", "deepseek-v4-flash")
    key = scope_identity(chunks, course_id=course_id, embedding_identity=embeddings.identity(), model=model)
    root = Path(os.getenv("EDUMATRIX_HIPPORAG_DIR", str(Path(__file__).resolve().parents[1] / "data" / "hipporag2")))
    directory = root / key[:24]
    directory.mkdir(parents=True, exist_ok=True)
    identity = {"scope_key": key, "course_id": course_id, "adapter": ADAPTER_VERSION,
                "upstream_commit": UPSTREAM_COMMIT, "embedding": embeddings.identity(), "model": model,
                "passages": sorted([{"id": chunk.id, "content_hash": _digest(chunk.content)} for chunk in chunks], key=lambda item: item['id'])}
    with FileLock(str(directory / "index.lock")):
        engine = _build_engine(directory, embeddings, model, identity)
        try:
            ready = directory / "ready.json"
            if not ready.exists():
                engine.index([Chunk(content=chunk.content, source_id=chunk.id,
                                    metadata={"canonical_chunk_id": chunk.id}) for chunk in chunks])
                _save(directory / "scope.json", identity)
                _save(directory / "graph.json", {
                    "info": engine.get_graph_info(),
                    "nodes": [vertex.attributes() for vertex in engine.graph.vs],
                    "edges": [{"source": engine.graph.vs[edge.source]["name"],
                               "target": engine.graph.vs[edge.target]["name"], **edge.attributes()}
                              for edge in engine.graph.es],
                })
                _save(ready, {"scope_key": key, "index_seconds": time.monotonic() - started})
            result = engine.retrieve([query], num_to_retrieve=len(chunks))[0]
            # Upstream deduplicates identical passage text. Map back to a current
            # authorized chunk, never to an ID merely stored in an old index.
            by_text = {chunk.content: chunk.id for chunk in chunks}
            order = [by_text[content] for content in result.docs]
            diagnostics = {chunk_id: {"hipporag_rank": rank, "hipporag_score": float(score),
                                      "semantic_score": float(embeddings.score(query, content))}
                           for rank, (chunk_id, score, content) in enumerate(zip(order, result.doc_scores, result.docs), 1)}
            trace = {"method": "hipporag2", "upstream_commit": UPSTREAM_COMMIT,
                     "scope_key": key, "graph": engine.get_graph_info(),
                     "graph_used": bool(engine.trace.get("ppr")), **engine.trace,
                     "ranking": [{"chunk_id": chunk_id, **diagnostics[chunk_id]} for chunk_id in order],
                     "elapsed_seconds": time.monotonic() - started}
            _save(directory / "queries" / f"{_digest(query)}.json", {"query": query, **trace})
            return order, diagnostics, {"method": "hipporag2", "hipporag2": trace,
                                        "embedding": embeddings.identity()}
        finally:
            engine.close()
