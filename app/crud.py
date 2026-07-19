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

def calibrate_student_prior_collaborative(db: Session, profile: StudentProfile) -> None:
    """协同画像先验校准：若当前画像无掌握度数据，寻找相似 Peer 的特征均值进行初始化。"""
    from app.database import DBStudentProfile
    peers = db.query(DBStudentProfile).filter(DBStudentProfile.student_id != profile.student_id).all()
    if not peers:
        return
        
    peer_scores = []
    for peer in peers:
        score = 0.0
        if peer.major and profile.major and peer.major == profile.major:
            score += 3.0
        if peer.cognitive_style and profile.cognitive_style and peer.cognitive_style == profile.cognitive_style:
            score += 2.0
        if peer.motivation_type and profile.motivation_type and peer.motivation_type == profile.motivation_type:
            score += 1.0
        
        if score > 0.0 and peer.concept_mastery:
            peer_scores.append((score, peer))
            
    if not peer_scores:
        return
        
    peer_scores.sort(key=lambda x: x[0], reverse=True)
    top_peers = [p for _, p in peer_scores[:3]]
    
    mastery_sum = {}
    mastery_count = {}
    bkt_states_merged = {}
    
    for peer in top_peers:
        for c, m in (peer.concept_mastery or {}).items():
            mastery_sum[c] = mastery_sum.get(c, 0.0) + m
            mastery_count[c] = mastery_count.get(c, 0) + 1
            
        for c, bkt in (peer.bkt_states or {}).items():
            if c not in bkt_states_merged:
                bkt_states_merged[c] = {
                    "p_mastered": bkt.get("p_mastered", 0.3),
                    "smoothed_mastery": bkt.get("smoothed_mastery", 0.3),
                    "p_err": bkt.get("p_err", 0.1),
                    "attempts": bkt.get("attempts", 0),
                    "accuracy": bkt.get("accuracy", 0.0),
                    "history": bkt.get("history", []),
                    "layers": bkt.get("layers", {})
                }
            else:
                bkt_states_merged[c]["p_mastered"] += bkt.get("p_mastered", 0.3)
                bkt_states_merged[c]["smoothed_mastery"] += bkt.get("smoothed_mastery", 0.3)
                bkt_states_merged[c]["p_err"] += bkt.get("p_err", 0.1)
                
    for c in mastery_sum:
        count = mastery_count[c]
        profile.concept_mastery[c] = round(mastery_sum[c] / count, 4)
        
    for c in bkt_states_merged:
        count = len(top_peers)
        bkt_states_merged[c]["p_mastered"] = round(bkt_states_merged[c]["p_mastered"] / count, 4)
        bkt_states_merged[c]["smoothed_mastery"] = round(bkt_states_merged[c]["smoothed_mastery"] / count, 4)
        bkt_states_merged[c]["p_err"] = round(bkt_states_merged[c]["p_err"] / count, 4)
        
    profile.bkt_states = bkt_states_merged

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
                profile.concept_layers = dict(getattr(db_profile, "concept_layers", {}) or {})
                profile.bkt_states = dict(getattr(db_profile, "bkt_states", {}) or {})
                profile.cognitive_map = dict(getattr(db_profile, "cognitive_map", {}) or {})
                profile.fsm_mode = getattr(db_profile, "fsm_mode", "normal") or "normal"
                profile.fsm_accuracy_history = dict(getattr(db_profile, "fsm_accuracy_history", {}) or {})
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
    profile.concept_layers = dict(getattr(db_profile, "concept_layers", {}) or {})
    profile.bkt_states = dict(getattr(db_profile, "bkt_states", {}) or {})
    profile.cognitive_map = dict(getattr(db_profile, "cognitive_map", {}) or {})
    profile.fsm_mode = getattr(db_profile, "fsm_mode", "normal") or "normal"
    profile.fsm_accuracy_history = dict(getattr(db_profile, "fsm_accuracy_history", {}) or {})
    
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
    db_profile.concept_layers = to_dict_safe(profile.concept_layers)
    db_profile.bkt_states = to_dict_safe(profile.bkt_states)
    db_profile.cognitive_map = to_dict_safe(profile.cognitive_map)
    db_profile.fsm_mode = profile.fsm_mode
    db_profile.fsm_accuracy_history = to_dict_safe(profile.fsm_accuracy_history)
    
    db_profile.dimension_states = to_dict_safe(profile.dimension_states)
    db_profile.learning_state_causes = to_dict_safe(profile.learning_state_causes)

    
    db.commit()

