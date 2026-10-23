"""Build the FC0 competition-functional matrix from POST-AUDIT evidence."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "route_traceability" / "route_task_matrix.jsonl"
OUT_DIR = ROOT / "outputs" / "FC_比赛功能完全体"
OUT = OUT_DIR / "02_比赛功能完成度矩阵.jsonl"

FUNCTIONAL_STATES = {
    "FUNCTION_COMPLETE",
    "FUNCTION_PARTIAL",
    "FUNCTION_MISSING",
    "ENGINEERING_REQUIRED",
    "EXTERNAL_PROOF_DEFERRED",
    "NOT_REQUIRED_FOR_COMPETITION",
}

EXTERNAL_MARKERS = (
    "真人", "人工验收", "人工复核", "专家金标", "企业专家", "第三方",
    "官方审批", "真实企业", "非开发机", "干净 Windows", "目标并发",
    "企业性能", "正式性能", "生产规模", "容量基线", "法律", "负责人确认",
)

PERFORMANCE_MARKERS = (
    "性能预算", "数据库索引", "向量容量", "前端性能", "媒体性能",
    "负载测试", "资源泄漏", "企业容量", "吞吐", "P50", "P95", "长时间运行",
)

FC1_IDS = {
    "S10-012", "S10-015", "S10-016", "S10-018", "S10-019",
    "S10-022", "S10-026", "S10-028", "S10-050",
}

FC2_IDS = {"S12-007", "S12-014", "S12-016", "S12-017", "S12-018"}

COMPLETED_FC_ROUTES = {
    "S10-012": "FC1-001",
    "S10-015": "FC1-002",
    "S10-016": "FC1-003",
    "S10-018": "FC1-004",
    "S10-019": "FC1-005",
    "S10-022": "FC1-006",
    "S10-026": "FC1-007",
    "S10-028": "FC1-008",
    "S10-050": "FC1-009",
    "S12-007": "FC2-001",
    "S12-014": "FC2-002",
    "S12-016": "FC2-003",
    "S12-017": "FC2-004",
    "S12-018": "FC2-005",
}

COMPLETION_EVIDENCE_OVERRIDES = {
    "S10-012": "outputs/NEXT_完全体主动开发/evidence/NC-MEDIA-02/browser-e2e/",
}


def completion_evidence(route_id: str) -> str:
    package = COMPLETED_FC_ROUTES[route_id]
    evidence_path = COMPLETION_EVIDENCE_OVERRIDES.get(
        route_id, f"outputs/FC_比赛功能完全体/evidence/{package}/"
    )
    if not (ROOT / evidence_path).exists():
        raise SystemExit(f"missing FC completion evidence for {route_id}: {evidence_path}")
    return f"outputs/FC_比赛功能完全体/01_FC_WORKLOG2.md#{package}; {evidence_path}"


def classify(row: dict) -> tuple[str, str, str]:
    route_id = row["route_id"]
    title = row["task_name"]
    detail = row["detailed_requirement"]
    text = f"{title} {detail}"
    audit_status = row["current_status"]

    if route_id in FC1_IDS:
        return "FUNCTION_MISSING", "FC1", "POST-AUDIT 明确延期但具有比赛展示价值，进入高呈现度媒体与交互开发。"
    if route_id in FC2_IDS:
        return "FUNCTION_MISSING", "FC2", "POST-AUDIT 明确识别为未覆盖市场能力，进入学习市场完整闭环。"
    if route_id == "S13-035":
        return "NOT_REQUIRED_FOR_COMPETITION", "NONE", "用户明确不要求 Docker；Windows 无 Docker 路径为比赛基线。"
    if audit_status == "EXTERNAL_BOUNDARY" or any(marker in text for marker in EXTERNAL_MARKERS):
        return "EXTERNAL_PROOF_DEFERRED", "NONE", "依赖真人、专家、真实企业、独立环境或责任审批，不阻塞比赛功能开发。"
    if any(marker in text for marker in PERFORMANCE_MARKERS):
        return "EXTERNAL_PROOF_DEFERRED", "NONE", "属于固定环境性能/容量证明，不是当前功能完成门禁。"
    if audit_status in {"FULLY_COVERED", "CAPABILITY_COVERED"}:
        return "FUNCTION_COMPLETE", "REGRESSION_ONLY", "已有 M/W 代码、API、持久化、UI 或自动证据；只做回归，不重复开发。"
    if audit_status == "PARTIALLY_COVERED":
        if row["route_phase"] in {13, 14}:
            return "ENGINEERING_REQUIRED", "FC6", "功能主链已有证据，阶段 13/14 的剩余要求转入最终工程与验收门禁。"
        return "FUNCTION_PARTIAL", "FC3", "需要在 FC3 逐项核对可见入口、数据链、权限、失败和恢复。"
    if audit_status == "PACKAGE_REBUILD_REQUIRED":
        return "NOT_REQUIRED_FOR_COMPETITION", "NONE", "正式压缩包重建需要用户另行授权，不属于当前功能开发。"
    if audit_status == "DEFERRED_BY_SCOPE":
        return "NOT_REQUIRED_FOR_COMPETITION", "NONE", "不属于当前比赛功能范围。"
    return "FUNCTION_PARTIAL", "FC3", "POST-AUDIT 证据不足，进入 FC3 逐项核查。"


def main() -> None:
    source_rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(source_rows) != 782 or len({row["route_id"] for row in source_rows}) != 782:
        raise SystemExit("POST-AUDIT matrix must contain 782 unique tasks")

    rows = []
    for source in source_rows:
        functional_status, work_package, rationale = classify(source)
        initial_functional_status = functional_status
        fc_completion_evidence = ""
        if source["route_id"] in COMPLETED_FC_ROUTES:
            work_package = COMPLETED_FC_ROUTES[source["route_id"]]
            functional_status = "FUNCTION_COMPLETE"
            fc_completion_evidence = completion_evidence(source["route_id"])
            rationale = (
                f"FC0 初始识别的功能缺口已由 {work_package} 完成真实 API、持久化、权限、"
                "失败/恢复、聚焦测试和浏览器证据，并在 FC WORKLOG2 中关闭为 PASS。"
            )
        row = dict(source)
        row.update({
            "post_audit_status": source["current_status"],
            "initial_functional_status": initial_functional_status,
            "functional_status": functional_status,
            "fc_work_package": work_package,
            "fc_completion_evidence": fc_completion_evidence,
            "functional_rationale": rationale,
            "competition_required": functional_status not in {"EXTERNAL_PROOF_DEFERRED", "NOT_REQUIRED_FOR_COMPETITION"},
            "implementation_required": functional_status in {"FUNCTION_MISSING", "FUNCTION_PARTIAL", "ENGINEERING_REQUIRED"},
            "display_requirement": "评委可见功能必须具有真实 API、持久化、权限、失败状态和刷新恢复。" if functional_status in {"FUNCTION_MISSING", "FUNCTION_PARTIAL"} else "保持既有真实性边界。",
        })
        if functional_status not in FUNCTIONAL_STATES:
            raise SystemExit(f"invalid functional status: {functional_status}")
        rows.append(row)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    counts = Counter(row["functional_status"] for row in rows)
    work_counts = Counter(row["fc_work_package"] for row in rows)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "task_count": len(rows),
        "unique_route_ids": len({row["route_id"] for row in rows}),
        "functional_status_counts": dict(counts),
        "work_package_counts": dict(work_counts),
        "fc1_route_ids": sorted(FC1_IDS),
        "fc2_route_ids": sorted(FC2_IDS),
        "completed_fc_route_ids": dict(sorted(COMPLETED_FC_ROUTES.items())),
        "unexplained_function_missing": [row["route_id"] for row in rows if row["functional_status"] == "FUNCTION_MISSING"],
        "unmapped_required_tasks": [row["route_id"] for row in rows if row["implementation_required"] and row["fc_work_package"] in {"NONE", "REGRESSION_ONLY"}],
    }
    (OUT_DIR / "02_比赛功能完成度摘要.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
