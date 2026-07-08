import sys
import os
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

# 允许 app 导入 root 目录下的 models.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import StudentProfile, DimensionState, CauseBreakdown, KnowledgeTrace, AlignmentReport, ProfileEvidence, ProfileEvidenceSource
from app.database import DBStudentProfile, DBAlignmentLog, DBNote, DBReviewPlan, DBConversationHistory

def to_dict_safe(obj):
    """递归将 dataclass 转换为字典，安全避免 Enum/类型 循环递归"""
    from enum import Enum
    if isinstance(obj, Enum):
        return obj.value
    elif isinstance(obj, type):
        return obj.__name__
    elif hasattr(obj, "__dict__"):
        return {k: to_dict_safe(v) for k, v in obj.__dict__.items()}
    elif isinstance(obj, dict):
        return {k: to_dict_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_dict_safe(v) for v in obj]
    elif isinstance(obj, tuple):
        return [to_dict_safe(v) for v in obj]
    return obj

def load_student_profile(db: Session, student_id: str) -> StudentProfile:
    """从 SQLite 中加载学生画像，如果不存在则初始化并存入数据库
    
    Note: 使用 db.merge() 避免并发写入时的 UNIQUE 约束竞态 (BUG-07 fix)
    """
    from sqlalchemy.exc import IntegrityError

    db_profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == student_id).first()
    
    if not db_profile:
        # 创建默认画像并写入 SQLite 物理表
        profile = StudentProfile(student_id=student_id)
        try:
            save_student_profile(db, profile)
        except IntegrityError:
            db.rollback()
            # 并发写入冲突，重新读取
            db_profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == student_id).first()
            if db_profile:
                # 并发写入冲突，重新读取并映射
                profile = StudentProfile(student_id=student_id)
                profile.target_course = db_profile.target_course
                profile.knowledge_base = db_profile.knowledge_base
                profile.cognitive_style = db_profile.cognitive_style
                profile.focus_level = db_profile.focus_level
                profile.cognitive_load = db_profile.cognitive_load
                profile.motivation_type = getattr(db_profile, "motivation_type", "未诊断") or "未诊断"
                profile.frustration_index = getattr(db_profile, "frustration_index", 0.0) or 0.0
                profile.weak_points = list(db_profile.weak_points or [])
                profile.learning_goals = list(db_profile.learning_goals or [])
                profile.interaction_preferences = list(db_profile.interaction_preferences or [])
                profile.concept_mastery = dict(db_profile.concept_mastery or {})
                profile.misconception_patterns = dict(db_profile.misconception_patterns or {})
                if db_profile.history_logs:
                    profile.history = db_profile.history_logs.split("\n")
                profile.major = db_profile.major or ""
                profile.favorites = list(db_profile.favorites or [])
                profile.narrative_report = db_profile.narrative_report or ""
                profile.dashboard_report = getattr(db_profile, "dashboard_report", "") or ""
                profile.customized_fields = list(db_profile.customized_fields or [])
                profile.rl_q_table = dict(getattr(db_profile, "rl_q_table", {}) or {})
                profile.mental_state_history = list(getattr(db_profile, "mental_state_history", []) or [])
                return profile
        return profile

    # 物理反序列化映射：从 SQLite JSON 数据构建内存 Dataclass 实例
    profile = StudentProfile(student_id=student_id)
    profile.target_course = db_profile.target_course
    profile.knowledge_base = db_profile.knowledge_base
    profile.cognitive_style = db_profile.cognitive_style
    profile.focus_level = db_profile.focus_level
    profile.cognitive_load = db_profile.cognitive_load
    profile.motivation_type = getattr(db_profile, "motivation_type", "未诊断") or "未诊断"
    profile.frustration_index = getattr(db_profile, "frustration_index", 0.0) or 0.0
    
    profile.weak_points = list(db_profile.weak_points or [])
    profile.learning_goals = list(db_profile.learning_goals or [])
    profile.interaction_preferences = list(db_profile.interaction_preferences or [])
    profile.concept_mastery = dict(db_profile.concept_mastery or {})
    profile.misconception_patterns = dict(db_profile.misconception_patterns or {})
    
    if db_profile.history_logs:
        profile.history = db_profile.history_logs.split("\n")
    else:
        profile.history = []

    # 还原新增加的物理字段 (Task 6.2)
    profile.major = db_profile.major or ""
    profile.favorites = list(db_profile.favorites or [])
    profile.narrative_report = db_profile.narrative_report or ""
    profile.dashboard_report = getattr(db_profile, "dashboard_report", "") or ""
    profile.customized_fields = list(db_profile.customized_fields or [])
    profile.rl_q_table = dict(getattr(db_profile, "rl_q_table", {}) or {})
    profile.mental_state_history = list(getattr(db_profile, "mental_state_history", []) or [])
    
    if db_profile.knowledge_traces:
        for k, v in db_profile.knowledge_traces.items():
            profile.knowledge_traces[k] = KnowledgeTrace(
                concept=v.get("concept", k),
                mastery=v.get("mastery", 0.48),
                attempts=v.get("attempts", 0),
                correct_attempts=v.get("correct_attempts", 0),
                last_updated=v.get("last_updated", "")
            )
            
    if db_profile.profile_evidence:
        profile.profile_evidence = [
            ProfileEvidence(
                source=ProfileEvidenceSource(e.get("source")),
                text=e.get("text", ""),
                features=tuple(e.get("features", [])),
                weight=e.get("weight", 0.0),
                confidence=e.get("confidence", 0.0),
                timestamp=e.get("timestamp", "")
            )
            for e in db_profile.profile_evidence if e
        ]

    # 还原 dimension_states
    if db_profile.dimension_states:
        for k, v in db_profile.dimension_states.items():
            profile.dimension_states[k] = DimensionState(
                key=v.get("key", k),
                label=v.get("label", ""),
                score=v.get("score", 0.0),
                confidence=v.get("confidence", 0.0),
                status=v.get("status", ""),
                evidence_count=v.get("evidence_count", 0),
                evidence_fragments=list(v.get("evidence_fragments", [])),
                recommended_interventions=list(v.get("recommended_interventions", [])),
                last_updated=v.get("last_updated", "")
            )
            
    # 还原 learning_state_causes
    if db_profile.learning_state_causes:
        for k, v in db_profile.learning_state_causes.items():
            profile.learning_state_causes[k] = CauseBreakdown(
                key=v.get("key", k),
                label=v.get("label", ""),
                percentage=v.get("percentage", 0.0),
                confidence=v.get("confidence", 0.0),
                evidence_count=v.get("evidence_count", 0),
                evidence_fragments=list(v.get("evidence_fragments", [])),
                recommended_interventions=list(v.get("recommended_interventions", []))
            )

    return profile