def record_alignment_log(db: Session, student_id: str, report: AlignmentReport, target_concept: str) -> None:
    """记录每一次流形对齐校验的测地线距离与冲突建议"""
    # 确保学生画像已创建，防止外键约束失败 (FOREIGN KEY constraint failed)
    load_student_profile(db, student_id)
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
    
    processed_concepts = []
    if concepts:
        for c in concepts:
            if "与" in c:
                processed_concepts.extend([sub.strip() for sub in c.split("与") if sub.strip()])
            elif "和" in c:
                processed_concepts.extend([sub.strip() for sub in c.split("和") if sub.strip()])
            else:
                processed_concepts.append(c)

    db_note = DBNote(
        id=note_id,
        student_id=student_id,
        source=source,
        content=content,
        tags=tags or [],
        concepts=processed_concepts,
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


def delete_note(db: Session, note_id: str, student_id: str | None = None) -> bool:
    query = db.query(DBNote).filter(DBNote.id == note_id)
    if student_id:
        query = query.filter(DBNote.student_id == student_id)
    note = query.first()
    if not note:
        return False
    db.delete(note)
    db.commit()
    return True


def update_note(
    db: Session,
    note_id: str,
    content: str,
    tags: list[str] | None = None,
    concepts: list[str] | None = None,
    student_id: str | None = None,
) -> DBNote | None:
    query = db.query(DBNote).filter(DBNote.id == note_id)
    if student_id:
        query = query.filter(DBNote.student_id == student_id)
    db_note = query.first()
    if not db_note:
        return None
    db_note.content = content
    if tags is not None:
        db_note.tags = tags
    if concepts is not None:
        processed_concepts = []
        for c in concepts:
            if "与" in c:
                processed_concepts.extend([sub.strip() for sub in c.split("与") if sub.strip()])
            elif "和" in c:
                processed_concepts.extend([sub.strip() for sub in c.split("和") if sub.strip()])
            else:
                processed_concepts.append(c)
        db_note.concepts = processed_concepts
    db_note.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_note)
    return db_note


def append_wrong_question_reflection(db: Session, student_id: str, concept: str, quiz_record_id: str, wrong_reason: str) -> DBNote:
    from app.database import DBQuizRecord
    record = db.query(DBQuizRecord).filter(
        DBQuizRecord.id == quiz_record_id,
        DBQuizRecord.student_id == student_id,
    ).first()
    
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
    db_profile = load_student_profile(db, student_id)
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
        init_easiness = 2.5
        if db_profile and getattr(db_profile, "bkt_states", None) and concept in db_profile.bkt_states:
            bkt_state = db_profile.bkt_states[concept]
            p_err = bkt_state.get("p_err", 0.5) if isinstance(bkt_state, dict) else getattr(bkt_state, "p_err", 0.5)
            if p_err > 0.4:
                init_easiness = max(1.8, 2.5 - (p_err - 0.4) * 1.5)

        existing = DBReviewPlan(
            student_id=student_id,
            concept=concept,
            interval_days=interval_days,
            next_review_at=_utcnow_naive() + timedelta(days=interval_days),
            mastery=mastery,
            review_count=0,
            easiness_factor=init_easiness,
            last_quality=0,
            priority=1.0,
        )
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


def delete_review_plan(db: Session, plan_id: int, student_id: str | None = None) -> bool:
    query = db.query(DBReviewPlan).filter(DBReviewPlan.id == plan_id)
    if student_id:
        query = query.filter(DBReviewPlan.student_id == student_id)
    plan = query.first()
    if not plan:
        return False
    db.delete(plan)
    db.commit()
    return True



