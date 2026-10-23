"""Static model-call inventory and drift gate for production Python paths."""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CallsitePolicy:
    classification: str
    activity: str
    mechanism: str
    capability: str


@dataclass(frozen=True)
class ModelCallsite:
    key: str
    path: str
    function: str
    callee: str
    line: int
    classification: str
    activity: str
    mechanism: str
    capability: str

    def payload(self) -> dict[str, object]:
        return self.__dict__.copy()


POLICIES: dict[tuple[str, str, str], CallsitePolicy] = {
    ("agent_swarm.py", "_async_extract_with_llm", "self.llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "answer"),
    ("agent_swarm.py", "_async_llm_evaluate", "self._llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "evaluate"),
    ("agent_swarm.py", "_generate_one", "self.generator.generate"): CallsitePolicy("domain_orchestrator", "active", "delegated_gateway", "compound"),
    ("app/m2_api.py", "generate", "M2StructuredArtifactGenerator(llm).generate"): CallsitePolicy("domain_orchestrator", "frozen_compat", "delegated_generator", "m2_artifact"),
    ("app/m2_artifacts.py", "generate", "self.llm.generate"): CallsitePolicy("migration_required", "frozen_compat", "direct_backend", "m2_artifact"),
    ("app/m3_api.py", "review_claim", "self.llm.generate"): CallsitePolicy("migration_required", "frozen_compat", "direct_backend", "decision"),
    ("app/m3_api.py", "run", "M3PersonalizedResourceGenerator(llm).generate"): CallsitePolicy("domain_orchestrator", "frozen_compat", "delegated_generator", "m3_resource"),
    ("app/m3_resources.py", "generate", "self.llm.generate"): CallsitePolicy("migration_required", "frozen_compat", "direct_backend", "m3_resource"),
    ("app/m4_executor.py", "execute", "self.llm.generate"): CallsitePolicy("migration_required", "frozen_compat", "direct_backend", "m4_evaluation"),
    ("app/m5_gateway.py", "execute", "backend.generate"): CallsitePolicy("gateway_core", "active", "unified_gateway", "dynamic"),
    ("app/m5_legacy_calls.py", "audited_legacy_text_call", "llm.generate"): CallsitePolicy("adapter_core", "active", "streaming_lifecycle", "dynamic"),
    ("app/m5_legacy_calls.py", "audited_legacy_sync_text_call", "llm.generate"): CallsitePolicy("adapter_core", "active", "sync_lifecycle", "dynamic"),
    ("app/code_review.py", "review", "self.backend.generate"): CallsitePolicy("domain_orchestrator", "active", "delegated_adapter", "code_review"),
    ("app/main.py", "test_vision_connection", "vision_llm.generate_stream"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "vision"),
    ("app/main.py", "polish_note", "active_swarm.llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "answer"),
    ("app/utils/graph_builder.py", "extract_triplets_from_text", "llm.generate"): CallsitePolicy("governed_compat", "active", "sync_lifecycle", "mindmap"),
    ("drag_debate.py", "_collective_batch_judge", "self.llm.generate"): CallsitePolicy("dormant_legacy", "dormant", "none", "decision"),
    ("drag_debate.py", "_collective_batch_judge_async", "self.llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "decision"),
    ("instruct_rag.py", "generate", "self.llm.generate"): CallsitePolicy("dormant_legacy", "dormant", "none", "answer"),
    ("instruct_rag.py", "generate_stream", "self.llm.generate_stream"): CallsitePolicy("dormant_legacy", "dormant", "none", "answer"),
    ("knowledge_api.py", "_generate_doc_guide_for_document", "active_llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "lecture"),
    ("llm_client.py", "generate_stream", "fallback_backend.generate_stream"): CallsitePolicy("backend_internal", "active", "provider_fallback", "dynamic"),
    ("llm_client.py", "generate", "local_backup.generate"): CallsitePolicy("backend_internal", "active", "provider_fallback", "dynamic"),
    ("llm_client.py", "generate_stream", "local_backup.generate_stream"): CallsitePolicy("backend_internal", "active", "provider_fallback", "dynamic"),
    ("llm_client.py", "generate", "DeterministicEducationLLM().generate"): CallsitePolicy("backend_internal", "active", "deterministic_backend", "dynamic"),
    ("llm_client.py", "generate_stream", "DeterministicEducationLLM().generate"): CallsitePolicy("backend_internal", "active", "deterministic_backend", "dynamic"),
    ("llm_client.py", "generate", "self.text_backend.generate"): CallsitePolicy("backend_internal", "active", "multimodal_dispatch", "dynamic"),
    ("llm_client.py", "generate_stream", "backend.generate_stream"): CallsitePolicy("backend_internal", "active", "multimodal_dispatch", "dynamic"),
    ("llm_client.py", "generate", "self.primary.generate"): CallsitePolicy("backend_internal", "active", "provider_fallback", "dynamic"),
    ("llm_client.py", "generate", "self.fallback.generate"): CallsitePolicy("backend_internal", "active", "provider_fallback", "dynamic"),
    ("llm_client.py", "generate_stream", "self.primary.generate_stream"): CallsitePolicy("backend_internal", "active", "provider_fallback", "dynamic"),
    ("llm_client.py", "generate_stream", "self.fallback.generate_stream"): CallsitePolicy("backend_internal", "active", "provider_fallback", "dynamic"),
    ("llm_client.py", "call_spark_api", "DEFAULT_LLM.generate"): CallsitePolicy("backend_internal", "compatibility", "legacy_entrypoint", "answer"),
    ("note_engine.py", "summarize_conversation", "self.llm.generate"): CallsitePolicy("dormant_legacy", "dormant", "none", "answer"),
    ("profile_api.py", "_generate_agent", "self.llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "report"),
    ("quiz_api.py", "_call_quiz_model", "llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "quiz"),
    ("stream_api.py", "_plan_socratic_move", "llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "plan"),
    ("stream_api.py", "_generate_socratic_teacher", "llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "answer"),
    ("stream_api.py", "_stream_socratic_teacher", "llm.generate_stream"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "answer"),
    ("stream_api.py", "_generate_peer_challenge", "llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "quiz"),
    ("stream_api.py", "_generate_suggested_questions", "swarm.llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "answer"),
    ("stream_api.py", "_ocr_multimodal_describer", "vision_backend.generate_stream"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "vision"),
    ("stream_api.py", "_run_professional_chain", "llm.generate"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "answer"),
    ("stream_api.py", "canonical_event_generator", "swarm.llm.generate_stream"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "answer"),
    ("stream_api.py", "event_generator", "swarm.llm.generate_stream"): CallsitePolicy("governed_compat", "active", "streaming_lifecycle", "answer"),
    ("stream_api.py", "regenerate_component", "swarm.async_generator.generate"): CallsitePolicy("domain_orchestrator", "active", "delegated_generator", "compound"),
    ("app/resource_bundles.py", "_real_model_payload", "backend.generate"): CallsitePolicy("domain_orchestrator", "active", "delegated_gateway", "compound"),
    ("app/resource_bundles.py", "_real_model_payload_async", "backend.generate"): CallsitePolicy("domain_orchestrator", "active", "delegated_gateway", "compound"),
    ("app/resource_bundles.py", "_shared_semantic_plan_async", "backend.generate"): CallsitePolicy("domain_orchestrator", "active", "delegated_gateway", "planning"),
    ("app/resource_bundles.py", "_resource_review_async", "backend.generate"): CallsitePolicy("domain_orchestrator", "active", "delegated_gateway", "review"),
}


def _callee(node: ast.Call) -> str:
    try:
        return ast.unparse(node.func)
    except Exception:
        return ""


def _function_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return "<module>"


def _candidate(callee: str) -> bool:
    return callee.endswith((".generate", ".generate_stream")) or ".chat.completions.create" in callee or ".responses.create" in callee


def _source_files(root: Path) -> Iterable[Path]:
    yield from sorted(root.glob("*.py"))
    yield from sorted((root / "app").rglob("*.py"))


def scan_model_calls(root: Path) -> list[ModelCallsite]:
    callsites: list[ModelCallsite] = []
    occurrences: Counter[tuple[str, str, str]] = Counter()
    for path in _source_files(root):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in sorted((item for item in ast.walk(tree) if isinstance(item, ast.Call)), key=lambda item: item.lineno):
            callee = _callee(node)
            if not _candidate(callee):
                continue
            function = _function_name(node, parents)
            lookup = (relative, function, callee)
            policy = POLICIES.get(lookup, CallsitePolicy("unregistered", "unknown", "none", "unknown"))
            occurrences[lookup] += 1
            key = f"{relative}:{function}:{callee}:{occurrences[lookup]}"
            callsites.append(ModelCallsite(key, relative, function, callee, node.lineno, policy.classification, policy.activity, policy.mechanism, policy.capability))
    return callsites


def governance_summary(callsites: list[ModelCallsite]) -> dict[str, object]:
    classifications = Counter(item.classification for item in callsites)
    unregistered = [item.payload() for item in callsites if item.classification == "unregistered"]
    active_direct = [item.payload() for item in callsites if item.activity == "active" and item.mechanism in {"none", "direct_backend"}]
    migration_required = [item.payload() for item in callsites if item.classification == "migration_required"]
    return {
        "schema_version": "next.model-call-governance.v1",
        "registry_version": "2026-08-03.1",
        "total_callsites": len(callsites),
        "classification_counts": dict(sorted(classifications.items())),
        "unregistered_count": len(unregistered),
        "active_direct_count": len(active_direct),
        "migration_required_count": len(migration_required),
        "unregistered": unregistered,
        "active_direct": active_direct,
        "migration_required": migration_required,
    }