def save_student_profile(db: Session, profile: StudentProfile) -> None:
    """持久化保存/更新学生画像至 SQLite 数据库，实现事务性保存"""
    db_profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == profile.student_id).first()
    
    if not db_profile:
        db_profile = DBStudentProfile(student_id=profile.student_id)
        db.add(db_profile)
        
    db_profile.target_course = profile.target_course
    db_profile.knowledge_base = profile.knowledge_base
    db_profile.cognitive_style = profile.cognitive_style
    db_profile.focus_level = profile.focus_level
    db_profile.cognitive_load = profile.cognitive_load
    db_profile.motivation_type = profile.motivation_type
    db_profile.frustration_index = profile.frustration_index
    
    db_profile.weak_points = profile.weak_points
    db_profile.learning_goals = profile.learning_goals
    db_profile.interaction_preferences = profile.interaction_preferences
    db_profile.concept_mastery = profile.concept_mastery
    db_profile.misconception_patterns = profile.misconception_patterns
    
    db_profile.history_logs = "\n".join(profile.history)
    
    # 序列化复杂/新增物理对象为 JSON 格式存入 SQLite (Task 6.2)
    db_profile.major = profile.major
    db_profile.favorites = to_dict_safe(profile.favorites)
    db_profile.narrative_report = profile.narrative_report
    db_profile.dashboard_report = profile.dashboard_report
    db_profile.knowledge_traces = to_dict_safe(profile.knowledge_traces)
    db_profile.profile_evidence = to_dict_safe(profile.profile_evidence)
    db_profile.customized_fields = to_dict_safe(profile.customized_fields)
    db_profile.rl_q_table = to_dict_safe(profile.rl_q_table)
    db_profile.mental_state_history = to_dict_safe(profile.mental_state_history)
    
    db_profile.dimension_states = to_dict_safe(profile.dimension_states)
    db_profile.learning_state_causes = to_dict_safe(profile.learning_state_causes)
    
    db.commit()

