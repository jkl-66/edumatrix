"""Deterministic lzz demo overlay for the complete embedded ML course."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any

from app.database import (
    DBAssessmentAttempt,
    DBAssessmentExam,
    DBAssessmentExamItem,
    DBAssessmentExamSitting,
    DBAssessmentExamVersion,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBArtifact,
    DBArtifactVersion,
    DBChapter,
    DBChapterKnowledgePoint,
    DBChatConversation,
    DBChatMessage,
    DBCourse,
    DBCourseMembership,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningPath,
    DBNote,
    DBNoteVersion,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBQuizRecord,
    DBReviewPlan,
    DBSourceDocument,
    DBSourceRef,
    DBStudentProfile,
    DBUser,
    DBWrongQuestion,
)
from app.resource_bundles import _deterministic_demo_content
from app.source_refs import chat_source_ref, project_source_ref
from course_catalog import load_versioned_course_bundle, upsert_course_bundle


ROOT = Path(__file__).resolve().parents[1]
COURSE_ID = "course-embedded-machine-learning-engineering-v2"
COURSE_MANIFEST_PATH = (
    ROOT / "data" / "curated" / "embedded_machine_learning_engineering_v2" / "course_manifest.json"
)
DEMO_SCOPE = "post-data-complete-course-v1"
TRACE_ID = "trace-postdata-lzz-complete-course-v1"
PROFILE_ID = "postdata-profile-lzz-eml-v1"
PLAN_ID = "postdata-plan-lzz-eml-v1"
PLAN_VERSION_ID = "postdata-plan-version-lzz-eml-v1"
PATH_ID = "postdata-path-lzz-eml-v1"
NOTE_ID = "postdata-note-lzz-eml-deployment"
NOTE_VERSION_ID = "postdata-note-version-lzz-eml-deployment-v1"
CONVERSATION_ID = "postdata-chat-lzz-eml-deployment"
EXAM_ID = "postdata-exam-lzz-eml-v1"
EXAM_VERSION_ID = "postdata-exam-version-lzz-eml-v1"
SITTING_ID = "postdata-exam-sitting-lzz-eml-v1"
FOCUS_CODE = "EML-KP-05"
FROZEN_AT = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)
VIDEO_RELATIVE_PATH = "curated/embedded_machine_learning_engineering_v2/media/课程导览_嵌入式机器学习工程实践.mp4"


RESOURCE_SPECS = (
    ("handout", "边缘异常检测与阈值治理个性化讲义"),
    ("mind_map", "异常检测阈值治理思维导图"),
    ("quiz", "异常检测与阈值治理测验题"),
    ("training_task", "设备侧异常检测实训任务书"),
    ("code_sandbox", "分类阈值校准代码沙盒"),
    ("video", "嵌入式机器学习课程导览视频"),
    ("deck", "异常检测与部署决策网页课件"),
    ("interactive_model", "分类阈值校准可交互模型"),
    ("feynman", "异常阈值治理费曼复述任务"),
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    raw = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resource_id(resource_type: str) -> str:
    return f"postdata-resource-eml-{resource_type.replace('_', '-')}"


def _resource_version_id(resource_type: str) -> str:
    return f"{_resource_id(resource_type)}-v1"


@lru_cache(maxsize=1)
def _course_bundle() -> dict[str, Any]:
    return load_versioned_course_bundle(COURSE_MANIFEST_PATH)


def _values_equal(current: Any, expected: Any) -> bool:
    if isinstance(current, datetime) and isinstance(expected, datetime):
        current = current.astimezone(timezone.utc).replace(tzinfo=None) if current.tzinfo else current
        expected = expected.astimezone(timezone.utc).replace(tzinfo=None) if expected.tzinfo else expected
    return current == expected


def _repair_row(
    db: Any,
    model: Any,
    row_id: Any,
    values: dict[str, Any],
    *,
    identity_fields: tuple[str, ...] = (),
) -> tuple[Any, int]:
    row = db.get(model, row_id)
    if row is None:
        row = model(id=row_id, **values)
        db.add(row)
        db.flush()
        return row, 1
    for field in identity_fields:
        if getattr(row, field) != values[field]:
            raise ValueError(f"post-data demo identity conflict: {model.__name__}:{row_id}:{field}")
    changed = False
    for field, value in values.items():
        if not _values_equal(getattr(row, field), value):
            setattr(row, field, value)
            changed = True
    if changed:
        db.flush()
    return row, int(changed)


def _course_bundle_ready(db: Any) -> bool:
    bundle = _course_bundle()
    course_data = bundle["course"]
    course = db.get(DBCourse, COURSE_ID)
    if course is None:
        return False
    for field in ("version", "title", "subject", "description", "domain_pack", "manifest_version"):
        if getattr(course, field) != course_data[field]:
            return False
    expected = {item["id"]: item for item in bundle["documents"]}
    rows = db.query(DBSourceDocument).filter_by(course_id=COURSE_ID).all()
    by_legacy_id = {row.legacy_document_id: row for row in rows}
    if set(by_legacy_id) != set(expected):
        return False
    return all(
        by_legacy_id[row_id].content_hash == item["content_hash"]
        and by_legacy_id[row_id].processing_status == "ready"
        for row_id, item in expected.items()
    )


def ensure_post_data_course(db: Any) -> int:
    """Ensure the curated bundle exists before the competition seed transaction starts."""
    if _course_bundle_ready(db):
        return 0
    upsert_course_bundle(db, _course_bundle())
    return 1


def _course_context(db: Any) -> dict[str, Any]:
    course = db.get(DBCourse, COURSE_ID)
    if course is None:
        raise ValueError("post-data demo course is unavailable")
    points = db.query(DBKnowledgePoint).filter_by(
        domain_pack=course.domain_pack, status="active",
    ).order_by(DBKnowledgePoint.code).all()
    points_by_code = {row.code: row for row in points}
    if set(points_by_code) != {f"EML-KP-{index:02d}" for index in range(1, 9)}:
        raise ValueError("post-data demo knowledge-point projection is incomplete")
    focus = points_by_code[FOCUS_CODE]
    linked_chapter_ids = [
        row.chapter_id for row in db.query(DBChapterKnowledgePoint).filter_by(
            knowledge_point_id=focus.id, relation_type="teaches",
        ).all()
    ]
    focus_chapters = db.query(DBChapter).filter(
        DBChapter.id.in_(linked_chapter_ids or ["-"]),
    ).order_by(DBChapter.position, DBChapter.id).all()
    main_pdf = db.query(DBSourceDocument).filter_by(
        course_id=COURSE_ID, file_format="pdf", processing_status="ready",
    ).order_by(DBSourceDocument.id).first()
    refs: list[DBSourceRef] = []
    if main_pdf is not None:
        ref = db.query(DBSourceRef).filter_by(source_document_id=main_pdf.id).order_by(DBSourceRef.id).first()
        if ref is not None:
            refs.append(ref)
    if focus_chapters:
        ref = db.query(DBSourceRef).filter_by(chapter_id=focus_chapters[0].id).order_by(DBSourceRef.id).first()
        if ref is not None and ref.id not in {item.id for item in refs}:
            refs.append(ref)
    if not refs:
        raise ValueError("post-data demo source references are unavailable")
    documents = {
        row.id: row for row in db.query(DBSourceDocument).filter(
            DBSourceDocument.id.in_([ref.source_document_id for ref in refs]),
        ).all()
    }
    chapters = {
        row.id: row for row in db.query(DBChapter).filter(
            DBChapter.id.in_([ref.chapter_id for ref in refs if ref.chapter_id] or ["-"]),
        ).all()
    }
    source_snapshots = []
    for ref in refs:
        source = documents[ref.source_document_id]
        chapter = chapters.get(ref.chapter_id)
        source_snapshots.append({
            "source_ref_id": ref.id,
            "source_document_id": source.id,
            "title": source.title,
            "location_kind": ref.location_kind,
            "location_label": ref.location_label or (chapter.title if chapter else source.title),
            "quote": ref.quote,
            "content_hash": ref.content_hash,
        })
    return {
        "course": course,
        "points": points,
        "points_by_code": points_by_code,
        "focus": focus,
        "focus_chapter": focus_chapters[0] if focus_chapters else None,
        "source_refs": refs,
        "source_snapshots": source_snapshots,
    }


def _profile_snapshot(context: dict[str, Any]) -> dict[str, Any]:
    points = context["points_by_code"]
    return {
        "schema_version": "postdata.profile.v1",
        "demo_scope": DEMO_SCOPE,
        "course_id": COURSE_ID,
        "mastery": 0.64,
        "participated": True,
        "attention": True,
        "mastered_knowledge_point_ids": [points[code].id for code in ("EML-KP-01", "EML-KP-02", "EML-KP-03")],
        "weak_knowledge_point_ids": [points[code].id for code in ("EML-KP-04", "EML-KP-05")],
        "concept_mastery": {row.id: score for row, score in zip(context["points"], (0.88, 0.76, 0.72, 0.48, 0.42, 0.61, 0.54, 0.57))},
        "misconception": {
            "label": "把离线验证最优阈值直接当作现场固定阈值",
            "knowledge_point_id": points["EML-KP-05"].id,
            "status": "confirmed_synthetic_demo",
        },
        "learning_goal": "完成从模型训练、量化部署到现场阈值治理的可追溯工程闭环。",
        "truthfulness": "frozen_synthetic_demo_data",
    }


def _ensure_profile(db: Any, *, owner: DBUser, context: dict[str, Any]) -> int:
    changed = 0
    snapshot = _profile_snapshot(context)
    _, delta = _repair_row(
        db,
        DBProfileSnapshot,
        PROFILE_ID,
        {
            "owner_public_id": owner.public_id,
            "legacy_student_id": owner.username,
            "profile_version": "postdata.profile.v1",
            "snapshot": snapshot,
            "content_hash": _hash(snapshot),
            "trace_id": TRACE_ID,
            "created_at": FROZEN_AT,
        },
        identity_fields=("owner_public_id",),
    )
    changed += delta
    mastery_scores = (0.88, 0.76, 0.72, 0.48, 0.42, 0.61, 0.54, 0.57)
    mastery = {row.title: score for row, score in zip(context["points"], mastery_scores)}
    evidence = {
        "source": "performance_signal",
        "origin": "frozen_synthetic_course_journey",
        "source_object_id": PROFILE_ID,
        "text": "基于嵌入式机器学习完整课程的冻结合成学习旅程构建，用于比赛功能演示。",
        "features": ["course_mastery", "assessment", "resource_completion", "review"],
        "weight": 1.0,
        "confidence": 0.92,
        "timestamp": FROZEN_AT.isoformat(),
        "version": "postdata.profile-evidence.v1",
        "trace_id": TRACE_ID,
        "demo_scope": DEMO_SCOPE,
        "snapshot_id": PROFILE_ID,
    }
    legacy = db.get(DBStudentProfile, owner.username)
    if legacy is None:
        legacy = DBStudentProfile(student_id=owner.username)
        db.add(legacy)
        db.flush()
        changed += 1
    existing_evidence = [
        item for item in (legacy.profile_evidence or [])
        if not (isinstance(item, dict) and item.get("demo_scope") == DEMO_SCOPE)
    ]
    desired = {
        "target_course": context["course"].title,
        "knowledge_base": "机器学习基础扎实，设备部署与阈值治理待加强",
        "cognitive_style": "图示理解 + 代码验证 + 工程检查点",
        "motivation_type": "项目成果驱动",
        "frustration_index": 0.21,
        "focus_level": 0.81,
        "cognitive_load": 0.56,
        "weak_points": [context["points_by_code"][code].title for code in ("EML-KP-04", "EML-KP-05")],
        "learning_goals": [
            "完成模型量化与设备部署检查",
            "能够解释阈值、误报与漏报之间的工程取舍",
            "形成可复现的边缘机器学习验证记录",
        ],
        "interaction_preferences": ["先看结构图", "再运行代码", "最后用测验和复述检查理解"],
        "concept_mastery": mastery,
        "misconception_patterns": {"离线阈值直接上线": 0.68, "只看准确率忽略设备约束": 0.44},
        "dimension_states": {
            "知识理解": {"score": 0.72, "confidence": 0.86},
            "工程应用": {"score": 0.55, "confidence": 0.78},
            "证据意识": {"score": 0.67, "confidence": 0.82},
        },
        "learning_state_causes": {
            "设备部署经验不足": {"label": "设备部署经验不足", "percentage": 42},
            "阈值治理证据偏少": {"label": "阈值治理证据偏少", "percentage": 35},
            "知识迁移仍在形成": {"label": "知识迁移仍在形成", "percentage": 23},
        },
        "history_logs": "已完成课程导论与训练工作流；正在推进量化部署和异常阈值治理。",
        "narrative_report": "你已经建立了边缘机器学习的基础工作流。下一步需要把离线指标转化为设备侧可验证的部署与阈值决策。",
        "dashboard_report": "当前课程总体掌握度 64%。量化部署与异常阈值治理是本轮重点，今日先完成代码校准，再进入实训与交互模型。",
        "major": "人工智能与电子信息工程",
        "profile_evidence": [*existing_evidence, evidence],
    }
    row_changed = False
    for field, value in desired.items():
        if getattr(legacy, field) != value:
            setattr(legacy, field, value)
            row_changed = True
    if row_changed:
        changed += 1
        db.flush()
    return changed


def _question_specs(context: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    points = context["points_by_code"]
    return (
        {
            "code": "q01",
            "point_id": points["EML-KP-04"].id,
            "prompt": "将训练好的 FP32 模型部署到资源受限设备前，哪项检查最能降低部署失败风险？",
            "options": ["只比较训练准确率", "同时检查量化误差、峰值内存、算子支持和设备时延", "删除验证集", "只压缩模型文件名"],
            "answer": "B",
            "explanation": "设备部署需要同时验证精度变化、内存、算子兼容和真实时延，不能只看训练准确率。",
            "bloom": "apply",
            "difficulty": 0.48,
        },
        {
            "code": "q02",
            "point_id": points["EML-KP-05"].id,
            "prompt": "异常检测系统在现场出现误报上升时，最合理的第一步是什么？",
            "options": ["立即把阈值调到最大", "检查现场数据分布、误报样本和当前阈值依据", "删除全部历史记录", "只汇报离线准确率"],
            "answer": "B",
            "explanation": "先回到现场分布、失败样本和阈值证据，才能判断是数据漂移、阈值不适配还是模型问题。",
            "bloom": "analyze",
            "difficulty": 0.56,
        },
        {
            "code": "q03",
            "point_id": points["EML-KP-05"].id,
            "prompt": "为什么同一个异常分数阈值不应未经复核直接用于所有设备和场景？",
            "options": ["因为阈值没有数值", "因为设备噪声、数据分布和误报成本可能不同", "因为模型不能输出分数", "因为阈值只能由教师查看"],
            "answer": "B",
            "explanation": "阈值是场景决策，不同设备、分布和误报成本会改变合理取值。",
            "bloom": "evaluate",
            "difficulty": 0.62,
        },
    )


def _ensure_questions_and_attempts(
    db: Any, *, owner: DBUser, context: dict[str, Any], source_ref_ids: list[str],
) -> tuple[list[str], int]:
    changed = 0
    version_ids: list[str] = []
    specs = _question_specs(context)
    for spec in specs:
        question_id = f"postdata-assessment-eml-{spec['code']}"
        version_id = f"{question_id}-v1"
        question, delta = _repair_row(
            db,
            DBAssessmentQuestion,
            question_id,
            {
                "course_id": COURSE_ID,
                "owner_public_id": owner.public_id,
                "question_type": "single_choice",
                "origin": "derived",
                "status": "approved",
                "current_version_id": version_id,
            },
            identity_fields=("course_id", "owner_public_id"),
        )
        changed += delta
        payload = {
            "prompt": spec["prompt"],
            "options": spec["options"],
            "answer_key": {"choice": spec["answer"]},
            "scoring_rule": {"version": "postdata-objective-v1", "correct_threshold": 1.0},
            "explanation": spec["explanation"],
            "primary_knowledge_point_id": spec["point_id"],
            "bloom_level": spec["bloom"],
            "source_ref_ids": source_ref_ids,
        }
        _, delta = _repair_row(
            db,
            DBAssessmentQuestionVersion,
            version_id,
            {
                "question_id": question.id,
                "version_number": 1,
                "prompt": spec["prompt"],
                "options": spec["options"],
                "answer_key": payload["answer_key"],
                "scoring_rule": payload["scoring_rule"],
                "explanation": spec["explanation"],
                "misconception_tags": ["deployment_boundary", "threshold_governance", "evidence_gap"],
                "primary_knowledge_point_id": spec["point_id"],
                "secondary_knowledge_point_ids": [],
                "bloom_level": spec["bloom"],
                "expert_difficulty": spec["difficulty"],
                "measured_difficulty": None,
                "irt_parameters": {"alpha_vector": [1.1, 0.35, 0.55], "beta_vector": [0.1, 0.3, 0.45], "gamma": 0.25},
                "sample_size": 0,
                "source_ref_ids": source_ref_ids,
                "content_hash": _hash(payload),
                "created_by_public_id": owner.public_id,
                "created_at": FROZEN_AT,
            },
            identity_fields=("question_id",),
        )
        changed += delta
        version_ids.append(version_id)

    attempts = (
        ("postdata-attempt-lzz-eml-q01", version_ids[0], {"choice": "B"}, 1.0, True, 42),
        ("postdata-attempt-lzz-eml-q02", version_ids[1], {"choice": "A"}, 0.0, False, 55),
    )
    for attempt_id, version_id, answer, score, correct, duration in attempts:
        _, delta = _repair_row(
            db,
            DBAssessmentAttempt,
            attempt_id,
            {
                "owner_public_id": owner.public_id,
                "course_id": COURSE_ID,
                "question_version_id": version_id,
                "idempotency_key": f"{DEMO_SCOPE}:{attempt_id}",
                "mode": "practice",
                "answer": answer,
                "score": score,
                "correct": correct,
                "confidence": 0.78 if correct else 0.66,
                "duration_seconds": duration,
                "grading_status": "graded",
                "feedback_policy": "immediate",
                "submitted_at": FROZEN_AT + timedelta(minutes=duration),
            },
            identity_fields=("owner_public_id", "question_version_id"),
        )
        changed += delta

    records = (
        ("postdata-quiz-record-lzz-eml-q01", specs[0], "B", 1.0, "advance", "量化部署检查项识别正确。"),
        ("postdata-quiz-record-lzz-eml-q02", specs[1], "A", 0.0, "review", "应先检查现场分布、误报样本和阈值依据。"),
    )
    for record_id, spec, answer, score, next_action, feedback in records:
        _, delta = _repair_row(
            db,
            DBQuizRecord,
            record_id,
            {
                "student_id": owner.username,
                "question": spec["prompt"],
                "student_answer": answer,
                "correct_answer": spec["answer"],
                "ai_confidence": 0.95,
                "student_confidence": 0.78 if score else 0.66,
                "accuracy_score": score,
                "target_concept": spec["point_id"],
                "feedback": feedback,
                "next_action": next_action,
                "attempt_number": 1,
                "session_id": "postdata-quiz-session-lzz-eml-v1",
                "options": spec["options"],
                "created_at": FROZEN_AT + timedelta(minutes=6 if score else 12),
                "irt_alpha": 1.1,
                "irt_beta": spec["difficulty"],
                "irt_gamma": 0.25,
                "irt_alpha_vec": [1.1, 0.35, 0.55],
                "irt_beta_vec": [0.1, 0.3, 0.45],
            },
            identity_fields=("student_id",),
        )
        changed += delta

    wrong = db.query(DBWrongQuestion).filter_by(
        student_id=owner.username, source_object_id=version_ids[1],
    ).first()
    wrong_values = {
        "quiz_record_id": "postdata-quiz-record-lzz-eml-q02",
        "source_event_id": None,
        "concept_name": context["points_by_code"]["EML-KP-05"].title,
        "wrong_reason_category": "忽略现场数据分布与阈值证据",
        "pinned": True,
        "notes": "先核查误报样本、现场分布和阈值来源，再决定是否调整模型或阈值。",
    }
    if wrong is None:
        db.add(DBWrongQuestion(
            student_id=owner.username, source_object_id=version_ids[1], **wrong_values,
        ))
        db.flush()
        changed += 1
    else:
        row_changed = False
        for field, value in wrong_values.items():
            if getattr(wrong, field) != value:
                setattr(wrong, field, value)
                row_changed = True
        if row_changed:
            db.flush()
            changed += 1

    review_marker = f"postdata-review:{version_ids[1]}"
    reviews = [
        row for row in db.query(DBReviewPlan).filter_by(student_id=owner.username).all()
        if review_marker in (row.similar_quiz_ids or [])
    ]
    if len(reviews) > 1:
        raise ValueError("duplicate post-data review baseline")
    review_values = {
        "concept": context["points_by_code"]["EML-KP-05"].id,
        "interval_days": 1,
        "next_review_at": FROZEN_AT + timedelta(days=1),
        "mastery": 0.42,
        "review_count": 1,
        "easiness_factor": 2.2,
        "last_quality": 2,
        "similar_quiz_ids": [review_marker, "postdata-quiz-record-lzz-eml-q02"],
        "priority": 0.12,
    }
    if not reviews:
        db.add(DBReviewPlan(student_id=owner.username, **review_values))
        db.flush()
        changed += 1
    else:
        row_changed = False
        for field, value in review_values.items():
            if not _values_equal(getattr(reviews[0], field), value):
                setattr(reviews[0], field, value)
                row_changed = True
        if row_changed:
            db.flush()
            changed += 1
    return version_ids, changed


def _quiz_content(context: dict[str, Any], source_ref_ids: list[str], version_ids: list[str]) -> str:
    focus = context["focus"]
    return _canonical({
        "schemaVersion": "f6.quiz-resource.v1",
        "title": "异常检测与阈值治理测验题",
        "summary": "三道题分别检查设备部署、现场误报分析和阈值迁移边界；已有两次作答保留在资源历史中。",
        "courseTitle": context["course"].title,
        "knowledgePoint": {"id": focus.id, "title": focus.title},
        "adaptation": {
            "learningGoal": "能够依据现场数据和失败样本解释阈值调整，而不是机械修改数值。",
            "profileSummary": "当前已掌握训练工作流，但设备部署与阈值治理证据较少。",
            "masterySummary": "量化部署 48%，异常检测与阈值治理 42%。",
            "recentLearningSummary": "已完成一道部署题，误答一道现场误报分析题，第三题待完成。",
        },
        "sourceRefIds": source_ref_ids,
        "questions": [
            {"questionVersionId": version_id, "position": index, "required": True}
            for index, version_id in enumerate(version_ids, start=1)
        ],
        "requiredQuestionCount": 3,
    })


def _video_content(context: dict[str, Any], source_ref_ids: list[str]) -> tuple[str, dict[str, str]]:
    artifact_id = _resource_id("video")
    recommendation_id = "postdata-local-course-tour"
    content = {
        "schemaVersion": "f5.video-recommendation.v1",
        "title": "嵌入式机器学习课程导览视频",
        "summary": "本地打包的 25 秒静音导览展示从数据、训练、量化到设备验证的课程主线；页面同时保留可搜索文字说明。",
        "learningGoal": "先建立整门课程的工程顺序，再进入异常检测与阈值治理任务。",
        "adaptationSummary": "当前优先观看课程主线和部署检查点，视频不冒充语音转写。",
        "recommendations": [{
            "id": recommendation_id,
            "title": "从数据到设备：嵌入式机器学习工程主线",
            "sourceKind": "local_ref",
            "availability": "playable",
            "url": None,
            "localRef": f"/api/v1/m5/resources/{artifact_id}/video-media/{recommendation_id}",
            "durationSeconds": 25,
            "author": "EduMatrix 团队",
            "language": "无旁白，中文字幕画面",
            "licenseStatus": "packaged_demo",
            "licenseLabel": "团队原创比赛演示视频；课程来源署名与改编说明随课程包保留。",
            "licenseUrl": None,
            "reason": "帮助学生在开始当前模块前理解数据、训练、部署和监控之间的顺序。",
            "segments": [
                {"id": "overview", "title": "课程工程闭环", "startSeconds": 0, "endSeconds": 12, "learningFocus": "识别数据、训练、量化部署和现场监控四个阶段。"},
                {"id": "deployment", "title": "设备验证与阈值治理", "startSeconds": 12, "endSeconds": 25, "learningFocus": "关注资源约束、误报漏报和持续监控。"},
            ],
            "sourceRefIds": source_ref_ids,
            "alternatives": [],
        }],
    }
    return _canonical(content), {recommendation_id: VIDEO_RELATIVE_PATH}


def _ensure_resources(
    db: Any,
    *,
    owner: DBUser,
    context: dict[str, Any],
    version_ids: list[str],
) -> int:
    changed = 0
    source_ref_ids = [row.id for row in context["source_refs"]]
    generation_manifest = {
        "knowledge_point_id": context["focus"].id,
        "context": {
            "course_title": context["course"].title,
            "knowledge_point_title": context["focus"].title,
            "learning_goal": "能够以可追溯证据完成异常检测阈值分析、代码校准和设备侧验证。",
            "profile_adaptation": "为已有机器学习基础、但设备部署经验不足的学生提供图示、代码和检查点。",
            "mastery_summary": "量化部署 48%，异常检测与阈值治理 42%。",
            "recent_learning_summary": "已完成课程导论与训练工作流，正在进入设备部署与阈值治理。",
            "source_count": len(source_ref_ids),
        },
    }
    for resource_type, title in RESOURCE_SPECS:
        artifact_id = _resource_id(resource_type)
        version_id = _resource_version_id(resource_type)
        item = {
            "title": title,
            "source_ref_ids": source_ref_ids,
            "completion_rule": "完成页面规定的必需检查，并通过明确提交动作记录学习证据。",
        }
        linked: list[str] = []
        if resource_type == "mind_map":
            linked = [_resource_id("handout")]
        elif resource_type == "training_task":
            linked = [_resource_id("code_sandbox"), _resource_id("interactive_model")]
        local_video_files: dict[str, str] = {}
        if resource_type == "quiz":
            content = _quiz_content(context, source_ref_ids, version_ids)
        elif resource_type == "video":
            content, local_video_files = _video_content(context, source_ref_ids)
        else:
            content = _deterministic_demo_content(
                resource_type=resource_type,
                item=item,
                manifest=generation_manifest,
                source_snapshots=context["source_snapshots"],
                linked_resource_ids=linked,
            )
        content_format = "markdown" if resource_type == "feynman" else "json"
        _, delta = _repair_row(
            db,
            DBArtifact,
            artifact_id,
            {
                "owner_public_id": owner.public_id,
                "course_id": COURSE_ID,
                "artifact_type": resource_type,
                "title": title,
                "status": "approved",
                "current_version_id": version_id,
                "creating_task_id": None,
                "lock_version": 1,
                "archived_at": None,
            },
            identity_fields=("owner_public_id", "course_id"),
        )
        changed += delta
        metadata = {
            "resource_type": resource_type,
            "knowledge_point_id": context["focus"].id,
            "knowledge_point_title": context["focus"].title,
            "profile_snapshot_id": PROFILE_ID,
            "source_ref_ids": source_ref_ids,
            "module": context["focus_chapter"].title if context["focus_chapter"] else context["focus"].title,
            "completion_rule": item["completion_rule"],
            "generation_state": "succeeded",
            "demo_scope": DEMO_SCOPE,
            "truthfulness": "local_deterministic_demo_content",
        }
        if local_video_files:
            metadata["local_video_files"] = local_video_files
        _, delta = _repair_row(
            db,
            DBArtifactVersion,
            version_id,
            {
                "artifact_id": artifact_id,
                "version_number": 1,
                "content": content,
                "content_format": content_format,
                "content_hash": _hash(content),
                "metadata_json": metadata,
                "created_by_public_id": owner.public_id,
                "created_task_id": None,
                "created_at": FROZEN_AT,
            },
            identity_fields=("artifact_id",),
        )
        changed += delta
    return changed


def _path_specs(context: dict[str, Any]) -> list[dict[str, Any]]:
    points = context["points_by_code"]
    return [
        {"key": "course-foundation", "title": "回顾边缘机器学习责任边界", "point": points["EML-KP-01"], "resource": "handout", "status": "completed", "minutes": 22},
        {"key": "workflow-check", "title": "完成端到端工作流测验", "point": points["EML-KP-03"], "resource": "quiz", "status": "completed", "minutes": 14},
        {"key": "threshold-code", "title": "运行分类阈值校准代码", "point": points["EML-KP-05"], "resource": "code_sandbox", "status": "in_progress", "minutes": 25},
        {"key": "deployment-task", "title": "完成设备侧异常检测实训", "point": points["EML-KP-05"], "resource": "training_task", "status": "pending", "minutes": 45},
        {"key": "threshold-model", "title": "观察阈值变化对误报漏报的影响", "point": points["EML-KP-05"], "resource": "interactive_model", "status": "pending", "minutes": 20},
        {"key": "course-video", "title": "观看从数据到设备课程导览", "point": points["EML-KP-04"], "resource": "video", "status": "pending", "minutes": 8},
        {"key": "deployment-deck", "title": "阅读异常检测与部署决策课件", "point": points["EML-KP-04"], "resource": "deck", "status": "pending", "minutes": 18},
        {"key": "threshold-feynman", "title": "用费曼法解释阈值治理边界", "point": points["EML-KP-05"], "resource": "feynman", "status": "pending", "minutes": 15},
    ]


def _ensure_plan_path(db: Any, *, owner: DBUser, context: dict[str, Any]) -> int:
    changed = 0
    specs = _path_specs(context)
    plan_content = {
        "schema_version": "m5.plan.v1",
        "goal": "完成嵌入式机器学习从训练、量化部署到异常阈值治理的工程闭环",
        "deadline": None,
        "assumptions": ["每日最多三项必做任务", "冻结合成学习记录仅用于比赛演示"],
        "nodes": [{
            "node_key": spec["key"],
            "node_type": "resource",
            "target_object_id": _resource_id(spec["resource"]),
            "title": spec["title"],
            "prerequisites": [] if index == 0 else [specs[index - 1]["key"]],
            "resource_status": "existing",
            "estimate_min_minutes": spec["minutes"],
            "estimate_max_minutes": spec["minutes"],
            "extension_reason": "",
            "required": index in {2, 3, 4},
            "risk_level": "normal",
            "knowledge_point_id": spec["point"].id,
        } for index, spec in enumerate(specs)],
    }
    _, delta = _repair_row(
        db,
        DBPlanDraft,
        PLAN_ID,
        {
            "owner_public_id": owner.public_id,
            "course_id": COURSE_ID,
            "title": "嵌入式机器学习工程实践学习计划",
            "status": "confirmed",
            "idempotency_key": f"{DEMO_SCOPE}:{PLAN_ID}",
            "current_version_id": PLAN_VERSION_ID,
            "confirmed_version_id": PLAN_VERSION_ID,
            "confirmed_at": FROZEN_AT,
            "lock_version": 1,
            "archived_at": None,
        },
        identity_fields=("owner_public_id", "course_id"),
    )
    changed += delta
    _, delta = _repair_row(
        db,
        DBPlanVersion,
        PLAN_VERSION_ID,
        {
            "plan_draft_id": PLAN_ID,
            "version_number": 1,
            "profile_snapshot_id": PROFILE_ID,
            "content": plan_content,
            "content_hash": _hash(plan_content),
            "created_by_public_id": owner.public_id,
            "created_at": FROZEN_AT,
        },
        identity_fields=("plan_draft_id",),
    )
    changed += delta
    path, delta = _repair_row(
        db,
        DBLearningPath,
        PATH_ID,
        {
            "owner_public_id": owner.public_id,
            "course_id": COURSE_ID,
            "source_plan_version_id": PLAN_VERSION_ID,
            "status": "active",
            "supersedes_path_id": None,
            "lock_version": 1,
            "paused_at": None,
            "archived_at": None,
            "completed_at": None,
        },
        identity_fields=("owner_public_id", "course_id"),
    )
    changed += delta
    for index, spec in enumerate(specs, start=1):
        node_id = f"postdata-path-node-eml-{index:02d}"
        _, delta = _repair_row(
            db,
            DBPathNode,
            node_id,
            {
                "learning_path_id": PATH_ID,
                "node_key": spec["key"],
                "sequence": index,
                "node_type": "resource",
                "target_object_id": _resource_id(spec["resource"]),
                "title": spec["title"],
                "status": spec["status"],
                "prerequisites": [] if index == 1 else [specs[index - 2]["key"]],
                "is_extension": False,
                "resource_status": "existing",
                "estimate_min_minutes": spec["minutes"],
                "estimate_max_minutes": spec["minutes"],
                "actual_minutes": spec["minutes"] if spec["status"] == "completed" else None,
                "blocked_reason": "",
                "created_at": FROZEN_AT + timedelta(minutes=index),
            },
            identity_fields=("learning_path_id",),
        )
        changed += delta
    latest_other = db.query(DBLearningPath).filter(
        DBLearningPath.owner_public_id == owner.public_id,
        DBLearningPath.id != PATH_ID,
        DBLearningPath.status.in_(("active", "paused")),
    ).order_by(DBLearningPath.updated_at.desc()).first()
    if latest_other is not None and path.updated_at <= latest_other.updated_at:
        path.updated_at = max(datetime.now(timezone.utc), latest_other.updated_at.replace(tzinfo=timezone.utc)) + timedelta(seconds=1)
        db.flush()
        changed += 1
    return changed


def _ensure_note_and_chat(db: Any, *, owner: DBUser, context: dict[str, Any]) -> int:
    changed = 0
    source_ref_ids = [row.id for row in context["source_refs"]]
    chat_source_refs = [
        chat_source_ref(project_source_ref(
            db,
            source_ref_id,
            actor=owner,
            expected_course_id=COURSE_ID,
        ))
        for source_ref_id in source_ref_ids
    ]
    note_content = (
        "# 量化部署与异常阈值治理复盘\n\n"
        "## 我已经确认\n"
        "- 部署前需要同时检查量化误差、算子支持、峰值内存和设备时延。\n"
        "- 阈值不是模型内部的固定真理，而是结合现场分布、误报成本和人工接管规则形成的决策。\n\n"
        "## 当前错因\n"
        "我在误报上升时直接选择了调高阈值，忽略了先检查现场数据分布和失败样本。\n\n"
        "## 下一步\n"
        "先在代码沙盒中比较不同阈值的混淆矩阵，再进入实训任务书记录设备侧约束。"
    )
    source_metadata = {
        "course_id": COURSE_ID,
        "source_ref_ids": source_ref_ids,
        "profile_snapshot_id": PROFILE_ID,
        "demo_scope": DEMO_SCOPE,
        "truthfulness": "frozen_synthetic_demo_data",
    }
    _, delta = _repair_row(
        db,
        DBNote,
        NOTE_ID,
        {
            "student_id": owner.username,
            "source": "course_reader",
            "content": note_content,
            "tags": ["TinyML", "量化部署", "异常检测", "阈值治理"],
            "concepts": [context["points_by_code"][code].title for code in ("EML-KP-04", "EML-KP-05")],
            "source_metadata": source_metadata,
            "lock_version": 1,
            "ai_suggestion": "补充一组不同阈值下的误报、漏报和设备告警成本对比。",
            "ai_suggestion_metadata": {"basis": "postdata-quiz-record-lzz-eml-q02", "demo_scope": DEMO_SCOPE},
            "created_at": FROZEN_AT,
            "updated_at": FROZEN_AT + timedelta(minutes=18),
        },
        identity_fields=("student_id",),
    )
    changed += delta
    _, delta = _repair_row(
        db,
        DBNoteVersion,
        NOTE_VERSION_ID,
        {
            "note_id": NOTE_ID,
            "version_number": 1,
            "content": note_content,
            "tags": ["TinyML", "量化部署", "异常检测", "阈值治理"],
            "concepts": [context["points_by_code"][code].title for code in ("EML-KP-04", "EML-KP-05")],
            "source": "course_reader",
            "source_metadata": source_metadata,
            "change_type": "saved",
            "restored_from_version": None,
            "event_id": None,
            "created_at": FROZEN_AT + timedelta(minutes=18),
        },
        identity_fields=("note_id",),
    )
    changed += delta
    _, delta = _repair_row(
        db,
        DBChatConversation,
        CONVERSATION_ID,
        {
            "owner_public_id": owner.public_id,
            "course_id": COURSE_ID,
            "title": "为什么异常阈值不能直接固定上线",
            "status": "active",
            "lock_version": 1,
            "created_at": FROZEN_AT + timedelta(minutes=20),
            "updated_at": FROZEN_AT + timedelta(minutes=22),
            "archived_at": None,
        },
        identity_fields=("owner_public_id", "course_id"),
    )
    changed += delta
    messages = (
        (
            "postdata-chat-message-lzz-eml-01",
            1,
            "user",
            "现场误报变多时，为什么不能直接把异常分数阈值调高？",
            [],
        ),
        (
            "postdata-chat-message-lzz-eml-02",
            2,
            "assistant",
            "直接调高阈值可能暂时减少误报，却同时增加漏报。应先检查现场数据分布、误报样本、设备噪声和当前阈值的验证依据，再用混淆矩阵与业务成本比较候选阈值。这个结论可回到课程工程手册和异常检测模块复核。",
            chat_source_refs,
        ),
    )
    for message_id, sequence, role, content, refs in messages:
        _, delta = _repair_row(
            db,
            DBChatMessage,
            message_id,
            {
                "conversation_id": CONVERSATION_ID,
                "owner_public_id": owner.public_id,
                "reply_to_message_id": "postdata-chat-message-lzz-eml-01" if sequence == 2 else None,
                "sequence": sequence,
                "role": role,
                "status": "completed",
                "content": content,
                "content_sha256": _hash(content),
                "idempotency_key": f"{DEMO_SCOPE}:{message_id}",
                "context_refs": [{"course_id": COURSE_ID, "knowledge_point_id": context["focus"].id}],
                "attachment_ids": [],
                "source_refs": refs,
                "resource_links": [{"id": _resource_id("code_sandbox"), "route": f"/workspace/code/{_resource_id('code_sandbox')}"}] if sequence == 2 else [],
                "stream_checkpoint": {"completed": True, "deterministic_demo": True},
                "error_code": "",
                "error_message": "",
                "lock_version": 1,
                "created_at": FROZEN_AT + timedelta(minutes=20 + sequence),
                "updated_at": FROZEN_AT + timedelta(minutes=20 + sequence),
                "completed_at": FROZEN_AT + timedelta(minutes=20 + sequence),
            },
            identity_fields=("conversation_id", "owner_public_id"),
        )
        changed += delta
    return changed


def _ensure_exam(db: Any, *, owner: DBUser, version_ids: list[str], context: dict[str, Any]) -> int:
    changed = 0
    configuration = {
        "course_id": COURSE_ID,
        "question_count": 3,
        "knowledge_point_ids": [context["points_by_code"][code].id for code in ("EML-KP-04", "EML-KP-05")],
        "difficulty": "adaptive_demo",
        "idempotency_key": f"{DEMO_SCOPE}:intelligent-exam",
        "truthfulness": "frozen_synthetic_demo_data",
    }
    coverage = {
        "knowledge_points": [
            {"id": context["points_by_code"][code].id, "title": context["points_by_code"][code].title}
            for code in ("EML-KP-04", "EML-KP-05")
        ],
        "question_count": 3,
    }
    _, delta = _repair_row(
        db,
        DBAssessmentExam,
        EXAM_ID,
        {
            "course_id": COURSE_ID,
            "owner_public_id": owner.public_id,
            "generation_key": f"{DEMO_SCOPE}:intelligent-exam",
            "title": "量化部署与异常阈值治理智能组卷",
            "status": "open",
            "current_version_id": EXAM_VERSION_ID,
            "scheduled_open_at": None,
            "scheduled_close_at": None,
            "duration_minutes": 30,
            "lock_version": 1,
        },
        identity_fields=("course_id", "owner_public_id"),
    )
    changed += delta
    manifest_hash = _hash({"configuration": configuration, "questions": version_ids})
    _, delta = _repair_row(
        db,
        DBAssessmentExamVersion,
        EXAM_VERSION_ID,
        {
            "exam_id": EXAM_ID,
            "version_number": 1,
            "instructions": "完成三道题后提交。作答记录保留，提交后进入统一画像、路径、错题与复习聚合。",
            "feedback_policy": "after_submission",
            "total_points": 30.0,
            "manifest_hash": manifest_hash,
            "configuration": configuration,
            "generation_context": {"profile_snapshot_id": PROFILE_ID, "path_id": PATH_ID, "demo_scope": DEMO_SCOPE},
            "coverage": coverage,
            "created_by_public_id": owner.public_id,
            "created_at": FROZEN_AT + timedelta(minutes=30),
        },
        identity_fields=("exam_id",),
    )
    changed += delta
    for index, version_id in enumerate(version_ids, start=1):
        _, delta = _repair_row(
            db,
            DBAssessmentExamItem,
            f"postdata-exam-item-lzz-eml-{index:02d}",
            {
                "exam_version_id": EXAM_VERSION_ID,
                "question_version_id": version_id,
                "position": index,
                "points": 10.0,
                "required": True,
                "created_at": FROZEN_AT + timedelta(minutes=30),
            },
            identity_fields=("exam_version_id", "question_version_id"),
        )
        changed += delta
    _, delta = _repair_row(
        db,
        DBAssessmentExamSitting,
        SITTING_ID,
        {
            "exam_id": EXAM_ID,
            "exam_version_id": EXAM_VERSION_ID,
            "owner_public_id": owner.public_id,
            "status": "assigned",
            "started_at": None,
            "due_at": None,
            "submitted_at": None,
            "released_at": None,
            "lock_version": 1,
            "created_at": FROZEN_AT + timedelta(minutes=31),
            "updated_at": FROZEN_AT + timedelta(minutes=31),
        },
        identity_fields=("exam_id", "owner_public_id"),
    )
    changed += delta
    return changed


def _event_specs(context: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    focus_id = context["focus"].id
    return (
        {"suffix": "handout", "type": "resource_completed", "object_type": "artifact", "object_id": _resource_id("handout"), "action": "complete", "eligible": True, "strength": 0.55, "effect": "complete", "point_ids": [context["points_by_code"]["EML-KP-01"].id]},
        {"suffix": "quiz-correct", "type": "assessment_attempt_submitted", "object_type": "assessment_attempt", "object_id": "postdata-attempt-lzz-eml-q01", "action": "submit", "eligible": True, "strength": 0.82, "effect": "complete", "point_ids": [context["points_by_code"]["EML-KP-04"].id]},
        {"suffix": "quiz-wrong", "type": "assessment_attempt_submitted", "object_type": "assessment_attempt", "object_id": "postdata-attempt-lzz-eml-q02", "action": "submit", "eligible": True, "strength": 0.78, "effect": "progress", "point_ids": [focus_id]},
        {"suffix": "code", "type": "code_run_completed", "object_type": "artifact", "object_id": _resource_id("code_sandbox"), "action": "run", "eligible": True, "strength": 0.68, "effect": "progress", "point_ids": [focus_id]},
        {"suffix": "feynman", "type": "feynman_completed", "object_type": "artifact", "object_id": _resource_id("feynman"), "action": "submit", "eligible": True, "strength": 0.64, "effect": "progress", "point_ids": [focus_id]},
        {"suffix": "review", "type": "review_completed", "object_type": "knowledge_point", "object_id": focus_id, "action": "review", "eligible": True, "strength": 0.58, "effect": "progress", "point_ids": [focus_id]},
        {"suffix": "note", "type": "note_saved", "object_type": "note", "object_id": NOTE_ID, "action": "save", "eligible": False, "strength": 0.0, "effect": "none", "point_ids": [focus_id]},
        {"suffix": "chat", "type": "conversation_completed", "object_type": "conversation", "object_id": CONVERSATION_ID, "action": "complete", "eligible": False, "strength": 0.0, "effect": "none", "point_ids": [focus_id]},
        {"suffix": "browse", "type": "resource_opened", "object_type": "source_document", "object_id": context["source_refs"][0].source_document_id, "action": "open", "eligible": False, "strength": 0.0, "effect": "none", "point_ids": []},
    )


def _ensure_events(db: Any, *, owner: DBUser, context: dict[str, Any]) -> int:
    changed = 0
    for index, spec in enumerate(_event_specs(context), start=1):
        event_id = f"postdata-event-lzz-eml-{spec['suffix']}"
        eligible = spec["eligible"]
        _, delta = _repair_row(
            db,
            DBLearningEvent,
            event_id,
            {
                "owner_public_id": owner.public_id,
                "legacy_student_id": owner.username,
                "course_id": COURSE_ID,
                "event_type": spec["type"],
                "schema_version": "postdata.learning-event.v1",
                "idempotency_key": f"{DEMO_SCOPE}:{event_id}",
                "source": "seed",
                "trace_id": TRACE_ID,
                "object_type": spec["object_type"],
                "object_id": spec["object_id"],
                "action": spec["action"],
                "context_ref": {"profile_snapshot_id": PROFILE_ID, "path_id": PATH_ID},
                "evidence_strength": spec["strength"],
                "evidence_status": "accepted" if eligible else "none",
                "evidence_reason": "冻结合成比赛演示证据" if eligible else "普通内容操作不进入掌握度证据",
                "mastery_eligible": eligible,
                "completion_effect": spec["effect"],
                "payload_version": "1",
                "payload": {
                    "demo_scope": DEMO_SCOPE,
                    "truthfulness": "frozen_synthetic_demo_data",
                    "knowledge_point_ids": spec["point_ids"],
                    "course_id": COURSE_ID,
                },
                "occurred_at": FROZEN_AT + timedelta(minutes=index * 5),
                "recorded_at": FROZEN_AT + timedelta(minutes=index * 5),
            },
            identity_fields=("owner_public_id", "course_id"),
        )
        changed += delta
    return changed


def _ensure_membership(db: Any, *, owner: DBUser) -> int:
    stable = db.get(DBCourseMembership, "postdata-membership-lzz-eml-v1")
    existing = db.query(DBCourseMembership).filter_by(
        course_id=COURSE_ID, user_public_id=owner.public_id,
    ).first()
    if stable is not None and existing is not None and stable.id != existing.id:
        raise ValueError("post-data course membership is duplicated")
    row = stable or existing
    if row is None:
        db.add(DBCourseMembership(
            id="postdata-membership-lzz-eml-v1",
            course_id=COURSE_ID,
            user_public_id=owner.public_id,
            role="student",
            status="active",
            created_at=FROZEN_AT,
            updated_at=FROZEN_AT,
        ))
        db.flush()
        return 1
    if row.course_id != COURSE_ID or row.user_public_id != owner.public_id:
        raise ValueError("post-data course membership identity conflict")
    changed = False
    for field, value in {"role": "student", "status": "active"}.items():
        if getattr(row, field) != value:
            setattr(row, field, value)
            changed = True
    if changed:
        db.flush()
    return int(changed)


def ensure_post_data_overlay(db: Any, *, owner: DBUser) -> int:
    if owner.username != "lzz" or owner.role != "student":
        raise ValueError("post-data demo overlay requires the lzz student account")
    context = _course_context(db)
    changed = _ensure_membership(db, owner=owner)
    changed += _ensure_profile(db, owner=owner, context=context)
    version_ids, delta = _ensure_questions_and_attempts(
        db,
        owner=owner,
        context=context,
        source_ref_ids=[row.id for row in context["source_refs"]],
    )
    changed += delta
    changed += _ensure_resources(db, owner=owner, context=context, version_ids=version_ids)
    changed += _ensure_plan_path(db, owner=owner, context=context)
    changed += _ensure_note_and_chat(db, owner=owner, context=context)
    changed += _ensure_exam(db, owner=owner, version_ids=version_ids, context=context)
    changed += _ensure_events(db, owner=owner, context=context)
    db.flush()
    return changed


def post_data_demo_issues(db: Any, *, owner: DBUser) -> list[str]:
    issues: list[str] = []
    if not _course_bundle_ready(db):
        return ["postdata:course_bundle"]
    try:
        context = _course_context(db)
    except ValueError:
        return ["postdata:course_context"]
    membership = db.query(DBCourseMembership).filter_by(
        course_id=COURSE_ID, user_public_id=owner.public_id,
    ).first()
    if membership is None or membership.role != "student" or membership.status != "active":
        issues.append("postdata:membership")
    snapshot = db.get(DBProfileSnapshot, PROFILE_ID)
    expected_snapshot = _profile_snapshot(context)
    if (
        snapshot is None
        or snapshot.owner_public_id != owner.public_id
        or snapshot.snapshot != expected_snapshot
        or snapshot.content_hash != _hash(expected_snapshot)
    ):
        issues.append("postdata:profile_snapshot")
    legacy = db.get(DBStudentProfile, owner.username)
    if legacy is None or legacy.target_course != context["course"].title or set(legacy.concept_mastery or {}) != {row.title for row in context["points"]}:
        issues.append("postdata:legacy_profile")
    path = db.get(DBLearningPath, PATH_ID)
    if path is None or path.owner_public_id != owner.public_id or path.course_id != COURSE_ID or path.status != "active":
        issues.append("postdata:path")
    expected_node_states = {
        f"postdata-path-node-eml-{index:02d}": spec["status"]
        for index, spec in enumerate(_path_specs(context), start=1)
    }
    nodes = db.query(DBPathNode).filter_by(learning_path_id=PATH_ID).all() if path else []
    if {row.id: row.status for row in nodes} != expected_node_states:
        issues.append("postdata:path_nodes")
    artifact_ids = {_resource_id(resource_type): _resource_version_id(resource_type) for resource_type, _ in RESOURCE_SPECS}
    artifacts = db.query(DBArtifact).filter_by(owner_public_id=owner.public_id, course_id=COURSE_ID).filter(
        DBArtifact.id.like("postdata-resource-eml-%"),
    ).all()
    if {row.id for row in artifacts} != set(artifact_ids):
        issues.append("postdata:resources")
    elif any(row.status != "approved" or row.current_version_id != artifact_ids[row.id] for row in artifacts):
        issues.append("postdata:resource_state")
    if db.query(DBAssessmentQuestion).filter_by(owner_public_id=owner.public_id, course_id=COURSE_ID).filter(
        DBAssessmentQuestion.id.like("postdata-assessment-eml-%"),
    ).count() != 3:
        issues.append("postdata:questions")
    if db.query(DBAssessmentAttempt).filter_by(owner_public_id=owner.public_id, course_id=COURSE_ID).filter(
        DBAssessmentAttempt.id.like("postdata-attempt-lzz-eml-%"),
    ).count() != 2:
        issues.append("postdata:attempts")
    if db.get(DBNote, NOTE_ID) is None or db.get(DBNoteVersion, NOTE_VERSION_ID) is None:
        issues.append("postdata:note")
    if db.get(DBChatConversation, CONVERSATION_ID) is None or db.query(DBChatMessage).filter_by(
        conversation_id=CONVERSATION_ID, owner_public_id=owner.public_id,
    ).count() != 2:
        issues.append("postdata:chat")
    exam = db.get(DBAssessmentExam, EXAM_ID)
    sitting = db.get(DBAssessmentExamSitting, SITTING_ID)
    if exam is None or exam.status != "open" or sitting is None or sitting.status != "assigned":
        issues.append("postdata:exam")
    if db.query(DBLearningEvent).filter_by(owner_public_id=owner.public_id, course_id=COURSE_ID).filter(
        DBLearningEvent.id.like("postdata-event-lzz-eml-%"),
    ).count() != len(_event_specs(context)):
        issues.append("postdata:events")
    review_marker = "postdata-review:postdata-assessment-eml-q02-v1"
    reviews = [
        row for row in db.query(DBReviewPlan).filter_by(student_id=owner.username).all()
        if review_marker in (row.similar_quiz_ids or [])
    ]
    if len(reviews) != 1:
        issues.append("postdata:review")
    if db.query(DBWrongQuestion).filter_by(
        student_id=owner.username, source_object_id="postdata-assessment-eml-q02-v1",
    ).count() != 1:
        issues.append("postdata:wrong_question")
    return sorted(set(issues))


def post_data_stable_ids(db: Any, *, owner: DBUser) -> dict[str, Any]:
    review_marker = "postdata-review:postdata-assessment-eml-q02-v1"
    review = next(
        (
            row for row in db.query(DBReviewPlan).filter_by(student_id=owner.username).all()
            if review_marker in (row.similar_quiz_ids or [])
        ),
        None,
    )
    wrong = db.query(DBWrongQuestion).filter_by(
        student_id=owner.username, source_object_id="postdata-assessment-eml-q02-v1",
    ).first()
    return {
        "membership": (db.query(DBCourseMembership).filter_by(course_id=COURSE_ID, user_public_id=owner.public_id).first() or type("Missing", (), {"id": None})()).id,
        "profile": PROFILE_ID if db.get(DBProfileSnapshot, PROFILE_ID) else None,
        "path": PATH_ID if db.get(DBLearningPath, PATH_ID) else None,
        "resources": sorted(row.id for row in db.query(DBArtifact).filter_by(owner_public_id=owner.public_id, course_id=COURSE_ID).filter(DBArtifact.id.like("postdata-resource-eml-%")).all()),
        "note": NOTE_ID if db.get(DBNote, NOTE_ID) else None,
        "conversation": CONVERSATION_ID if db.get(DBChatConversation, CONVERSATION_ID) else None,
        "exam": EXAM_ID if db.get(DBAssessmentExam, EXAM_ID) else None,
        "review": review.id if review else None,
        "wrong_question": wrong.id if wrong else None,
    }
