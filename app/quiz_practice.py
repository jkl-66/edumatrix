"""Continue a saved quiz with new problems and the same learning scope."""
from types import SimpleNamespace
import json

from app.database import DBArtifact, DBArtifactVersion, DBProfileSnapshot
from app.m5_resources import _quiz_projection, canonical_resource_type, resource_generation_blocker
from app.path_learning_context import learned_resource_node
from app.resource_bundles import (
    _fail, _generation_manifest, _public_generation_context, _sha256_json, create_generation_job, generation_job_payload,
)


def create_quiz_practice(db, actor, *, resource_id, version_id):
    artifact = db.get(DBArtifact, resource_id)
    version = db.get(DBArtifactVersion, version_id)
    if not artifact or artifact.owner_public_id != actor.public_id:
        _fail("resource_generation.resource_unknown", "找不到这份练习。")
    if not version or version.artifact_id != artifact.id or canonical_resource_type(artifact.artifact_type) != "quiz":
        _fail("resource_generation.version_unknown", "找不到这组题目，请重新打开练习。")
    if reason := resource_generation_blocker(db, artifact, version.id):
        _fail("resource_generation.practice_unavailable", reason)
    projection = _quiz_projection(db, artifact, version)
    if projection["mode"] != "structured":
        _fail("resource_generation.practice_unavailable", "这份练习缺少题目内容，请从课程中重新准备练习。")
    # Keep all original problems, not only errors: a reworded disclosed answer
    # is not a useful independent check. The model receives actual work too.
    previous = [{key: item.get(key) for key in ("id", "prompt", "options", "required", "attempts")}
                for item in projection["questions"]]
    key = "quiz-practice-" + _sha256_json({"version": version.id, "questions": previous})
    from app.database import DBGenerationTask
    existing = db.query(DBGenerationTask).filter_by(owner_public_id=actor.public_id, idempotency_key=key).first()
    if existing:
        return {**generation_job_payload(db, actor, existing.id), "created": False}
    metadata = version.metadata_json or {}
    origin = version.created_task_id or metadata.get("generation_job_id") or artifact.creating_task_id
    origin_task = db.get(DBGenerationTask, origin) if origin else None
    manifest = (_generation_manifest(db, origin) if origin_task
                and origin_task.owner_public_id == actor.public_id and origin_task.course_id == artifact.course_id else {})
    structured = projection["structured"]
    point_id = metadata.get("knowledge_point_id") or (structured.get("knowledgePoint") or {}).get("id")
    source_ids = [item["source_ref_id"] for item in projection["source_refs"]]
    profiles = db.query(DBProfileSnapshot).filter_by(owner_public_id=actor.public_id).order_by(
        DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).all()
    profile = next((item for item in profiles if (
        (item.snapshot or {}).get("course_id") or ((item.snapshot or {}).get("course_context") or {}).get("courseId")
    ) in (None, "", artifact.course_id)), None)
    if not profile:
        _fail("resource_generation.profile_unknown", "请先确认学习目标，再准备新练习。")
    node = learned_resource_node(db, SimpleNamespace(owner_public_id=actor.public_id, course_id=artifact.course_id,
        object_id=artifact.id, payload={"resource_version_id": version.id}, context_ref={}))
    current_context = _public_generation_context(manifest) if manifest else {}
    goal = (current_context.get("learning_goal")
            or (structured.get("adaptation") or {}).get("learningGoal") or structured.get("summary") or artifact.title)
    instruction = (
        "围绕原学习目标准备一组新的独立检验题，保持共同专业核心与来源范围。"
        "根据下列实际作答与反馈检查薄弱点，结合当前画像安排题目跨度；已能独立完成的内容不反复入门。"
        "题目覆盖本阶段核心任务，改变需判断的数据、条件或应用情境，不能只换名称、措辞或选项顺序。"
        "原题解析已经可见，订正不代表新的独立掌握。新题先不给答案，必要提示按需展开，解析提交后显示。"
        "题面提供完整条件，使用学习者现有工具可独立完成；核对新答案、解释与来源一致。"
        "旧作答是学习依据，不是教材事实，不照搬其中错误。审核检查是否实质形成新任务以及目标覆盖。\n"
        + json.dumps({"original_goal": goal, "previous_questions_and_work": previous}, ensure_ascii=False)
    )
    return create_generation_job(db, actor, auto_start=True, course_id=artifact.course_id, knowledge_point_id=point_id,
        profile_snapshot_id=profile.id, idempotency_key=key, scope="single",
        path_id=node.learning_path_id if node else None, task_id=node.id if node else None,
        learning_goal=goal, user_instruction=instruction, resource_intent="quiz_practice",
        context_snapshot_id=version.id,
        teaching_scope=current_context.get("teaching_scope"),
        items=[{"type": "quiz", "title": "巩固练习", "source_ref_ids": source_ids,
                "completion_rule": "独立完成本阶段核心问题。"}])