def record_alignment_log(db: Session, student_id: str, report: AlignmentReport, target_concept: str) -> None:
    """记录每一次流形对齐校验的测地线距离与冲突建议"""
    log_entry = DBAlignmentLog(
        student_id=student_id,
        target_concept=target_concept,
        passed=report.passed,
        distance=report.distance,
        threshold=report.threshold,
        conflicts=list(report.conflicts),
        advice=report.advice
    )
    db.add(log_entry)
    db.commit()


def create_note(db: Session, student_id: str, source: str, content: str, tags: list[str] | None = None, concepts: list[str] | None = None) -> DBNote:
    import hashlib
    note_id = hashlib.sha256(f"{student_id}:{content[:64]}:{datetime.utcnow().isoformat()}".encode()).hexdigest()[:16]
    db_note = DBNote(
        id=note_id,
        student_id=student_id,
        source=source,
        content=content,
        tags=tags or [],
        concepts=concepts or [],
    )
    db.add(db_note)
    db.commit()
    db.refresh(db_note)
    return db_note


def get_notes(db: Session, student_id: str, limit: int = 20) -> list[DBNote]:
    return (
        db.query(DBNote)
        .filter(DBNote.student_id == student_id)
        .order_by(DBNote.created_at.desc())
        .limit(limit)
        .all()
    )


def delete_note(db: Session, note_id: str) -> bool:
    note = db.query(DBNote).filter(DBNote.id == note_id).first()
    if not note:
        return False
    db.delete(note)
    db.commit()
    return True


def update_note(db: Session, note_id: str, content: str, tags: list[str] | None = None, concepts: list[str] | None = None) -> DBNote | None:
    db_note = db.query(DBNote).filter(DBNote.id == note_id).first()
    if not db_note:
        return None
    db_note.content = content
    if tags is not None:
        db_note.tags = tags
    if concepts is not None:
        db_note.concepts = concepts
    db_note.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_note)
    return db_note


