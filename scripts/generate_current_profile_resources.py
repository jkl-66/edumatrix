"""Generate current-course deterministic resources for the three demo profiles.

The source database is copied before imports and all writes go to an isolated
SQLite file under outputs/_current_profile_resource_generation_20260905.  The
exported JSON is evidence data; the runtime database is not a submission asset.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "edumatrix.db"
WORK_DIR = ROOT / "outputs" / "_current_profile_resource_generation_20260905"
DB_PATH = WORK_DIR / "current_profile_resources.db"
EXPORT_DIR = ROOT / "outputs" / "competition_submission_rebuild" / "test_data" / "current_evaluation_20260905"
COURSE_ID = "course-machine-learning-foundations-v1"
PROFILE_SPECS = (
    ("learner-visual-beginner", "profile_demo_beginner", "profile_demo_beginner-profile-snapshot"),
    ("learner-project-engineer", "profile_demo_engineer", "profile_demo_engineer-profile-snapshot"),
    ("learner-theory-researcher", "profile_demo_theorist", "profile_demo_theorist-profile-snapshot"),
)
RESOURCE_TYPES = (
    "handout", "mind_map", "quiz", "training_task", "code_sandbox",
    "video", "deck", "interactive_model", "feynman",
)


def main() -> None:
    if not SOURCE_DB.is_file():
        raise FileNotFoundError(SOURCE_DB)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        target = Path(f"{DB_PATH}{suffix}")
        if target.exists():
            target.unlink()
        source = Path(f"{SOURCE_DB}{suffix}")
        if source.exists():
            shutil.copy2(source, target)

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
        "EDUMATRIX_AUTH_SECRET_KEY": "current-profile-resource-evidence-secret-2026",
    })
    sys.path.insert(0, str(ROOT))

    from app.database import (  # noqa: PLC0415
        DBArtifact,
        DBArtifactVersion,
        DBChapter,
        DBChapterKnowledgePoint,
        DBKnowledgePoint,
        DBProfileSnapshot,
        DBStudentProfile,
        DBSourceDocument,
        DBSourceRef,
        DBUser,
        SessionLocal,
    )
    from app.resource_bundles import (  # noqa: PLC0415
        GENERATION_RESOURCE_TYPES,
        create_generation_job,
        execute_generation_job_demo,
    )

    session = SessionLocal()
    exported_profiles: list[dict] = []
    isolated_projection_repairs: list[dict[str, str]] = []
    try:
        for logical_id, username, snapshot_id in PROFILE_SPECS:
            actor = session.query(DBUser).filter_by(username=username, is_active=True).one()
            snapshot = session.query(DBProfileSnapshot).filter_by(id=snapshot_id).one()
            snapshot_data = snapshot.snapshot or {}
            if snapshot_data.get("course_id") != COURSE_ID:
                raise ValueError(f"{snapshot_id} is not bound to {COURSE_ID}")
            expected_major = str(snapshot_data.get("profile_projection", {}).get("major") or "").strip()
            projection = session.get(DBStudentProfile, username)
            if projection is not None and expected_major and str(projection.major or "").strip() != expected_major:
                isolated_projection_repairs.append({
                    "student_id": username,
                    "field": "major",
                    "before": str(projection.major or ""),
                    "after": expected_major,
                    "reason": "align isolated legacy projection with the current profile snapshot",
                })
                projection.major = expected_major
                session.flush()
            point_id = str(snapshot_data.get("knowledge_point_id") or "")
            point = session.get(DBKnowledgePoint, point_id)
            if point is None:
                raise ValueError(f"knowledge point missing: {point_id}")
            chapters = (
                session.query(DBChapter)
                .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.chapter_id == DBChapter.id)
                .filter(
                    DBChapter.course_id == COURSE_ID,
                    DBChapterKnowledgePoint.knowledge_point_id == point.id,
                    DBChapterKnowledgePoint.relation_type == "teaches",
                )
                .order_by(DBChapter.position, DBChapter.id)
                .all()
            )
            source_rows = (
                session.query(DBSourceRef, DBSourceDocument)
                .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
                .filter(
                    DBSourceRef.chapter_id.in_([chapter.id for chapter in chapters]),
                    DBSourceDocument.course_id == COURSE_ID,
                    DBSourceDocument.processing_status == "ready",
                )
                .order_by(DBSourceRef.id)
                .limit(4)
                .all()
            )
            source_ref_ids = list(dict.fromkeys(ref.id for ref, _doc in source_rows))
            if not source_ref_ids:
                raise ValueError(f"no source refs for {snapshot_id}")
            adaptation = snapshot_data.get("profile_adaptation_plan") or {}
            label = str(snapshot_data.get("profile_projection", {}).get("major") or logical_id)
            items = [
                {
                    "type": resource_type,
                    "title": f"{point.title} · {label} · {resource_type}",
                    "source_ref_ids": source_ref_ids,
                    "completion_rule": "完成资源规定的学习动作并提交结果。",
                }
                for resource_type in RESOURCE_TYPES
            ]
            task_payload = create_generation_job(
                session,
                actor,
                course_id=COURSE_ID,
                knowledge_point_id=point.id,
                profile_snapshot_id=snapshot.id,
                idempotency_key=f"current-profile-resource-evidence-20260905:{logical_id}",
                items=items,
                scope="bundle",
                learning_goal="；".join(snapshot_data.get("profile_projection", {}).get("learning_goals") or [point.title]),
                user_instruction=f"为{label}生成严格绑定课程来源的差异化学习资源。",
                selected_resource_types=list(RESOURCE_TYPES),
            )
            task_id = task_payload["job_id"]
            result = execute_generation_job_demo(session, actor, task_id)
            session.commit()
            artifact_rows = (
                session.query(DBArtifact, DBArtifactVersion)
                .join(DBArtifactVersion, DBArtifactVersion.id == DBArtifact.current_version_id)
                .filter(DBArtifact.creating_task_id == task_id)
                .order_by(DBArtifact.artifact_type)
                .all()
            )
            artifacts = []
            for artifact, version in artifact_rows:
                try:
                    content = json.loads(version.content) if isinstance(version.content, str) else version.content
                except json.JSONDecodeError:
                    content = version.content
                artifacts.append({
                    "artifact_id": artifact.id,
                    "artifact_type": artifact.artifact_type,
                    "title": artifact.title,
                    "status": artifact.status,
                    "version_id": version.id,
                    "content_hash": version.content_hash,
                    "content": content,
                })
            exported_profiles.append({
                "logical_profile_id": logical_id,
                "username": username,
                "snapshot_id": snapshot.id,
                "course_id": COURSE_ID,
                "knowledge_point_id": point.id,
                "knowledge_point_title": point.title,
                "source_ref_ids": source_ref_ids,
                "profile_adaptation_plan": adaptation,
                "task_id": task_id,
                "task_status": result.get("status"),
                "task_checkpoint": result.get("checkpoint"),
                "resource_count": len(artifacts),
                "artifacts": artifacts,
            })
    finally:
        session.close()

    generated_at = datetime.now(timezone.utc).isoformat()
    output = {
        "schema_version": "xh-202630.current-profile-resource-generation.v1",
        "generated_at": generated_at,
        "runtime_database": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
        "runtime_database_is_submission_asset": False,
        "provider": "deterministic",
        "course_id": COURSE_ID,
        "profiles": exported_profiles,
        "isolated_projection_repairs": isolated_projection_repairs,
        "claim_boundary": "Resources were generated in an isolated database using the current resource bundle deterministic path; this is not external-model quality or a human learning experiment.",
    }
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    (EXPORT_DIR / "current_profile_resource_generation.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output": str((EXPORT_DIR / "current_profile_resource_generation.json").relative_to(ROOT)),
        "profile_count": len(exported_profiles),
        "task_statuses": [item["task_status"] for item in exported_profiles],
        "resource_counts": [item["resource_count"] for item in exported_profiles],
        "task_ids": [item["task_id"] for item in exported_profiles],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
