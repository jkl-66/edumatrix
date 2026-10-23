"""Seed three same-course learner profiles for a reviewer-facing demo.

This script creates only uniquely named demo learners and owner-scoped copies of
existing valid resource shapes. It never updates the lzz account or course rows.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth import get_password_hash
from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBChatConversation,
    DBChatMessage,
    DBCourse,
    DBCourseMembership,
    DBOnboardingSession,
    DBProfileSnapshot,
    DBStudentProfile,
    DBUser,
    SessionLocal,
)
from app.m1_repository import create_artifact_with_version
from app.profile_adaptation import build_profile_adaptation, profile_prompt_context

COURSE_ID = "course-machine-learning-foundations-v1"
COURSE_TITLE = "机器学习基础与实践"
KP_ID = "kp-063fa2c83380bff6580b7f72"
KP_TITLE = "决策树分类"
PASSWORD = "EduMatrixProfile2026!"
PREFIX = "profile_demo_"

PROFILES = [
    {
        "key": "beginner",
        "username": f"{PREFIX}beginner",
        "display_name": "林一 · 入门画像",
        "major": "软件工程",
        "knowledge_base": "会写基础 Python，但第一次系统学习机器学习。",
        "cognitive_style": "分步讲解",
        "motivation_type": "就业与岗位转型",
        "learning_goals": ["理解决策树分类", "完成第一个可运行的小实验"],
        "interaction_preferences": ["具体例子", "分步讲解"],
        "weak_points": [KP_TITLE],
        "mastery": 0.24,
        "cognitive_load": 0.78,
        "frustration_index": 0.38,
        "focus_level": 0.52,
        "dimension_states": {
            "knowledge_mastery": {"score": 0.24, "summary": "基础概念尚未稳定"},
            "cognitive_processing": {"score": 0.78, "summary": "一次处理的信息不宜过多"},
            "understanding_fluency_transfer": {"score": 0.28, "summary": "需要示范后再迁移"},
            "interaction_preference": {"score": 0.82, "summary": "偏好例子和分步讲解"},
        },
        "adaptation_label": "入门巩固",
        "adaptation_sentence": "先用 if/else 的直觉建立决策树概念，再用短步骤和小检查逐步练习。",
        "chat": (
            "我先用一个你熟悉的场景来理解决策树：它像代码里的 if/else，先问一个最能区分结果的问题，"
            "再沿着分支继续判断，最后在叶节点给出分类。以汽车可接受性为例，可以先问价格是否过高，"
            "再看安全性和座位数。接下来建议先完成一个小检查：说出样本、特征和标签分别是什么，"
            "然后再运行一棵限制深度的树。每次只改一个参数，比较结果后再继续。"
        ),
    },
    {
        "key": "engineer",
        "username": f"{PREFIX}engineer",
        "display_name": "周工 · 工程画像",
        "major": "数据科学与大数据技术",
        "knowledge_base": "熟悉 Python、数据处理和模型训练，希望提升工程交付能力。",
        "cognitive_style": "代码实操",
        "motivation_type": "项目交付",
        "learning_goals": ["比较不同分类模型", "完成岗位级评估报告"],
        "interaction_preferences": ["代码实操", "方案对比"],
        "weak_points": [],
        "mastery": 0.82,
        "cognitive_load": 0.28,
        "frustration_index": 0.12,
        "focus_level": 0.9,
        "dimension_states": {
            "knowledge_mastery": {"score": 0.82, "summary": "基础概念已掌握"},
            "understanding_fluency_transfer": {"score": 0.9, "summary": "能迁移到项目"},
            "interaction_preference": {"score": 0.9, "summary": "偏好代码和方案对比"},
        },
        "adaptation_label": "进阶迁移",
        "adaptation_sentence": "跳过重复定义，直接用可运行基线比较树深、过拟合和上线约束。",
        "chat": (
            "如果你已经熟悉训练流程，可以直接把决策树作为一个可解释的分类基线。先用 train_test_split 划分数据，"
            "训练 max_depth=3、5、None 三个版本，同时记录训练集和测试集指标。重点观察树深增加后训练准确率接近 1，"
            "但测试表现未必同步提升。工程上还要检查 min_samples_leaf、类别不平衡、特征重要性以及推理延迟，"
            "最后将它与逻辑回归或随机森林做一次同数据对比，再写出选型结论。"
        ),
    },
    {
        "key": "theorist",
        "username": f"{PREFIX}theorist",
        "display_name": "陈研 · 研究画像",
        "major": "人工智能",
        "knowledge_base": "数学和机器学习理论基础较强，关注机制、假设和边界条件。",
        "cognitive_style": "公式推导",
        "motivation_type": "科研与算法分析",
        "learning_goals": ["解释决策树的划分准则", "分析复杂度与泛化边界"],
        "interaction_preferences": ["公式推导", "反例比较"],
        "weak_points": ["决策树复杂度与泛化边界"],
        "mastery": 0.58,
        "cognitive_load": 0.42,
        "frustration_index": 0.22,
        "focus_level": 0.84,
        "dimension_states": {
            "knowledge_mastery": {"score": 0.58, "summary": "机制理解基本形成"},
            "understanding_fluency_transfer": {"score": 0.7, "summary": "需要跨层次推导"},
            "interaction_preference": {"score": 0.86, "summary": "偏好公式、边界和反例"},
        },
        "adaptation_label": "基础应用",
        "adaptation_sentence": "先推导基尼不纯度和信息增益，再用反例分析树深与泛化之间的边界。",
        "chat": (
            "决策树的划分可以从节点不纯度来理解。以基尼不纯度为例，节点中第 k 类比例为 p_k 时，"
            "G=1-Σp_k²；候选划分的目标是让左右子节点的加权不纯度下降最多。树继续递归生长，"
            "直到满足深度、叶节点样本数或纯度等停止条件。这里最值得辨析的边界是：训练误差下降并不等于泛化更好。"
            "你可以固定数据划分，比较 max_depth=2、5、None 的训练/验证曲线，并说明为什么无限生长会把噪声也编码进规则。"
        ),
    },
]


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _profile_snapshot_payload(spec: dict, adaptation: dict, public_id: str) -> dict:
    return {
        "kind": "profile_demo_seed",
        "data_label": "合成演示数据，不代表真实用户调研",
        "owner_public_id": public_id,
        "legacy_student_id": spec["username"],
        "course_id": COURSE_ID,
        "course_title": COURSE_TITLE,
        "knowledge_point_id": KP_ID,
        "knowledge_point_title": KP_TITLE,
        "profile_projection": {
            key: spec[key]
            for key in (
                "major", "knowledge_base", "cognitive_style", "motivation_type",
                "learning_goals", "interaction_preferences", "weak_points",
                "mastery", "cognitive_load", "frustration_index", "focus_level",
                "dimension_states",
            )
        },
        "profile_adaptation_plan": profile_prompt_context(adaptation),
        "profile_adaptation_summary": adaptation["summary"],
    }


def _adaptation(spec: dict) -> dict:
    profile = type("Profile", (), {})()
    for key, value in spec.items():
        setattr(profile, key, value)
    profile.concept_mastery = {KP_ID: spec["mastery"], KP_TITLE: spec["mastery"]}
    profile.misconception_patterns = {}
    profile.knowledge_traces = {KP_ID: {"mastery": spec["mastery"]}}
    return build_profile_adaptation(None, profile=profile, knowledge_point={"id": KP_ID, "title": KP_TITLE, "code": "ML-KP-10"})


def _content_variant(raw: str, spec: dict, resource_type: str) -> str:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        marker = f"\n\n本版本学习安排：{spec['adaptation_sentence']}\n"
        return raw.replace("lzz", spec["username"]) + marker
    if not isinstance(payload, dict):
        return raw
    label = spec["adaptation_label"]
    sentence = spec["adaptation_sentence"]
    payload["title"] = f"{KP_TITLE} · {label}"
    for key in ("summary", "learningGoal", "adaptationSummary", "profileSummary"):
        if isinstance(payload.get(key), str):
            payload[key] = f"{payload[key]} {sentence}"
    if isinstance(payload.get("profileAdaptation"), dict):
        payload["profileAdaptation"]["summary"] = sentence
        payload["profileAdaptation"]["difficulty"] = label
        payload["profileAdaptation"]["scaffolding"] = ["高支架" if spec["key"] == "beginner" else "轻量提示" if spec["key"] == "engineer" else "条件提示", sentence]
    if isinstance(payload.get("adaptation"), dict):
        payload["adaptation"]["profileSummary"] = sentence
        payload["adaptation"]["learningGoal"] = "；".join(spec["learning_goals"])
    if isinstance(payload.get("concepts"), list) and payload["concepts"]:
        payload["concepts"][0]["explanation"] = sentence + " " + str(payload["concepts"][0].get("explanation") or "")
    if isinstance(payload.get("sections"), list) and payload["sections"]:
        payload["sections"][0]["body"] = sentence + " " + str(payload["sections"][0].get("body") or "")
    if isinstance(payload.get("nodes"), list) and payload["nodes"]:
        payload["nodes"][0]["summary"] = sentence
    if isinstance(payload.get("slides"), list) and payload["slides"]:
        payload["slides"][0]["subtitle"] = sentence
    if isinstance(payload.get("steps"), list) and payload["steps"]:
        payload["steps"][0]["instruction"] = sentence + " " + str(payload["steps"][0].get("instruction") or "")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _copy_resources(db, spec: dict, snapshot_id: str, public_id: str) -> list[str]:
    template_owner = db.query(DBUser).filter_by(username="lzz").one()
    templates = db.query(DBArtifact).filter_by(owner_public_id=template_owner.public_id, course_id=COURSE_ID).order_by(DBArtifact.artifact_type).all()
    created_ids = []
    adaptation = _adaptation(spec)
    for template in templates:
        source_version = db.get(DBArtifactVersion, template.current_version_id)
        if source_version is None:
            continue
        artifact_id = f"{spec['username']}-resource-{template.artifact_type}"
        existing = db.get(DBArtifact, artifact_id)
        if existing:
            existing_version = db.get(DBArtifactVersion, existing.current_version_id) if existing.current_version_id else None
            if existing_version is not None and "NumPy 数组与向量化计算" in existing_version.content:
                existing_version.content = existing_version.content.replace("NumPy 数组与向量化计算", KP_TITLE)
                existing_version.content_hash = _hash(existing_version.content)
            if existing_version is not None:
                if "分类决策、指标权衡与误差诊断" in existing_version.content:
                    existing_version.content = existing_version.content.replace("分类决策、指标权衡与误差诊断", "决策树分类、过拟合控制与泛化评估")
                    existing_version.content_hash = _hash(existing_version.content)
                metadata = copy.deepcopy(existing_version.metadata_json or {})
                metadata["source_ref_ids"] = ["ref-f157e38d0b189998655836aa", "ref-f79df7bdb0554773a7a1e4ed"]
                existing_version.metadata_json = metadata
            created_ids.append(existing.id)
            continue
        content = _content_variant(source_version.content, spec, template.artifact_type)
        content = content.replace("为 lzz 提供", "为本学习者提供").replace("lzz", "本学习者")
        metadata = copy.deepcopy(source_version.metadata_json or {})
        metadata.update({
            "resource_type": template.artifact_type,
            "knowledge_point_id": KP_ID,
            "profile_snapshot_id": snapshot_id,
            "profile_adaptation_plan": profile_prompt_context(adaptation),
            "profile_adaptation_summary": spec["adaptation_sentence"],
            "demo_scope": "same_course_three_profile_demo",
            "data_label": "合成演示数据，不代表真实用户调研",
        })
        artifact = DBArtifact(id=artifact_id, owner_public_id=public_id, course_id=COURSE_ID, artifact_type=template.artifact_type, title=f"{KP_TITLE} · {spec['adaptation_label']} · {template.artifact_type}", status="approved", lock_version=1)
        db.add(artifact)
        db.flush()
        version = DBArtifactVersion(
            id=f"{artifact_id}-version-1", artifact_id=artifact.id, version_number=1,
            content=content, content_format=source_version.content_format,
            content_hash=_hash(content), metadata_json=metadata,
            created_by_public_id=public_id,
        )
        db.add(version)
        db.flush()
        artifact.current_version_id = version.id
        created_ids.append(artifact.id)
    return created_ids


def _create_chat(db, spec: dict, snapshot_id: str, public_id: str, adaptation: dict) -> str:
    conversation_id = f"{spec['username']}-conversation"
    conversation = db.get(DBChatConversation, conversation_id)
    if conversation is None:
        conversation = DBChatConversation(id=conversation_id, owner_public_id=public_id, course_id=COURSE_ID, title=f"{KP_TITLE} · {spec['adaptation_label']}", status="active", lock_version=1)
        db.add(conversation)
        db.flush()
    if db.query(DBChatMessage).filter_by(conversation_id=conversation_id).count():
        return conversation_id
    question = f"请结合《{COURSE_TITLE}》讲解{KP_TITLE}，并告诉我下一步怎么练习。"
    context = [{"courseId": COURSE_ID, "knowledgePointId": KP_ID, "title": f"{COURSE_TITLE} · {KP_TITLE}", "status": "可用"}]
    for sequence, role, content in ((1, "user", question), (2, "assistant", spec["chat"])):
        db.add(DBChatMessage(
            id=f"{conversation_id}-message-{sequence}", conversation_id=conversation_id,
            owner_public_id=public_id, sequence=sequence, role=role, status="completed",
            content=content, content_sha256=_hash(content),
            idempotency_key=f"{conversation_id}-message-{sequence}", context_refs=context,
            source_refs=[], stream_checkpoint={"profile_snapshot_id": snapshot_id, "profile_adaptation_plan": profile_prompt_context(adaptation)},
            lock_version=1, completed_at=_now(),
        ))
    return conversation_id


def main() -> int:
    db = SessionLocal()
    result = {"course_id": COURSE_ID, "course_title": COURSE_TITLE, "data_label": "合成演示数据，不代表真实用户调研", "accounts": []}
    try:
        course = db.get(DBCourse, COURSE_ID)
        if course is None:
            raise RuntimeError(f"missing course {COURSE_ID}")
        for spec in PROFILES:
            user = db.query(DBUser).filter_by(username=spec["username"]).one_or_none()
            if user is None:
                user = DBUser(username=spec["username"], display_name=spec["display_name"], role="student", is_active=True, hashed_password=get_password_hash(PASSWORD))
                db.add(user)
                db.flush()
            membership = db.query(DBCourseMembership).filter_by(course_id=COURSE_ID, user_public_id=user.public_id).one_or_none()
            if membership is None:
                db.add(DBCourseMembership(course_id=COURSE_ID, user_public_id=user.public_id, role="student", status="active"))
            profile = db.get(DBStudentProfile, spec["username"])
            if profile is None:
                profile = DBStudentProfile(student_id=spec["username"])
                db.add(profile)
            profile.target_course = COURSE_TITLE
            profile.major = spec["major"]
            profile.knowledge_base = spec["knowledge_base"]
            profile.cognitive_style = spec["cognitive_style"]
            profile.motivation_type = spec["motivation_type"]
            profile.learning_goals = spec["learning_goals"]
            profile.interaction_preferences = spec["interaction_preferences"]
            profile.weak_points = spec["weak_points"]
            profile.concept_mastery = {KP_ID: spec["mastery"], KP_TITLE: spec["mastery"]}
            profile.cognitive_load = spec["cognitive_load"]
            profile.frustration_index = spec["frustration_index"]
            profile.focus_level = spec["focus_level"]
            profile.dimension_states = spec["dimension_states"]
            profile.customized_fields = ["major", "target_course", "knowledge_base", "cognitive_style", "motivation_type", "learning_goals", "interaction_preferences"]
            profile.history_logs = "已建立同一课程下的合成演示初始画像。"
            db.flush()
            onboarding = db.query(DBOnboardingSession).filter_by(student_id=spec["username"]).one_or_none()
            if onboarding is not None:
                onboarding.status = "confirmed"
                onboarding.current_dimension = "completed"
                onboarding.checkpoint = 5
                onboarding.version = max(int(onboarding.version or 1), 6)
                onboarding.confirmed_fields = {"target_course": COURSE_TITLE, "profile_demo": True}
                onboarding.missing_fields = []
                onboarding.course_context = {"courseId": COURSE_ID, "courseTitle": COURSE_TITLE}
                onboarding.confirmed_at = _now()
            adaptation = _adaptation(spec)
            snapshot_id = f"{spec['username']}-profile-snapshot"
            snapshot_payload = _profile_snapshot_payload(spec, adaptation, user.public_id)
            snapshot = db.get(DBProfileSnapshot, snapshot_id)
            if snapshot is None:
                snapshot = DBProfileSnapshot(id=snapshot_id, owner_public_id=user.public_id, legacy_student_id=spec["username"], profile_version="profile-demo.v1", snapshot=snapshot_payload, content_hash=_hash(json.dumps(snapshot_payload, ensure_ascii=False, sort_keys=True)), trace_id=f"{spec['username']}-profile-trace")
                db.add(snapshot)
            else:
                snapshot.snapshot = snapshot_payload
            db.flush()
            resources = _copy_resources(db, spec, snapshot_id, user.public_id)
            conversation_id = _create_chat(db, spec, snapshot_id, user.public_id, adaptation)
            result["accounts"].append({
                "username": spec["username"], "password": PASSWORD, "display_name": spec["display_name"],
                "course_id": COURSE_ID, "course_title": COURSE_TITLE, "knowledge_point": KP_TITLE,
                "profile": {"major": spec["major"], "mastery": spec["mastery"], "goals": spec["learning_goals"], "preferences": spec["interaction_preferences"], "style": spec["cognitive_style"], "adaptation": spec["adaptation_label"]},
                "resource_ids": resources, "conversation_id": conversation_id,
            })
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    output = ROOT / "outputs" / "profile_demo_accounts"
    output.mkdir(parents=True, exist_ok=True)
    (output / "accounts.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