def append_wrong_question_reflection(db: Session, student_id: str, concept: str, quiz_record_id: str, wrong_reason: str) -> DBNote:
    from app.database import DBQuizRecord
    record = db.query(DBQuizRecord).filter(DBQuizRecord.id == quiz_record_id).first()
    
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    q_text = (record.question or "自适应测试题").strip() if record else "自适应测试题"
    std_ans = (record.student_answer or "未提交").strip() if record else "未提交"
    ref_ans = (record.correct_answer or "未提供").strip() if record else "未提供"
    
    diag_feedback = (record.feedback or "未提供诊断反馈").strip() if (record and record.feedback) else "未提供诊断反馈"
    
    # 格式化我的回答，防止多行或代码块错乱
    if "\n" in std_ans or "```" in std_ans:
        formatted_std_ans = f"\n```\n{std_ans}\n```"
    else:
        formatted_std_ans = f"`{std_ans}`"
        
    category_labels = {
        "review": "需复习",
        "practice": "需练习",
        "advance": "可进阶",
        "misconception": "概念误解",
        "outlier_sensitivity": "对异常值敏感",
        "calculation_error": "计算错误",
        "carelessness": "粗心大意",
    }
    reason_label = category_labels.get(wrong_reason, wrong_reason)

    reflection_md = (
        f"\n\n---\n\n"
        f"### ❌ 错题反思小记 ({time_str})\n\n"
        f"> [!IMPORTANT]\n"
        f"> **💡 系统诊断反馈**\n"
        f"> {diag_feedback}\n\n"
        f"- **核心概念**：`{concept}`\n"
        f"- **错因分类**：`{reason_label}` ({wrong_reason})\n\n"
        f"#### **📝 错题题目**\n"
        f"{q_text}\n\n"
        f"#### **👤 我的回答**\n"
        f"{formatted_std_ans}\n\n"
        f"#### **🎯 参考答案与解析**\n"
        f"{ref_ans}\n\n"
        f"---\n"
    )
    
    # 查找此概念对应的现有错题集笔记（通过 source="错题本反思" 来隔离普通笔记）
    notes = db.query(DBNote).filter(
        DBNote.student_id == student_id,
        DBNote.source == "错题本反思"
    ).all()
    existing_note = None
    
    # 1. 优先精确匹配 concepts (忽略大小写)
    for n in notes:
        if n.concepts and any(concept.strip().lower() == c.strip().lower() for c in n.concepts):
            existing_note = n
            break
            
    # 2. 其次匹配 tags (忽略大小写)
    if not existing_note:
        for n in notes:
            if n.tags and any(concept.strip().lower() == t.strip().lower() for t in n.tags):
                existing_note = n
                break
                
    # 3. 再次匹配标题或内容的前几行 (首行通常是标题)
    if not existing_note:
        for n in notes:
            first_lines = n.content.split('\n')[:5]
            if any(concept.strip().lower() in line.lower() for line in first_lines if line.strip()):
                existing_note = n
                break
            
    if existing_note:
        existing_note.content += reflection_md
        existing_note.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing_note)
        return existing_note
    else:
        import hashlib
        note_id = hashlib.sha256(f"{student_id}:{concept}:{datetime.utcnow().isoformat()}".encode()).hexdigest()[:16]
        new_note = DBNote(
            id=note_id,
            student_id=student_id,
            source="错题本反思",
            content=f"# {concept} 错题集\n\n该笔记由错题本反思自动初始化。{reflection_md}",
            tags=["错题整理", "反思"],
            concepts=[concept],
        )
        db.add(new_note)
        db.commit()
        db.refresh(new_note)
        return new_note


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def review_plan_to_dict(plan: DBReviewPlan) -> dict:
    now = _utcnow_naive()
    next_review_at = _as_utc_naive(plan.next_review_at)
    is_due = next_review_at is None or next_review_at <= now
    if next_review_at is None:
        days_until_due = 0
    elif is_due:
        days_until_due = 0
    else:
        days_until_due = max(1, (next_review_at.date() - now.date()).days)

    return {
        "id": plan.id,
        "concept": plan.concept,
        "interval_days": plan.interval_days,
        "next_review_at": next_review_at.isoformat() if next_review_at else None,
        "mastery": plan.mastery,
        "review_count": plan.review_count or 0,
        "easiness_factor": round(plan.easiness_factor or 2.5, 2),
        "last_quality": plan.last_quality or 0,
        "is_due": is_due,
        "days_until_due": days_until_due,
        "priority": plan.priority if plan.priority is not None else 1.0,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


def get_review_plan(db: Session, student_id: str) -> list[DBReviewPlan]:
    return (
        db.query(DBReviewPlan)
        .filter(DBReviewPlan.student_id == student_id)
        .order_by(DBReviewPlan.next_review_at.asc())
        .all()
    )


def upsert_review_plan(db: Session, student_id: str, concept: str, mastery: float, interval_days: int) -> DBReviewPlan:
    # 确保学生画像已创建并保存，以防外键约束失败 (FOREIGN KEY constraint failed)
    load_student_profile(db, student_id)
    existing = (
        db.query(DBReviewPlan)
        .filter(DBReviewPlan.student_id == student_id, DBReviewPlan.concept == concept)
        .first()
    )
    if existing:
        existing.interval_days = interval_days
        existing.next_review_at = _utcnow_naive() + timedelta(days=interval_days)
        existing.mastery = mastery
        existing.easiness_factor = existing.easiness_factor or 2.5
        existing.review_count = existing.review_count or 0
        existing.last_quality = existing.last_quality or 0
        existing.priority = existing.priority if existing.priority is not None else 1.0
    else:
        existing = DBReviewPlan(
            student_id=student_id,
            concept=concept,
            interval_days=interval_days,
            next_review_at=_utcnow_naive() + timedelta(days=interval_days),
            mastery=mastery,
            review_count=0,
            easiness_factor=2.5,
            last_quality=0,
            priority=1.0,
        )
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


def apply_review_feedback(db: Session, student_id: str, concept: str, quality: int) -> DBReviewPlan:
    if quality not in (2, 4, 5):
        raise ValueError("quality must be one of 2, 4, 5")
    if not concept:
        raise ValueError("concept is required")

    from anki_engine import sm2_schedule

    load_student_profile(db, student_id)
    plan = (
        db.query(DBReviewPlan)
        .filter(DBReviewPlan.student_id == student_id, DBReviewPlan.concept == concept)
        .first()
    )
    if plan is None:
        plan = DBReviewPlan(
            student_id=student_id,
            concept=concept,
            interval_days=1,
            next_review_at=_utcnow_naive(),
            mastery=0.3,
            review_count=0,
            easiness_factor=2.5,
            last_quality=0,
            priority=1.0,
        )
        db.add(plan)
        db.flush()

    current_easiness = plan.easiness_factor or 2.5
    current_interval = plan.interval_days or 1
    new_easiness, new_interval = sm2_schedule(current_easiness, current_interval, quality)

    mastery = plan.mastery if plan.mastery is not None else 0.3
    if quality == 5:
        mastery = min(1.0, mastery + 0.08)
    elif quality == 4:
        mastery = min(1.0, mastery + 0.04)
    else:
        mastery = max(0.0, mastery - 0.10)

    plan.easiness_factor = new_easiness
    plan.interval_days = new_interval
    plan.last_quality = quality
    plan.review_count = (plan.review_count or 0) + 1
    plan.mastery = mastery
    plan.next_review_at = _utcnow_naive() + timedelta(days=new_interval)
    plan.priority = 0.35 if quality < 4 else (0.7 if new_interval <= 1 else 1.0)

    db_profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == student_id).first()
    if db_profile:
        concept_mastery = dict(db_profile.concept_mastery or {})
        concept_mastery[concept] = round(mastery, 2)
        db_profile.concept_mastery = concept_mastery

        weak_points = list(db_profile.weak_points or [])
        if quality == 2 and concept not in weak_points:
            weak_points.insert(0, concept)
        elif quality in (4, 5) and mastery >= 0.7 and concept in weak_points:
            weak_points = [item for item in weak_points if item != concept]
        db_profile.weak_points = weak_points[:20]

    db.commit()
    db.refresh(plan)
    return plan


