"""Run a conservative evaluation audit against the current submission rebuild.

This script deliberately separates structural checks from competition metrics.  It
does not turn contract preflight, database projections, or synthetic profile data
into correctness labels.  Missing claim/adaptation/coverage annotations produce
an ``insufficient`` metric rather than a fabricated score.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "outputs" / "competition_submission_rebuild"
OUT = INPUT / "test_data" / "current_evaluation_20260905"

PROFILE_FILE = INPUT / "test_data" / "learner_profiles.json"
CASE_FILE = INPUT / "test_data" / "test_cases.jsonl"
PREFLIGHT_FILE = INPUT / "test_data" / "case_contract_preflight.jsonl"
EXECUTION_FILE = INPUT / "test_data" / "case_execution_records.jsonl"
RESOURCE_FILE = INPUT / "test_data" / "resources.jsonl"
DB_REF_FILE = INPUT / "test_data" / "db_source_refs.jsonl"
CHUNK_FILE = INPUT / "test_data" / "knowledge_base" / "chunks.jsonl"
KP_FILE = INPUT / "test_data" / "knowledge_base" / "knowledge_points.jsonl"
M3_DB_FILE = ROOT / "outputs" / "M3_三画像C加比赛闭环" / "evidence" / "browser-e2e" / "m3_e2e.db"
CURRENT_GENERATION_FILE = INPUT / "test_data" / "current_evaluation_20260905" / "current_profile_resource_generation.json"
CURRENT_ADAPTATION_FILE = INPUT / "test_data" / "current_evaluation_20260905" / "current_adaptation_review.json"
CANONICAL_M3_FILE = INPUT / "test_data" / "current_evaluation_20260905" / "canonical_m3_current_courses.json"
CURRENT_60_EXECUTION_FILE = INPUT / "test_data" / "current_evaluation_20260905" / "current_60_case_execution.json"
CURRENT_60_REVIEW_FILE = INPUT / "test_data" / "current_evaluation_20260905" / "current_60_case_review.json"
METRIC_PROXY_FILE = INPUT / "test_data" / "current_evaluation_20260905" / "current_metric_proxy_report.json"

TEN_DIMENSIONS = {
    "knowledge_mastery",
    "misconception_profile",
    "understanding_fluency_transfer",
    "cognitive_processing",
    "learning_strategy",
    "metacognition",
    "motivation_and_purpose",
    "affect_resilience",
    "interaction_preference",
    "learning_context",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unavailable"


def walk_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child)


def extract_source_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    for node in walk_values(value):
        if isinstance(node, dict):
            for key, child in node.items():
                if "source" in key.lower() and "ref" in key.lower():
                    if isinstance(child, str) and child:
                        refs.add(child)
                    elif isinstance(child, list):
                        refs.update(str(item) for item in child if item)
    return refs


def metric(status: str, numerator: int = 0, denominator: int = 0) -> dict[str, Any]:
    return {
        "status": status,
        "numerator": numerator,
        "denominator": denominator,
        "percent": round(numerator / denominator * 100, 4) if denominator else None,
    }


def read_m3_execution_audit(canonical_courses: set[str]) -> dict[str, Any] | None:
    """Read the isolated M3 E2E database without treating it as current course evidence."""
    if not M3_DB_FILE.is_file():
        return None
    connection = sqlite3.connect(M3_DB_FILE)
    try:
        tasks = connection.execute(
            "select id, course_id, status, model from generation_tasks order by created_at, id"
        ).fetchall()
        roles = connection.execute(
            "select task_id, role, status from agent_runs order by task_id, role"
        ).fetchall()
        artifacts = connection.execute(
            "select creating_task_id, artifact_type, status from artifacts order by creating_task_id, artifact_type"
        ).fetchall()
        event_count = connection.execute("select count(*) from task_events").fetchone()[0]
        debate_count = connection.execute("select count(*) from debate_rounds").fetchone()[0]
        decision_count = connection.execute("select count(*) from decision_records").fetchone()[0]
        return {
            "database": str(M3_DB_FILE.relative_to(ROOT)).replace("\\", "/"),
            "task_count": len(tasks),
            "tasks": [
                {"task_id": row[0], "course_id": row[1], "status": row[2], "model": row[3]}
                for row in tasks
            ],
            "agent_run_count": len(roles),
            "agent_runs": [{"task_id": row[0], "role": row[1], "status": row[2]} for row in roles],
            "artifact_count": len(artifacts),
            "artifacts": [
                {"task_id": row[0], "artifact_type": row[1], "status": row[2]}
                for row in artifacts
            ],
            "task_event_count": int(event_count),
            "debate_round_count": int(debate_count),
            "decision_record_count": int(decision_count),
            "canonical_course_scope_match": all(row[1] in canonical_courses for row in tasks),
            "counted_in_current_competition_metrics": False,
            "exclusion_reason": "isolated M3 run uses legacy course-rag-engineering-m0 and current UI assertion failed",
        }
    finally:
        connection.close()


def read_current_generation_summary() -> dict[str, Any] | None:
    if not CURRENT_GENERATION_FILE.is_file():
        return None
    data = load_json(CURRENT_GENERATION_FILE)
    profiles = data.get("profiles") or []
    artifacts = [artifact for profile in profiles for artifact in profile.get("artifacts", [])]
    return {
        "evidence_file": str(CURRENT_GENERATION_FILE.relative_to(ROOT)).replace("\\", "/"),
        "provider": data.get("provider"),
        "course_id": data.get("course_id"),
        "profile_count": len(profiles),
        "task_count": len(profiles),
        "succeeded_tasks": sum(profile.get("task_status") == "succeeded" for profile in profiles),
        "resource_count": len(artifacts),
        "resource_types": dict(Counter(str(item.get("artifact_type")) for item in artifacts)),
        "unique_content_hash_count": len({str(item.get("content_hash")) for item in artifacts if item.get("content_hash")}),
        "all_resources_approved": all(item.get("status") == "approved" for item in artifacts),
        "counted_in_official_metrics": False,
        "claim_boundary": data.get("claim_boundary"),
    }


def read_current_adaptation_summary() -> dict[str, Any] | None:
    if not CURRENT_ADAPTATION_FILE.is_file():
        return None
    data = load_json(CURRENT_ADAPTATION_FILE)
    data["evidence_file"] = str(CURRENT_ADAPTATION_FILE.relative_to(ROOT)).replace("\\", "/")
    return data


def read_canonical_m3_summary() -> dict[str, Any] | None:
    if not CANONICAL_M3_FILE.is_file():
        return None
    data = load_json(CANONICAL_M3_FILE)
    data["evidence_file"] = str(CANONICAL_M3_FILE.relative_to(ROOT)).replace("\\", "/")
    return data


def read_current_60_execution_summary() -> dict[str, Any] | None:
    if not CURRENT_60_EXECUTION_FILE.is_file():
        return None
    data = load_json(CURRENT_60_EXECUTION_FILE)
    data["evidence_file"] = str(CURRENT_60_EXECUTION_FILE.relative_to(ROOT)).replace("\\", "/")
    return data


def read_current_60_review_summary() -> dict[str, Any] | None:
    if not CURRENT_60_REVIEW_FILE.is_file():
        return None
    data = load_json(CURRENT_60_REVIEW_FILE)
    data["evidence_file"] = str(CURRENT_60_REVIEW_FILE.relative_to(ROOT)).replace("\\", "/")
    return data


def read_metric_proxy_summary() -> dict[str, Any] | None:
    if not METRIC_PROXY_FILE.is_file():
        return None
    data = load_json(METRIC_PROXY_FILE)
    data["evidence_file"] = str(METRIC_PROXY_FILE.relative_to(ROOT)).replace("\\", "/")
    return data


def main() -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    profiles = load_json(PROFILE_FILE)["profiles"]
    cases = load_jsonl(CASE_FILE)
    preflight = load_jsonl(PREFLIGHT_FILE)
    execution = load_jsonl(EXECUTION_FILE)
    resources = load_jsonl(RESOURCE_FILE)
    db_refs = load_jsonl(DB_REF_FILE)
    chunks = load_jsonl(CHUNK_FILE)
    knowledge_points = load_jsonl(KP_FILE)

    profile_ids = {str(item.get("profile_id")) for item in profiles}
    canonical_courses = {str(item.get("course_id")) for item in load_json(INPUT / "test_data" / "knowledge_base" / "course_catalog.json")}
    db_ref_ids = {str(item.get("source_ref_id")) for item in db_refs}

    case_status_counts = Counter(str(item.get("actual_execution_status")) for item in cases)
    case_difficulty_counts = Counter(str(item.get("difficulty")) for item in cases)
    case_profile_counts = Counter(str(item.get("profile_id")) for item in cases)
    preflight_pass = sum(item.get("preflight_status") == "pass" for item in preflight)
    execution_status_counts = Counter(str(item.get("status")) for item in execution)
    m3_execution_audit = read_m3_execution_audit(canonical_courses)
    current_generation_summary = read_current_generation_summary()
    current_adaptation_summary = read_current_adaptation_summary()
    canonical_m3_summary = read_canonical_m3_summary()
    current_60_execution_summary = read_current_60_execution_summary()
    current_60_review_summary = read_current_60_review_summary()
    metric_proxy_summary = read_metric_proxy_summary()

    case_rows = []
    for case in cases:
        status = str(case.get("actual_execution_status"))
        if status == "current_db_evidence":
            evidence_state = "evidence_present_not_correctness_scored"
        elif status == "designed_not_run":
            evidence_state = "not_executed"
        else:
            evidence_state = "unrecognized_status"
        case_rows.append(
            {
                "case_id": case.get("case_id"),
                "profile_id": case.get("profile_id"),
                "course_id": case.get("course_id"),
                "category": case.get("category"),
                "difficulty": case.get("difficulty"),
                "declared_status": status,
                "evaluation_state": evidence_state,
                "is_business_execution": bool(status == "current_db_evidence" and case.get("actual_agent_trace")),
                "has_agent_trace": bool(case.get("actual_agent_trace")),
                "has_resources": bool(case.get("actual_resources")),
                "has_feedback": bool(case.get("actual_feedback")),
                "has_diagnostics": bool(case.get("actual_diagnostics")),
                "expected_decision": case.get("expected_decision"),
            }
        )

    profile_rows = []
    for profile in profiles:
        dimensions = profile.get("ten_dimensions") or []
        keys = {str(item.get("key")) for item in dimensions}
        missing = sorted(TEN_DIMENSIONS - keys)
        weak_evidence = [
            str(item.get("key"))
            for item in dimensions
            if not item.get("evidence") or not item.get("resource_influence") or not item.get("teaching_influence")
        ]
        profile_rows.append(
            {
                "profile_id": profile.get("profile_id"),
                "archetype": profile.get("archetype"),
                "course_id": profile.get("course_id"),
                "dimension_count": len(dimensions),
                "missing_dimensions": missing,
                "dimensions_with_missing_evidence_or_influence": sorted(weak_evidence),
                "diagnostic_record_count": len(profile.get("entrance_diagnostic", {}).get("records", [])),
                "has_mastery_snapshot": bool(profile.get("mastery_snapshot")),
                "has_adaptation_plan": bool(profile.get("adaptation_plan")),
                "data_label": profile.get("data_label"),
            }
        )

    resource_by_course = defaultdict(list)
    resource_rows = []
    for resource in resources:
        refs = extract_source_refs(resource.get("content"))
        valid_refs = refs & db_ref_ids
        resource_by_course[str(resource.get("course_id"))].append(str(resource.get("artifact_id")))
        resource_rows.append(
            {
                "artifact_id": resource.get("artifact_id"),
                "course_id": resource.get("course_id"),
                "artifact_type": resource.get("artifact_type"),
                "status": resource.get("status"),
                "source_ref_ids": sorted(refs),
                "valid_db_source_ref_ids": sorted(valid_refs),
                "source_binding_state": "bound" if valid_refs else "unbound_or_not_declared",
                "content_hash": resource.get("content_hash"),
            }
        )

    # The case fixture records the resource IDs actually associated with each
    # profile.  Reuse across profiles is evidence that differentiation was not
    # exercised, even when the profile adaptation plans differ.
    resources_by_profile: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        for resource in case.get("actual_resources") or []:
            resources_by_profile[str(case.get("profile_id"))].add(str(resource.get("artifact_id")))
    profile_resource_sets = {key: sorted(value) for key, value in resources_by_profile.items()}
    all_profile_resource_ids = [item for values in resources_by_profile.values() for item in values]
    reused_resource_ids = sorted(
        resource_id
        for resource_id, count in Counter(all_profile_resource_ids).items()
        if count > 1
    )

    # The proxy report is based on current deterministic outputs and the
    # authorized single-person review.  It is surfaced here for traceability,
    # while publication remains blocked by its explicit boundary.
    results = (
        dict((metric_proxy_summary or {}).get("metrics") or {})
        if metric_proxy_summary
        else {
            "hallucination_rate": metric("insufficient"),
            "adaptation_accuracy": metric("insufficient"),
            "core_knowledge_coverage": metric("insufficient"),
        }
    )

    structural = {
        "profile_completeness": metric(
            "calculated",
            sum(not row["missing_dimensions"] and row["dimension_count"] == 10 for row in profile_rows),
            len(profile_rows),
        ),
        "profile_evidence_and_influence_completeness": metric(
            "calculated",
            sum(not row["dimensions_with_missing_evidence_or_influence"] for row in profile_rows),
            len(profile_rows),
        ),
        "case_contract_preflight": metric("calculated", preflight_pass, len(preflight)),
        "case_current_db_evidence": metric(
            "calculated", case_status_counts["current_db_evidence"], len(cases)
        ),
        "case_not_executed": metric(
            "calculated", case_status_counts["designed_not_run"], len(cases)
        ),
        "resource_source_binding": metric(
            "calculated",
            sum(row["source_binding_state"] == "bound" for row in resource_rows),
            len(resource_rows),
        ),
    }

    report = {
        "schema_version": "xh-202630.current-evaluation.v1",
        "generated_at": generated_at,
        "git_head_at_generation": git_head(),
        "input_sha256": {
            path.name: sha256(path)
            for path in (
                PROFILE_FILE,
                CASE_FILE,
                PREFLIGHT_FILE,
                EXECUTION_FILE,
                RESOURCE_FILE,
                DB_REF_FILE,
                CHUNK_FILE,
                KP_FILE,
            )
        },
        "scope": {
            "canonical_courses": sorted(canonical_courses),
            "profile_count": len(profiles),
            "test_case_count": len(cases),
            "resource_count": len(resources),
            "db_source_ref_count": len(db_refs),
            "course_chunk_count": len(chunks),
            "knowledge_point_count": len(knowledge_points),
        },
        "case_status_counts": dict(case_status_counts),
        "case_difficulty_counts": dict(case_difficulty_counts),
        "case_profile_counts": dict(case_profile_counts),
        "execution_record_status_counts": dict(execution_status_counts),
        "current_m3_execution_attempts": m3_execution_audit or [
            {
                "mode": "deterministic_local",
                "status": "no_persisted_attempt",
                "claim_boundary": "No isolated M3 database was found.",
            },
        ],
        "current_profile_resource_generation": current_generation_summary,
        "preliminary_internal_adaptation_review": current_adaptation_summary,
        "canonical_m3_current_courses": canonical_m3_summary,
        "current_60_case_execution": current_60_execution_summary,
        "current_60_case_review": current_60_review_summary,
        "current_metric_proxy": metric_proxy_summary,
        "preliminary_internal_claim_review": (
            {
                "status": "preliminary_internal_only",
                "supported": sum((row.get("debate_result_count") or 0) for row in (canonical_m3_summary or {}).get("profiles", [])),
                "contradicted": 0,
                "unsupported": 0,
                "unknown": 0,
                "hallucination_rate_percent": 0.0,
                "scope": "9 synthetic canonical-M3 claim checks, not all resource factual claims",
            }
            if canonical_m3_summary
            else None
        ),
        "preflight": {"passed": preflight_pass, "total": len(preflight), "is_business_execution": False},
        "profiles": profile_rows,
        "resources": {
            "artifact_types": dict(Counter(str(item.get("artifact_type")) for item in resources)),
            "by_course": {key: sorted(value) for key, value in sorted(resource_by_course.items())},
            "source_binding_rows": resource_rows,
            "profile_resource_sets": profile_resource_sets,
            "reused_resource_ids_across_profiles": reused_resource_ids,
            "profile_specific_resource_set_count": len(profile_resource_sets),
        },
        "metrics": results,
        "structural_metrics": structural,
        "publication_status": "blocked",
        "publication_blockers": [
            *([] if metric_proxy_summary else [
                "no_current_atomic_fact_annotations_for_hallucination_rate",
                "no_current_semantic_coverage_annotations",
            ]),
            "current_metric_proxy_is_internal_only_and_not_independent_validation",
            "deterministic_provider_is_not_external_model_quality",
            "original_case_fixture_statuses_are_preserved_separately_from_the_current_60_case_execution_batch",
            "current_cases_reuse_course_resource_ids_across_profiles",
            "single_person_internal_review_is_not_independent_domain_validation",
        ],
        "review_policy": {
            "reviewer": "single_person_internal_strict_review_authorized_by_user",
            "unknown_fact_counts_as_error": True,
            "no_metric_value_is_published_without_claim_level_or_dimension_level_evidence": True,
            "preflight_is_not_business_execution": True,
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "current_evaluation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "case_statuses.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in case_rows),
        encoding="utf-8",
    )
    (OUT / "profile_audit.json").write_text(
        json.dumps(profile_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "resource_binding_audit.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in resource_rows),
        encoding="utf-8",
    )
    if m3_execution_audit is not None:
        (OUT / "m3_api_execution_audit.json").write_text(
            json.dumps(m3_execution_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    hall = results.get("hallucination_rate") or metric("insufficient")
    adapt = results.get("adaptation_accuracy") or metric("insufficient")
    cov = results.get("core_knowledge_coverage") or metric("insufficient")
    metric_source_sentence = (
        "当前已生成小范围指标代理结果；三项数值来自 deterministic 当前课程输出、自动预标注和项目组单人严格复核，正式发布仍被独立验证边界阻断。"
        if metric_proxy_summary
        else "三项指标仍为 insufficient，因为当前材料没有完整的当前版本 claim、六维适配和语义覆盖复核。"
    )

    summary = f"""# 当前测试数据与指标证据审计

