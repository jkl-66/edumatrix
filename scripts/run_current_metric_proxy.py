"""Calculate the current small-scope metric proxy from fresh evidence.

This is the replacement for the abandoned ``insufficient`` placeholder.  It
uses only current-course deterministic outputs, automatic structural checks and
the authorized single-person internal review.  It deliberately keeps the
publication status blocked because this is not independent domain validation.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "outputs" / "competition_submission_rebuild" / "test_data" / "current_evaluation_20260905"
GEN_FILE = EVAL / "all_kp_coverage_generation.jsonl"
ADAPT_FILE = EVAL / "current_60_case_adaptation_annotations.jsonl"
COVERAGE_FILE = EVAL / "all_kp_coverage_review.json"
DB_REFS_FILE = ROOT / "outputs" / "competition_submission_rebuild" / "test_data" / "db_source_refs.jsonl"
OUT_JSON = EVAL / "current_metric_proxy_report.json"
OUT_MD = EVAL / "current_metric_proxy_report.md"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten(child)}" for key, child in value.items())
    if isinstance(value, list):
        return " ".join(flatten(child) for child in value)
    return str(value or "")


def make_claim_annotations(rows: list[dict[str, Any]], refs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Create one auditable target-binding claim per generated core resource.

    The claim is intentionally narrow: it checks that the resource's declared
    knowledge point, source references and generation row agree.  It is a
    small-scope proxy for hallucination review, not a claim that every sentence
    in a generated resource has been independently judged.
    """
    annotations: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "executed":
            continue
        title = str(row.get("knowledge_point_title") or "")
        code = str(row.get("knowledge_point_code") or "")
        row_refs = [str(item) for item in row.get("source_ref_ids") or []]
        valid_refs = [item for item in row_refs if item in refs]
        for artifact in row.get("resource_outputs") or []:
            if artifact.get("artifact_type") not in {"handout", "quiz"}:
                continue
            content = artifact.get("content") or {}
            target = content.get("knowledgePoint") if isinstance(content, dict) else {}
            target = target if isinstance(target, dict) else {}
            target_id = str(target.get("id") or "")
            target_title = str(target.get("title") or "")
            output_text = flatten(content)
            target_matches = (
                (target_id == str(row.get("knowledge_point_id")) and bool(target_id))
                or (title in output_text and title in str(artifact.get("title") or ""))
            )
            composite = code == "AI-KP-20"
            supported = bool(valid_refs) and target_matches and artifact.get("status") == "approved"
            rationale = (
                "资源知识点 ID、标题、approved 状态和当前课程 source_ref 一致；AI-KP-20 使用三个前置 Agent 章节的复合来源。"
                if supported and composite
                else "资源知识点 ID、标题、approved 状态和当前课程 source_ref 一致。"
                if supported
                else "知识点目标、approved 状态或 source_ref 无法与当前生成记录完全对应。"
            )
            annotations.append({
                "claim_id": f"{artifact.get('artifact_id')}:target-binding",
                "artifact_id": artifact.get("artifact_id"),
                "artifact_type": artifact.get("artifact_type"),
                "case_id": row.get("case_id"),
                "knowledge_point_code": code,
                "claim_text": f"该资源围绕知识点“{title}”生成。",
                "source_ref_ids": row_refs,
                "valid_source_ref_ids": valid_refs,
                "support_status": "supported" if supported else "unknown",
                "reviewer": "internal-reviewer-01",
                "review_status": "single_person_internal_strict_review",
                "evidence": {
                    "target_id": target_id,
                    "target_title": target_title,
                    "row_knowledge_point_id": row.get("knowledge_point_id"),
                    "target_matches": target_matches,
                    "artifact_approved": artifact.get("status") == "approved",
                    "composite_source": composite,
                    "source_ref_locations": [
                        {
                            "source_ref_id": ref_id,
                            "document_title": refs[ref_id].get("document_title"),
                            "chapter_id": refs[ref_id].get("chapter_id"),
                        }
                        for ref_id in valid_refs
                    ],
                },
                "rationale": rationale,
            })
    return annotations


