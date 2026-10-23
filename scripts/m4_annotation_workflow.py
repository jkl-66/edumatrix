"""Prepare, execute, adjudicate and verify the object-correct M4 annotation streams."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import (  # noqa: E402
    DBArtifact,
    DBArtifactVersion,
    DBCourseDocument,
    DBEvaluationCase,
    DBEvaluationResult,
    DBEvaluationRun,
    DBSourceDocument,
    DBSourceRef,
)
from app.m4_evaluation import load_frozen_benchmark  # noqa: E402
from app.m4_offline_evaluation import (  # noqa: E402
    OfflineAnnotationRecord,
    OfflineAnnotationTask,
    agreement_report,
    calculate_offline_metrics,
    canonical_json,
    content_hash,
    make_task,
    resolve_annotations,
)
from llm_client import build_async_llm, parse_json_object  # noqa: E402


DEFAULT_M4_DB = ROOT / "outputs" / "M4_量化评测与可靠性交付" / "evidence" / "real-run" / "m4_real.db"
DEFAULT_M3_DB = ROOT / "outputs" / "M3_三画像C加比赛闭环" / "evidence" / "browser-e2e" / "m3_e2e.db"
DEFAULT_M3_REPORT = ROOT / "outputs" / "M3_三画像C加比赛闭环" / "evidence" / "browser-e2e" / "report.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "M4_量化评测与可靠性交付" / "evidence" / "annotation-workflow-20260802"
DATASET_DIR = ROOT / "outputs" / "M0_阶段0基线与架构契约" / "datasets"
COURSE_DIR = ROOT / "outputs" / "M0_阶段0基线与架构契约" / "baseline_course"


CHAPTER_KPS = {
    "01_来源许可与课程边界.md": ("KP-01", "KP-02", "KP-03"),
    "02_文档解析与结构保留.md": ("KP-04", "KP-05", "KP-06", "KP-07"),
    "03_分块元数据与索引.md": ("KP-08", "KP-09", "KP-10"),
    "04_混合检索与重排.md": ("KP-11", "KP-12", "KP-13", "KP-14", "KP-15", "KP-30"),
    "05_引用约束生成与拒答.md": ("KP-16", "KP-17", "KP-18", "KP-19", "KP-20"),
    "06_画像适配与资源契约.md": ("KP-21", "KP-22", "KP-23"),
    "07_幻觉率与覆盖率评测.md": ("KP-24", "KP-25", "KP-26", "KP-27"),
    "08_故障恢复与技能验收.md": ("KP-28", "KP-29", "KP-31", "KP-32"),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _session(path: Path) -> Session:
    if not path.is_file():
        raise FileNotFoundError(path)
    return Session(create_engine(f"sqlite:///{path.resolve().as_posix()}", future=True))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[Any]) -> None:
    path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path, model: Any) -> tuple[Any, ...]:
    return tuple(model.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


@contextmanager
def _exclusive_output_lock(output: Path):
    """Prevent two annotation processes from appending to one evidence file."""
    lock = output.with_suffix(output.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = lock.open("x", encoding="ascii")
    except FileExistsError as exc:
        raise RuntimeError(f"annotation output is already locked: {lock}") from exc
    try:
        handle.write(str(__import__("os").getpid()))
        handle.flush()
        yield
    finally:
        handle.close()
        lock.unlink(missing_ok=True)


def _m4_run(session: Session, run_id: str | None) -> DBEvaluationRun:
    query = session.query(DBEvaluationRun)
    row = query.filter_by(id=run_id).first() if run_id else query.order_by(DBEvaluationRun.started_at.desc()).first()
    if row is None or row.status != "awaiting_annotation":
        raise ValueError("M4 requires a sealed awaiting_annotation run")
    if session.query(DBEvaluationResult).filter_by(evaluation_run_id=row.id).count() != 60:
        raise ValueError("M4 annotation requires exactly 60 persisted results")
    return row


def _source_map(session: Session) -> dict[str, dict[str, Any]]:
    rows = (
        session.query(DBSourceRef, DBSourceDocument, DBCourseDocument)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .join(DBCourseDocument, DBCourseDocument.id == DBSourceDocument.legacy_document_id)
        .filter(DBSourceDocument.course_id == "course-rag-engineering-m0")
        .all()
    )
    result = {}
    for ref, source, document in rows:
        start = max(0, int(ref.char_start or 0))
        end = int(ref.char_end or len(document.content or ""))
        result[ref.id] = {
            "source_ref_id": ref.id,
            "title": source.title,
            "excerpt": (document.content or "")[start:end].strip()[:6000],
        }
    return result


def _m3_resources(m3_db: Path, report_path: Path) -> list[dict[str, Any]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    profiles = {item["task_id"]: item for item in report["checks"]["three_profile_differences"]}
    resources = []
    with _session(m3_db) as session:
        rows = (
            session.query(DBArtifact, DBArtifactVersion)
            .join(DBArtifactVersion, DBArtifactVersion.id == DBArtifact.current_version_id)
            .filter(DBArtifact.creating_task_id.in_(profiles), DBArtifact.artifact_type.in_(("lesson", "lab_guide", "tiered_quiz")))
            .all()
        )
        for artifact, version in rows:
            profile = profiles[artifact.creating_task_id]
            resources.append({
                "artifact_id": artifact.id,
                "artifact_version_id": version.id,
                "artifact_type": artifact.artifact_type,
                "title": artifact.title,
                "profile_id": profile["profile_id"],
                "expected_personalization": profile["personalization"],
                "source_ref_ids": list((version.metadata_json or {}).get("source_ref_ids") or profile["source_ref_ids"]),
                "content": json.loads(version.content),
                "content_sha256": hashlib.sha256(version.content.encode("utf-8")).hexdigest(),
            })
    if len(resources) != 9:
        raise ValueError(f"expected 9 M3 resource instances, found {len(resources)}")
    counts = defaultdict(int)
    for item in resources:
        counts[item["profile_id"]] += 1
    if sorted(counts.values()) != [3, 3, 3]:
        raise ValueError(f"M3 resources are not balanced by profile: {dict(counts)}")
    return sorted(resources, key=lambda item: (item["profile_id"], item["artifact_type"]))


def _task_rubrics() -> dict[str, dict[str, Any]]:
    return {
        "case_validity": {
            "labels": {"validity": ["valid", "invalid", "unknown"], "failure_type": "string"},
            "rule": "valid only when the response addresses the frozen input, respects gold/failure boundaries, and is semantically reviewable; execution completion alone is insufficient",
        },
        "atomic_fact": {
            "labels": {"label": ["supported", "contradicted", "unsupported", "unknown", "non_factual"]},
            "rule": "use only frozen source excerpts and case gold; citation presence without support does not pass",
        },
        "adaptation": {
            "labels": {
                "prerequisite_fit": ["fit", "partial", "unfit", "unknown"],
                "difficulty_fit": ["fit", "partial", "unfit", "unknown"],
                "format_fit": ["fit", "partial", "unfit", "unknown"],
                "scaffolding_fit": ["fit", "partial", "unfit", "unknown"],
                "assessment_fit": ["fit", "partial", "unfit", "unknown"],
                "factual_quality_passed": "boolean",
            },
            "rule": "score each of the 9 actual M3 resource instances independently; style or length alone is not personalization",
        },
        "artifact_approval": {
            "labels": {
                "semantic_quality_passed": "boolean", "source_traceability_passed": "boolean",
                "version_integrity_passed": "boolean", "approved": "boolean conjunction",
            },
            "rule": "approve only when semantic quality, source traceability and frozen-version integrity all pass",
        },
        "coverage": {
            "labels": {
                "substantial": "boolean", "traceable_source_or_original": "boolean",
                "semantic_review_passed": "boolean", "artifact_approved": "boolean",
            },
            "rule": "all four conditions must be true; keyword occurrence alone never counts",
        },
    }


_HIDDEN_EVALUATION_KEYS = {"gold", "gold_data", "failure_branch", "failure_branch_data"}


def _public_annotation_payload(value: Any) -> Any:
    """Remove hidden labels before any annotation task reaches an LLM."""
    if isinstance(value, dict):
        return {
            str(key): _public_annotation_payload(child)
            for key, child in value.items()
            if str(key).strip().lower() not in _HIDDEN_EVALUATION_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_public_annotation_payload(child) for child in value]
    return value


def prepare(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite annotation workflow: {output}")
    benchmark = load_frozen_benchmark(DATASET_DIR)
    case_map = {case.case_id: case for case in benchmark.cases}
    sources: dict[str, dict[str, Any]]
    tasks: list[OfflineAnnotationTask] = []
    rubrics = _task_rubrics()
    with _session(args.m4_db) as session:
        run = _m4_run(session, args.run_id)
        sources = _source_map(session)
        rows = (
            session.query(DBEvaluationCase, DBEvaluationResult)
            .join(DBEvaluationResult, DBEvaluationResult.evaluation_case_id == DBEvaluationCase.id)
            .filter(DBEvaluationResult.evaluation_run_id == run.id)
            .order_by(DBEvaluationCase.case_code)
            .all()
        )
        for case_row, result in rows:
            case = case_map[case_row.case_code]
            output_data = result.output_data
            case_payload = {
                "case": case.model_dump(mode="json"),
                "response": output_data,
                "allowed_sources": [sources[key] for key in output_data.get("evidence", {}).get("source_scope", []) if key in sources],
            }
            tasks.append(make_task(
                task_id=f"case:{case.case_id}", task_type="case_validity", subject_id=case.case_id,
                payload=case_payload, rubric=rubrics["case_validity"],
            ))
            for claim in output_data.get("evidence", {}).get("claims", []):
                cited = [sources[key] for key in claim.get("source_ref_ids", []) if key in sources]
                tasks.append(make_task(
                    task_id=f"claim:{case.case_id}:{claim['claim_id']}",
                    task_type="atomic_fact", subject_id=f"{case.case_id}:{claim['claim_id']}",
                    payload={
                        "case_id": case.case_id, "input": case.input, "gold": case.gold,
                        "failure_branch": case.failure_branch, "claim": claim, "cited_sources": cited,
                    },
                    rubric=rubrics["atomic_fact"],
                ))
        run_data = {
            "run_id": run.id, "trace_id": run.trace_id, "code_version": run.code_version,
            "data_version": run.data_version, "model_version": run.model_version,
        }

    resources = _m3_resources(args.m3_db, args.m3_report)
    for resource in resources:
        tasks.append(make_task(
            task_id=f"adapt:{resource['artifact_version_id']}", task_type="adaptation",
            subject_id=resource["artifact_version_id"], payload=resource, rubric=rubrics["adaptation"],
        ))

    kp_data = json.loads((DATASET_DIR / "core_knowledge_points.json").read_text(encoding="utf-8"))
    course_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for filename, kp_ids in CHAPTER_KPS.items():
        path = COURSE_DIR / filename
        evidence = {
            "artifact_ref": f"baseline-course:{filename}", "kind": "project_original_lesson",
            "status": "FROZEN_FOR_M0_REVIEW", "sha256": _sha256(path), "content": path.read_text(encoding="utf-8"),
        }
        for kp_id in kp_ids:
            course_evidence[kp_id].append(evidence)
    cases_by_kp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in benchmark.cases:
        for kp_id in case.kp:
            cases_by_kp[kp_id].append({
                "artifact_ref": f"evaluation-case:{case.case_id}", "kind": "frozen_assessment",
                "input": case.input, "gold": case.gold, "difficulty": case.difficulty,
            })
    for point in kp_data["points"]:
        kp_id = point["id"]
        related_resources = resources if kp_id in {"KP-11", "KP-12", "KP-13"} else []
        tasks.append(make_task(
            task_id=f"coverage:{kp_id}", task_type="coverage", subject_id=kp_id,
            payload={
                "knowledge_point": point,
                "candidate_teaching_artifacts": course_evidence[kp_id],
                "candidate_assessments": cases_by_kp[kp_id],
                "approved_m3_resources": related_resources,
                "coverage_rule": kp_data["coverage_rule"],
            },
            rubric=rubrics["coverage"],
        ))

    type_counts = Counter(task.task_type for task in tasks)
    if type_counts["case_validity"] != 60 or type_counts["adaptation"] != 9 or type_counts["coverage"] != 32:
        raise ValueError(f"invalid task distribution: {dict(type_counts)}")
    output.mkdir(parents=True)
    _write_jsonl(output / "tasks.jsonl", [task.model_dump(mode="json") for task in tasks])
    instructions = (
        "# M4 独立标注说明\n\n"
        "本目录严格分离四类对象：60 例案例有效性、原子事实、M3 的 9 个真实资源实例、32 KP 覆盖。\n"
        "两次标注必须分别运行，不得将另一遍结果作为输入；第三遍只处理 disagreement_tasks.jsonl。\n"
        "当前授权采用两次隔离 AI 标注与第三次 AI 裁决，不得对外改写为两名真人专家签字。\n"
        "最终报告固定 publication_authorized=false，除非未来补充真实独立人工复核。\n"
    )
    (output / "README.md").write_text(instructions, encoding="utf-8")
    manifest = {
        "schema_version": "m4.annotation-workflow-manifest.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_method": "two_isolated_ai_passes_with_ai_adjudication",
        "m4_run": run_data,
        "inputs": {
            "m4_db_sha256": _sha256(args.m4_db), "m3_db_sha256": _sha256(args.m3_db),
            "m3_report_sha256": _sha256(args.m3_report),
            "benchmark_case_sha256": benchmark.case_file_sha256,
            "benchmark_kp_sha256": benchmark.knowledge_point_file_sha256,
        },
        "task_counts": dict(type_counts),
        "task_count": len(tasks),
        "tasks_sha256": _sha256(output / "tasks.jsonl"),
        "human_validation_completed": False,
    }
    _write_json(output / "manifest.json", manifest)
    print(json.dumps({"ok": True, "output": str(output), "task_counts": dict(type_counts), "task_count": len(tasks)}, ensure_ascii=False))
    return 0


def _annotation_prompt(
    tasks: list[OfflineAnnotationTask], *, annotator_ref: str, status: str,
    candidate_labels: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, str]:
    examples = {
        "case_validity": {"validity": "valid", "failure_type": ""},
        "atomic_fact": {"label": "supported"},
        "adaptation": {
            "prerequisite_fit": "fit", "difficulty_fit": "fit", "format_fit": "fit",
            "scaffolding_fit": "fit", "assessment_fit": "fit", "factual_quality_passed": True,
        },
        "artifact_approval": {
            "semantic_quality_passed": True, "source_traceability_passed": True,
            "version_integrity_passed": True, "approved": True,
        },
        "coverage": {
            "substantial": True, "traceable_source_or_original": True,
            "semantic_review_passed": True, "artifact_approved": True,
        },
    }
    task_type = tasks[0].task_type
    decision_rules = {
        "case_validity": (
            "A case is valid only when the response substantively satisfies the frozen gold and avoids the failure_branch. "
            "Being parseable, complete, or semantically reviewable is necessary but not sufficient."
        ),
        "atomic_fact": "Judge the exact atomic claim against its cited frozen excerpts and gold boundary.",
        "adaptation": "Judge the actual resource instance, not its declared personalization metadata alone.",
        "artifact_approval": "Approval is the conjunction of semantic quality, traceability and exact-version integrity.",
        "coverage": "Coverage requires substantive teaching/execution/measurement and an independently approved artifact.",
    }
    system = (
        "You are an independent EduMatrix evaluation annotator. Return one raw JSON object only. "
        "Use only each task payload and rubric; do not infer missing evidence, optimize toward target thresholds, "
        "or prefer confident/verbose model text. For every task, produce exact labels, a concise evidence-based rationale, "
        "and at least one evidence_ref copied from the task subject or payload. "
        f"Every labels object in this batch MUST contain exactly these keys and no others: {canonical_json(examples[task_type])}. "
        f"Decision rule: {decision_rules[task_type]}"
    )
    request = {
        "annotator_ref": annotator_ref,
        "status": status,
        "required_output": {"annotations": [{"task_id": "...", "labels": examples[task_type], "rationale": "...", "evidence_refs": ["..."]}]},
        "tasks": [
            {
                **task.model_dump(mode="json", exclude={"payload"}),
                "payload": _public_annotation_payload(task.payload),
            }
            for task in tasks
        ],
    }
    if candidate_labels is not None:
        request["independent_candidate_labels"] = {
            task.task_id: candidate_labels[task.task_id] for task in tasks
        }
        request["adjudication_instruction"] = (
            "Resolve the disagreement from frozen evidence and rubric. Do not majority-vote or assume either candidate is correct."
        )
    return system, canonical_json(request)


def _batch_size(task_type: str) -> int:
    return {"case_validity": 3, "atomic_fact": 12, "adaptation": 1, "artifact_approval": 1, "coverage": 2}[task_type]


async def _annotate_batches(
    tasks: tuple[OfflineAnnotationTask, ...], output: Path, annotator_ref: str, *, reverse: bool,
    status: str, candidate_labels: dict[str, dict[str, Any]] | None = None,
) -> None:
    existing = list(_read_jsonl(output, OfflineAnnotationRecord)) if output.is_file() else []
    completed = {record.task_id for record in existing}
    grouped = sorted(tasks, key=lambda task: (task.task_type, task.task_id))
    ordered = list(reversed(grouped)) if reverse else grouped
    pending = [task for task in ordered if task.task_id not in completed]
    llm = build_async_llm()
    index = 0
    while index < len(pending):
        task_type = pending[index].task_type
        batch = []
        while index < len(pending) and pending[index].task_type == task_type and len(batch) < _batch_size(task_type):
            batch.append(pending[index])
            index += 1
        system, prompt = _annotation_prompt(
            batch, annotator_ref=annotator_ref, status=status, candidate_labels=candidate_labels,
        )
        last_error: Exception | None = None
        for attempt in range(3):
            request = prompt if attempt == 0 else canonical_json({
                "original_request": json.loads(prompt),
                "validation_feedback": str(last_error),
                "instruction": "Regenerate every annotation in the batch with exact task IDs and label keys.",
            })
            raw = await llm.generate(system, request, role=f"m4_{status}_annotation")
            try:
                payload = parse_json_object(raw)
                rows = payload.get("annotations")
                if not isinstance(rows, list) or len(rows) != len(batch):
                    raise ValueError("annotation batch count mismatch")
                by_id = {task.task_id: task for task in batch}
                records = []
                for row in rows:
                    task = by_id.get(str(row.get("task_id", "")))
                    if task is None:
                        raise ValueError("annotation returned an unknown task ID")
                    record = OfflineAnnotationRecord(
                        task_id=task.task_id, task_hash=task.task_hash, task_type=task.task_type,
                        annotator_ref=annotator_ref, status=status, labels=row.get("labels", {}),
                        rationale=str(row.get("rationale", "")), evidence_refs=tuple(row.get("evidence_refs") or (task.subject_id,)),
                    )
                    from app.m4_offline_evaluation import validate_annotation
                    validate_annotation(task, record)
                    records.append(record)
                if len({record.task_id for record in records}) != len(batch):
                    raise ValueError("annotation batch contains duplicate task IDs")
                with output.open("a", encoding="utf-8") as handle:
                    for record in records:
                        handle.write(canonical_json(record.model_dump(mode="json")) + "\n")
                print(json.dumps({"annotator": annotator_ref, "completed": len(completed) + len(records), "remaining": len(tasks) - len(completed) - len(records)}, ensure_ascii=False), flush=True)
                completed.update(record.task_id for record in records)
                break
            except Exception as exc:
                last_error = exc
        else:
            raise ValueError(f"annotation batch failed strict repair: {last_error}")


def annotate(args: argparse.Namespace, *, adjudicate: bool = False) -> int:
    tasks = _read_jsonl(args.tasks, OfflineAnnotationTask)
    candidate_labels = None
    if adjudicate:
        disagreements = json.loads(args.agreement.read_text(encoding="utf-8"))["disagreements"]
        disagreement_ids = {item["task_id"] for item in disagreements}
        candidate_labels = {
            item["task_id"]: {"first": item["first_labels"], "second": item["second_labels"]}
            for item in disagreements
        }
        tasks = tuple(task for task in tasks if task.task_id in disagreement_ids)
        status = "adjudicated"
    else:
        status = "final"
    with _exclusive_output_lock(args.output):
        asyncio.run(_annotate_batches(
            tasks, args.output, args.annotator_ref, reverse=args.reverse, status=status,
            candidate_labels=candidate_labels,
        ))
    print(json.dumps({"ok": True, "output": str(args.output), "count": len(tasks), "status": status}, ensure_ascii=False))
    return 0


def compare(args: argparse.Namespace) -> int:
    tasks = _read_jsonl(args.tasks, OfflineAnnotationTask)
    first = _read_jsonl(args.first, OfflineAnnotationRecord)
    second = _read_jsonl(args.second, OfflineAnnotationRecord)
    report = agreement_report(tasks, first, second)
    _write_json(args.output, report)
    disagreement_ids = {item["task_id"] for item in report["disagreements"]}
    _write_jsonl(args.output.with_name("disagreement_tasks.jsonl"), [task.model_dump(mode="json") for task in tasks if task.task_id in disagreement_ids])
    print(json.dumps({"ok": True, "task_count": len(tasks), "disagreement_count": report["disagreement_count"]}, ensure_ascii=False))
    return 0


def _load_human_validation_manifest(
    path: Path,
    agreement: dict[str, Any],
    first: tuple[OfflineAnnotationRecord, ...],
    second: tuple[OfflineAnnotationRecord, ...],
    adjudications: tuple[OfflineAnnotationRecord, ...],
) -> dict[str, Any]:
    """Load explicit human-review evidence without treating AI output as human evidence."""
    if not path.is_file():
        raise ValueError(f"human validation manifest does not exist: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "m4.human-validation.v1":
        raise ValueError("human validation manifest schema mismatch")
    if manifest.get("completed") is not True:
        raise ValueError("human validation manifest is not completed")
    if not str(manifest.get("attestation", "")).strip():
        raise ValueError("human validation manifest requires an attestation")

    reviewer_refs = tuple(str(value).strip() for value in (manifest.get("annotator_refs") or ()))
    if len(reviewer_refs) != 2 or len(set(reviewer_refs)) != 2:
        raise ValueError("human validation requires two distinct annotator refs")
    if any(not value or value.lower().startswith(("ai-", "deepseek-")) for value in reviewer_refs):
        raise ValueError("AI annotator refs cannot be declared as human reviewers")
    if set(agreement.get("annotators") or ()) != set(reviewer_refs):
        raise ValueError("human reviewer refs do not match the agreement evidence")
    if {record.annotator_ref for record in first + second} != set(reviewer_refs):
        raise ValueError("annotation streams are not bound to the declared human reviewers")

    adjudicator_ref = str(manifest.get("adjudicator_ref", "")).strip()
    if agreement.get("disagreement_count", 0):
        if not adjudicator_ref:
            raise ValueError("human adjudicator ref is required for disagreements")
        if adjudicator_ref.lower().startswith(("ai-", "deepseek-")):
            raise ValueError("AI adjudicator refs cannot be declared as human evidence")
        if {record.annotator_ref for record in adjudications} != {adjudicator_ref}:
            raise ValueError("adjudications are not bound to the declared human adjudicator")
    elif adjudications:
        raise ValueError("adjudications are not allowed when the agreement has no disagreements")

    return {
        "schema_version": "m4.human-validation.v1",
        "completed": True,
        "annotator_refs": list(reviewer_refs),
        "adjudicator_ref": adjudicator_ref or None,
        "agreement_verified": True,
        "manifest_path": str(path.resolve()),
        "attestation": str(manifest["attestation"]).strip(),
    }


def report(args: argparse.Namespace) -> int:
    tasks = _read_jsonl(args.tasks, OfflineAnnotationTask)
    first = _read_jsonl(args.first, OfflineAnnotationRecord)
    second = _read_jsonl(args.second, OfflineAnnotationRecord)
    adjudications = _read_jsonl(args.adjudications, OfflineAnnotationRecord) if args.adjudications.is_file() else ()
    agreement = agreement_report(tasks, first, second)
    resolved = resolve_annotations(tasks, first, second, adjudications)
    human_validation = None
    if args.method == "two_independent_human_annotators":
        if args.human_validation_manifest is None:
            raise ValueError("human validation method requires --human-validation-manifest")
        human_validation = _load_human_validation_manifest(
            args.human_validation_manifest, agreement, first, second, adjudications,
        )
    metrics = calculate_offline_metrics(
        tasks,
        resolved,
        method=args.method,
        human_validation=human_validation,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    _write_json(args.output / "agreement.json", agreement)
    _write_json(args.output / "metrics.json", metrics)
    _write_jsonl(args.output / "resolved_annotations.jsonl", [row.model_dump(mode="json") for row in resolved])
    files = {}
    for name in ("agreement.json", "metrics.json", "resolved_annotations.jsonl"):
        path = args.output / name
        files[name] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    manifest = {
        "schema_version": "m4.annotation-evidence-manifest.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": metrics["evaluation_method"], "publication_authorized": metrics["publication_authorized"],
        "task_count": len(tasks), "disagreement_count": agreement["disagreement_count"],
        "source_hashes": {
            "tasks": _sha256(args.tasks), "first": _sha256(args.first),
            "second": _sha256(args.second), "adjudications": _sha256(args.adjudications),
        },
        "files": files,
    }
    _write_json(args.output / "manifest.json", manifest)
    print(json.dumps({"ok": True, "output": str(args.output), "metrics": metrics}, ensure_ascii=False))
    return 0


def verify(args: argparse.Namespace) -> int:
    manifest = json.loads((args.input / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        path = args.input / name
        if not path.is_file() or _sha256(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            raise ValueError(f"evidence verification failed: {name}")
    print(json.dumps({"ok": True, "task_count": manifest["task_count"], "disagreement_count": manifest["disagreement_count"]}, ensure_ascii=False))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prepare_cmd = commands.add_parser("prepare")
    prepare_cmd.add_argument("--m4-db", type=Path, default=DEFAULT_M4_DB)
    prepare_cmd.add_argument("--m3-db", type=Path, default=DEFAULT_M3_DB)
    prepare_cmd.add_argument("--m3-report", type=Path, default=DEFAULT_M3_REPORT)
    prepare_cmd.add_argument("--run-id")
    prepare_cmd.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    for name in ("annotate", "adjudicate"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--tasks", type=Path, required=True)
        cmd.add_argument("--output", type=Path, required=True)
        cmd.add_argument("--annotator-ref", required=True)
        cmd.add_argument("--reverse", action="store_true")
        if name == "adjudicate":
            cmd.add_argument("--agreement", type=Path, required=True)
    compare_cmd = commands.add_parser("compare")
    compare_cmd.add_argument("--tasks", type=Path, required=True)
    compare_cmd.add_argument("--first", type=Path, required=True)
    compare_cmd.add_argument("--second", type=Path, required=True)
    compare_cmd.add_argument("--output", type=Path, required=True)
    report_cmd = commands.add_parser("report")
    report_cmd.add_argument("--tasks", type=Path, required=True)
    report_cmd.add_argument("--first", type=Path, required=True)
    report_cmd.add_argument("--second", type=Path, required=True)
    report_cmd.add_argument("--adjudications", type=Path, required=True)
    report_cmd.add_argument("--output", type=Path, required=True)
    report_cmd.add_argument(
        "--method",
        choices=("two_isolated_ai_passes_with_ai_adjudication", "two_independent_human_annotators"),
        default="two_isolated_ai_passes_with_ai_adjudication",
    )
    report_cmd.add_argument("--human-validation-manifest", type=Path)
    verify_cmd = commands.add_parser("verify")
    verify_cmd.add_argument("--input", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    return {
        "prepare": prepare, "annotate": annotate,
        "adjudicate": lambda value: annotate(value, adjudicate=True),
        "compare": compare, "report": report, "verify": verify,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
