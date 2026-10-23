#!/usr/bin/env python3
"""Build versioned, lossless context-recovery packets for the fusion refactor."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
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
STATUS_PATH = OUTPUT / "00_唯一执行状态.md"
CONSTITUTION_PATH = OUTPUT / "06_用户意图与产品宪法.md"
CODE_MAP_MD_PATH = OUTPUT / "07_双版本代码地图与功能清单.md"
ROUTE_MATRIX_PATH = OUTPUT / "08_用户需求追踪与路由迁移矩阵.md"
PRODUCT_MD_PATH = OUTPUT / "09_EduMatrix最终产品方案.md"
PRODUCT_JSON_PATH = OUTPUT / "09_EduMatrix最终产品方案.json"
PLAN_MD_PATH = OUTPUT / "10_原版融合重构详细实施方案.md"
PLAN_JSON_PATH = OUTPUT / "10_原版融合重构详细实施方案.json"
RECOVERY_INDEX_PATH = OUTPUT / "11_上下文恢复与实施索引.md"
AUDIT_MD_PATH = OUTPUT / "13_改进想法逐句逐图实质落实审计.md"
AUDIT_JSON_PATH = OUTPUT / "13_改进想法逐句逐图实质落实审计.json"
WORKLOG_PATH = OUTPUT / "02_融合重构_WORKLOG.md"
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

BOOTSTRAP_READ_ORDER = [
    "evidence/context_recovery/goal_contract.md",
    "00_唯一执行状态.md",
    "06_用户意图与产品宪法.md",
    "11_上下文恢复与实施索引.md",
    "02_融合重构_WORKLOG.md",
    "10_原版融合重构详细实施方案.md",
    "09_EduMatrix最终产品方案.md",
    "13_改进想法逐句逐图实质落实审计.md",
]

PINNED_AUTHORITY_SOURCES = {
    "goal_contract": GOAL_PATH,
    "constitution": CONSTITUTION_PATH,
    "code_map_md": CODE_MAP_MD_PATH,
    "route_matrix": ROUTE_MATRIX_PATH,
    "product_md": PRODUCT_MD_PATH,
    "product_json": PRODUCT_JSON_PATH,
    "implementation_md": PLAN_MD_PATH,
    "implementation_json": PLAN_JSON_PATH,
    "audit_md": AUDIT_MD_PATH,
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

OPERATIONAL_SOURCES = {
    "status": STATUS_PATH,
    "recovery_index": RECOVERY_INDEX_PATH,
    "worklog": WORKLOG_PATH,
}

AUTHORITY_SOURCES = {**PINNED_AUTHORITY_SOURCES, **OPERATIONAL_SOURCES}
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,95}$")
GOAL_ID_PATTERN = re.compile(r"执行目标[：:]\s*([A-Z0-9-]+)")
ALLOWED_GOAL_HANDOFFS = {
    (
        "EDUMATRIX-F0-F10-CONTEXT-SAFE-FUSION-REFACTOR",
        "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
    ): ("F5", "F5-T01", "NOT_STARTED"),
    (
        "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION",
    ): ("F9", "F9-T01", "NOT_STARTED"),
}
CHECKPOINT_STATES = (
    "NOT_STARTED",
    "CONTEXT_VERIFIED",
    "EDITING",
    "CODE_COMPLETE",
    "TESTED",
    "EVIDENCE_VERIFIED",
    "CLOSED",
)


def task_atomic_execution_contract(
    task_id: str,
    primary_atoms: list[dict[str, Any]],
    related_atoms: list[dict[str, Any]],
) -> dict[str, Any]:
    """Embed the non-transferable per-task atomic gate in every task packet."""
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


def utc_stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def file_record(path: Path) -> dict[str, Any]:
    exists = path.is_file()
    return {
        "path": relative(path),
        "exists": exists,
        "bytes": path.stat().st_size if exists else None,
        "sha256": sha256_file(path) if exists else None,
    }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(canonical_text(value).encode("utf-8"))
    temp.replace(path)


def validate_version(value: str) -> str:
    if not VERSION_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid protocol version name: {value!r}")
    version_dir = (CONTEXT_ROOT / "versions" / value).resolve()
    if version_dir.parent != (CONTEXT_ROOT / "versions").resolve():
        raise ValueError(f"Protocol version escapes versions directory: {value!r}")
    return value


def read_goal_id() -> str:
    match = GOAL_ID_PATTERN.search(GOAL_PATH.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError("Active goal contract does not declare an execution goal ID")
    return match.group(1)


def load_active_checkpoint_for_rebuild(
    task_ids: set[str], source_records: dict[str, dict[str, Any]], goal_id: str
) -> tuple[dict[str, Any] | None, bool]:
    """Load the live checkpoint without trusting an immutable version's initial state."""
    active_path = CONTEXT_ROOT / "active_manifest.json"
    if not active_path.is_file():
        return None, False
    active = read_json(active_path)
    if active.get("status") != "VERIFIED":
        return None, False
    checkpoint_record = active.get("current_checkpoint")
    if not isinstance(checkpoint_record, dict):
        raise RuntimeError("Active manifest has no live current_checkpoint record")
    checkpoint_path = (ROOT / str(checkpoint_record.get("path", ""))).resolve()
    context_root = CONTEXT_ROOT.resolve()
    if checkpoint_path != context_root and context_root not in checkpoint_path.parents:
        raise RuntimeError("Active checkpoint path escapes context_recovery")
    actual_record = file_record(checkpoint_path)
    if actual_record != checkpoint_record:
        raise RuntimeError(
            "Active checkpoint record does not match the live checkpoint; repair the "
            "active record instead of silently resetting progress"
        )
    checkpoint = read_json(checkpoint_path)
    checkpoint_goal_id = str(checkpoint.get("goal_id", ""))
    if checkpoint_goal_id != goal_id:
        required_position = ALLOWED_GOAL_HANDOFFS.get((checkpoint_goal_id, goal_id))
        actual_position = (
            checkpoint.get("phase"),
            checkpoint.get("task"),
            checkpoint.get("state"),
        )
        if required_position != actual_position:
            raise RuntimeError("Active checkpoint belongs to a different goal")
    if checkpoint.get("protocol_version") != active.get("active_version"):
        raise RuntimeError("Active checkpoint protocol version disagrees with active_manifest")
    if checkpoint.get("task") not in task_ids:
        raise RuntimeError(f"Active checkpoint task is absent from the new plan: {checkpoint.get('task')}")
    if checkpoint.get("state") not in CHECKPOINT_STATES:
        raise RuntimeError(f"Invalid active checkpoint state: {checkpoint.get('state')}")
    old_hashes = checkpoint.get("source_hashes", {})
    sources_unchanged = all(
        old_hashes.get(name) == record.get("sha256")
        for name, record in source_records.items()
    )
    return checkpoint, sources_unchanged