def build_review_adaptation_payload(concept: str, quality: int, mastery: float | None = None) -> dict:
    """Create a deterministic card-morphing payload for difficult reviews."""
    mastery_score = max(0.0, min(1.0, float(mastery if mastery is not None else 0.3)))
    if quality != 2:
        return {
            "triggered": False,
            "concept": concept,
            "quality": quality,
            "mastery": round(mastery_score, 2),
            "agent_trace": [
                "Director Agent: 复习反馈已记录，保持原卡片结构。",
                "SM-2 Engine: 已根据评分更新下次复习间隔。",
            ],
        }

    simplified = (
        f"检测到「{concept}」仍然吃力，先把它拆成三步："
        f"第一步只确认它要解决什么问题；第二步看输入怎样一步步变成输出；"
        f"第三步再回到公式或代码细节。当前掌握度约 {round(mastery_score * 100)}%，"
        "建议先看一遍可视化例子，再做一道最小变式题。"
    )
    mermaid = (
        "flowchart LR\n"
        f"    A[直觉问题: {concept}] --> B[生活化类比]\n"
        "    B --> C[关键变量]\n"
        "    C --> D[最小例题]\n"
        "    D --> E[重新复述]\n"
    )
    return {
        "triggered": True,
        "concept": concept,
        "quality": quality,
        "mastery": round(mastery_score, 2),
        "mode": "generative_morphing",
        "title": f"「{concept}」降维解释已生成",
        "simplified_explanation": simplified,
        "mermaid": mermaid,
        "card_back": simplified + "\n\n" + mermaid,
        "agent_trace": [
            "Director Agent: 检测到困难反馈，切换为降维解释模式。",
            "Visualizer Agent: 已生成 Mermaid 思维对比图。",
            "Profile Agent: 已下调该概念掌握度，并写入薄弱点列表。",
            "Planner Agent: 下一次学习路径会重新考虑该薄弱点。",
        ],
    }


def record_conversation(
    db: Session, student_id: str, query: str, response_summary: str, target: str, resources_count: int, alignment_passed: bool
) -> DBConversationHistory:
    record = DBConversationHistory(
        student_id=student_id,
        query=query,
        response_summary=response_summary,
        target=target,
        resources_count=resources_count,
        alignment_passed=alignment_passed,
    )
    db.add(record)
    db.commit()
    return record


def get_conversation_history(db: Session, student_id: str, limit: int = 30) -> list[DBConversationHistory]:
    return (
        db.query(DBConversationHistory)
        .filter(DBConversationHistory.student_id == student_id)
        .order_by(DBConversationHistory.created_at.desc())
        .limit(limit)
        .all()
    )