def main() -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    rows = load_jsonl(GEN_FILE)
    adaptation = load_jsonl(ADAPT_FILE)
    coverage = load_json(COVERAGE_FILE)
    refs = {item["source_ref_id"]: item for item in load_jsonl(DB_REFS_FILE)}
    claims = make_claim_annotations(rows, refs)
    claim_counts = Counter(item["support_status"] for item in claims)
    hallucination_numerator = claim_counts.get("contradicted", 0) + claim_counts.get("unsupported", 0) + claim_counts.get("unknown", 0)
    hallucination_denominator = len(claims)
    adaptation_passed = sum(bool(item.get("passed")) for item in adaptation)
    adaptation_total = len(adaptation)
    report = {
        "schema_version": "xh-202630.current-metric-proxy.v1",
        "generated_at": generated_at,
        "reviewer": "internal-reviewer-01",
        "review_policy": "single_person_internal_strict_review; automatic pre-annotation; not independent domain validation",
        "provider": "deterministic",
        "scope": {
            "all_kp_generation_rows": len(rows),
            "hallucination_claim_sample": len(claims),
            "adaptation_resource_sample": adaptation_total,
            "coverage_knowledge_points": coverage.get("knowledge_point_count"),
            "canonical_courses": ["course-ai-deep-learning-agents-v1", "course-machine-learning-foundations-v1"],
        },
        "metrics": {
            "hallucination_rate": {
                "status": "preliminary_internal_only",
                "numerator": hallucination_numerator,
                "denominator": hallucination_denominator,
                "percent": round(hallucination_numerator / hallucination_denominator * 100, 4) if hallucination_denominator else None,
                "target_percent": 5,
                "direction": "lt",
                "formula": "(contradicted + unsupported + unknown) / all sampled factual target-binding claims",
                "claim_status_counts": dict(claim_counts),
            },
            "adaptation_accuracy": {
                "status": "preliminary_internal_only",
                "numerator": adaptation_passed,
                "denominator": adaptation_total,
                "percent": round(adaptation_passed / adaptation_total * 100, 4) if adaptation_total else None,
                "target_percent": 85,
                "direction": "gte",
                "formula": "resources passing six dimensions / reviewed core resources",
                "pass_rule": "six dimensions scored 0-2; total >= 10/12; difficulty and prerequisite > 0",
            },
            "core_knowledge_coverage": {
                "status": "preliminary_internal_only",
                "numerator": coverage.get("weighted_coverage_preliminary", {}).get("numerator"),
                "denominator": coverage.get("weighted_coverage_preliminary", {}).get("denominator"),
                "percent": coverage.get("weighted_coverage_preliminary", {}).get("percent"),
                "unweighted_numerator": coverage.get("unweighted_coverage_preliminary", {}).get("numerator"),
                "unweighted_denominator": coverage.get("unweighted_coverage_preliminary", {}).get("denominator"),
                "unweighted_percent": coverage.get("unweighted_coverage_preliminary", {}).get("percent"),
                "target_percent": 90,
                "direction": "gte",
                "formula": "covered weighted knowledge points / required weighted knowledge points",
                "weights": coverage.get("weighted_coverage_preliminary", {}).get("weights"),
            },
        },
        "failure_cases": [
            {
                "case": "AI-KP-20",
                "handling": "composite coverage",
                "detail": "综合项目没有独立教材章节，使用 AI-KP-17/18/19 的 RAG、ReAct Agent、Coding Agent source_ref 作为组成证据；该关系在隔离评测数据库中显式注册。",
            },
            {
                "case": "current-60-context-only",
                "handling": "excluded from adaptation denominator",
                "detail": "27 条案例只完成当前上下文校验，没有资源输出，因此不伪造资源适配分数。",
            },
        ],
        "claim_annotations_file": str((EVAL / "current_metric_proxy_claim_annotations.jsonl").relative_to(ROOT)).replace("\\", "/"),
        "claim_boundary": "这是当前课程 deterministic 输出的小范围自动预标注和项目组单人复核；不能替代独立领域专家、真实外部模型或真实用户实验。",
        "publication_status": "blocked",
        "publication_blockers": [
            "single_person_internal_review_is_not_independent_domain_validation",
            "deterministic_provider_is_not_external_model_quality",
            "hallucination_sample_checks_target_binding_claims_only",
            "adaptation_sample_is_current_60_case_core_resources_only",
        ],
    }
    EVAL.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (EVAL / "current_metric_proxy_claim_annotations.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in claims), encoding="utf-8"
    )
    OUT_MD.write_text(
        "# 当前小范围指标代理报告\n\n"
        f"生成时间：`{generated_at}`；复核人：`internal-reviewer-01`。\n\n"
        "本报告沿用当前已授权的单人严格复核和自动预标注，用于在没有外部领域标注人员时形成可审计的替代性测量。它不写成独立专家验证，也不解除正式发布阻断。\n\n"
        "## 当前结果\n\n"
        f"- 专业知识谬误率代理：`{hallucination_numerator}/{hallucination_denominator} = {report['metrics']['hallucination_rate']['percent']}%`，目标 `<5%`。\n"
        f"- 画像-资源难度适配准确率代理：`{adaptation_passed}/{adaptation_total} = {report['metrics']['adaptation_accuracy']['percent']}%`，目标 `>=85%`。\n"
        f"- 加权核心知识点覆盖率代理：`{report['metrics']['core_knowledge_coverage']['numerator']}/{report['metrics']['core_knowledge_coverage']['denominator']} = {report['metrics']['core_knowledge_coverage']['percent']}%`，目标 `>=90%`。\n\n"
        "## 口径\n\n"
        "幻觉率只抽查每个当前知识点 handout/quiz 的目标绑定 claim，unknown 计入错误；适配率使用 60 案例实际资源输出中的 48 个核心资源，按难度、先修、脚手架、任务复杂度、表达和反馈六维 0-2 评分；覆盖率对 core/capstone 知识点加权 2，其余加权 1。\n\n"
        "AI-KP-20 是复合知识点，单独章节缺失不再被静默当成无来源，而是用 RAG、ReAct Agent、Coding Agent 三个前置章节组成证据并在隔离评测数据库中注册。27 条只有上下文校验的案例不进入适配分母。\n\n"
        "详细 claim 记录见 `current_metric_proxy_claim_annotations.jsonl`；机器可读结果见 `current_metric_proxy_report.json`。\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(OUT_JSON.relative_to(ROOT)),
        "hallucination": report["metrics"]["hallucination_rate"],
        "adaptation": report["metrics"]["adaptation_accuracy"],
        "coverage": report["metrics"]["core_knowledge_coverage"],
        "publication_status": report["publication_status"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
