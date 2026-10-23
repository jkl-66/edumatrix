#!/usr/bin/env python3
"""Independently verify and activate a context-recovery packet version."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "原系统融合重构执行"
CONTEXT_ROOT = OUTPUT / "evidence" / "context_recovery"

GOAL_PATH = CONTEXT_ROOT / "goal_contract.md"
CONSTITUTION_PATH = OUTPUT / "06_用户意图与产品宪法.md"
PRODUCT_JSON_PATH = OUTPUT / "09_EduMatrix最终产品方案.json"
PLAN_JSON_PATH = OUTPUT / "10_原版融合重构详细实施方案.json"
AUDIT_JSON_PATH = OUTPUT / "13_改进想法逐句逐图实质落实审计.json"
DOCX_PATH = ROOT / "outputs" / "改进想法.docx"
PDF_PATH = ROOT / "赛题" / "XH-202630上海云之脑智能科技有限公司-领域知识个性化生成与多智能体协同决策系统研究比赛方案.pdf"
LEGACY_MANIFEST_PATH = OUTPUT / "evidence" / "dual_version_audit" / "improvement_ideas" / "manifest.json"
IMAGE_DIR = LEGACY_MANIFEST_PATH.parent
DUAL_CODE_MAP_PATH = OUTPUT / "evidence" / "dual_version_audit" / "dual_version_code_map.json"
SCOPE_MATRIX_PATH = OUTPUT / "evidence" / "fusion_scope_matrix" / "fusion_scope_matrix.json"
PROTECTION_PATH = OUTPUT / "evidence" / "protection_baseline" / "protected_pages_baseline.json"
CURRENT_ROUTE_PATH = OUTPUT / "evidence" / "route_product_spec" / "route_product_spec.json"
TARGET_ROUTE_PATH = OUTPUT / "evidence" / "target_product_spec" / "target_product_route_spec.json"
TARGET_GLOBAL_PATH = OUTPUT / "evidence" / "target_product_spec" / "target_product_global_contracts.json"

PINNED_AUTHORITY_PATHS = {
    "goal_contract": GOAL_PATH,
    "constitution": CONSTITUTION_PATH,
    "code_map_md": OUTPUT / "07_双版本代码地图与功能清单.md",
    "route_matrix": OUTPUT / "08_用户需求追踪与路由迁移矩阵.md",
    "product_md": OUTPUT / "09_EduMatrix最终产品方案.md",
    "product_json": PRODUCT_JSON_PATH,
    "implementation_md": OUTPUT / "10_原版融合重构详细实施方案.md",
    "implementation_json": PLAN_JSON_PATH,
    "audit_md": OUTPUT / "13_改进想法逐句逐图实质落实审计.md",
    "audit_json": AUDIT_JSON_PATH,
    "improvement_docx": DOCX_PATH,
    "competition_pdf": PDF_PATH,
    "legacy_word_manifest": LEGACY_MANIFEST_PATH,
    "dual_version_code_map": DUAL_CODE_MAP_PATH,
    "fusion_scope_matrix": SCOPE_MATRIX_PATH,
    "protection_baseline": PROTECTION_PATH,
    "current_route_spec": CURRENT_ROUTE_PATH,
    "target_route_spec": TARGET_ROUTE_PATH,
    "target_global_contracts": TARGET_GLOBAL_PATH,
}

OPERATIONAL_PATHS = {
    "status": OUTPUT / "00_唯一执行状态.md",
    "recovery_index": OUTPUT / "11_上下文恢复与实施索引.md",
    "worklog": OUTPUT / "02_融合重构_WORKLOG.md",
}

VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,95}$")

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CODE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".css", ".json"}
CODE_ROOTS = ("app", "frontend/src", "tests", "scripts")
PATH_PATTERN = re.compile(
    r"(?:(?:frontend/src|app|tests|scripts|data)/[A-Za-z0-9_.\-/]+"
    r"(?:\.(?:py|js|mjs|cjs|ts|tsx|jsx|vue|css|json|md))?)"
)
ROUTE_PATTERN = re.compile(r"/[A-Za-z0-9_{}:$*?./-]+")
JS_IMPORT_PATTERN = re.compile(
    r"(?:from\s+|import\s*\(|require\s*\()\s*['\"]([^'\"]+)['\"]"
)


def task_atomic_execution_contract(
    task_id: str,
    primary_atoms: list[dict[str, Any]],
    related_atoms: list[dict[str, Any]],
) -> dict[str, Any]:
    """Independently derive the required per-task atomic execution contract."""
    return {
        "schema_version": "context-recovery.task-atomic-contract.v1",
        "task_id": task_id,
        "scope_is_task_local": True,
        "must_reload_on_entry_resume_compaction_handoff_and_task_switch": True,
        "previous_task_understanding_or_evidence_cannot_substitute": True,
        "must_read_every_primary_and_related_atom": True,
        "must_correlate_word_paragraphs_and_full_size_images": True,
        "editing_forbidden_before_context_verified": True,
        "context_verified_requires_per_atom_understanding": True,
        "ledger_must_remain_active_during_planning_editing_testing_and_review": True,
        "every_edit_batch_requires_atom_or_protection_mapping": True,
        "ledger_must_be_updated_after_each_edit_or_test_batch": True,
        "conflicts_require_authoritative_source_recheck": True,
        "evidence_verified_requires_per_atom_realization": True,
        "closure_requires_per_atom_reconciliation_without_group_substitution": True,
        "resume_must_continue_from_incomplete_ledger_entries": True,
        "task_close_requires_realization_gate": True,
        "next_task_forbidden_before_current_task_closed": True,
        "primary_atomic_requirement_ids": [
            item["atomic_requirement_id"] for item in primary_atoms
        ],
        "related_atomic_requirement_ids": [
            item["atomic_requirement_id"] for item in related_atoms
        ],
        "required_understanding_fields": [
            "product_meaning",
            "behavior_boundaries",
            "implementation_scope",
            "verification_plan",
        ],
        "required_primary_realization_fields": [
            "implementation_evidence",
            "verification_evidence",
            "user_visible_result",
        ],
        "required_related_realization_fields": [
            "verification_evidence",
            "compatibility_or_defer_rationale",
        ],
    }


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def record(path: Path) -> dict[str, Any]:
    return {
        "path": rel(path),
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else None,
        "sha256": sha_file(path) if path.is_file() else None,
    }


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(
        (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
    )
    temp.replace(path)


def validate_version(value: str) -> str:
    if not VERSION_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid protocol version name: {value!r}")
    version_dir = (CONTEXT_ROOT / "versions" / value).resolve()
    if version_dir.parent != (CONTEXT_ROOT / "versions").resolve():
        raise ValueError(f"Protocol version escapes versions directory: {value!r}")
    return value


def verified_checkpoint_next_step(checkpoint: dict[str, Any]) -> str:
    checkpoint_state = str(checkpoint.get("state", "NOT_STARTED"))
    checkpoint_task = str(checkpoint.get("task", "F2-T01"))
    previous = checkpoint.get("previous_checkpoint")
    if isinstance(previous, dict):
        previous_next_step = previous.get("next_step")
        same_position = all(
            previous.get(field) == checkpoint.get(field)
            for field in ("phase", "task", "state")
        )
        if (
            previous.get("sources_unchanged") is True
            and same_position
            and isinstance(previous_next_step, str)
            and previous_next_step.startswith("PAUSED:")
        ):
            return previous_next_step
    if checkpoint_state == "NOT_STARTED":
        return (
            f"Load and verify the {checkpoint_task} task packet, then transition to "
            "CONTEXT_VERIFIED before editing code."
        )
    return (
        f"Resume {checkpoint_task} from the preserved {checkpoint_state} checkpoint; "
        "do not repeat earlier verified transitions."
    )


class Checks:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, check_id: str, passed: bool, detail: Any) -> None:
        self.items.append(
            {"id": check_id, "status": "PASS" if passed else "FAIL", "detail": detail}
        )

    @property
    def passed(self) -> bool:
        return all(item["status"] == "PASS" for item in self.items)

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [item for item in self.items if item["status"] == "FAIL"]


def parse_docx() -> dict[str, Any]:
    with zipfile.ZipFile(DOCX_PATH) as archive:
        document_bytes = archive.read("word/document.xml")
        rels_bytes = archive.read("word/_rels/document.xml.rels")
        document = ET.fromstring(document_bytes)
        rels = ET.fromstring(rels_bytes)
        relations = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in rels.findall(f"{{{PKG_REL_NS}}}Relationship")
        }
        body = document.find(f"{{{W_NS}}}body")
        if body is None:
            raise RuntimeError("Word body missing")
        paragraphs: list[dict[str, Any]] = []
        referenced: set[str] = set()
        for index, paragraph in enumerate(body.findall(f"{{{W_NS}}}p"), start=1):
            text = "".join(
                node.text or "" for node in paragraph.findall(f".//{{{W_NS}}}t")
            ).strip()
            media: list[str] = []
            for element in paragraph.iter():
                relation_id = element.attrib.get(f"{{{R_NS}}}embed") or element.attrib.get(
                    f"{{{R_NS}}}link"
                )
                target = relations.get(relation_id or "")
                if target and "media/" in target:
                    name = Path(target).name
                    media.append(name)
                    referenced.add(name)
            paragraphs.append(
                {
                    "paragraph": index,
                    "text": text,
                    "media": media,
                    "xml_sha256": sha_bytes(ET.tostring(paragraph, encoding="utf-8")),
                }
            )
        media_records = []
        for name in sorted(referenced):
            data = archive.read(f"word/media/{name}")
            media_records.append(
                {
                    "internal_path": f"word/media/{name}",
                    "filename": name,
                    "bytes": len(data),
                    "sha256": sha_bytes(data),
                }
            )
    return {
        "document_xml_sha256": sha_bytes(document_bytes),
        "relationships_sha256": sha_bytes(rels_bytes),
        "paragraphs": paragraphs,
        "media": media_records,
    }


def media_name(value: str) -> str:
    return re.sub(r"^\d+_", "", Path(value).name)


def paragraph_sig(item: dict[str, Any]) -> str:
    text = re.sub(r"\s+", "", str(item.get("text", ""))).lower()
    media = ",".join(sorted(media_name(value) for value in item.get("media", [])))
    return f"{text}|{media}"


def independent_mapping(legacy: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, Any]:
    from difflib import SequenceMatcher

    old = [paragraph_sig(item) for item in legacy]
    new = [paragraph_sig(item) for item in current]
    matcher = SequenceMatcher(a=old, b=new, autojunk=False)
    mapping: dict[int, int] = {}
    for old_start, new_start, length in matcher.get_matching_blocks():
        for offset in range(length):
            mapping[old_start + offset] = new_start + offset
    return {
        "legacy_count": len(legacy),
        "current_count": len(current),
        "mapping": [
            {
                "legacy_paragraph": old_index + 1,
                "current_paragraph": mapping[old_index] + 1,
                "signature_sha256": sha_bytes(old[old_index].encode("utf-8")),
            }
            for old_index in sorted(mapping)
        ],
        "inserted_current_paragraphs": [
            index + 1 for index in range(len(current)) if index not in set(mapping.values())
        ],
        "mapped": len(mapping),
    }


def parse_pdf() -> dict[str, Any]:
    pages = []
    for index, page in enumerate(PdfReader(str(PDF_PATH)).pages, start=1):
        text = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")
        pages.append({"page": index, "text": text, "text_sha256": sha_bytes(text.encode("utf-8"))})
    return {"page_count": len(pages), "pages": pages}


def strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)


def declared_paths(value: Any) -> list[str]:
    found: set[str] = set()
    for text in strings(value):
        for item in PATH_PATTERN.findall(text.replace("\\", "/")):
            found.add(item.rstrip(".,;:，。；："))
    return sorted(found)


def code_inventory() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    inventory: dict[str, dict[str, Any]] = {}
    texts: dict[str, str] = {}
    for root_name in CODE_ROOTS:
        base = ROOT / root_name
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in CODE_SUFFIXES:
                continue
            relative_path = rel(path)
            inventory[relative_path] = record(path)
            texts[relative_path] = path.read_text(encoding="utf-8", errors="replace")
    return inventory, texts


def resolve_py(current: str, module: str | None, level: int) -> list[str]:
    current_path = Path(current)
    candidates: list[Path] = []
    if level:
        base = current_path.parent
        for _ in range(max(level - 1, 0)):
            base = base.parent
        if module:
            base = base / Path(module.replace(".", "/"))
        candidates.extend([base.with_suffix(".py"), base / "__init__.py"])
    elif module:
        base = Path(module.replace(".", "/"))
        candidates.extend([base.with_suffix(".py"), base / "__init__.py"])
    return [item.as_posix() for item in candidates if (ROOT / item).is_file()]


def resolve_js(current: str, specifier: str) -> list[str]:
    if not specifier.startswith("."):
        return []
    base = (Path(current).parent / specifier).as_posix()
    candidates = [
        Path(base),
        Path(base + ".js"),
        Path(base + ".ts"),
        Path(base + ".vue"),
        Path(base + ".css"),
        Path(base) / "index.js",
        Path(base) / "index.ts",
    ]
    return [item.as_posix() for item in candidates if (ROOT / item).is_file()]


def import_graph(texts: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    graph: dict[str, set[str]] = defaultdict(set)
    reverse: dict[str, set[str]] = defaultdict(set)
    for path, text in texts.items():
        suffix = Path(path).suffix.lower()
        targets: set[str] = set()
        if suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for item in node.names:
                            targets.update(resolve_py(path, item.name, 0))
                    elif isinstance(node, ast.ImportFrom):
                        targets.update(resolve_py(path, node.module, node.level))
        elif suffix in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue"}:
            for specifier in JS_IMPORT_PATTERN.findall(text):
                targets.update(resolve_js(path, specifier))
        graph[path].update(targets)
        for target in targets:
            reverse[target].add(path)
    return graph, reverse


def forward_closure(seeds: Iterable[str], graph: dict[str, set[str]]) -> set[str]:
    result: set[str] = set()
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        if current in result:
            continue
        result.add(current)
        queue.extend(item for item in graph.get(current, set()) if item not in result)
    return result


def reverse_closure(seeds: Iterable[str], reverse: dict[str, set[str]]) -> set[str]:
    result: set[str] = set()
    queue = deque((seed, 0) for seed in seeds)
    while queue:
        current, depth = queue.popleft()
        if depth >= 2:
            continue
        for item in reverse.get(current, set()):
            if item in result:
                continue
            result.add(item)
            queue.append((item, depth + 1))
    return result


def route_refs(task: dict[str, Any]) -> list[str]:
    found: set[str] = set()
    for text in strings(task.get("routes", [])):
        found.update(ROUTE_PATTERN.findall(text))
    for atom in task.get("atomic_contracts", []):
        found.update(ROUTE_PATTERN.findall(str(atom.get("target_routes", ""))))
    return sorted(found)


def expected_code_closure(
    task: dict[str, Any],
    inventory: dict[str, dict[str, Any]],
    texts: dict[str, str],
    graph: dict[str, set[str]],
    reverse: dict[str, set[str]],
    code_map: dict[str, Any],
) -> dict[str, Any]:
    declared = declared_paths(task)
    direct = sorted(item for item in declared if item in inventory)
    missing = sorted(item for item in declared if item not in inventory)
    dependencies = forward_closure(direct, graph)
    callers = reverse_closure(direct, reverse)
    refs = route_refs(task)
    terms = {task["id"], *refs}
    for item in direct:
        terms.update({item, Path(item).stem})
    tests = sorted(
        path
        for path, text in texts.items()
        if path.startswith("tests/") and any(term and term in text for term in terms)
    )
    closure = sorted(set(direct) | dependencies | callers | set(tests))
    basenames = {Path(item).name for item in closure}
    current = code_map["current"]
    endpoints = [
        item
        for item in current.get("resolved_backend_routes", [])
        if Path(str(item.get("file", ""))).name in basenames
        or any(token and token in str(item.get("final_path", "")) for token in refs)
    ]
    models = [
        item
        for item in current.get("orm_models", [])
        if rel(ROOT / str(item.get("file", ""))) in closure
        or Path(str(item.get("file", ""))).name in basenames
    ]
    frontend_apis = [item for item in current.get("frontend_apis", []) if str(item.get("file", "")) in closure]
    broad = any("course-scoped" in text for text in strings(task.get("routes", [])))
    view_names = {Path(item).name for item in closure if item.endswith(".vue")}
    vue_routes = [
        item
        for item in current.get("vue_routes", [])
        if (broad and item.get("course_scoped"))
        or Path(str(item.get("view", ""))).name in view_names
        or any(token == item.get("path") or token.rstrip("/") == str(item.get("path", "")).rstrip("/") for token in refs)
    ]
    return {
        "declared_paths": declared,
        "direct_existing_files": [inventory[item] for item in direct],
        "declared_new_or_missing_files": missing,
        "dependency_files": [inventory[item] for item in sorted(dependencies) if item in inventory],
        "caller_files": [inventory[item] for item in sorted(callers) if item in inventory],
        "test_files": [inventory[item] for item in tests if item in inventory],
        "all_closure_files": [inventory[item] for item in closure if item in inventory],
        "route_references": refs,
        "vue_routes": vue_routes,
        "frontend_api_modules": frontend_apis,
        "backend_endpoints": endpoints,
        "orm_models": models,
    }


def expected_word_context(
    task: dict[str, Any],
    primary: list[dict[str, Any]],
    related: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    image_units: list[dict[str, Any]],
) -> tuple[list[int], list[int], list[int]]:
    selected = set(int(value) for value in task.get("source_word_paragraphs", []))
    for atom in primary + related:
        selected.update(int(value) for value in atom.get("word_paragraphs", []))
    for group in task.get("source_group_contracts", []):
        selected.update(int(value) for value in group.get("paragraphs", []))
    image_ids = set(int(value) for value in task.get("source_images", []))
    for atom in primary + related:
        image_ids.update(int(value) for value in atom.get("source_images", []))
    for group in task.get("source_group_contracts", []):
        image_ids.update(int(value) for value in group.get("images", []))
    by_image = {int(item["image"]): item for item in image_units}
    for image_id in image_ids:
        item = by_image.get(image_id)
        if item:
            selected.update(int(value) for value in item.get("source_context_paragraphs", []))
            selected.update(int(value) for value in item.get("semantic_anchor_paragraphs", []))
            selected.update(int(value) for value in item.get("boundary_context_paragraphs", []))
    nonempty = [int(item["paragraph"]) for item in paragraphs if item["text"].strip()]
    expanded = set(selected)
    for paragraph in list(selected):
        previous = next((value for value in reversed(nonempty) if value < paragraph), None)
        following = next((value for value in nonempty if value > paragraph), None)
        if previous:
            expanded.add(previous)
        if following:
            expanded.add(following)
    return sorted(selected), sorted(expanded), sorted(image_ids)


def expected_machine_fact_references(
    task: dict[str, Any], code_closure: dict[str, Any]
) -> dict[str, Any]:
    sources = {
        "dual_version_code_map": DUAL_CODE_MAP_PATH,
        "fusion_scope_matrix": SCOPE_MATRIX_PATH,
        "current_route_spec": CURRENT_ROUTE_PATH,
        "target_route_spec": TARGET_ROUTE_PATH,
        "target_global_contracts": TARGET_GLOBAL_PATH,
    }
    return {
        "schema_version": "context-recovery.machine-fact-references.v1",
        "source_records": {name: record(path) for name, path in sources.items()},
        "task_projection": {
            "task_id": task["id"],
            "declared_source_groups": task.get("source_groups", []),
            "declared_routes": code_closure.get("route_references", []),
            "resolved_frontend_routes": [
                item.get("path") for item in code_closure.get("vue_routes", [])
            ],
            "resolved_backend_endpoints": [
                f"{item.get('method')} {item.get('path')}"
                for item in code_closure.get("backend_endpoints", [])
            ],
            "resolved_orm_models": [
                item.get("name") or item.get("class")
                for item in code_closure.get("orm_models", [])
            ],
            "closure_file_count": len(code_closure.get("all_closure_files", [])),
        },
        "resolution_rule": (
            "The complete global documents are content-addressed by path, byte count and SHA-256. "
            "The task packet embeds the complete task-specific code closure; load a global document "
            "only when its task projection or a conflict requires wider evidence."
        ),
    }


def reconstruct(descriptor_path: Path, checks: Checks) -> dict[str, Any] | None:
    try:
        descriptor = load(descriptor_path)
    except Exception as exc:
        checks.add(f"packet:{descriptor_path.name}:descriptor", False, str(exc))
        return None
    chunks: list[bytes] = []
    chunk_ok = True
    for item in descriptor.get("chunks", []):
        path = ROOT / item["path"]
        if not path.is_file():
            chunk_ok = False
            continue
        data = path.read_bytes()
        if len(data) != item["bytes"] or sha_bytes(data) != item["sha256"]:
            chunk_ok = False
        chunks.append(data)
    combined = b"".join(chunks)
    expected_eof = [item for item in descriptor.get("chunks", []) if item.get("eof")]
    valid = (
        chunk_ok
        and len(chunks) == descriptor.get("chunk_count")
        and len(expected_eof) == 1
        and expected_eof[0].get("index") == descriptor.get("chunk_count")
        and len(combined) == descriptor.get("total_bytes")
        and sha_bytes(combined) == descriptor.get("payload_sha256")
    )
    eof_path = ROOT / descriptor.get("eof_record", {}).get("path", "")
    eof_valid = eof_path.is_file() and sha_file(eof_path) == descriptor.get("eof_record", {}).get("sha256")
    if eof_valid:
        eof = load(eof_path)
        eof_valid = (
            eof.get("eof") is True
            and eof.get("chunk_count") == descriptor.get("chunk_count")
            and eof.get("total_bytes") == descriptor.get("total_bytes")
            and eof.get("payload_sha256") == descriptor.get("payload_sha256")
        )
    checks.add(
        f"packet:{descriptor_path.stem}:chunks",
        valid and eof_valid,
        {
            "chunk_count": len(chunks),
            "expected": descriptor.get("chunk_count"),
            "bytes": len(combined),
            "eof": eof_valid,
        },
    )
    if not valid or not eof_valid:
        return None
    try:
        return json.loads(combined.decode("utf-8"))
    except Exception as exc:
        checks.add(f"packet:{descriptor_path.stem}:json", False, str(exc))
        return None


def safe_replace_tree(source: Path, destination: Path) -> None:
    root = CONTEXT_ROOT.resolve()
    resolved = destination.resolve()
    if resolved.parent != root:
        raise RuntimeError(f"Refusing to replace directory outside context root: {resolved}")
    source_resolved = source.resolve()
    versions_root = (CONTEXT_ROOT / "versions").resolve()
    if versions_root not in source_resolved.parents:
        raise RuntimeError(f"Refusing to activate source outside immutable versions: {source_resolved}")

    token = f"{os.getpid()}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    staging = CONTEXT_ROOT / f".{destination.name}.staging-{token}"
    backup = CONTEXT_ROOT / f".{destination.name}.backup-{token}"
    shutil.copytree(source, staging)
    had_destination = destination.exists()

    def replace_with_retry(current: Path, target: Path) -> None:
        attempts = 5 if os.name == "nt" else 1
        for attempt in range(attempts):
            try:
                current.replace(target)
                return
            except PermissionError:
                if attempt + 1 == attempts:
                    raise
                time.sleep(0.1 * (attempt + 1))

    try:
        if had_destination:
            replace_with_retry(destination, backup)
        replace_with_retry(staging, destination)
    except Exception:
        if destination.exists() and not had_destination:
            shutil.rmtree(destination)
        if backup.exists() and not destination.exists():
            replace_with_retry(backup, destination)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    if backup.exists():
        shutil.rmtree(backup)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        version = validate_version(args.version)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    version_dir = CONTEXT_ROOT / "versions" / version
    if not version_dir.is_dir():
        raise SystemExit(f"Unknown version: {version_dir}")

    checks = Checks()
    authority_path = version_dir / "authority_manifest.json"
    authority = load(authority_path)
    checks.add("protocol-version", authority.get("protocol_version") == args.version, authority.get("protocol_version"))
    checks.add("building-state", authority.get("status") == "BUILDING", authority.get("status"))
    activation_path = version_dir / "protocol_activation.json"
    activation_before = load(activation_path)
    checks.add(
        "activation-building-state",
        activation_before.get("status") == "BUILDING",
        activation_before.get("status"),
    )

    product = load(PRODUCT_JSON_PATH)
    plan = load(PLAN_JSON_PATH)
    audit = load(AUDIT_JSON_PATH)
    legacy = load(LEGACY_MANIFEST_PATH)
    code_map = load(DUAL_CODE_MAP_PATH)
    scope_matrix = load(SCOPE_MATRIX_PATH)
    protection = load(PROTECTION_PATH)
    current_routes = load(CURRENT_ROUTE_PATH)
    target_routes = load(TARGET_ROUTE_PATH)
    target_globals = load(TARGET_GLOBAL_PATH)
    word = parse_docx()
    mapping = independent_mapping(legacy.get("paragraphs", []), word["paragraphs"])
    pdf = parse_pdf()
    inventory, texts = code_inventory()
    graph, reverse = import_graph(texts)

    actual_source_records = {
        name: record(path) for name, path in PINNED_AUTHORITY_PATHS.items()
    }
    manifest_sources = authority.get("source_files", {})
    checks.add("authority-source-set", set(manifest_sources) == set(actual_source_records), sorted(manifest_sources))
    for name, actual in actual_source_records.items():
        checks.add(
            f"source-hash:{name}",
            manifest_sources.get(name) == actual,
            {"expected": actual, "manifest": manifest_sources.get(name)},
        )
    actual_operational_records = {
        name: record(path) for name, path in OPERATIONAL_PATHS.items()
    }
    manifest_operational = authority.get("operational_files", {})
    checks.add(
        "operational-source-set",
        set(manifest_operational) == set(actual_operational_records),
        sorted(manifest_operational),
    )
    for name, actual in actual_operational_records.items():
        checks.add(
            f"operational-source-build-snapshot:{name}",
            manifest_operational.get(name) == actual,
            {"expected": actual, "manifest": manifest_operational.get(name)},
        )

    expected_counts = {
        "word_paragraphs": len(word["paragraphs"]),
        "word_nonempty_paragraphs": sum(bool(item["text"].strip()) for item in word["paragraphs"]),
        "legacy_word_manifest_paragraphs": len(legacy.get("paragraphs", [])),
        "images": len(audit.get("image_text_units", [])),
        "product_sections": len(product.get("sections", [])),
        "target_routes": len(product.get("routes", [])),
        "atomic_requirements": len(audit.get("atomic_requirements", [])),
        "phases": len(plan.get("phases", [])),
        "tasks": len(plan.get("tasks", [])),
        "current_frontend_routes": len(code_map["current"].get("vue_routes", [])),
        "current_backend_endpoints": len(code_map["current"].get("resolved_backend_routes", [])),
        "current_orm_models": len(code_map["current"].get("orm_models", [])),
        "code_inventory_files": len(inventory),
    }
    checks.add("derived-counts", authority.get("derived_counts") == expected_counts, expected_counts)
    checks.add("word-paragraphs", authority.get("word", {}).get("paragraphs") == word["paragraphs"], {"count": len(word["paragraphs"])})
    checks.add("word-61-to-73-mapping", authority.get("word", {}).get("paragraph_mapping", {}).get("mapping") == mapping["mapping"] and mapping["mapped"] == len(legacy.get("paragraphs", [])), mapping)
    checks.add("word-inserted-blanks", authority.get("word", {}).get("paragraph_mapping", {}).get("inserted_current_paragraphs") == mapping["inserted_current_paragraphs"], mapping["inserted_current_paragraphs"])
    checks.add("competition-pages", authority.get("competition") == pdf, {"pages": pdf["page_count"]})
    checks.add("code-inventory", authority.get("code_inventory") == [inventory[path] for path in sorted(inventory)], {"files": len(inventory)})

    image_units = audit.get("image_text_units", [])
    image_by_id = {int(item["image"]): item for item in image_units}
    docx_media = {item["filename"]: item for item in word["media"]}
    expected_images = []
    for item in image_units:
        copied = IMAGE_DIR / item["filename"]
        expected_images.append(
            {
                "image": int(item["image"]),
                "filename": item["filename"],
                "copied_file": record(copied),
                "docx_media": docx_media.get(media_name(item["filename"])),
                "paragraph": int(item["paragraph"]),
                "semantic_anchor_paragraphs": item.get("semantic_anchor_paragraphs", []),
                "boundary_context_paragraphs": item.get("boundary_context_paragraphs", []),
            }
        )
    checks.add("image-records", authority.get("images") == expected_images, {"images": len(expected_images)})

    product_sections = {item["id"]: item for item in product.get("sections", [])}
    atoms = audit.get("atomic_requirements", [])
    tasks = {item["id"]: item for item in plan.get("tasks", [])}
    task_descriptor_paths = sorted((version_dir / "task_packets").glob("F*-T*.json"))
    checks.add("task-descriptor-count", len(task_descriptor_paths) == len(tasks), {"actual": len(task_descriptor_paths), "expected": len(tasks)})
    checks.add("task-descriptor-set", {path.stem for path in task_descriptor_paths} == set(tasks), sorted(path.stem for path in task_descriptor_paths))

    packet_summaries: dict[str, dict[str, Any]] = {}
    for descriptor_path in task_descriptor_paths:
        task_id = descriptor_path.stem
        payload = reconstruct(descriptor_path, checks)
        if payload is None or task_id not in tasks:
            continue
        task = tasks[task_id]
        primary = [item for item in atoms if item.get("primary_implementation_task_id") == task_id]
        related = [item for item in atoms if task_id in item.get("implementation_task_ids", []) and item.get("primary_implementation_task_id") != task_id]
        checks.add(f"task:{task_id}:exact-object", payload.get("exact_task_object") == task, task.get("title"))
        checks.add(f"task:{task_id}:primary-atoms", payload.get("primary_atomic_requirements") == primary, [item["atomic_requirement_id"] for item in primary])
        checks.add(f"task:{task_id}:related-atoms", payload.get("related_atomic_requirements") == related, len(related))
        expected_atomic_contract = task_atomic_execution_contract(task_id, primary, related)
        checks.add(
            f"task:{task_id}:atomic-execution-contract",
            payload.get("task_atomic_execution_contract") == expected_atomic_contract,
            {
                "primary": len(primary),
                "related": len(related),
                "task_local": True,
            },
        )
        section_ids: set[str] = set()
        for atom in primary + related:
            section_ids.update(atom.get("product_section_ids", []))
        for contract in task.get("atomic_contracts", []):
            section_ids.update(contract.get("product_section_ids", []))
        expected_sections = [product_sections[item] for item in sorted(section_ids) if item in product_sections]
        checks.add(f"task:{task_id}:product-sections", payload.get("product_responsibility_sections") == expected_sections, sorted(section_ids))
        selected, expanded, image_ids = expected_word_context(task, primary, related, word["paragraphs"], image_units)
        word_context = payload.get("word_context", {})
        paragraph_index = {item["paragraph"]: item for item in word["paragraphs"]}
        expected_paragraphs = [paragraph_index[item] for item in expanded if item in paragraph_index]
        checks.add(f"task:{task_id}:word-context", word_context.get("selected_paragraphs") == selected and word_context.get("selected_with_nonempty_neighbors") == expanded and word_context.get("paragraphs") == expected_paragraphs, {"selected": selected, "expanded": expanded})
        checks.add(f"task:{task_id}:mapping", payload.get("legacy_to_current_paragraph_mapping", {}).get("mapping") == mapping["mapping"], {"rows": len(mapping["mapping"])})
        packet_image_ids = [int(item["image_text_unit"]["image"]) for item in payload.get("images", [])]
        images_valid = packet_image_ids == image_ids
        for packed in payload.get("images", []):
            unit = packed.get("image_text_unit", {})
            expected_unit = image_by_id.get(int(unit.get("image", -1)))
            copied_path = IMAGE_DIR / str(unit.get("filename", ""))
            if unit != expected_unit or not copied_path.is_file() or packed.get("file_record", {}).get("copied_file") != record(copied_path):
                images_valid = False
        checks.add(f"task:{task_id}:images", images_valid, image_ids)
        shared = payload.get("shared_protocols", {})
        checks.add(f"task:{task_id}:goal-contract", shared.get("goal_contract", {}).get("text") == GOAL_PATH.read_text(encoding="utf-8") and shared.get("goal_contract", {}).get("sha256") == sha_file(GOAL_PATH), shared.get("goal_contract", {}).get("sha256"))
        checks.add(f"task:{task_id}:constitution", shared.get("constitution", {}).get("text") == CONSTITUTION_PATH.read_text(encoding="utf-8") and shared.get("constitution", {}).get("sha256") == sha_file(CONSTITUTION_PATH), shared.get("constitution", {}).get("sha256"))
        checks.add(f"task:{task_id}:competition", payload.get("competition_clauses", {}).get("pages") == pdf["pages"], {"pages": pdf["page_count"]})
        expected_closure = expected_code_closure(task, inventory, texts, graph, reverse, code_map)
        actual_closure = payload.get("code_impact_closure", {})
        closure_keys = set(expected_closure)
        checks.add(f"task:{task_id}:code-closure", all(actual_closure.get(key) == expected_closure[key] for key in closure_keys), {"files": len(expected_closure["all_closure_files"]), "tests": len(expected_closure["test_files"])})
        facts = payload.get("supporting_machine_facts", {})
        checks.add(
            f"task:{task_id}:machine-facts",
            facts == expected_machine_fact_references(task, expected_closure),
            {
                "source_records": sorted(facts.get("source_records", {})),
                "closure_files": len(expected_closure["all_closure_files"]),
            },
        )
        descriptor = load(descriptor_path)
        packet_summaries[task_id] = {
            "descriptor": record(descriptor_path),
            "payload_sha256": descriptor.get("payload_sha256"),
            "chunk_count": descriptor.get("chunk_count"),
            "total_bytes": descriptor.get("total_bytes"),
        }

    phase_paths = sorted((version_dir / "phase_packets").glob("F[0-9]*.json"))
    phase_paths = [path for path in phase_paths if path.name != "F0-F10.json"]
    phases = {item["id"]: item for item in plan.get("phases", [])}
    checks.add("phase-descriptor-count", len(phase_paths) == len(phases), {"actual": len(phase_paths), "expected": len(phases)})
    for path in phase_paths:
        phase_id = path.stem
        payload = reconstruct(path, checks)
        if payload is None or phase_id not in phases:
            continue
        checks.add(f"phase:{phase_id}:exact-object", payload.get("exact_phase_object") == phases[phase_id], phases[phase_id].get("title"))
        expected_task_ids = [item["id"] for item in plan.get("tasks", []) if item["id"].startswith(phase_id + "-")]
        actual_task_ids = [item.get("task_id") for item in payload.get("task_packets", [])]
        checks.add(f"phase:{phase_id}:task-set", actual_task_ids == expected_task_ids, actual_task_ids)
        linkage_ok = all(item.get("payload_sha256") == packet_summaries.get(item.get("task_id"), {}).get("payload_sha256") for item in payload.get("task_packets", []))
        checks.add(f"phase:{phase_id}:task-linkage", linkage_ok, {"tasks": len(actual_task_ids)})
    phase_index_path = version_dir / "phase_packets" / "F0-F10.json"
    phase_index = load(phase_index_path)
    checks.add("phase-index", {item.get("phase_id") for item in phase_index.get("phases", [])} == set(phases), {"phases": len(phase_index.get("phases", []))})

    report = {
        "schema_version": "context-recovery.verification.v1",
        "protocol_version": args.version,
        "verifier": rel(Path(__file__)),
        "independent": True,
        "verified_at": now(),
        "status": "PASS" if checks.passed else "FAIL",
        "check_count": len(checks.items),
        "failure_count": len(checks.failures),
        "checks": checks.items,
    }
    report_path = version_dir / "verification_report.json"
    dump(report_path, report)

    if not checks.passed:
        activation_path = version_dir / "protocol_activation.json"
        activation = load(activation_path)
        activation.update({"status": "FAILED", "verification_report": record(report_path)})
        dump(activation_path, activation)
        print(json.dumps({"status": "FAIL", "version": args.version, "failures": checks.failures[:20], "report": rel(report_path)}, ensure_ascii=False, indent=2))
        return 1

    authority["status"] = "VERIFIED"
    authority["verified_at"] = now()
    dump(authority_path, authority)
    checkpoint_path = version_dir / "current_checkpoint.json"
    checkpoint = load(checkpoint_path)
    checkpoint_state = checkpoint.get("state", "NOT_STARTED")
    checkpoint_task = checkpoint.get("task", "F2-T01")
    next_step = verified_checkpoint_next_step(checkpoint)
    checkpoint.update(
        {
            "gate": "CONTEXT_RECOVERY_VERIFIED",
            "authority_manifest_sha256": sha_file(authority_path),
            "known_limitations": [
                item
                for item in checkpoint.get("known_limitations", [])
                if item != "Protocol version is still BUILDING and not active."
            ],
            "next_step": next_step,
            "protocol_verified_at": now(),
            "snapshot_sequence": int(checkpoint.get("snapshot_sequence", 0)) + 1,
        }
    )
    dump(checkpoint_path, checkpoint)
    dump(
        version_dir
        / "checkpoint_snapshots"
        / f"{checkpoint['snapshot_sequence']:04d}_PROTOCOL_VERIFIED_{checkpoint_task}_{checkpoint_state}.json",
        checkpoint,
    )

    report["authority_manifest_sha256"] = sha_file(authority_path)
    report["checkpoint_sha256"] = sha_file(checkpoint_path)
    dump(report_path, report)
    activation_path = version_dir / "protocol_activation.json"
    activation = load(activation_path)
    activation.update(
        {
            "status": "VERIFIED",
            "authority_manifest": record(authority_path),
            "verification_report": record(report_path),
            "activated_at": now(),
        }
    )
    dump(activation_path, activation)

    safe_replace_tree(version_dir / "phase_packets", CONTEXT_ROOT / "phase_packets")
    safe_replace_tree(version_dir / "task_packets", CONTEXT_ROOT / "task_packets")
    safe_replace_tree(version_dir / "checkpoint_snapshots", CONTEXT_ROOT / "checkpoint_snapshots")
    for name in ("authority_manifest.json", "current_checkpoint.json", "verification_report.json", "protocol_activation.json"):
        shutil.copy2(version_dir / name, CONTEXT_ROOT / name)

    active = {
        "schema_version": "context-recovery.active.v1",
        "status": "VERIFIED",
        "active_version": args.version,
        "version_path": rel(version_dir),
        "goal_contract": record(GOAL_PATH),
        "authority_manifest": record(CONTEXT_ROOT / "authority_manifest.json"),
        "current_checkpoint": record(CONTEXT_ROOT / "current_checkpoint.json"),
        "verification_report": record(CONTEXT_ROOT / "verification_report.json"),
        "protocol_activation": record(CONTEXT_ROOT / "protocol_activation.json"),
        "phase_index": record(CONTEXT_ROOT / "phase_packets" / "F0-F10.json"),
        "task_packet_count": len(tasks),
        "phase_packet_count": len(phases),
        "activated_at": now(),
        "activation_rule": "active_manifest.json is written last and only after independent verification passes.",
    }
    dump(CONTEXT_ROOT / "active_manifest.json", active)

    print(
        json.dumps(
            {
                "status": "VERIFIED",
                "version": args.version,
                "checks": len(checks.items),
                "failures": 0,
                "report": rel(report_path),
                "active_manifest": rel(CONTEXT_ROOT / "active_manifest.json"),
                "task_packets": len(tasks),
                "phase_packets": len(phases),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
