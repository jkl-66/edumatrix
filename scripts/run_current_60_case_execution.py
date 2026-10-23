"""Execute the 60 current submission cases in an isolated deterministic run.

This harness exercises the current course context and resource-generation
engine.  Each case receives its own task/idempotency key.  Results are reported
as execution evidence, not as the competition's hallucination/adaptation/
coverage metrics unless the case supplies the required semantic annotations.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "edumatrix.db"
WORK_DIR = ROOT / "outputs" / "_current_60_case_execution_20260905"
DB_PATH = WORK_DIR / "current_60_cases.db"
INPUT = ROOT / "outputs" / "competition_submission_rebuild" / "test_data"
CASE_FILE = INPUT / "test_cases.jsonl"
PROFILE_FILE = INPUT / "learner_profiles.json"
OUT_DIR = INPUT / "current_evaluation_20260905"
ML_COURSE = "course-machine-learning-foundations-v1"
AI_COURSE = "course-ai-deep-learning-agents-v1"
PROFILE_SPECS = {
    "learner-visual-beginner": ("profile_demo_beginner", "profile_demo_beginner-profile-snapshot", ML_COURSE),
    "learner-project-engineer": ("profile_demo_engineer", "profile_demo_engineer-profile-snapshot", AI_COURSE),
    "learner-theory-researcher": ("profile_demo_theorist", "profile_demo_theorist-profile-snapshot", ML_COURSE),
}


def copy_database() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        target = Path(f"{DB_PATH}{suffix}")
        if target.exists():
            target.unlink()
        source = Path(f"{SOURCE_DB}{suffix}")
        if source.exists():
            shutil.copy2(source, target)


def resource_types_for(category: str) -> tuple[str, ...] | None:
    mapping = {
        "lesson_generation": ("handout",),
        "lab_generation": ("code_sandbox", "interactive_model", "training_task"),
        "tiered_quiz": ("quiz",),
        "sandbox": ("code_sandbox",),
        "evidence_review": ("handout", "quiz"),
        "decision": ("handout", "quiz"),
        "path_update": ("handout", "quiz"),
        "review_schedule": ("quiz",),
        "feedback": ("handout", "quiz"),
        "recovery": ("handout", "quiz"),
        "version_conflict": ("handout", "quiz"),
    }
    return mapping.get(category)


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
        "EDUMATRIX_AUTH_SECRET_KEY": "current-60-case-execution-secret-2026",
    })
    sys.path.insert(0, str(ROOT))
    from app.database import DBArtifact, DBArtifactVersion, DBProfileSnapshot, DBStudentProfile, DBUser, SessionLocal  # noqa: PLC0415
    from app.resource_bundles import create_generation_job, execute_generation_job_demo  # noqa: PLC0415
    from run_canonical_m3_current_courses import (  # noqa: PLC0415
        AI_COURSE as CANONICAL_AI_COURSE,
        digest,
        ensure_ai_snapshot,
        ensure_domain_versions,
        repair_snapshot_hash,
        source_context,
    )

    cases = [json.loads(line) for line in CASE_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    profile_fixtures = {
        item["profile_id"]: item
        for item in json.loads(PROFILE_FILE.read_text(encoding="utf-8")).get("profiles", [])
    }
    session = SessionLocal()
    rows: list[dict[str, Any]] = []
    try:
        domains = ensure_domain_versions(session)
        ai_snapshot_id = ensure_ai_snapshot(
            session,
            "profile_demo_engineer-profile-snapshot",
            CANONICAL_AI_COURSE,
            domains[CANONICAL_AI_COURSE],
        )
        session.commit()
        for case in cases:
            started = time.perf_counter()
            case_id = str(case["case_id"])
            logical_profile = str(case["profile_id"])
            username, original_snapshot_id, expected_course = PROFILE_SPECS[logical_profile]
            course_id = str(case.get("course_id") or expected_course)
            snapshot_id = ai_snapshot_id if course_id == AI_COURSE else original_snapshot_id
            category = str(case.get("category"))
            row: dict[str, Any] = {
                "case_id": case_id,
                "profile_id": logical_profile,
                "course_id": course_id,
                "category": category,
                "difficulty": case.get("difficulty"),
                "execution_mode": "current_context_validation",
                "status": "failed",
                "business_execution": False,
                "task_id": None,
                "resource_types": [],
                "resource_states": [],
                "source_ref_ids": [],
                "error": "",
            }
            try:
                repair_snapshot_hash(session, snapshot_id)
                # The AI course uses a derived snapshot because the original
                # demo snapshot predates the current course binding.  Carry
                # over the frozen project-engineer adaptation plan so the
                # generated resource is judged against the same learner
                # signals shown in the submission data.
                if logical_profile == "learner-project-engineer" and course_id == AI_COURSE:
                    fixture = profile_fixtures.get(logical_profile) or {}
                    snapshot = session.get(DBProfileSnapshot, snapshot_id)
                    fixture_plan = fixture.get("adaptation_plan") or {}
                    if snapshot is not None and fixture_plan:
                        snapshot_data = json.loads(json.dumps(snapshot.snapshot or {}, ensure_ascii=False))
                        snapshot_data["profile_adaptation_plan"] = fixture_plan
                        projection = dict(snapshot_data.get("profile_projection") or {})
                        for key in (
                            "major", "knowledge_base", "cognitive_style", "motivation_type",
                            "learning_goals", "interaction_preferences", "weak_points",
                        ):
                            if key in fixture:
                                continue
                            value = (fixture_plan.get("registration_profile") or {}).get(key)
                            if value not in (None, "", [], {}):
                                projection[key] = value
                        mastery = fixture.get("mastery_snapshot") or {}
                        if mastery.get("overall") is not None:
                            projection["overall_mastery"] = mastery["overall"]
                            projection["course_mastery"] = mastery["overall"]
                        concept_mastery = dict(projection.get("concept_mastery") or {})
                        if mastery.get("concept_mastery"):
                            concept_mastery.update(mastery["concept_mastery"])
                        target_id = snapshot_data.get("knowledge_point_id")
                        if target_id and mastery.get("overall") is not None:
                            concept_mastery[str(target_id)] = mastery["overall"]
                        if concept_mastery:
                            projection["concept_mastery"] = concept_mastery
                        snapshot_data["profile_projection"] = projection
                        snapshot.snapshot = snapshot_data
                        snapshot.content_hash = digest(snapshot_data)
                        live_profile = session.get(DBStudentProfile, username)
                        if live_profile is not None:
                            live_profile.concept_mastery = concept_mastery
                            live_profile.major = (fixture_plan.get("registration_profile") or {}).get("major") or live_profile.major
                            live_profile.knowledge_base = (fixture_plan.get("registration_profile") or {}).get("knowledge_base") or live_profile.knowledge_base
                            live_profile.cognitive_style = (fixture_plan.get("registration_profile") or {}).get("cognitive_style") or live_profile.cognitive_style
                            live_profile.motivation_type = (fixture_plan.get("registration_profile") or {}).get("motivation_type") or live_profile.motivation_type
                            live_profile.learning_goals = (fixture_plan.get("registration_profile") or {}).get("learning_goals") or live_profile.learning_goals
                            live_profile.interaction_preferences = (fixture_plan.get("registration_profile") or {}).get("interaction_preferences") or live_profile.interaction_preferences
                        session.flush()
                context, point, refs = source_context(
                    session,
                    owner_public_id=session.query(DBUser).filter_by(username=username, is_active=True).one().public_id,
                    course_id=course_id,
                    snapshot_id=snapshot_id,
                    domain_version_id=domains[course_id],
                )
                row["knowledge_point_id"] = point.id
                row["knowledge_point_title"] = point.title
                row["source_ref_ids"] = refs
                resource_types = resource_types_for(category)
                if resource_types is None:
                    # Non-generation categories execute the same canonical
                    # context/profile/source checks and are intentionally kept
                    # as validation evidence rather than fake generation runs.
                    row["status"] = "context_validated"
                    row["execution_mode"] = "current_context_validation"
                    row["business_execution"] = True
                else:
                    actor = session.query(DBUser).filter_by(username=username, is_active=True).one()
                    items = [
                        {
                            "type": resource_type,
                            "title": f"{point.title} · {case_id} · {resource_type}",
                            "source_ref_ids": refs,
                            "completion_rule": "完成资源规定的学习动作并提交结果。",
                        }
                        for resource_type in resource_types
                    ]
                    scope = "single" if len(items) == 1 else "bundle"
                    job = create_generation_job(
                        session,
                        actor,
                        course_id=course_id,
                        knowledge_point_id=point.id,
                        profile_snapshot_id=snapshot_id,
                        idempotency_key=f"current-60-case-20260905:{case_id}",
                        items=items,
                        scope=scope,
                        learning_goal=str(case.get("input", {}).get("goal", [point.title])[0]),
                        user_instruction=f"执行当前案例 {case_id} 的 deterministic 资源生成探针。",
                        selected_resource_types=list(resource_types),
                    )
                    result = execute_generation_job_demo(session, actor, job["job_id"])
                    row["execution_mode"] = "current_resource_engine_deterministic"
                    row["business_execution"] = True
                    row["task_id"] = job["job_id"]
                    row["resource_types"] = list(resource_types)
                    row["resource_states"] = [
                        {"type": item.get("type"), "state": item.get("state"), "failure": item.get("failure")}
                        for item in (result.get("items") or [])
                    ]
                    resource_rows = (
                        session.query(DBArtifact, DBArtifactVersion)
                        .join(DBArtifactVersion, DBArtifactVersion.id == DBArtifact.current_version_id)
                        .filter(DBArtifact.creating_task_id == job["job_id"])
                        .order_by(DBArtifact.artifact_type, DBArtifact.id)
                        .all()
                    )
                    row["resource_outputs"] = []
                    for artifact, version in resource_rows:
                        try:
                            content = json.loads(version.content) if isinstance(version.content, str) else version.content
                        except json.JSONDecodeError:
                            content = version.content
                        row["resource_outputs"].append({
                            "artifact_id": artifact.id,
                            "artifact_type": artifact.artifact_type,
                            "title": artifact.title,
                            "status": artifact.status,
                            "version_id": version.id,
                            "content_hash": version.content_hash,
                            "content": content,
                        })
                    row["status"] = "executed" if result.get("status") in {"completed", "succeeded"} else "execution_failed"
                session.commit()
            except Exception as exc:  # preserve the failure as evidence
                session.rollback()
                row["status"] = "execution_failed"
                row["error"] = f"{type(exc).__name__}: {str(exc)[:800]}"
            row["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
            rows.append(row)
    finally:
        session.close()

    generated_at = datetime.now(timezone.utc).isoformat()
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    output = {
        "schema_version": "xh-202630.current-60-case-execution.v1",
        "generated_at": generated_at,
        "provider": "deterministic",
        "runtime_database": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
        "runtime_database_is_submission_asset": False,
        "case_count": len(rows),
        "status_counts": status_counts,
        "business_execution_count": sum(bool(row["business_execution"]) for row in rows),
        "resource_engine_execution_count": sum(row["execution_mode"] == "current_resource_engine_deterministic" for row in rows),
        "context_validation_count": sum(row["execution_mode"] == "current_context_validation" for row in rows),
        "claim_boundary": "This batch executes current context validation and deterministic resource-generation tasks in an isolated database. It is evidence of current engine behavior, not external-model quality or independent human validation.",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "current_60_case_execution.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "current_60_case_execution.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    (OUT_DIR / "current_60_case_execution.md").write_text(
        "# 当前 60 案例 deterministic 执行批次\n\n"
        f"生成时间：`{generated_at}`；案例：{len(rows)}；状态：`{json.dumps(status_counts, ensure_ascii=False)}`。\n\n"
        f"资源引擎实际执行：{output['resource_engine_execution_count']} 条；当前上下文校验：{output['context_validation_count']} 条。\n\n"
        "本批次使用隔离数据库。`executed` 只表示当前 deterministic 引擎任务完成，不表示三项比赛指标达标；逐案详情见 `current_60_case_execution.jsonl`。\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str((OUT_DIR / "current_60_case_execution.json").relative_to(ROOT)), **output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