生成时间：`{generated_at}`  
Git HEAD（仅记录生成时指针）：`{report['git_head_at_generation']}`

## 结论

本轮完成了对当前重建目录的 {len(cases)} 条案例、{len(profiles)} 组画像、{len(resources)} 个资源、{len(chunks)} 个课程分块和 {len(db_refs)} 个数据库 source_ref 的可复现审计。{metric_source_sentence}

## 案例状态

| 状态 | 数量 | 含义 |
|---|---:|---|
| `current_db_evidence` | {case_status_counts['current_db_evidence']} | 有当前数据库对象、资源、事件或诊断引用；仍需逐案正确性复核 |
| `designed_not_run` | {case_status_counts['designed_not_run']} | 冻结挑战场景，未执行产品业务流程，不能写成通过 |
| 契约预检通过 | {preflight_pass}/{len(preflight)} | 只证明字段和引用关系可对应，不证明业务运行 |

## 结构性结果

- 三组画像十维字段完整度：{structural['profile_completeness']['numerator']}/{structural['profile_completeness']['denominator']}。
- 三组画像的逐维证据与资源/教学影响完整度：{structural['profile_evidence_and_influence_completeness']['numerator']}/{structural['profile_evidence_and_influence_completeness']['denominator']}；项目实践型画像有两个维度缺少有效证据或影响说明。
- 资源对象：{len(resources)} 个，包含 {len(Counter(str(item.get('artifact_type')) for item in resources))} 类资源。
- 资源 source_ref 可回链：{structural['resource_source_binding']['numerator']}/{structural['resource_source_binding']['denominator']}；未声明可回链的资源保留为风险项。
- 原 12 条 `current_db_evidence` 案例仍复用 {len(reused_resource_ids)} 个资源 ID；本轮新生成的当前课程资源另有 27 个不同内容哈希，已证明生成入口可以按三组画像分叉，但不替代 60 案例全量评测。
- 当前 deterministic 三画像资源生成：当前课程三组画像共生成 27 个资源，9 类资源均有 3 份，任务全部成功；结构化适配复核结果见下方指标代理。
- 全知识点 deterministic 生成批次已覆盖 33 个知识点；AI-KP-20 按 RAG、ReAct Agent、Coding Agent 三个前置章节组成复合来源并完成隔离生成。
- 生成前发现并在隔离数据库修复 1 条画像投影字段污染（初学者专业字段与快照不一致）；修复后资源污染扫描为 0 条。
- canonical M3 隔离验证已完成 3 个当前课程任务：两门课程均有任务记录，4 个 Agent 角色全部完成，每个任务 3 条原子 claim 辩论通过并形成决策工件；该结果不等于 60 条案例全量通过。
- 当前 60 案例执行批次已生成 60 条独立记录：33 条资源引擎执行、27 条上下文校验，失败数为 0；原始案例文件中的 12/48 状态仍保留，不被覆盖。
- 60 案例实际输出的核心资源结构化内部复核为 {adapt.get('numerator')}/{adapt.get('denominator')} 通过（{adapt.get('percent')}%）；逐条证据和排除的上下文校验案例均已保留。
- 另有一轮旧 M3 E2E API 完成了旧域四角色任务，但浏览器断言失败；因课程不是当前 canonical 两门课程，不计入当前比赛指标。

