import sys
import os
from sqlalchemy.orm import Session
from datetime import datetime

# 允许 app 导入 root 目录下的 models.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import StudentProfile, DimensionState, CauseBreakdown, KnowledgeTrace, AlignmentReport
from app.database import DBStudentProfile, DBAlignmentLog

def to_dict_safe(obj) -> dict:
    """递归将 dataclass 转换为字典"""
    if hasattr(obj, "__dict__"):
        return {k: to_dict_safe(v) for k, v in obj.__dict__.items()}
    elif isinstance(obj, dict):
        return {k: to_dict_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_dict_safe(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(to_dict_safe(v) for v in obj)
    return obj

def load_student_profile(db: Session, student_id: str) -> StudentProfile:
    """从 SQLite 中加载学生画像，如果不存在则初始化并存入数据库"""
    db_profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == student_id).first()
    
    if not db_profile:
        # 创建默认画像并写入 SQLite 物理表
        profile = StudentProfile(student_id=student_id)
        save_student_profile(db, profile)
        return profile

    # 物理反序列化映射：从 SQLite JSON 数据构建内存 Dataclass 实例
    profile = StudentProfile(student_id=student_id)
    profile.target_course = db_profile.target_course
    profile.knowledge_base = db_profile.knowledge_base
    profile.cognitive_style = db_profile.cognitive_style
    profile.focus_level = db_profile.focus_level
    profile.cognitive_load = db_profile.cognitive_load
    
    profile.weak_points = list(db_profile.weak_points or [])
    profile.learning_goals = list(db_profile.learning_goals or [])
    profile.interaction_preferences = list(db_profile.interaction_preferences or [])
    profile.concept_mastery = dict(db_profile.concept_mastery or {})
    profile.misconception_patterns = dict(db_profile.misconception_patterns or {})
    
    if db_profile.history_logs:
        profile.history = db_profile.history_logs.split("\n")
    else:
        profile.history = []

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
    
    db_profile.weak_points = profile.weak_points
    db_profile.learning_goals = profile.learning_goals
    db_profile.interaction_preferences = profile.interaction_preferences
    db_profile.concept_mastery = profile.concept_mastery
    db_profile.misconception_patterns = profile.misconception_patterns
    
    db_profile.history_logs = "\n".join(profile.history)
    
    # 序列化复杂对象为 JSON 格式存入 SQLite
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
