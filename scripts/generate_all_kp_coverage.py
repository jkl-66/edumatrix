"""Generate a source-bound handout and quiz for every current course knowledge point."""

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
WORK_DIR = ROOT / "outputs" / "_all_kp_coverage_20260905"
DB_PATH = WORK_DIR / "all_kp_coverage.db"
DATA = ROOT / "outputs" / "competition_submission_rebuild" / "test_data"
OUT_DIR = DATA / "current_evaluation_20260905"
ML_COURSE = "course-machine-learning-foundations-v1"
AI_COURSE = "course-ai-deep-learning-agents-v1"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    import hashlib
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
        "EDUMATRIX_AUTH_SECRET_KEY": "all-kp-coverage-evidence-secret-2026",
    })
    sys.path.insert(0, str(ROOT))
    from app.database import (  # noqa: PLC0415
        DBArtifact,
        DBArtifactVersion,
        DBChapter,
        DBChapterKnowledgePoint,
        DBCourse,
        DBKnowledgePoint,
        DBProfileSnapshot,
        DBSourceDocument,
        DBSourceRef,
        DBUser,
        SessionLocal,
    )
    from app.resource_bundles import create_generation_job, execute_generation_job_demo  # noqa: PLC0415
    from run_canonical_m3_current_courses import ensure_domain_versions  # noqa: PLC0415

    session = SessionLocal()
    rows: list[dict[str, Any]] = []
    try:
        domains = ensure_domain_versions(session)
        base_profiles = {
            ML_COURSE: ("profile_demo_beginner", "profile_demo_beginner-profile-snapshot"),
            AI_COURSE: ("profile_demo_engineer", "profile_demo_engineer-profile-snapshot"),
        }
        kps = (
            session.query(DBKnowledgePoint)
            .filter(DBKnowledgePoint.domain_pack.in_(
                ["domain-machine-learning-foundations-v1", "domain-ai-deep-learning-agents-v1"]
            ))
            .order_by(DBKnowledgePoint.domain_pack, DBKnowledgePoint.code)
            .all()
        )
        for index, point in enumerate(kps, 1):
            course_id = ML_COURSE if point.domain_pack == "domain-machine-learning-foundations-v1" else AI_COURSE
            username, base_snapshot_id = base_profiles[course_id]
            actor = session.query(DBUser).filter_by(username=username, is_active=True).one()
            base_snapshot = session.get(DBProfileSnapshot, base_snapshot_id)
            if base_snapshot is None:
                raise ValueError(f"missing base snapshot: {base_snapshot_id}")
            snapshot_data = json.loads(json.dumps(base_snapshot.snapshot, ensure_ascii=False))
            snapshot_data["course_id"] = course_id
            snapshot_data["domain_version_id"] = domains[course_id]
            snapshot_data["knowledge_point_id"] = point.id
            snapshot_data["knowledge_point_title"] = point.title
            snapshot_data["focus_knowledge_point_ids"] = [point.id]
            plan = dict(snapshot_data.get("profile_adaptation_plan") or {})
            plan["content_focus"] = point.title
            snapshot_data["profile_adaptation_plan"] = plan
            if point.code == "AI-KP-20":
                # Register the capstone as a composite teaching target in the
                # isolated evaluation database.  The current course already
                # contains the three component chapters (RAG, ReAct Agent and
                # Coding Agent); this relation makes that prerequisite chain
                # visible to the same context validator used by the product.
                component_codes = ("AI-KP-17", "AI-KP-18", "AI-KP-19")
                component_chapters = (
                    session.query(DBChapter)
                    .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.chapter_id == DBChapter.id)
                    .join(DBKnowledgePoint, DBKnowledgePoint.id == DBChapterKnowledgePoint.knowledge_point_id)
                    .filter(
                        DBChapter.course_id == course_id,
                        DBKnowledgePoint.code.in_(component_codes),
                        DBChapterKnowledgePoint.relation_type == "teaches",
                    )
                    .order_by(DBChapter.position, DBChapter.id)
                    .all()
                )
                existing_links = {
                    chapter_id
                    for (chapter_id,) in session.query(DBChapterKnowledgePoint.chapter_id)
                    .filter(DBChapterKnowledgePoint.knowledge_point_id == point.id)
                    .all()
                }
                for chapter in component_chapters:
                    if chapter.id not in existing_links:
                        session.add(DBChapterKnowledgePoint(
                            chapter_id=chapter.id,
                            knowledge_point_id=point.id,
                            relation_type="teaches",
                        ))
                session.flush()
            chapters = (
                session.query(DBChapter)
                .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.chapter_id == DBChapter.id)
                .filter(
                    DBChapter.course_id == course_id,
                    DBChapterKnowledgePoint.knowledge_point_id == point.id,
                    DBChapterKnowledgePoint.relation_type == "teaches",
                )
                .order_by(DBChapter.position, DBChapter.id)
                .all()
            )
            ref_rows = (
                session.query(DBSourceRef, DBSourceDocument)
                .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
                .filter(
                    DBSourceRef.chapter_id.in_([chapter.id for chapter in chapters]),
                    DBSourceDocument.course_id == course_id,
                    DBSourceDocument.processing_status == "ready",
                )
                .order_by(DBSourceRef.id)
                .limit(2)
                .all()
            )
            refs = list(dict.fromkeys(ref.id for ref, _doc in ref_rows))
            # AI-KP-20 is a capstone assembled from the three preceding
            # agent-engineering chapters.  It has no standalone source file,
            # so bind the generation to those existing canonical chapters
            # instead of silently treating the capstone as source-less.
            if not refs and point.code == "AI-KP-20":
                composite_codes = ("AI-KP-17", "AI-KP-18", "AI-KP-19")
                composite_rows = (
                    session.query(DBSourceRef, DBSourceDocument)
                    .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
                    .join(DBChapter, DBChapter.id == DBSourceRef.chapter_id)
                    .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.chapter_id == DBChapter.id)
                    .join(DBKnowledgePoint, DBKnowledgePoint.id == DBChapterKnowledgePoint.knowledge_point_id)
                    .filter(
                        DBChapter.course_id == course_id,
                        DBKnowledgePoint.code.in_(composite_codes),
                        DBChapterKnowledgePoint.relation_type == "teaches",
                        DBSourceDocument.course_id == course_id,
                        DBSourceDocument.processing_status == "ready",
                    )
                    .order_by(DBKnowledgePoint.code, DBSourceRef.id)
                    .limit(6)
                    .all()
                )
                refs = list(dict.fromkeys(ref.id for ref, _doc in composite_rows))
            if not refs:
                rows.append({
                    "case_id": f"coverage-{index:03d}-{point.code}",
                    "course_id": course_id,
                    "knowledge_point_id": point.id,
                    "knowledge_point_code": point.code,
                    "knowledge_point_title": point.title,
                    "profile_owner": username,
                    "profile_snapshot_id": None,
                    "source_ref_ids": [],
                    "status": "source_unavailable",
                    "task_id": None,
                    "resource_outputs": [],
                    "error": f"source refs missing: {course_id}/{point.code}",
                    "duration_ms": 0.0,
                })
                continue
            snapshot_data["planning_constraints"] = {
                **(snapshot_data.get("planning_constraints") or {}),
                "source_ref_ids": refs,
            }
            snapshot_id = f"coverage-{course_id.removeprefix('course-')}-{point.code.lower()}"
            snapshot = session.get(DBProfileSnapshot, snapshot_id)
            if snapshot is None:
                snapshot = DBProfileSnapshot(
                    id=snapshot_id,
                    owner_public_id=base_snapshot.owner_public_id,
                    profile_version=base_snapshot.profile_version,
                    snapshot=snapshot_data,
                    content_hash=digest(snapshot_data),
                    trace_id=f"trace-{snapshot_id}",
                )
                session.add(snapshot)
            else:
                snapshot.snapshot = snapshot_data
                snapshot.content_hash = digest(snapshot_data)
            session.flush()
            items = [
                {
                    "type": resource_type,
                    "title": f"{point.title} · {point.code} · {resource_type}",
                    "source_ref_ids": refs,
                    "completion_rule": "完成资源规定的学习动作并提交结果。",
                }
                for resource_type in ("handout", "quiz")
            ]
            started = time.perf_counter()
            row: dict[str, Any] = {
                "case_id": f"coverage-{index:03d}-{point.code}",
                "course_id": course_id,
                "knowledge_point_id": point.id,
                "knowledge_point_code": point.code,
                "knowledge_point_title": point.title,
                "profile_owner": username,
                "profile_snapshot_id": snapshot_id,
                "source_ref_ids": refs,
                "status": "failed",
                "task_id": None,
                "resource_outputs": [],
            }
            try:
                job = create_generation_job(
                    session,
                    actor,
                    course_id=course_id,
                    knowledge_point_id=point.id,
                    profile_snapshot_id=snapshot_id,
                    idempotency_key=f"all-kp-coverage-20260905:{point.id}",
                    items=items,
                    scope="bundle",
                    learning_goal=f"掌握{point.title}并能完成一次可验证练习",
                    user_instruction="为当前知识点生成有来源约束的讲义和测验。",
                    selected_resource_types=["handout", "quiz"],
                )
                result = execute_generation_job_demo(session, actor, job["job_id"])
                row["task_id"] = job["job_id"]
                for artifact, version in (
                    session.query(DBArtifact, DBArtifactVersion)
                    .join(DBArtifactVersion, DBArtifactVersion.id == DBArtifact.current_version_id)
                    .filter(DBArtifact.creating_task_id == job["job_id"])
                    .order_by(DBArtifact.artifact_type)
                    .all()
                ):
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
            except Exception as exc:
                session.rollback()
                row["status"] = "execution_failed"
                row["error"] = f"{type(exc).__name__}: {str(exc)[:800]}"
            row["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
            rows.append(row)
    finally:
        session.close()

    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    output = {
        "schema_version": "xh-202630.all-kp-coverage-generation.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "deterministic",
        "course_ids": [ML_COURSE, AI_COURSE],
        "knowledge_point_count": len(rows),
        "status_counts": status_counts,
        "resource_count": sum(len(row.get("resource_outputs") or []) for row in rows),
        "runtime_database": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
        "runtime_database_is_submission_asset": False,
        "claim_boundary": "This batch demonstrates deterministic current-course resource generation for every rebuilt knowledge point. Coverage still requires semantic review of each resource and source excerpt.",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "all_kp_coverage_generation.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "all_kp_coverage_generation.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    (OUT_DIR / "all_kp_coverage_generation.md").write_text(
        "# 全知识点资源生成批次\n\n"
        f"知识点：{len(rows)}；资源：{output['resource_count']}；状态：`{json.dumps(status_counts, ensure_ascii=False)}`。\n\n"
        "资源运行在隔离数据库中，正式提交包不得包含该数据库。覆盖率仍需逐知识点语义复核后发布。\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str((OUT_DIR / "all_kp_coverage_generation.json").relative_to(ROOT)), **output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
