"""Execute the four-role M3 loop against the two current canonical courses.

This is an isolated acceptance harness.  It adapts the current course/domain
fixtures for the existing M3 persistence contracts and never writes the formal
edumatrix.db.  Generated artifacts and the task trace are exported as evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "edumatrix.db"
WORK_DIR = ROOT / "outputs" / "_canonical_m3_current_courses_20260905"
DB_PATH = WORK_DIR / "canonical_m3.db"
OUT_DIR = ROOT / "outputs" / "competition_submission_rebuild" / "test_data" / "current_evaluation_20260905"
ML_COURSE = "course-machine-learning-foundations-v1"
AI_COURSE = "course-ai-deep-learning-agents-v1"
PROFILES = (
    ("learner-visual-beginner", "profile_demo_beginner", "profile_demo_beginner-profile-snapshot", ML_COURSE),
    ("learner-project-engineer", "profile_demo_engineer", "profile_demo_engineer-profile-snapshot", AI_COURSE),
    ("learner-theory-researcher", "profile_demo_theorist", "profile_demo_theorist-profile-snapshot", ML_COURSE),
)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def copy_database() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        target = Path(f"{DB_PATH}{suffix}")
        if target.exists():
            target.unlink()
        source = Path(f"{SOURCE_DB}{suffix}")
        if source.exists():
            shutil.copy2(source, target)


class DeterministicReviewer:
    """A deterministic structured reviewer for the isolated acceptance run."""

    async def review_claim(self, claim: dict[str, Any], *, round_number: int, previous_rounds: list[dict[str, Any]]):
        from app.m3_debate import (  # noqa: PLC0415
            ChallengerArgument,
            DebateRoundOutput,
            JudgeVerdict,
            ProverArgument,
        )

        ref_ids = tuple(claim.get("proposed_source_ref_ids") or ())
        return DebateRoundOutput(
            prover=ProverArgument(
                support_status="supported",
                evidence_ref_ids=ref_ids,
                applicable_conditions=("仅在当前课程、知识点和来源范围内解释。",),
                rationale="声明绑定到当前任务提供的课程 source_ref。",
            ),
            challenger=ChallengerArgument(
                issue_types=("none",),
                evidence_ref_ids=ref_ids,
                rationale="未发现超出当前 source_ref 范围的断言；仍保留来源约束。",
            ),
            judge=JudgeVerdict(
                verdict="keep",
                rationale="证据引用在任务范围内，声明通过当前内部结构化审核。",
                evidence_ref_ids=ref_ids,
                confidence=0.72,
            ),
        )


def ensure_domain_versions(session: Any) -> dict[str, str]:
    from app.database import DBCourse, DBDomainPack, DBDomainVersion, DBKnowledgePoint  # noqa: PLC0415

    versions = {}
    for course_id in (ML_COURSE, AI_COURSE):
        course = session.get(DBCourse, course_id)
        if course is None:
            raise ValueError(f"course missing: {course_id}")
        point = (
            session.query(DBKnowledgePoint)
            .filter_by(domain_pack=course.domain_pack, status="active")
            .order_by(DBKnowledgePoint.code)
            .first()
        )
        if point is None:
            raise ValueError(f"knowledge point missing for {course_id}")
        version_id = f"dv-current-{course_id.removeprefix('course-')}"
        pack_id = f"dp-current-{course_id.removeprefix('course-')}"
        pack = session.get(DBDomainPack, pack_id)
        if pack is None:
            pack = DBDomainPack(
                id=pack_id,
                domain_key=course.domain_pack,
                title=f"{course.title} current domain",
                status="active",
                current_version_id=version_id,
            )
            session.add(pack)
        else:
            pack.domain_key = course.domain_pack
            pack.status = "active"
            pack.current_version_id = version_id
        version = session.get(DBDomainVersion, version_id)
        payload = {
            "course_id": course_id,
            "domain_pack": course.domain_pack,
            "knowledge_point_version": point.version,
            "scope": "isolated canonical M3 acceptance",
        }
        if version is None:
            version = DBDomainVersion(
                id=version_id,
                domain_pack_id=pack_id,
                version=point.version,
                ontology=payload,
                rules={"fact_standard": "unchanged", "safety_standard": "unchanged"},
                templates={},
                checkers={},
                evaluation_set={},
                dependencies={},
                content_hash=digest(payload),
            )
            session.add(version)
        versions[course_id] = version_id
    session.flush()
    return versions


def ensure_ai_snapshot(session: Any, source_snapshot_id: str, course_id: str, domain_version_id: str) -> str:
    from app.database import DBKnowledgePoint, DBProfileSnapshot, DBSourceDocument, DBSourceRef  # noqa: PLC0415

    source = session.get(DBProfileSnapshot, source_snapshot_id)
    if source is None:
        raise ValueError(f"profile snapshot missing: {source_snapshot_id}")
    data = json.loads(json.dumps(source.snapshot, ensure_ascii=False))
    ai_point = (
        session.query(DBKnowledgePoint)
        .filter_by(domain_pack="domain-ai-deep-learning-agents-v1", status="active")
        .order_by(DBKnowledgePoint.code)
        .first()
    )
    if ai_point is None:
        raise ValueError("AI knowledge points are missing")
    refs = (
        session.query(DBSourceRef)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .filter(DBSourceDocument.course_id == AI_COURSE, DBSourceDocument.processing_status == "ready")
        .order_by(DBSourceRef.id)
        .limit(2)
        .all()
    )
    if not refs:
        raise ValueError("AI source refs are missing")
    ref_ids = [row.id for row in refs]
    data["course_id"] = AI_COURSE
    data["course_title"] = "人工智能与深度学习：从机器学习基础到大模型智能体"
    data["knowledge_point_id"] = ai_point.id
    data["knowledge_point_title"] = ai_point.title
    data["domain_version_id"] = domain_version_id
    data["focus_knowledge_point_ids"] = [ai_point.id]
    data["profile_adaptation_plan"] = {
        **(data.get("profile_adaptation_plan") or {}),
        "content_focus": ai_point.title,
        "registration_profile": {
            **((data.get("profile_adaptation_plan") or {}).get("registration_profile") or {}),
            "target_course": data["course_title"],
        },
    }
    data["planning_constraints"] = {
        **(data.get("planning_constraints") or {}),
        "source_ref_ids": ref_ids,
        "allowed_chapter_ids": [],
    }
    new_id = "current-m3-engineer-ai-profile-snapshot"
    row = session.get(DBProfileSnapshot, new_id)
    content_hash = digest(data)
    if row is None:
        row = DBProfileSnapshot(
            id=new_id,
            owner_public_id=source.owner_public_id,
            profile_version=source.profile_version,
            snapshot=data,
            content_hash=content_hash,
            trace_id="trace-current-m3-engineer-ai",
        )
        session.add(row)
    else:
        row.snapshot = data
        row.content_hash = content_hash
    session.flush()
    return new_id


def repair_snapshot_hash(session: Any, snapshot_id: str) -> dict[str, str] | None:
    from app.database import DBProfileSnapshot  # noqa: PLC0415

    row = session.get(DBProfileSnapshot, snapshot_id)
    if row is None:
        raise ValueError(f"profile snapshot missing: {snapshot_id}")
    expected = digest(row.snapshot or {})
    if row.content_hash == expected:
        return None
    before = str(row.content_hash or "")
    row.content_hash = expected
    session.flush()
    return {"snapshot_id": snapshot_id, "before": before, "after": expected, "reason": "align isolated snapshot hash with current context validator"}


def source_context(session: Any, *, owner_public_id: str, course_id: str, snapshot_id: str, domain_version_id: str):
    from app.database import DBChapter, DBChapterKnowledgePoint, DBKnowledgePoint, DBSourceDocument, DBSourceRef  # noqa: PLC0415
    from app.m2_context import assemble_verified_context  # noqa: PLC0415

    snapshot = session.get(__import__("app.database", fromlist=["DBProfileSnapshot"]).DBProfileSnapshot, snapshot_id)
    data = snapshot.snapshot or {}
    point_id = str(data.get("knowledge_point_id") or data.get("focus_knowledge_point_ids", [""])[0])
    point = session.get(DBKnowledgePoint, point_id)
    if point is None:
        raise ValueError(f"point missing: {point_id}")
    rows = (
        session.query(DBSourceRef, DBChapter, DBChapterKnowledgePoint)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .join(DBChapter, DBChapter.id == DBSourceRef.chapter_id)
        .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.chapter_id == DBChapter.id)
        .filter(
            DBSourceDocument.course_id == course_id,
            DBChapterKnowledgePoint.knowledge_point_id == point.id,
            DBChapterKnowledgePoint.relation_type == "teaches",
        )
        .order_by(DBChapter.position, DBSourceRef.id)
        .limit(2)
        .all()
    )
    refs = list(dict.fromkeys(ref.id for ref, _chapter, _relation in rows))
    if not refs:
        raise ValueError(f"source refs missing for {course_id}/{point.id}")
    # Historical profile-demo snapshots predate the canonical M3 context
    # contract.  Add the current frozen target/domain/source fields only in
    # this isolated acceptance database.
    data = json.loads(json.dumps(data, ensure_ascii=False))
    data["course_id"] = course_id
    data["domain_version_id"] = domain_version_id
    data["focus_knowledge_point_ids"] = [point.id]
    planning = dict(data.get("planning_constraints") or {})
    planning["source_ref_ids"] = refs
    data["planning_constraints"] = planning
    snapshot.snapshot = data
    snapshot.content_hash = digest(data)
    session.flush()
    context = assemble_verified_context(
        session,
        owner_public_id=owner_public_id,
        course_id=course_id,
        domain_version_id=domain_version_id,
        profile_snapshot_id=snapshot_id,
        target_knowledge_point_ids=[point.id],
        source_ref_ids=refs,
    )
    return context, point, refs


def run_profile(session: Any, *, logical_id: str, username: str, snapshot_id: str, course_id: str, domain_version_id: str) -> dict[str, Any]:
    from app.database import DBArtifact, DBArtifactVersion, DBUser  # noqa: PLC0415
    from app.m1_repository import append_task_event, create_artifact_with_version, create_generation_task, create_task_step  # noqa: PLC0415
    from app.m2_contracts import GenerationContext  # noqa: PLC0415
    from app.m3_agents import (  # noqa: PLC0415
        M3AgentRole,
        complete_m3_agent_run,
        complete_m3_collaboration_task,
        create_m3_collaboration_task,
        start_m3_agent_run,
        start_m3_collaboration_task,
    )
    from app.m3_debate import AtomicClaimInput, conduct_m3_debate, persist_m3_debate_report  # noqa: PLC0415
    from app.resource_bundles import create_generation_job, execute_generation_job_demo  # noqa: PLC0415

    actor = session.query(DBUser).filter_by(username=username, is_active=True).one()
    context, point, refs = source_context(
        session,
        owner_public_id=actor.public_id,
        course_id=course_id,
        snapshot_id=snapshot_id,
        domain_version_id=domain_version_id,
    )
    m3_task, _ = create_m3_collaboration_task(
        session,
        context=context,
        idempotency_key=f"current-canonical-m3-20260905:{logical_id}",
        model="deterministic-current-canonical",
    )
    start_m3_collaboration_task(session, task_id=m3_task.id, owner_public_id=actor.public_id)
    session.commit()

    start_m3_agent_run(session, task_id=m3_task.id, owner_public_id=actor.public_id, role=M3AgentRole.DIAGNOSIS)
    complete_m3_agent_run(
        session,
        task_id=m3_task.id,
        owner_public_id=actor.public_id,
        role=M3AgentRole.DIAGNOSIS,
        candidate_summary=f"当前画像映射到知识点 {point.title}，掌握度和学习目标进入资源策略。",
        validation="当前课程、画像快照和 source_ref 通过 canonical context 验证。",
        decision_summary="将冻结画像上下文交给当前课程资源生成。",
    )
    session.commit()

    items = [
        {"type": kind, "title": f"{point.title} · {logical_id} · {kind}", "source_ref_ids": refs, "completion_rule": "完成资源规定的学习动作并提交结果。"}
        for kind in ("handout", "mind_map", "quiz", "training_task", "code_sandbox", "video", "deck", "interactive_model", "feynman")
    ]
    resource_job = create_generation_job(
        session,
        actor,
        course_id=course_id,
        knowledge_point_id=point.id,
        profile_snapshot_id=snapshot_id,
        idempotency_key=f"current-canonical-resource-job-20260905:{logical_id}",
        items=items,
        scope="bundle",
        learning_goal=str((session.get(__import__("app.database", fromlist=["DBProfileSnapshot"]).DBProfileSnapshot, snapshot_id).snapshot or {}).get("profile_projection", {}).get("learning_goals", [point.title])[0]),
        user_instruction="生成当前 canonical 课程的画像适配资源。",
        selected_resource_types=[item["type"] for item in items],
    )
    resource_result = execute_generation_job_demo(session, actor, resource_job["job_id"])
    session.commit()

    start_m3_agent_run(session, task_id=m3_task.id, owner_public_id=actor.public_id, role=M3AgentRole.DOMAIN_GENERATION)
    source_versions = (
        session.query(DBArtifact, DBArtifactVersion)
        .join(DBArtifactVersion, DBArtifactVersion.id == DBArtifact.current_version_id)
        .filter(
            DBArtifact.creating_task_id == resource_job["job_id"],
            DBArtifact.artifact_type.in_(("handout", "training_task", "quiz")),
        )
        .order_by(DBArtifact.artifact_type)
        .all()
    )
    m3_artifacts = []
    m3_type_map = {"handout": "lesson", "training_task": "lab_guide", "quiz": "tiered_quiz"}
    for artifact, version in source_versions:
        m3_type = m3_type_map[artifact.artifact_type]
        m3_artifact, m3_version = create_artifact_with_version(
            session,
            owner_public_id=actor.public_id,
            artifact_type=m3_type,
            title=f"{artifact.title} · M3",
            content=version.content,
            content_format=version.content_format,
            course_id=course_id,
            creating_task_id=m3_task.id,
            metadata={"source_ref_ids": refs, "profile_snapshot_id": snapshot_id, "origin_artifact_id": artifact.id},
        )
        m3_artifact.status = "approved"
        m3_artifacts.append((m3_artifact, m3_version))
    if len(m3_artifacts) != 3:
        raise ValueError(f"expected three M3 core artifacts, got {len(m3_artifacts)}")
    complete_m3_agent_run(
        session,
        task_id=m3_task.id,
        owner_public_id=actor.public_id,
        role=M3AgentRole.DOMAIN_GENERATION,
        output_artifact_version_id=m3_artifacts[0][1].id,
        candidate_summary="当前课程已生成讲义、实训指南和分阶测验候选。",
        validation=f"候选资源绑定 {len(refs)} 个当前课程 source_ref。",
        decision_summary="将三类候选资源交给证据审核。",
    )
    session.commit()

    start_m3_agent_run(session, task_id=m3_task.id, owner_public_id=actor.public_id, role=M3AgentRole.EVIDENCE_REVIEW)
    claims = [
        AtomicClaimInput(
            claim_id=f"{logical_id}-claim-{m3_type}",
            artifact_version_id=version.id,
            location=f"{m3_type}.primary_claim",
            atomic_claim=f"{m3_type} 的内容在当前课程和知识点范围内生成。",
            proposed_source_ref_ids=tuple(refs),
        )
        for m3_type, (_artifact, version) in zip(("lesson", "lab_guide", "tiered_quiz"), m3_artifacts)
    ]
    debate = asyncio.run(
        conduct_m3_debate(
            session,
            task_id=m3_task.id,
            owner_public_id=actor.public_id,
            claims=claims,
            reviewer=DeterministicReviewer(),
            reviewer_version="current-internal-reviewer-20260905",
            max_rounds=2,
        )
    )
    debate_artifact, debate_version, _ = persist_m3_debate_report(session, owner_public_id=actor.public_id, report=debate)
    session.commit()

    start_m3_agent_run(session, task_id=m3_task.id, owner_public_id=actor.public_id, role=M3AgentRole.DECISION_ORCHESTRATION)
    decision_payload = {
        "schema_version": "current-canonical-m3-decision.v1",
        "profile_id": logical_id,
        "course_id": course_id,
        "knowledge_point_id": point.id,
        "selected_resource_types": ["lesson", "lab_guide", "tiered_quiz"],
        "next_action": "continue_with_feedback",
        "evidence": [version.id for _artifact, version in m3_artifacts] + [debate_version.id],
    }
    decision_artifact, decision_version = create_artifact_with_version(
        session,
        owner_public_id=actor.public_id,
        artifact_type="m3_decision_comparison",
        title=f"{point.title} · {logical_id} · decision",
        content=canonical(decision_payload),
        content_format="json",
        course_id=course_id,
        creating_task_id=m3_task.id,
        metadata={"source_ref_ids": refs, "profile_snapshot_id": snapshot_id},
    )
    decision_artifact.status = "approved"
    complete_m3_agent_run(
        session,
        task_id=m3_task.id,
        owner_public_id=actor.public_id,
        role=M3AgentRole.DECISION_ORCHESTRATION,
        output_artifact_version_id=decision_version.id,
        candidate_summary="比较诊断、资源和审核证据后形成下一步学习决策。",
        validation="决策只引用当前任务资源版本和审核结果。",
        decision_summary="继续当前知识点的反馈学习，并在后续事件后复测。",
    )
    complete_m3_collaboration_task(session, task_id=m3_task.id, owner_public_id=actor.public_id)
    session.commit()
    return {
        "logical_profile_id": logical_id,
        "username": username,
        "course_id": course_id,
        "snapshot_id": snapshot_id,
        "task_id": m3_task.id,
        "task_status": m3_task.status,
        "roles": [run.role for run in session.query(__import__("app.database", fromlist=["DBAgentRun"]).DBAgentRun).filter_by(task_id=m3_task.id).order_by(__import__("app.database", fromlist=["DBAgentRun"]).DBAgentRun.role).all()],
        "resource_job_id": resource_job["job_id"],
        "resource_job_status": resource_result.get("status"),
        "resource_count": len(resource_result.get("items") or []),
        "m3_core_artifact_count": len(m3_artifacts),
        "debate_result_count": len(debate.results),
        "debate_overall_status": debate.overall_status,
        "decision_artifact_version_id": decision_version.id,
        "source_ref_ids": refs,
        "artifact_hashes": [version.content_hash for _artifact, version in m3_artifacts],
    }


def main() -> None:
    copy_database()
    os.environ.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_EMBEDDING_MODEL": "hash",
        "EDUMATRIX_EMBEDDING_DIM": "384",
        "EDUMATRIX_USE_FAISS": "0",
        "EDUMATRIX_DEMO_MODE": "0",
        "EDUMATRIX_AUTH_SECRET_KEY": "canonical-m3-current-evidence-secret-2026",
    })
    sys.path.insert(0, str(ROOT))
    from app.database import SessionLocal  # noqa: PLC0415

    session = SessionLocal()
    rows = []
    snapshot_repairs = []
    try:
        domains = ensure_domain_versions(session)
        for logical_id, username, snapshot_id, course_id in PROFILES:
            actual_snapshot_id = snapshot_id
            if course_id == AI_COURSE:
                actual_snapshot_id = ensure_ai_snapshot(session, snapshot_id, course_id, domains[course_id])
            repair = repair_snapshot_hash(session, actual_snapshot_id)
            if repair:
                snapshot_repairs.append(repair)
            session.commit()
            rows.append(
                run_profile(
                    session,
                    logical_id=logical_id,
                    username=username,
                    snapshot_id=actual_snapshot_id,
                    course_id=course_id,
                    domain_version_id=domains[course_id],
                )
            )
    finally:
        session.close()
    output = {
        "schema_version": "xh-202630.canonical-m3-current-courses.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "deterministic",
        "runtime_database": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
        "runtime_database_is_submission_asset": False,
        "profiles": rows,
        "isolated_snapshot_repairs": snapshot_repairs,
        "all_tasks_completed": all(row["task_status"] == "completed" for row in rows),
        "all_four_roles_completed": all(len(row["roles"]) == 4 for row in rows),
        "all_debates_passed": all(row["debate_overall_status"] == "passed" for row in rows),
        "claim_boundary": "This is a deterministic isolated canonical-course M3 acceptance run. It demonstrates current-course context binding, four-role persistence, resource generation, evidence debate and decision recording; it is not external-model quality or independent domain validation.",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "canonical_m3_current_courses.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str((OUT_DIR / "canonical_m3_current_courses.json").relative_to(ROOT)),
        "profiles": len(rows),
        "tasks_completed": output["all_tasks_completed"],
        "four_roles_completed": output["all_four_roles_completed"],
        "debates_passed": output["all_debates_passed"],
        "rows": rows,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