def apply_review_feedback(db: Session, student_id: str, concept: str, quality: float) -> DBReviewPlan:
    if quality not in (2, 4, 5):
        raise ValueError("quality must be one of 2, 4, 5")
    if not concept:
        raise ValueError("concept is required")

    from anki_engine import sm2_schedule

    db_profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == student_id).first()
    cognitive_load = 0.45
    frustration = 0.0
    if db_profile:
        cognitive_load = getattr(db_profile, "cognitive_load", 0.45) or 0.45
        frustration = getattr(db_profile, "frustration_index", 0.0) or 0.0

    plan = (
        db.query(DBReviewPlan)
        .filter(DBReviewPlan.student_id == student_id, DBReviewPlan.concept == concept)
        .first()
    )
    if plan is None:
        init_easiness = 2.5
        if db_profile and getattr(db_profile, "bkt_states", None) and concept in db_profile.bkt_states:
            bkt_state = db_profile.bkt_states[concept]
            p_err = bkt_state.get("p_err", 0.5) if isinstance(bkt_state, dict) else getattr(bkt_state, "p_err", 0.5)
            if p_err > 0.4:
                init_easiness = max(1.8, 2.5 - (p_err - 0.4) * 1.5)

        plan = DBReviewPlan(
            student_id=student_id,
            concept=concept,
            interval_days=1,
            next_review_at=_utcnow_naive(),
            mastery=0.3,
            review_count=0,
            easiness_factor=init_easiness,
            last_quality=0,
            priority=1.0,
        )
        db.add(plan)
        db.flush()

    try:
        q_val = float(quality)
    except (TypeError, ValueError):
        q_val = 4.0
    q_clamped = max(0.0, min(5.0, q_val))

    current_easiness = plan.easiness_factor or 2.5
    current_interval = plan.interval_days or 1
    new_easiness, new_interval = sm2_schedule(
        current_easiness,
        current_interval,
        q_clamped,
        cognitive_load=cognitive_load,
        frustration=frustration,
    )

    mastery = plan.mastery if plan.mastery is not None else 0.3
    if q_clamped >= 4.5:
        mastery = min(1.0, mastery + 0.08)
    elif q_clamped >= 3.5:
        mastery = min(1.0, mastery + 0.04)
    else:
        mastery = max(0.0, mastery - 0.10)

    plan.easiness_factor = new_easiness
    plan.interval_days = new_interval
    plan.last_quality = int(round(q_clamped))
    plan.review_count = (plan.review_count or 0) + 1
    plan.mastery = mastery
    plan.next_review_at = _utcnow_naive() + timedelta(days=new_interval)
    plan.priority = 0.35 if q_clamped < 3.5 else (0.7 if new_interval <= 1 else 1.0)

    if db_profile:
        concept_mastery = dict(db_profile.concept_mastery or {})
        concept_mastery[concept] = round(mastery, 2)
        db_profile.concept_mastery = concept_mastery

        weak_points = list(db_profile.weak_points or [])
        if q_clamped < 3.5:
            if concept not in weak_points:
                weak_points.insert(0, concept)
        else:
            if mastery >= 0.7 and concept in weak_points:
                weak_points = [item for item in weak_points if item != concept]
        db_profile.weak_points = weak_points[:20]

    db.commit()
    db.refresh(plan)
    return plan


async def build_review_adaptation_payload(concept: str, quality: int, mastery: float | None = None) -> dict:
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
            "stream_chunks": [],
        }

    from llm_client import DEFAULT_LLM, get_concept_rich_adaptation
    import json
    import asyncio

    rich_data = get_concept_rich_adaptation(concept, mastery_score)
    simplified = rich_data["explanation"]
    mermaid = rich_data["mermaid"]
    llm_backend = "VisualizerAgent"

    try:
        llm_backend = getattr(DEFAULT_LLM, "__class__", type(DEFAULT_LLM)).__name__
        generated = await asyncio.to_thread(
            DEFAULT_LLM.generate,
            "你是 EduMatrix 的 Visualizer Agent 和 Director Agent。学生复习反馈为困难，请把概念降维成生活化解释。",
            (
                f"概念: {concept}\n"
                f"当前掌握度: {mastery_score:.2f}\n"
                "请输出一段不超过 120 字的中文解释，先讲直觉，再给最小行动建议。"
            ),
            role="概念可视化导师",
        )
        if generated and len(generated.strip()) >= 12 and "已基于检索证据处理主题" not in generated:
            try:
                parsed = json.loads(generated.strip())
                if isinstance(parsed, dict) and "explanation" in parsed and "mermaid" in parsed:
                    simplified = parsed["explanation"]
                    mermaid = parsed["mermaid"]
                else:
                    simplified = generated.strip()
            except Exception:
                simplified = generated.strip()
    except Exception:
        pass
    card_back = simplified + "\n\n" + mermaid
    stream_chunks = [card_back[i : i + 28] for i in range(0, len(card_back), 28)]
    return {
        "triggered": True,
        "concept": concept,
        "quality": quality,
        "mastery": round(mastery_score, 2),
        "mode": "generative_morphing",
        "llm_backend": llm_backend,
        "title": f"「{concept}」降维解释已生成",
        "simplified_explanation": simplified,
        "mermaid": mermaid,
        "card_back": card_back,
        "stream_chunks": stream_chunks,
        "agent_trace": [
            "Director Agent: 检测到困难反馈，切换为降维解释模式。",
            f"Visualizer Agent: 已通过 {llm_backend} 生成降维解释与 Mermaid 思维对比图。",
            "Profile Agent: 已下调该概念掌握度，并写入薄弱点列表。",
            "Planner Agent: 下一次学习路径会重新考虑该薄弱点。",
        ],
    }