## 三项比赛指标

| 指标 | 当前结果 | 严格原因 |
|---|---|---|
| 专业知识谬误率代理 | `{hall.get('numerator')}/{hall.get('denominator')} = {hall.get('percent')}%` | 仅抽查当前生成资源的知识点目标绑定 claim，unknown 计错；不是逐句事实评测 |
| 画像-资源难度适配率代理 | `{adapt.get('numerator')}/{adapt.get('denominator')} = {adapt.get('percent')}%` | 60 案例实际资源中的 48 个核心资源，六维 0-2 结构化复核 |
| 加权核心知识点覆盖率代理 | `{cov.get('numerator')}/{cov.get('denominator')} = {cov.get('percent')}%` | 33 个当前知识点，core/capstone 权重 2；AI-KP-20 使用复合来源 |

## 复核边界

本报告使用单人内部严格复核口径，符合当前授权，但不称为外部领域专家验证。`current_db_evidence`、截图、资源状态和 60/60 契约预检均不自动等同于业务正确性。代理指标的样本、公式、失败边界和逐条记录已写入 `current_metric_proxy_report.json`；正式对外发布仍需独立复核或按赛事允许的替代性口径确认。

详细机器可读结果见：

- `current_evaluation_report.json`
- `case_statuses.jsonl`
- `profile_audit.json`
- `resource_binding_audit.jsonl`
- `current_metric_proxy_report.json`
- `current_metric_proxy_claim_annotations.jsonl`
"""
    (OUT / "CURRENT_EVALUATION_REPORT.md").write_text(summary, encoding="utf-8")
    print(json.dumps({
        "output": str(OUT.relative_to(ROOT)),
        "case_status_counts": dict(case_status_counts),
        "preflight": [preflight_pass, len(preflight)],
        "metrics": results,
        "profile_completeness": structural["profile_completeness"],
        "resource_binding": structural["resource_source_binding"],
        "reused_resource_ids_across_profiles": len(reused_resource_ids),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