def copy_checkpoint_history(destination: Path) -> int:
    """Copy existing live snapshots into a new immutable protocol version."""
    source = CONTEXT_ROOT / "checkpoint_snapshots"
    destination.mkdir(parents=True, exist_ok=True)
    highest = 0
    if not source.is_dir():
        return highest
    for path in sorted(source.glob("*.json")):
        target = destination / path.name
        if not target.exists():
            shutil.copy2(path, target)
        match = re.match(r"^(\d+)_", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest


def split_text_by_bytes(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for char in text:
        encoded_size = len(char.encode("utf-8"))
        if current and size + encoded_size > limit:
            chunks.append("".join(current))
            current = []
            size = 0
        current.append(char)
        size += encoded_size
    if current:
        chunks.append("".join(current))
    return chunks or [""]


def write_chunked_packet(
    descriptor_path: Path,
    payload: dict[str, Any],
    chunk_bytes: int,
) -> dict[str, Any]:
    payload_text = canonical_text(payload)
    payload_bytes = payload_text.encode("utf-8")
    chunks = split_text_by_bytes(payload_text, chunk_bytes)
    chunk_dir = descriptor_path.with_suffix("")
    chunk_dir.mkdir(parents=True, exist_ok=False)
    chunk_records: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_path = chunk_dir / f"part-{index:04d}.jsonfrag"
        data = chunk.encode("utf-8")
        # Write the exact bytes used for size and hash calculations. Text-mode writes
        # translate LF to CRLF on Windows and would invalidate every packet hash.
        chunk_path.write_bytes(data)
        chunk_records.append(
            {
                "index": index,
                "path": relative(chunk_path),
                "bytes": len(data),
                "characters": len(chunk),
                "sha256": sha256_bytes(data),
                "eof": index == len(chunks),
            }
        )
    eof_path = chunk_dir / "EOF.json"
    eof_record = {
        "packet_id": payload["packet_id"],
        "chunk_count": len(chunks),
        "total_bytes": len(payload_bytes),
        "payload_sha256": sha256_bytes(payload_bytes),
        "eof": True,
    }
    atomic_write_json(eof_path, eof_record)
    descriptor = {
        "schema_version": "context-recovery.packet-descriptor.v1",
        "packet_id": payload["packet_id"],
        "packet_type": payload["packet_type"],
        "protocol_version": payload["protocol_version"],
        "payload_format": "utf-8-json-concatenated-chunks",
        "chunk_count": len(chunks),
        "total_bytes": len(payload_bytes),
        "payload_sha256": sha256_bytes(payload_bytes),
        "chunks": chunk_records,
        "eof_record": {
            "path": relative(eof_path),
            "sha256": sha256_file(eof_path),
        },
    }
    atomic_write_json(descriptor_path, descriptor)
    descriptor["descriptor"] = file_record(descriptor_path)
    return descriptor


def normalize_media_name(value: str) -> str:
    return re.sub(r"^\d+_", "", Path(value).name)


def extract_docx(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        document_bytes = archive.read("word/document.xml")
        rels_bytes = archive.read("word/_rels/document.xml.rels")
        document = ET.fromstring(document_bytes)
        rels = ET.fromstring(rels_bytes)
        relationships = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in rels.findall(f"{{{PKG_REL_NS}}}Relationship")
        }
        body = document.find(f"{{{W_NS}}}body")
        if body is None:
            raise RuntimeError("Word document has no body")
        paragraphs: list[dict[str, Any]] = []
        referenced_media: set[str] = set()
        for index, paragraph in enumerate(body.findall(f"{{{W_NS}}}p"), start=1):
            text = "".join(
                node.text or "" for node in paragraph.findall(f".//{{{W_NS}}}t")
            ).strip()
            media: list[str] = []
            for element in paragraph.iter():
                relation_id = element.attrib.get(f"{{{R_NS}}}embed") or element.attrib.get(
                    f"{{{R_NS}}}link"
                )
                target = relationships.get(relation_id or "")
                if target and "media/" in target:
                    name = Path(target).name
                    media.append(name)
                    referenced_media.add(name)
            paragraph_xml = ET.tostring(paragraph, encoding="utf-8")
            paragraphs.append(
                {
                    "paragraph": index,
                    "text": text,
                    "media": media,
                    "xml_sha256": sha256_bytes(paragraph_xml),
                }
            )
        media_records: list[dict[str, Any]] = []
        for name in sorted(referenced_media):
            internal_path = f"word/media/{name}"
            data = archive.read(internal_path)
            media_records.append(
                {
                    "internal_path": internal_path,
                    "filename": name,
                    "bytes": len(data),
                    "sha256": sha256_bytes(data),
                }
            )
    return {
        "document_xml_sha256": sha256_bytes(document_bytes),
        "relationships_sha256": sha256_bytes(rels_bytes),
        "paragraphs": paragraphs,
        "media": media_records,
    }


def paragraph_signature(item: dict[str, Any]) -> str:
    text = re.sub(r"\s+", "", str(item.get("text", ""))).lower()
    media = ",".join(sorted(normalize_media_name(value) for value in item.get("media", [])))
    return f"{text}|{media}"


def map_legacy_paragraphs(
    legacy_rows: list[dict[str, Any]], current_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    from difflib import SequenceMatcher

    old_signatures = [paragraph_signature(item) for item in legacy_rows]
    new_signatures = [paragraph_signature(item) for item in current_rows]
    matcher = SequenceMatcher(a=old_signatures, b=new_signatures, autojunk=False)
    mapping: dict[int, int] = {}
    for old_start, new_start, length in matcher.get_matching_blocks():
        for offset in range(length):
            mapping[old_start + offset] = new_start + offset
    if len(mapping) != len(legacy_rows):
        missing = [index + 1 for index in range(len(legacy_rows)) if index not in mapping]
        raise RuntimeError(f"Legacy Word manifest has unmapped paragraphs: {missing}")
    current_used = set(mapping.values())
    return {
        "legacy_count": len(legacy_rows),
        "current_count": len(current_rows),
        "mapping": [
            {
                "legacy_paragraph": old_index + 1,
                "current_paragraph": mapping[old_index] + 1,
                "signature_sha256": sha256_bytes(old_signatures[old_index].encode("utf-8")),
            }
            for old_index in sorted(mapping)
        ],
        "inserted_current_paragraphs": [
            index + 1 for index in range(len(current_rows)) if index not in current_used
        ],
        "explanation": (
            "The legacy manifest contains 61 paragraph slots. The current Word body contains "
            "73 direct paragraph slots because 12 blank paragraphs were inserted. After "
            "normalizing copied image filename prefixes, all 61 legacy rows map in order and "
            "without ambiguity to the current 73-paragraph coordinate system used by audit 13."
        ),
    }


def extract_pdf(path: Path) -> dict[str, Any]:
    reader = PdfReader(str(path))
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")
        pages.append(
            {
                "page": index,
                "text": text,
                "text_sha256": sha256_bytes(text.encode("utf-8")),
            }
        )
    return {"page_count": len(pages), "pages": pages}


def collect_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from collect_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from collect_strings(child)


def extract_declared_paths(value: Any) -> list[str]:
    paths: set[str] = set()
    for text in collect_strings(value):
        for match in PATH_PATTERN.findall(text.replace("\\", "/")):
            paths.add(match.rstrip(".,;:，。；："))
    return sorted(paths)


def scan_code_inventory() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    inventory: dict[str, dict[str, Any]] = {}
    texts: dict[str, str] = {}
    for root_name in CODE_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in CODE_SUFFIXES:
                continue
            rel = relative(path)
            record = file_record(path)
            inventory[rel] = record
            try:
                texts[rel] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                texts[rel] = path.read_text(encoding="utf-8", errors="replace")
    return inventory, texts


def resolve_python_import(current: str, module: str | None, level: int) -> list[str]:
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
    return [candidate.as_posix() for candidate in candidates if (ROOT / candidate).is_file()]


def resolve_js_import(current: str, specifier: str) -> list[str]:
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
    return [candidate.as_posix() for candidate in candidates if (ROOT / candidate).is_file()]


def build_import_graph(texts: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    imports: dict[str, set[str]] = defaultdict(set)
    reverse: dict[str, set[str]] = defaultdict(set)
    for path, text in texts.items():
        suffix = Path(path).suffix.lower()
        resolved: set[str] = set()
        if suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            resolved.update(resolve_python_import(path, name.name, 0))
                    elif isinstance(node, ast.ImportFrom):
                        resolved.update(resolve_python_import(path, node.module, node.level))
        elif suffix in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue"}:
            for specifier in JS_IMPORT_PATTERN.findall(text):
                resolved.update(resolve_js_import(path, specifier))
        imports[path].update(resolved)
        for target in resolved:
            reverse[target].add(path)
    return imports, reverse


def dependency_closure(seeds: Iterable[str], graph: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    queue = deque(seed for seed in seeds if seed in graph or (ROOT / seed).is_file())
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        for target in graph.get(current, set()):
            if target not in seen:
                queue.append(target)
    return seen


def caller_closure(seeds: Iterable[str], reverse: dict[str, set[str]], max_depth: int = 2) -> set[str]:
    seen: set[str] = set()
    queue = deque((seed, 0) for seed in seeds)
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for caller in reverse.get(current, set()):
            if caller in seen:
                continue
            seen.add(caller)
            queue.append((caller, depth + 1))
    return seen


def route_tokens(task: dict[str, Any]) -> list[str]:
    tokens: set[str] = set()
    for text in collect_strings(task.get("routes", [])):
        tokens.update(ROUTE_PATTERN.findall(text))
    for atom in task.get("atomic_contracts", []):
        tokens.update(ROUTE_PATTERN.findall(str(atom.get("target_routes", ""))))
    return sorted(tokens)


def build_code_closure(
    task: dict[str, Any],
    inventory: dict[str, dict[str, Any]],
    texts: dict[str, str],
    imports: dict[str, set[str]],
    reverse: dict[str, set[str]],
    code_map: dict[str, Any],
) -> dict[str, Any]:
    declared = extract_declared_paths(task)
    direct_existing = sorted(path for path in declared if path in inventory)
    direct_missing = sorted(path for path in declared if path not in inventory)
    dependencies = dependency_closure(direct_existing, imports)
    callers = caller_closure(direct_existing, reverse)
    closure_files = sorted(set(direct_existing) | dependencies | callers)
    route_refs = route_tokens(task)

    test_terms = {task["id"]}
    for path in direct_existing:
        test_terms.add(Path(path).stem)
        test_terms.add(path)
    test_terms.update(route_refs)
    tests = sorted(
        path
        for path, text in texts.items()
        if path.startswith("tests/") and any(term and term in text for term in test_terms)
    )
    closure_files = sorted(set(closure_files) | set(tests))

    current = code_map["current"]
    direct_basenames = {Path(path).name for path in closure_files}
    backend_routes = [
        item
        for item in current.get("resolved_backend_routes", [])
        if Path(str(item.get("file", ""))).name in direct_basenames
        or any(token and token in str(item.get("final_path", "")) for token in route_refs)
    ]
    orm_models = [
        item
        for item in current.get("orm_models", [])
        if relative(ROOT / str(item.get("file", ""))) in closure_files
        or Path(str(item.get("file", ""))).name in direct_basenames
    ]
    frontend_apis = [
        item
        for item in current.get("frontend_apis", [])
        if str(item.get("file", "")) in closure_files
    ]
    broad_course_scope = any("course-scoped" in text for text in collect_strings(task.get("routes", [])))
    view_basenames = {Path(path).name for path in closure_files if path.endswith(".vue")}
    vue_routes = [
        item
        for item in current.get("vue_routes", [])
        if (broad_course_scope and item.get("course_scoped"))
        or Path(str(item.get("view", ""))).name in view_basenames
        or any(token == item.get("path") or token.rstrip("/") == str(item.get("path", "")).rstrip("/") for token in route_refs)
    ]
    return {
        "closure_spec_version": "context-recovery.code-closure.v1",
        "declared_paths": declared,
        "direct_existing_files": [inventory[path] for path in direct_existing],
        "declared_new_or_missing_files": direct_missing,
        "dependency_files": [inventory[path] for path in sorted(dependencies) if path in inventory],
        "caller_files": [inventory[path] for path in sorted(callers) if path in inventory],
        "test_files": [inventory[path] for path in tests if path in inventory],
        "all_closure_files": [inventory[path] for path in closure_files if path in inventory],
        "route_references": route_refs,
        "vue_routes": vue_routes,
        "frontend_api_modules": frontend_apis,
        "backend_endpoints": backend_routes,
        "orm_models": orm_models,
        "global_inventory_reference": "authority_manifest.json#code_inventory",
        "method": (
            "Declared paths are mechanically extracted from the complete task object. The packet "
            "adds transitive internal imports, two reverse-caller levels, matching tests, frontend "
            "routes, API modules, registered backend endpoints and ORM models. The authority "
            "manifest preserves the conservative full source hash inventory for drift detection."
        ),
    }


def select_word_context(
    task: dict[str, Any],
    primary_atoms: list[dict[str, Any]],
    related_atoms: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    image_units: list[dict[str, Any]],
) -> dict[str, Any]:
    selected: set[int] = set(int(value) for value in task.get("source_word_paragraphs", []))
    for atom in primary_atoms + related_atoms:
        selected.update(int(value) for value in atom.get("word_paragraphs", []))
    for group in task.get("source_group_contracts", []):
        selected.update(int(value) for value in group.get("paragraphs", []))
    image_ids = set(int(value) for value in task.get("source_images", []))
    for atom in primary_atoms + related_atoms:
        image_ids.update(int(value) for value in atom.get("source_images", []))
    for group in task.get("source_group_contracts", []):
        image_ids.update(int(value) for value in group.get("images", []))
    by_image = {int(item["image"]): item for item in image_units}
    for image_id in image_ids:
        unit = by_image.get(image_id)
        if not unit:
            continue
        selected.update(int(value) for value in unit.get("source_context_paragraphs", []))
        selected.update(int(value) for value in unit.get("semantic_anchor_paragraphs", []))
        selected.update(int(value) for value in unit.get("boundary_context_paragraphs", []))
    by_index = {int(item["paragraph"]): item for item in paragraphs}
    nonempty = [int(item["paragraph"]) for item in paragraphs if item.get("text", "").strip()]
    expanded = set(selected)
    for paragraph in list(selected):
        previous = next((value for value in reversed(nonempty) if value < paragraph), None)
        following = next((value for value in nonempty if value > paragraph), None)
        if previous:
            expanded.add(previous)
        if following:
            expanded.add(following)
    return {
        "selected_paragraphs": sorted(selected),
        "selected_with_nonempty_neighbors": sorted(expanded),
        "paragraphs": [by_index[index] for index in sorted(expanded) if index in by_index],
        "image_ids": sorted(image_ids),
    }


def build_machine_fact_references(
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
        "source_records": {name: file_record(path) for name, path in sources.items()},
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", help="Immutable protocol version directory name")
    parser.add_argument("--chunk-bytes", type=int, default=220_000)
    args = parser.parse_args()

    missing = [name for name, path in AUTHORITY_SOURCES.items() if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing authority sources: {missing}")
    version = validate_version(
        args.version or datetime.now().astimezone().strftime("v%Y%m%dT%H%M%S%z")
    )
    version_dir = CONTEXT_ROOT / "versions" / version
    if version_dir.exists():
        raise SystemExit(f"Version already exists and is immutable: {version_dir}")
    version_dir.mkdir(parents=True)

    product = read_json(PRODUCT_JSON_PATH)
    plan = read_json(PLAN_JSON_PATH)
    audit = read_json(AUDIT_JSON_PATH)
    legacy_manifest = read_json(LEGACY_MANIFEST_PATH)
    code_map = read_json(DUAL_CODE_MAP_PATH)
    protection = read_json(PROTECTION_PATH)
    current_routes = read_json(CURRENT_ROUTE_PATH)
    target_routes = read_json(TARGET_ROUTE_PATH)
    target_globals = read_json(TARGET_GLOBAL_PATH)
    scope_matrix = read_json(SCOPE_MATRIX_PATH)

    docx = extract_docx(DOCX_PATH)
    paragraph_mapping = map_legacy_paragraphs(
        legacy_manifest.get("paragraphs", []), docx["paragraphs"]
    )
    pdf = extract_pdf(PDF_PATH)
    inventory, texts = scan_code_inventory()
    imports, reverse = build_import_graph(texts)

    source_records = {
        name: file_record(path) for name, path in PINNED_AUTHORITY_SOURCES.items()
    }
    operational_records = {
        name: file_record(path) for name, path in OPERATIONAL_SOURCES.items()
    }
    product_sections = {item["id"]: item for item in product.get("sections", [])}
    atoms = audit.get("atomic_requirements", [])
    atoms_by_id = {item["atomic_requirement_id"]: item for item in atoms}
    image_units = audit.get("image_text_units", [])
    image_units_by_id = {int(item["image"]): item for item in image_units}
    plan_tasks = {item["id"]: item for item in plan.get("tasks", [])}

    image_records: list[dict[str, Any]] = []
    docx_media = {item["filename"]: item for item in docx["media"]}
    for unit in image_units:
        copied_path = IMAGE_DIR / unit["filename"]
        normalized = normalize_media_name(unit["filename"])
        image_records.append(
            {
                "image": int(unit["image"]),
                "filename": unit["filename"],
                "copied_file": file_record(copied_path),
                "docx_media": docx_media.get(normalized),
                "paragraph": int(unit["paragraph"]),
                "semantic_anchor_paragraphs": unit.get("semantic_anchor_paragraphs", []),
                "boundary_context_paragraphs": unit.get("boundary_context_paragraphs", []),
            }
        )

    goal_id = read_goal_id()
    authority_manifest = {
        "schema_version": "context-recovery.authority.v1",
        "protocol_version": version,
        "status": "BUILDING",
        "created_at": utc_stamp(),
        "goal_id": goal_id,
        "authority_priority": [
            relative(PDF_PATH),
            relative(CONSTITUTION_PATH),
            relative(DOCX_PATH),
            relative(AUDIT_JSON_PATH),
            relative(PRODUCT_JSON_PATH),
            relative(PLAN_JSON_PATH),
            relative(CODE_MAP_MD_PATH),
            relative(ROUTE_MATRIX_PATH),
            "outputs/原系统融合重构执行/evidence",
            relative(STATUS_PATH),
            relative(RECOVERY_INDEX_PATH),
        ],
        "source_files": source_records,
        "operational_files": operational_records,
        "source_stability_contract": {
            "pinned_authority": (
                "Any hash change invalidates this protocol version and requires a new immutable build."
            ),
            "operational_live": (
                "00, 02 and 11 are read live on every recovery. Their build-time records prove "
                "construction coherence but do not invalidate semantic task packets when checkpoints "
                "or append-only worklogs advance."
            ),
        },
        "derived_counts": {
            "word_paragraphs": len(docx["paragraphs"]),
            "word_nonempty_paragraphs": sum(bool(item["text"].strip()) for item in docx["paragraphs"]),
            "legacy_word_manifest_paragraphs": len(legacy_manifest.get("paragraphs", [])),
            "images": len(image_units),
            "product_sections": len(product.get("sections", [])),
            "target_routes": len(product.get("routes", [])),
            "atomic_requirements": len(atoms),
            "phases": len(plan.get("phases", [])),
            "tasks": len(plan.get("tasks", [])),
            "current_frontend_routes": len(code_map["current"].get("vue_routes", [])),
            "current_backend_endpoints": len(code_map["current"].get("resolved_backend_routes", [])),
            "current_orm_models": len(code_map["current"].get("orm_models", [])),
            "code_inventory_files": len(inventory),
        },
        "word": {
            "document_xml_sha256": docx["document_xml_sha256"],
            "relationships_sha256": docx["relationships_sha256"],
            "paragraphs": docx["paragraphs"],
            "paragraph_mapping": paragraph_mapping,
        },
        "images": image_records,
        "competition": pdf,
        "code_inventory": [inventory[path] for path in sorted(inventory)],
        "bootstrap_read_order": BOOTSTRAP_READ_ORDER,
    }
    authority_path = version_dir / "authority_manifest.json"
    atomic_write_json(authority_path, authority_manifest)

    shared_protocols = {
        "goal_contract": {
            **file_record(GOAL_PATH),
            "text": GOAL_PATH.read_text(encoding="utf-8"),
        },
        "constitution": {
            **file_record(CONSTITUTION_PATH),
            "text": CONSTITUTION_PATH.read_text(encoding="utf-8"),
        },
        "f1_design_contract": plan.get("f1_design_contract"),
        "checkpoint_state_machine": list(CHECKPOINT_STATES),
        "competition_source": {**file_record(PDF_PATH), **pdf},
        "global_product_sections": [
            product_sections[item]
            for item in ("P00", "P02", "P03", "P04", "P27", "P29", "P30")
            if item in product_sections
        ],
    }

    task_descriptors: dict[str, dict[str, Any]] = {}
    for task_id in sorted(plan_tasks):
        task = plan_tasks[task_id]
        primary_atoms = [
            item for item in atoms if item.get("primary_implementation_task_id") == task_id
        ]
        related_atoms = [
            item
            for item in atoms
            if task_id in item.get("implementation_task_ids", [])
            and item.get("primary_implementation_task_id") != task_id
        ]
        section_ids: set[str] = set()
        for atom in primary_atoms + related_atoms:
            section_ids.update(atom.get("product_section_ids", []))
        for contract in task.get("atomic_contracts", []):
            section_ids.update(contract.get("product_section_ids", []))
        sections = [product_sections[item] for item in sorted(section_ids) if item in product_sections]
        word_context = select_word_context(
            task, primary_atoms, related_atoms, docx["paragraphs"], image_units
        )
        selected_images = [
            {
                "image_text_unit": image_units_by_id[image_id],
                "file_record": next(
                    item for item in image_records if item["image"] == image_id
                ),
            }
            for image_id in word_context["image_ids"]
            if image_id in image_units_by_id
        ]
        code_closure = build_code_closure(
            task, inventory, texts, imports, reverse, code_map
        )
        phase_id = task_id.split("-", 1)[0]
        phase = next(item for item in plan.get("phases", []) if item["id"] == phase_id)
        previous_tasks = [
            item["id"]
            for item in plan.get("tasks", [])
            if item["id"].split("-", 1)[0] == phase_id and item["id"] < task_id
        ]
        payload = {
            "schema_version": "context-recovery.task-payload.v1",
            "packet_id": task_id,
            "packet_type": "task",
            "protocol_version": version,
            "source_snapshot_hashes": {
                name: record["sha256"] for name, record in source_records.items()
            },
            "exact_task_object": task,
            "primary_atomic_requirements": primary_atoms,
            "related_atomic_requirements": related_atoms,
            "task_atomic_execution_contract": task_atomic_execution_contract(
                task_id, primary_atoms, related_atoms
            ),
            "protection_and_conflict_context": {
                "protected_pages": protection.get("pages", []),
                "protected_rules": protection.get("rules", []),
                "conflict_decisions": [
                    {
                        "atomic_requirement_id": atom["atomic_requirement_id"],
                        "decision": atom.get("conflict_or_defer_decision", ""),
                    }
                    for atom in primary_atoms + related_atoms
                ],
            },
            "word_context": word_context,
            "legacy_to_current_paragraph_mapping": paragraph_mapping,
            "images": selected_images,
            "product_responsibility_sections": sections,
            "competition_clauses": shared_protocols["competition_source"],
            "prerequisites": {
                "phase_dependencies": phase.get("dependencies", []),
                "previous_tasks_in_phase": previous_tasks,
                "declared_source_groups": task.get("source_groups", []),
            },
            "shared_protocols": shared_protocols,
            "code_impact_closure": code_closure,
            "verification_contract": {
                "automated_tests": task.get("automated_tests", []),
                "manual_acceptance": task.get("manual_acceptance", []),
                "rollback": task.get("rollback", []),
                "states": task.get("states", []),
                "full_state_contract": task.get("full_state_contract", ""),
                "close_condition": (
                    "The task may close only after the exact task object, primary atoms, Word/image "
                    "context, code closure hashes, focused tests, relevant regression, evidence, "
                    "rollback check and checkpoint transition are all verified."
                ),
            },
            "supporting_machine_facts": build_machine_fact_references(
                task, code_closure
            ),
        }
        descriptor_path = version_dir / "task_packets" / f"{task_id}.json"
        task_descriptors[task_id] = write_chunked_packet(
            descriptor_path, payload, args.chunk_bytes
        )

    phase_descriptors: dict[str, dict[str, Any]] = {}
    for phase in plan.get("phases", []):
        task_ids = [task["id"] for task in plan.get("tasks", []) if task["id"].startswith(phase["id"] + "-")]
        payload = {
            "schema_version": "context-recovery.phase-payload.v1",
            "packet_id": phase["id"],
            "packet_type": "phase",
            "protocol_version": version,
            "exact_phase_object": phase,
            "task_packets": [
                {
                    "task_id": task_id,
                    "descriptor": task_descriptors[task_id]["descriptor"],
                    "payload_sha256": task_descriptors[task_id]["payload_sha256"],
                    "chunk_count": task_descriptors[task_id]["chunk_count"],
                    "total_bytes": task_descriptors[task_id]["total_bytes"],
                }
                for task_id in task_ids
            ],
            "shared_protocols": shared_protocols,
            "stage_acceptance": phase.get("stage_acceptance", []),
        }
        descriptor_path = version_dir / "phase_packets" / f"{phase['id']}.json"
        phase_descriptors[phase["id"]] = write_chunked_packet(
            descriptor_path, payload, args.chunk_bytes
        )

    phase_index = {
        "schema_version": "context-recovery.phase-index.v1",
        "protocol_version": version,
        "phases": [
            {
                "phase_id": phase_id,
                "descriptor": descriptor["descriptor"],
                "payload_sha256": descriptor["payload_sha256"],
                "chunk_count": descriptor["chunk_count"],
                "total_bytes": descriptor["total_bytes"],
            }
            for phase_id, descriptor in sorted(phase_descriptors.items())
        ],
    }
    atomic_write_json(version_dir / "phase_packets" / "F0-F10.json", phase_index)

    active_checkpoint, sources_unchanged = load_active_checkpoint_for_rebuild(
        set(plan_tasks), source_records, goal_id
    )
    checkpoint_task = active_checkpoint.get("task") if active_checkpoint else "F2-T01"
    checkpoint_phase = active_checkpoint.get("phase") if active_checkpoint else "F2"
    checkpoint_state = active_checkpoint.get("state") if active_checkpoint else "NOT_STARTED"
    if active_checkpoint and not sources_unchanged:
        checkpoint_state = "NOT_STARTED"

    checkpoint = {
        "schema_version": "context-recovery.checkpoint.v1",
        "goal_id": goal_id,
        "protocol_version": version,
        "phase": checkpoint_phase,
        "task": checkpoint_task,
        "state": checkpoint_state,
        "gate": "CONTEXT_RECOVERY_NOT_VERIFIED",
        "authority_manifest_sha256": sha256_file(authority_path),
        "task_packet_descriptor": task_descriptors[checkpoint_task]["descriptor"],
        "source_hashes": {name: record["sha256"] for name, record in source_records.items()},
        "operational_file_records": operational_records,
        "impact_file_hashes": dict((active_checkpoint or {}).get("impact_file_hashes", {})),
        "read_evidence": list((active_checkpoint or {}).get("read_evidence", [])),
        "modified_files": list((active_checkpoint or {}).get("modified_files", [])),
        "test_commands": list((active_checkpoint or {}).get("test_commands", [])),
        "e2e": list((active_checkpoint or {}).get("e2e", [])),
        "screenshots": list((active_checkpoint or {}).get("screenshots", [])),
        "rollback_checks": list((active_checkpoint or {}).get("rollback_checks", [])),
        "atomic_requirement_ledger": (active_checkpoint or {}).get("atomic_requirement_ledger"),
        "atomic_requirement_counts": (active_checkpoint or {}).get("atomic_requirement_counts"),
        "known_limitations": [
            *list((active_checkpoint or {}).get("known_limitations", [])),
            "Protocol version is still BUILDING and not active.",
            *(
                ["Pinned authority changed; task position was preserved but task state was reset to NOT_STARTED."]
                if active_checkpoint and not sources_unchanged
                else []
            ),
        ],
        "next_step": "Run the independent verifier and activate this version only if every check passes.",
        "created_at": utc_stamp(),
        "previous_checkpoint": (
            {
                "protocol_version": active_checkpoint.get("protocol_version"),
                "phase": active_checkpoint.get("phase"),
                "task": active_checkpoint.get("task"),
                "state": active_checkpoint.get("state"),
                "next_step": active_checkpoint.get("next_step"),
                "sources_unchanged": sources_unchanged,
            }
            if active_checkpoint
            else None
        ),
    }
    snapshot_dir = version_dir / "checkpoint_snapshots"
    previous_sequence = copy_checkpoint_history(snapshot_dir)
    checkpoint["snapshot_sequence"] = previous_sequence + 1
    atomic_write_json(version_dir / "current_checkpoint.json", checkpoint)
    atomic_write_json(
        snapshot_dir
        / f"{checkpoint['snapshot_sequence']:04d}_BUILDING_{checkpoint_task}_{checkpoint_state}.json",
        checkpoint,
    )

    activation = {
        "schema_version": "context-recovery.activation.v1",
        "protocol_version": version,
        "status": "BUILDING",
        "created_at": utc_stamp(),
        "authority_manifest": file_record(authority_path),
        "verification_report": None,
        "activated_at": None,
    }
    atomic_write_json(version_dir / "protocol_activation.json", activation)

    CONTEXT_ROOT.mkdir(parents=True, exist_ok=True)
    active_path = CONTEXT_ROOT / "active_manifest.json"
    if not active_path.exists():
        atomic_write_json(
            active_path,
            {
                "schema_version": "context-recovery.active.v1",
                "status": "BOOTSTRAP",
                "active_version": None,
                "goal_contract": file_record(GOAL_PATH),
                "bootstrap_read_order": BOOTSTRAP_READ_ORDER,
                "reason": "No protocol version is active until independent verification passes.",
                "created_at": utc_stamp(),
            },
        )
    atomic_write_json(
        CONTEXT_ROOT / "bootstrap_manifest.json",
        {
            "schema_version": "context-recovery.bootstrap.v1",
            "status": "BOOTSTRAP",
            "building_version": version,
            "goal_contract": file_record(GOAL_PATH),
            "read_order": BOOTSTRAP_READ_ORDER,
            "previous_protocol_preserved": True,
            "created_at": utc_stamp(),
        },
    )

    print(
        json.dumps(
            {
                "status": "BUILDING",
                "version": version,
                "version_dir": relative(version_dir),
                "goal_sha256": source_records["goal_contract"]["sha256"],
                "counts": authority_manifest["derived_counts"],
                "phase_packets": len(phase_descriptors),
                "task_packets": len(task_descriptors),
                "legacy_word_mapping": {
                    "mapped": len(paragraph_mapping["mapping"]),
                    "inserted_current_paragraphs": paragraph_mapping[
                        "inserted_current_paragraphs"
                    ],
                },
                "next_step": "Run scripts/verify_context_recovery_packets.py --version " + version,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