def record_conversation(
    db: Session, student_id: str, query: str, response_summary: str, target: str, resources_count: int, alignment_passed: bool, profile_snapshot: dict | None = None
) -> DBConversationHistory:
    record = DBConversationHistory(
        student_id=student_id,
        query=query,
        response_summary=response_summary,

        target=target,
        resources_count=resources_count,
        alignment_passed=alignment_passed,
        profile_snapshot=profile_snapshot,
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


def migrate_anonymous_data(db: Session, anon_id: str, target_id: str):
    """
    将匿名临时ID(anon_id)产生的所有学情数据迁移/合并到正式账号(target_id)下，
    防止登录/注册后历史复习计划、笔记、错题本丢失。
    """
    if not anon_id or not target_id or anon_id == target_id:
        return

    # 1. 检查匿名画像和正式账号画像是否存在
    anon_profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == anon_id).first()
    target_profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == target_id).first()

    if not anon_profile:
        # 匿名账号没有任何画像数据，无需迁移
        return

    if not target_profile:
        # 如果正式账号没有画像，可以直接将匿名画像的主键更改为正式账号ID
        try:
            anon_profile.student_id = target_id
            db.commit()
            return
        except Exception:
            db.rollback()
            # 如果更新报错，回退到普通合并流程
            target_profile = DBStudentProfile(student_id=target_id)
            db.add(target_profile)
            db.commit()

    # 2. 合并画像状态 (Merge Profiles)
    target_profile.target_course = target_profile.target_course or anon_profile.target_course
    target_profile.major = target_profile.major or anon_profile.major
    target_profile.cognitive_style = target_profile.cognitive_style or anon_profile.cognitive_style
    
    # 融合 concept_mastery (保留更高的掌握度，或用最新的覆盖)
    mastery_a = dict(anon_profile.concept_mastery or {})
    mastery_t = dict(target_profile.concept_mastery or {})
    for k, v in mastery_a.items():
        if k not in mastery_t:
            mastery_t[k] = v
        else:
            mastery_t[k] = max(mastery_t[k], v)
    target_profile.concept_mastery = mastery_t

    # 融合 bkt_states
    bkt_a = dict(anon_profile.bkt_states or {})
    bkt_t = dict(target_profile.bkt_states or {})
    for k, v in bkt_a.items():
        if k not in bkt_t:
            bkt_t[k] = v
    target_profile.bkt_states = bkt_t

    # 融合 weak_points
    weak_a = list(anon_profile.weak_points or [])
    weak_t = list(target_profile.weak_points or [])
    for wp in weak_a:
        if wp not in weak_t:
            weak_t.append(wp)
    target_profile.weak_points = weak_t

    # 融合 history_logs
    if anon_profile.history_logs:
        target_profile.history_logs = (target_profile.history_logs or "") + "\n" + anon_profile.history_logs

    db.commit()

    # 3. 级联迁移所有相关的外键数据
    from app.database import (
        DBAlignmentLog, DBNote, DBReviewPlan, DBConversationHistory,
        DBKnowledgeDocument, DBQuizRecord, DBWebSearchHistory,
        DBCodeExecution, DBWrongQuestion, DBCheckinLog
    )

    # A. 迁移复习计划 (Review Plans)，防止重复主键冲突
    for plan in db.query(DBReviewPlan).filter_by(student_id=anon_id).all():
        exists = db.query(DBReviewPlan).filter_by(student_id=target_id, concept=plan.concept).first()
        if exists:
            exists.mastery = max(exists.mastery, plan.mastery)
            exists.interval_days = max(exists.interval_days, plan.interval_days)
            db.delete(plan)
        else:
            plan.student_id = target_id
    db.commit()

    # B. 迁移错题本 (Wrong Questions)
    for wrong in db.query(DBWrongQuestion).filter_by(student_id=anon_id).all():
        exists = db.query(DBWrongQuestion).filter_by(student_id=target_id, quiz_record_id=wrong.quiz_record_id).first()
        if exists:
            db.delete(wrong)
        else:
            wrong.student_id = target_id
    db.commit()

    # C. 批量迁移其他直接字段 (对话记录、笔记、坐标对齐、代码执行、Arxiv检索、打卡等)
    other_models = [
        DBAlignmentLog, DBNote, DBConversationHistory,
        DBKnowledgeDocument, DBQuizRecord, DBWebSearchHistory,
        DBCodeExecution, DBCheckinLog
    ]

    for model in other_models:
        try:
            db.query(model).filter(model.student_id == anon_id).update({"student_id": target_id}, synchronize_session=False)
            db.commit()
        except Exception as err:
            print(f"  [Migration] Failed to migrate {model.__name__}: {err}")
            db.rollback()

    # 4. 删除原匿名临时画像
    try:
        db.delete(anon_profile)
        db.commit()
    except Exception as err:
        print(f"  [Migration] Failed to delete anon profile: {err}")
        db.rollback()
