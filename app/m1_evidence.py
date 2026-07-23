"""M1 domain-pack seeding and trace evidence aggregation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.database import (
    DBAgentRun,
    DBArtifact,
    DBArtifactVersion,
    DBClaimCheck,
    DBDebateRound,
    DBDecisionRecord,
    DBDomainPack,
    DBDomainVersion,
    DBEvaluationRun,
    DBEvaluationCase,
    DBGenerationTask,
    DBJobTask,
    DBLearningEvent,
    DBProfileEvidence,
    DBProfileSnapshot,
    DBQualityCheck,
    DBSkillStandard,
)


ROOT = Path(__file__).resolve().parents[1]
M0 = ROOT / "outputs" / "M0_阶段0基线与架构契约"


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def seed_rag_domain_pack(session: Any) -> dict[str, int | str]:
    kp_gold = json.loads((M0 / "datasets" / "core_knowledge_points.json").read_text(encoding="utf-8"))
    pack = session.query(DBDomainPack).filter_by(domain_key=kp_gold["domain_id"]).first()
    if pack is None:
        pack = DBDomainPack(domain_key=kp_gold["domain_id"], title="RAG 工程与幻觉评测")
        session.add(pack)
        session.flush()
    payload = {
        "ontology": {"knowledge_points": kp_gold["points"]},
        "rules": {"coverage_rule": kp_gold["coverage_rule"]},
        "templates": {"artifact_types": ["lesson", "lab_guide", "tiered_quiz"]},
        "checkers": ["citation", "claim", "coverage", "runtime"],
        "evaluation_set": {"version": "evaluation-m0-0.1", "minimum_cases": 50},
        "dependencies": ["edumatrix-core>=1.1"],
    }
    version = session.query(DBDomainVersion).filter_by(domain_pack_id=pack.id, version=kp_gold["gold_version"]).first()
    if version is None:
        version = DBDomainVersion(domain_pack_id=pack.id, version=kp_gold["gold_version"])
        session.add(version)
    for key, value in payload.items():
        setattr(version, key, value)
    version.content_hash = _canonical_hash(payload)
    session.flush()
    pack.current_version_id = version.id

    jobs = [
        ("JOB-01", "核验来源、许可与版本"),
        ("JOB-02", "解析并保留文档结构"),
        ("JOB-03", "设计分块与元数据"),
        ("JOB-04", "构建混合检索与重排"),
        ("JOB-05", "实现引用约束生成"),
        ("JOB-06", "执行幻觉与覆盖评测"),
        ("JOB-07", "诊断检索和索引故障"),
        ("JOB-08", "验证隔离和安全降级"),
        ("JOB-09", "运行版本化评测集"),
        ("JOB-10", "诊断故障并恢复任务"),
        ("JOB-11", "执行交互技能验收"),
        ("JOB-12", "迁移企业培训标准"),
    ]
    for code, title in jobs:
        row = session.query(DBJobTask).filter_by(domain_version_id=version.id, code=code).first()
        if row is None:
            row = DBJobTask(domain_version_id=version.id, code=code)
            session.add(row)
        row.title = title
        row.inputs = ["course", "source_document"]
        row.outputs = ["artifact", "quality_check"]
        row.acceptance_rules = ["traceable", "versioned", "reviewable"]

    for level in ("foundation", "independent", "advanced"):
        row = session.query(DBSkillStandard).filter_by(
            domain_version_id=version.id, code="SKILL-RAG", level=level
        ).first()
        if row is None:
            row = DBSkillStandard(domain_version_id=version.id, code="SKILL-RAG", level=level)
            session.add(row)
        row.title = "RAG 应用工程"
        row.prerequisites = [] if level == "foundation" else ["SKILL-RAG:foundation"]
        row.job_task_codes = [code for code, _ in jobs]
        row.evidence_requirements = ["artifact", "hidden_test", "claim_check"]
        row.acceptance_rules = ["all_required_tasks_pass"]
    session.commit()
    return {"domain_pack_id": pack.id, "domain_version_id": version.id, "jobs": len(jobs), "skills": 3}


def seed_m0_evaluation_cases(session: Any, domain_version_id: str) -> int:
    path = M0 / "datasets" / "evaluation_cases.jsonl"
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        case = session.query(DBEvaluationCase).filter_by(
            case_code=item["case_id"], case_version="evaluation-m0-0.1"
        ).first()
        if case is None:
            case = DBEvaluationCase(
                case_code=item["case_id"], case_version="evaluation-m0-0.1",
                domain_version_id=domain_version_id, input_data={}, gold_data={},
                data_version="evaluation-m0-0.1", content_hash=_canonical_hash(item)
            )
            session.add(case)
        case.input_data = {
            "profile_id": item.get("profile_id"), "objective": item.get("objective"),
            "input": item.get("input"), "category": item.get("category"),
        }
        case.gold_data = {
            "gold": item.get("gold"), "kp": item.get("kp", []),
            "difficulty": item.get("difficulty"), "failure_branch": item.get("failure_branch"),
        }
        case.content_hash = _canonical_hash(item)
        count += 1
    session.commit()
    return count


def trace_bundle(session: Any, trace_id: str) -> dict[str, Any]:
    tasks = session.query(DBGenerationTask).filter_by(trace_id=trace_id).all()
    task_ids = [row.id for row in tasks]
    artifacts = session.query(DBArtifact).filter(DBArtifact.creating_task_id.in_(task_ids)).all() if task_ids else []
    artifact_ids = [row.id for row in artifacts]
    versions = session.query(DBArtifactVersion).filter(DBArtifactVersion.artifact_id.in_(artifact_ids)).all() if artifact_ids else []
    return {
        "trace_id": trace_id,
        "profile_snapshots": session.query(DBProfileSnapshot).filter_by(trace_id=trace_id).all(),
        "profile_evidence": session.query(DBProfileEvidence).filter_by(trace_id=trace_id).all(),
        "tasks": tasks,
        "agent_runs": session.query(DBAgentRun).filter_by(trace_id=trace_id).all(),
        "artifacts": artifacts,
        "artifact_versions": versions,
        "learning_events": session.query(DBLearningEvent).filter_by(trace_id=trace_id).all(),
        "quality_checks": session.query(DBQualityCheck).filter_by(trace_id=trace_id).all(),
        "claim_checks": session.query(DBClaimCheck).filter_by(trace_id=trace_id).all(),
        "debate_rounds": session.query(DBDebateRound).filter_by(trace_id=trace_id).all(),
        "decisions": session.query(DBDecisionRecord).filter_by(trace_id=trace_id).all(),
        "evaluation_runs": session.query(DBEvaluationRun).filter_by(trace_id=trace_id).all(),
    }


_TRACE_OBJECT_TYPES = {
    "profile_snapshots": "profile_snapshot",
    "profile_evidence": "profile_evidence",
    "tasks": "generation_task",
    "agent_runs": "agent_run",
    "artifacts": "artifact",
    "artifact_versions": "artifact_version",
    "learning_events": "learning_event",
    "quality_checks": "quality_check",
    "claim_checks": "claim_check",
    "debate_rounds": "debate_round",
    "decisions": "decision_record",
    "evaluation_runs": "evaluation_run",
}


def trace_bundle_summary(session: Any, trace_id: str) -> dict[str, Any] | None:
    """Return a non-content internal trace index suitable for an operator API."""
    bundle = trace_bundle(session, trace_id)
    if not any(bundle[key] for key in _TRACE_OBJECT_TYPES):
        return None
    safe_fields = (
        "id", "trace_id", "owner_public_id", "task_id", "artifact_id",
        "artifact_version_id", "profile_snapshot_id", "object_type", "object_id",
        "source_ref_id", "output_artifact_version_id", "event_type", "check_type",
        "decision_type", "role", "capability", "status", "version_number",
        "profile_version", "evidence_version", "source_type", "source_object_id",
        "observed_at", "agent_version", "checker_version", "model_version",
        "code_version", "data_version", "created_at", "started_at", "completed_at",
    )
    groups = {}
    counts = {}
    for key, object_type in _TRACE_OBJECT_TYPES.items():
        rows = []
        for row in bundle[key]:
            item = {"object_type": object_type}
            for field in safe_fields:
                value = getattr(row, field, None)
                if value is None:
                    continue
                item[field] = value.isoformat() if hasattr(value, "isoformat") else value
            rows.append(item)
        groups[key] = rows
        counts[key] = len(rows)
    return {"trace_id": trace_id, "counts": counts, "groups": groups}
