import json
import os
import asyncio
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Float, Integer, Text, DateTime, JSON, Boolean, LargeBinary, event, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import sessionmaker, relationship, declarative_base

from contextvars import ContextVar
from contextlib import contextmanager
from sqlalchemy.pool import Pool
from datetime import timezone
from app.identity import new_public_id

# SQLAlchemy-compatible utcnow (avoids Python 3.12+ deprecation)
def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

# 锁定租户上下文 ContextVar，默认值为公共(public)命名空间
tenant_context: ContextVar[str] = ContextVar("tenant_context", default="public")

@contextmanager
def set_tenant(tenant_name: str):
    """上下文管理器，用于安全地切换和恢复当前协程的租户上下文"""
    token = tenant_context.set(tenant_name)
    try:
        yield
    finally:
        tenant_context.reset(token)

# 物理连接池归还时拦截拦截：彻底物理洗白连接状态
@event.listens_for(Pool, "checkin")
def on_connection_checkin(dbapi_connection, connection_record):
    module_name = dbapi_connection.__class__.__module__
    if "psycopg" in module_name or "pg" in module_name or "postgres" in module_name:
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("SET search_path TO public;")
            cursor.close()
        except Exception:
            pass

# 锁定本地 SQLite 单文件物理路径
import sys
TESTING = (
    os.getenv("TESTING", "false") == "true"
    or "pytest" in sys.modules
    or "unittest" in sys.modules
    or "test_edumatrix" in sys.modules
    or os.getenv("EDUMATRIX_ENV") == "test"
)

_configured_db_path = os.getenv("EDUMATRIX_DB_PATH", "").strip()

if _configured_db_path:
    DB_PATH = os.path.abspath(os.path.expanduser(_configured_db_path))
elif TESTING:
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edumatrix_test.db")
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edumatrix.db")

DATABASE_URL = f"sqlite:///{DB_PATH}"


# 初始化引擎并锁定 WAL 模式提高并发性能
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30.0}, # 允许 FastAPI 多线程访问并提供 30 秒超时锁队列
    echo=False
)

# 物理连接池触发 WAL（Write-Ahead Logging）模式，实现读写非阻塞，并启用外键约束
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

# 每次执行 SQL 前拦截：对于 PostgreSQL，若有租户上下文，则动态设置 search_path
@event.listens_for(engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    if conn.dialect.name == "postgresql":
        tenant = tenant_context.get()
        if tenant and tenant != "public":
            clean_tenant = "".join(c for c in tenant if c.isalnum() or c == "_")
            if clean_tenant:
                cursor.execute(f"SET search_path TO {clean_tenant};")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

async def run_db_op(func, *args, **kwargs):
    """
    Run a database operation in a separate thread using a thread-local Session.
    Avoids transaction pollution and concurrency issues in AsyncIO environment.
    """
    loop = asyncio.get_running_loop()
    
    def _run_with_session():
        db = SessionLocal()
        try:
            res = func(db, *args, **kwargs)
            return res
        finally:
            db.close()
            
    return await loop.run_in_executor(None, _run_with_session)

class DBStudentProfile(Base):
    """持久化物理表：存储学生 10 维画像、掌握度、认知负荷与学习偏好"""
    __tablename__ = "student_profiles"

    student_id = Column(String(64), primary_key=True, index=True)
    # A profile created before onboarding has no course, knowledge base, or
    # learning-style evidence.  Real values are projected only from explicit
    # registration/onboarding/learning input.
    target_course = Column(String(128), default="")
    knowledge_base = Column(String(64), default="")
    cognitive_style = Column(String(128), default="")
    motivation_type = Column(String(64), default="未诊断")
    frustration_index = Column(Float, default=0.0)
    focus_level = Column(Float, default=0.72)
    cognitive_load = Column(Float, default=0.45)
    
    # 采用 SQLite JSON 字段，完美存储非结构化掌握度与时序记录
    weak_points = Column(JSON, default=list)             # 弱点概念列表
    learning_goals = Column(JSON, default=list)          # 学习目标列表
    interaction_preferences = Column(JSON, default=list) # 表达偏好列表
    concept_mastery = Column(JSON, default=dict)         # 概念掌握度百分比
    misconception_patterns = Column(JSON, default=dict)  # 误概念强度记录
    
    # 动态掌握度与认知维度明细数据
    dimension_states = Column(JSON, default=dict)        # 10维状态 DimensionState
    learning_state_causes = Column(JSON, default=dict)   # 原因占比 Breakdown
    
    history_logs = Column(Text, default="")              # 提问历史（以换行符或JSON数组隔开）
    narrative_report = Column(Text, default="")          # 📬 缓存的 StoryLensEdu 叙事学情成长信笺
    dashboard_report = Column(Text, default="")          # 📊 缓存的仪表盘全局学情分析报告
    last_updated = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # 扩充物理字段 (Task 6.2)
    major = Column(Text, default="")
    favorites = Column(JSON, default=list)
    knowledge_traces = Column(JSON, default=dict)
    profile_evidence = Column(JSON, default=list)
    customized_fields = Column(JSON, default=list)  # 用户手动设定的不可篡改字段列表
    rl_q_table = Column(JSON, default=dict)
    mental_state_history = Column(JSON, default=list)
    concept_layers = Column(JSON, default=dict)
    bkt_states = Column(JSON, default=dict)
    dkt_bias = Column(JSON, default=list)
    cognitive_map = Column(JSON, default=dict)
    fsm_mode = Column(String(64), default="normal")
    fsm_accuracy_history = Column(JSON, default=dict)


    # 级联删除配置关系 (Task 6.2)
    alignment_logs = relationship("DBAlignmentLog", back_populates="student_profile", cascade="all, delete-orphan", passive_deletes=False)
    notes = relationship("DBNote", back_populates="student_profile", cascade="all, delete-orphan", passive_deletes=False)
    review_plans = relationship("DBReviewPlan", back_populates="student_profile", cascade="all, delete-orphan", passive_deletes=False)
    conversation_history = relationship("DBConversationHistory", back_populates="student_profile", cascade="all, delete-orphan", passive_deletes=False)
    knowledge_documents = relationship("DBKnowledgeDocument", back_populates="student_profile", cascade="all, delete-orphan", passive_deletes=False)
    quiz_records = relationship("DBQuizRecord", back_populates="student_profile", cascade="all, delete-orphan", passive_deletes=False)
    web_search_history = relationship("DBWebSearchHistory", back_populates="student_profile", cascade="all, delete-orphan", passive_deletes=False)
    code_executions = relationship("DBCodeExecution", back_populates="student_profile", cascade="all, delete-orphan", passive_deletes=False)
    wrong_questions = relationship("DBWrongQuestion", back_populates="student_profile", cascade="all, delete-orphan", passive_deletes=False)
    checkin_logs = relationship("DBCheckinLog", back_populates="student_profile", cascade="all, delete-orphan", passive_deletes=False)


class DBOnboardingSession(Base):
    """Resumable five-dimension initial profile conversation owned by one learner."""

    __tablename__ = "onboarding_sessions"

    id = Column(String(64), primary_key=True, default=lambda: new_public_id("onboard"))
    owner_public_id = Column(
        String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, unique=True, index=True,
    )
    student_id = Column(String(64), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="in_progress", index=True)
    current_dimension = Column(String(32), nullable=False, default="background")
    confirmed_fields = Column(JSON, nullable=False, default=dict)
    missing_fields = Column(JSON, nullable=False, default=list)
    checkpoint = Column(Integer, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=1)
    course_context = Column(JSON, nullable=False, default=dict)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    confirmed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('in_progress','confirmed')", name="ck_onboarding_session_status"),
        CheckConstraint("checkpoint >= 0 AND version >= 1", name="ck_onboarding_session_version"),
    )


class DBOnboardingTurn(Base):
    """A learner answer is committed before any profile projection is attempted."""

    __tablename__ = "onboarding_turns"

    id = Column(String(64), primary_key=True, default=lambda: new_public_id("onturn"))
    session_id = Column(
        String(64), ForeignKey("onboarding_sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    turn_id = Column(String(128), nullable=False)
    question_dimension = Column(String(32), nullable=False, index=True)
    user_answer = Column(Text, nullable=False)
    extracted_candidates = Column(JSON, nullable=False, default=dict)
    confirmed_fields = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="saved", index=True)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    confirmed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("session_id", "turn_id", name="uq_onboarding_turn_session_turn"),
        CheckConstraint(
            "status IN ('saved','awaiting_confirmation','conflict','extraction_failed','projecting','projection_failed','confirmed')",
            name="ck_onboarding_turn_status",
        ),
    )


class DBOnboardingPersonalEvidence(Base):
    """Optional learner-owned transcript or timetable extraction for onboarding."""

    __tablename__ = "onboarding_personal_evidence"

    id = Column(String(64), primary_key=True, default=lambda: new_public_id("onfile"))
    session_id = Column(
        String(64), ForeignKey("onboarding_sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    owner_public_id = Column(
        String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True,
    )
    evidence_type = Column(String(24), nullable=False, index=True)
    filename = Column(String(256), nullable=False)
    file_format = Column(String(16), nullable=False)
    file_size = Column(Integer, nullable=False)
    source_sha256 = Column(String(64), nullable=False, index=True)
    parser_version = Column(String(64), nullable=False, default="")
    extracted_candidates = Column(JSON, nullable=False, default=list)
    confirmed_fields = Column(JSON, nullable=False, default=list)
    status = Column(String(24), nullable=False, default="parsed", index=True)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    confirmed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "session_id", "evidence_type", "source_sha256",
            name="uq_onboarding_personal_evidence_source",
        ),
        CheckConstraint("evidence_type IN ('transcript','timetable')", name="ck_onboarding_evidence_type"),
        CheckConstraint(
            "status IN ('parsed','parse_failed','confirmed','discarded')",
            name="ck_onboarding_evidence_status",
        ),
        CheckConstraint("file_size > 0", name="ck_onboarding_evidence_file_size"),
    )


class DBUser(Base):
    """用户表：存储登录凭证"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_id = Column(String(64), unique=True, index=True, nullable=False, default=lambda: new_public_id("usr"))
    username = Column(String(64), unique=True, index=True, nullable=False) # 通常与 student_id 一致
    hashed_password = Column(String(128), nullable=False)
    role = Column(String(16), default="student")  # "student" 或 "teacher"
    display_name = Column(String(64), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

class DBAlignmentLog(Base):
    __tablename__ = "alignment_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), index=True)
    target_concept = Column(String(128))
    passed = Column(Boolean, default=False)
    distance = Column(Float)
    threshold = Column(Float)
    conflicts = Column(JSON, default=list)
    advice = Column(Text)
    timestamp = Column(DateTime, default=_utcnow)

    student_profile = relationship("DBStudentProfile", back_populates="alignment_logs")

class DBNote(Base):
    __tablename__ = "notes"

    id = Column(String(64), primary_key=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), index=True)
    source = Column(String(128), default="conversation")
    content = Column(Text)
    tags = Column(JSON, default=list)
    concepts = Column(JSON, default=list)
    source_metadata = Column(JSON, default=dict)
    lock_version = Column(Integer, nullable=False, default=1)
    current_version_number = Column(Integer, nullable=False, default=1)
    ai_suggestion = Column(Text, nullable=False, default="")
    ai_suggestion_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    student_profile = relationship("DBStudentProfile", back_populates="notes")

    __table_args__ = (
        CheckConstraint("lock_version >= 1", name="ck_note_lock_version"),
        CheckConstraint("current_version_number >= 1", name="ck_note_current_version_number"),
    )


class DBNoteVersion(Base):
    __tablename__ = "note_versions"

    id = Column(String(64), primary_key=True, default=lambda: new_public_id("notev"))
    note_id = Column(String(64), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(JSON, default=list)
    concepts = Column(JSON, default=list)
    source = Column(String(128), nullable=False, default="manual")
    source_metadata = Column(JSON, default=dict)
    change_type = Column(String(32), nullable=False, default="saved")
    restored_from_version = Column(Integer, nullable=True)
    event_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("note_id", "version_number", name="uq_note_version_number"),
        CheckConstraint("version_number >= 1", name="ck_note_version_number"),
    )

class DBReviewPlan(Base):
    """持久化物理表：SM-2 间隔重复复习计划

    任务 7.5 扩展：easiness_factor, interval_days(已存在), next_review_at(已存在), last_quality
    """
    __tablename__ = "review_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), index=True)
    concept = Column(String(128))
    interval_days = Column(Integer, default=1)
    next_review_at = Column(DateTime)
    mastery = Column(Float, default=0.0)
    review_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)

    # === 任务 7.5: SM-2 间隔重复参数 ===
    easiness_factor = Column(Float, default=2.5)  # 易度因子 E, 下限 1.3
    last_quality = Column(Integer, default=0)     # 上次质量评分 q={2,4,5}

    # === 任务 7.7: 同类题联动 ===
    similar_quiz_ids = Column(JSON, default=list)  # 关联的相似题 quiz_id 列表
    priority = Column(Float, default=1.0)          # 复习紧迫度 (越低越紧迫)

    student_profile = relationship("DBStudentProfile", back_populates="review_plans")


class DBFlashcard(Base):
    __tablename__ = "flashcards"

    id = Column(String(64), primary_key=True, default=lambda: new_public_id("card"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), nullable=False, index=True)
    review_plan_id = Column(Integer, ForeignKey("review_plans.id", ondelete="SET NULL"), nullable=True, index=True)
    concept = Column(String(128), nullable=False, index=True)
    source_quiz_id = Column(String(128), nullable=False, default="", index=True)
    identity_hash = Column(String(64), nullable=False, unique=True, index=True)
    current_version_id = Column(String(64), nullable=True, index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    status = Column(String(16), nullable=False, default="active", index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        CheckConstraint("lock_version >= 1", name="ck_flashcard_lock_version"),
        CheckConstraint("status IN ('active','archived')", name="ck_flashcard_status"),
    )


class DBFlashcardVersion(Base):
    __tablename__ = "flashcard_versions"

    id = Column(String(64), primary_key=True, default=lambda: new_public_id("cardv"))
    flashcard_id = Column(String(64), ForeignKey("flashcards.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    front = Column(Text, nullable=False)
    back = Column(Text, nullable=False)
    source_snapshot = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("flashcard_id", "version_number", name="uq_flashcard_version_number"),)


class DBConversationHistory(Base):
    __tablename__ = "conversation_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), index=True)
    query = Column(Text)
    response_summary = Column(Text)
    target = Column(String(128))
    resources_count = Column(Integer, default=0)
    alignment_passed = Column(Boolean, default=True)
    profile_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


    student_profile = relationship("DBStudentProfile", back_populates="conversation_history")

class DBKnowledgeDocument(Base):
    """持久化物理表：存储用户上传的知识库文档"""
    __tablename__ = "knowledge_documents"

    id = Column(String(64), primary_key=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), index=True)
    filename = Column(String(256))
    file_type = Column(String(16))  # md / txt / pdf / pptx / mp4
    file_size = Column(Integer, default=0)
    title = Column(String(256), default="")
    content = Column(Text, default="")
    tags = Column(JSON, default=list)
    chunk_count = Column(Integer, default=0)
    is_multimodal = Column(Boolean, default=False)
    multimodal_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)

    student_profile = relationship("DBStudentProfile", back_populates="knowledge_documents")


class DBCourse(Base):
    """Versioned public or organization-scoped course catalog entry."""

    __tablename__ = "courses"

    id = Column(String(128), primary_key=True)
    version = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    subject = Column(String(128), default="")
    description = Column(Text, default="")
    domain_pack = Column(String(128), default="")
    language = Column(String(32), default="zh-CN")
    content_origin = Column(String(512), default="")
    license_text = Column(Text, default="")
    visibility = Column(String(32), default="public", index=True)
    status = Column(String(32), default="draft", index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    manifest_version = Column(String(128), nullable=False)
    manifest_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)


class DBCourseMembership(Base):
    """课程成员关系：角色属于课程上下文，不依赖请求体字段。"""

    __tablename__ = "course_memberships"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("cm"))
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    user_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False, default="student")
    status = Column(String(16), nullable=False, default="active", index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("course_id", "user_public_id", name="uq_course_membership_user"),
        CheckConstraint("role IN ('admin','teacher','assistant','student','visitor')", name="ck_course_membership_role"),
        CheckConstraint("status IN ('invited','active','suspended','removed')", name="ck_course_membership_status"),
    )
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class DBTeachingClass(Base):
    """A managed teaching class bound to one canonical course."""

    __tablename__ = "teaching_classes"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("tclass"))
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    term = Column(String(64), nullable=False, default="")
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("course_id", "title", "term", name="uq_teaching_class_course_title_term"),
        CheckConstraint("status IN ('active','withdrawn','archived') AND lock_version >= 1", name="ck_teaching_class_state"),
    )


class DBTeachingGroup(Base):
    __tablename__ = "teaching_groups"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("tgroup"))
    class_id = Column(String(64), ForeignKey("teaching_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    status = Column(String(24), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("class_id", "name", name="uq_teaching_group_class_name"),
        CheckConstraint("status IN ('active','archived') AND lock_version >= 1", name="ck_teaching_group_state"),
    )


class DBTeachingClassMember(Base):
    __tablename__ = "teaching_class_members"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("tcm"))
    class_id = Column(String(64), ForeignKey("teaching_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    group_id = Column(String(64), ForeignKey("teaching_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    role = Column(String(16), nullable=False, default="student")
    status = Column(String(24), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    joined_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("class_id", "user_public_id", name="uq_teaching_class_member_user"),
        CheckConstraint("role IN ('teacher','assistant','student')", name="ck_teaching_class_member_role"),
        CheckConstraint("status IN ('active','suspended','removed') AND lock_version >= 1", name="ck_teaching_class_member_state"),
    )


class DBTeachingTask(Base):
    __tablename__ = "teaching_tasks"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ttask"))
    class_id = Column(String(64), ForeignKey("teaching_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    group_id = Column(String(64), ForeignKey("teaching_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    instructions = Column(Text, default="")
    due_at = Column(DateTime, nullable=True)
    status = Column(String(24), nullable=False, default="draft", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    published_at = Column(DateTime, nullable=True)
    withdrawn_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("class_id", "idempotency_key", name="uq_teaching_task_class_idempotency"),
        CheckConstraint("status IN ('draft','published','withdrawn','archived') AND lock_version >= 1", name="ck_teaching_task_state"),
    )


class DBCourseWithdrawal(Base):
    """Immutable course withdrawal decision and its frozen impact snapshot."""

    __tablename__ = "course_withdrawals"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("cw"))
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    previous_status = Column(String(32), nullable=False)
    reason = Column(Text, nullable=False)
    reason_sha256 = Column(String(64), nullable=False)
    impact_snapshot = Column(JSON, nullable=False, default=dict)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class DBCourseShareRelease(Base):
    """Immutable published course snapshot offered to one class or organization."""

    __tablename__ = "course_share_releases"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("cshare"))
    source_course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_course_version = Column(String(64), nullable=False)
    source_manifest_version = Column(String(128), nullable=False)
    target_type = Column(String(24), nullable=False, index=True)
    target_id = Column(String(64), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    snapshot_data = Column(JSON, nullable=False)
    license_snapshot = Column(JSON, nullable=False)
    snapshot_hash = Column(String(64), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="published", index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    withdrawn_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("source_course_id", "source_course_version", "target_type", "target_id", "snapshot_hash", name="uq_course_share_release_snapshot"),
        CheckConstraint("target_type IN ('class','organization')", name="ck_course_share_target_type"),
        CheckConstraint("status IN ('published','withdrawn')", name="ck_course_share_release_status"),
    )


class DBCourseDerivedCopy(Base):
    """Recipient-owned canonical course derived from an immutable share release."""

    __tablename__ = "course_derived_copies"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ccopy"))
    release_id = Column(String(64), ForeignKey("course_share_releases.id", ondelete="RESTRICT"), nullable=False, index=True)
    derived_course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    recipient_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    applied_release_id = Column(String(64), ForeignKey("course_share_releases.id", ondelete="RESTRICT"), nullable=False)
    baseline_snapshot = Column(JSON, nullable=False)
    baseline_hash = Column(String(64), nullable=False)
    upstream_status = Column(String(24), nullable=False, default="current", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        CheckConstraint("upstream_status IN ('current','update_available','withdrawn') AND lock_version >= 1", name="ck_course_derived_copy_state"),
    )


class DBCourseShareDecision(Base):
    """Immutable recipient decision for a discovered upstream release."""

    __tablename__ = "course_share_decisions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("cdecision"))
    derived_copy_id = Column(String(64), ForeignKey("course_derived_copies.id", ondelete="RESTRICT"), nullable=False, index=True)
    upstream_release_id = Column(String(64), ForeignKey("course_share_releases.id", ondelete="RESTRICT"), nullable=False, index=True)
    action = Column(String(24), nullable=False)
    conflict_snapshot = Column(JSON, nullable=False)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    reason = Column(Text, nullable=False)
    reason_sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("derived_copy_id", "upstream_release_id", name="uq_course_share_decision_release"),
        CheckConstraint("action IN ('accept','ignore')", name="ck_course_share_decision_action"),
    )


class DBMarketplaceListing(Base):
    """Governed public listing over one frozen course or learning-object version."""
    __tablename__ = "marketplace_listings"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("market"))
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    course_version = Column(String(64), nullable=False)
    item_type = Column(String(32), nullable=False, default="course", server_default="course", index=True)
    source_object_id = Column(String(128), nullable=True, index=True)
    source_version_id = Column(String(128), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    summary = Column(Text, nullable=False)
    category = Column(String(128), nullable=False, index=True)
    tags = Column(JSON, nullable=False, default=list)
    snapshot_data = Column(JSON, nullable=False)
    license_snapshot = Column(JSON, nullable=False)
    snapshot_hash = Column(String(64), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="pending", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    published_at = Column(DateTime, nullable=True)
    withdrawn_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("course_id", "course_version", "snapshot_hash", name="uq_marketplace_listing_snapshot"),
        CheckConstraint("status IN ('pending','changes_requested','approved','published','withdrawn') AND lock_version >= 1", name="ck_marketplace_listing_state"),
        CheckConstraint("item_type IN ('course','resource','resource_bundle','learning_path')", name="ck_marketplace_listing_item_type"),
    )


class DBMarketplaceDecision(Base):
    """Immutable review or moderation decision for a marketplace listing."""
    __tablename__ = "marketplace_decisions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketdec"))
    listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    action = Column(String(32), nullable=False, index=True)
    from_status = Column(String(24), nullable=False)
    to_status = Column(String(24), nullable=False)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    actor_role = Column(String(32), nullable=False)
    reason = Column(Text, nullable=False)
    reason_sha256 = Column(String(64), nullable=False)
    evidence_snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=_utcnow)


class DBMarketplaceReport(Base):
    __tablename__ = "marketplace_reports"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketrep"))
    listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    reporter_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    category = Column(String(64), nullable=False)
    description = Column(Text, nullable=False)
    evidence_snapshot = Column(JSON, nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="open", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    resolved_at = Column(DateTime, nullable=True)
    __table_args__ = (CheckConstraint("status IN ('open','dismissed','resolved') AND lock_version >= 1", name="ck_marketplace_report_state"),)


class DBMarketplaceAcquisition(Base):
    """Immutable identity link from a public listing to a recipient course copy."""
    __tablename__ = "marketplace_acquisitions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketget"))
    listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    recipient_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    derived_course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, unique=True)
    listing_snapshot_hash = Column(String(64), nullable=False)
    source_status = Column(String(24), nullable=False, default="available")
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("listing_id", "recipient_public_id", name="uq_marketplace_acquisition_recipient"),
        CheckConstraint("source_status IN ('available','withdrawn')", name="ck_marketplace_acquisition_status"),
    )


class DBMarketplacePersonalCopy(Base):
    """Owner-scoped independent copy of a frozen marketplace learning object."""
    __tablename__ = "marketplace_personal_copies"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketcopy"))
    listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    recipient_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    item_type = Column(String(32), nullable=False, index=True)
    copy_object_id = Column(String(128), nullable=False, index=True)
    copy_version_id = Column(String(128), nullable=False, index=True)
    open_route = Column(Text, nullable=False)
    listing_snapshot_hash = Column(String(64), nullable=False, index=True)
    provenance_snapshot = Column(JSON, nullable=False, default=dict)
    source_status = Column(String(24), nullable=False, default="available", index=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("listing_id", "recipient_public_id", name="uq_marketplace_personal_copy_recipient"),
        CheckConstraint("item_type IN ('resource','resource_bundle','learning_path')", name="ck_marketplace_personal_copy_item_type"),
        CheckConstraint("source_status IN ('available','withdrawn')", name="ck_marketplace_personal_copy_status"),
    )


class DBMarketplaceComment(Base):
    """Comment state permanently bound to one frozen marketplace listing version."""
    __tablename__ = "marketplace_comments"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketcom"))
    listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_snapshot_hash = Column(String(64), nullable=False, index=True)
    course_version = Column(String(64), nullable=False)
    author_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    body = Column(Text, nullable=False)
    body_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    edit_deadline = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at = Column(DateTime, nullable=True)
    __table_args__ = (CheckConstraint("status IN ('active','deleted','hidden') AND lock_version >= 1", name="ck_marketplace_comment_state"),)


class DBMarketplaceCommentEvent(Base):
    """Immutable content and moderation transition for a marketplace comment."""
    __tablename__ = "marketplace_comment_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketcomevt"))
    comment_id = Column(String(64), ForeignKey("marketplace_comments.id", ondelete="RESTRICT"), nullable=False, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    action = Column(String(24), nullable=False, index=True)
    from_status = Column(String(24), nullable=False)
    to_status = Column(String(24), nullable=False)
    body_hash = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False, default="")
    snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=_utcnow)


class DBMarketplaceCommentReport(Base):
    """Version-bound report over one marketplace comment."""
    __tablename__ = "marketplace_comment_reports"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketcomrep"))
    comment_id = Column(String(64), ForeignKey("marketplace_comments.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    reporter_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    category = Column(String(64), nullable=False)
    description = Column(Text, nullable=False)
    evidence_snapshot = Column(JSON, nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="open", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    resolved_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("comment_id", "reporter_public_id", name="uq_marketplace_comment_reporter"),
        CheckConstraint("status IN ('open','dismissed','resolved') AND lock_version >= 1", name="ck_marketplace_comment_report_state"),
    )


class DBMarketplaceFavorite(Base):
    """Owner state for bookmarking one immutable marketplace listing version."""
    __tablename__ = "marketplace_favorites"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketfav"))
    listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_snapshot_hash = Column(String(64), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("listing_id", "owner_public_id", name="uq_marketplace_favorite_owner"),
        CheckConstraint("status IN ('active','removed') AND lock_version >= 1", name="ck_marketplace_favorite_state"),
    )


class DBMarketplaceReview(Base):
    """Current verified-use rating for one immutable marketplace listing version."""
    __tablename__ = "marketplace_reviews"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketrev"))
    listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_snapshot_hash = Column(String(64), nullable=False, index=True)
    course_version = Column(String(64), nullable=False)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    acquisition_id = Column(String(64), ForeignKey("marketplace_acquisitions.id", ondelete="RESTRICT"), nullable=False, index=True)
    derived_course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    body = Column(Text, nullable=False, default="")
    body_hash = Column(String(64), nullable=False)
    evidence_snapshot = Column(JSON, nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("listing_id", "owner_public_id", name="uq_marketplace_review_owner"),
        CheckConstraint("rating BETWEEN 1 AND 5 AND status = 'active' AND lock_version >= 1", name="ck_marketplace_review_state"),
    )


class DBMarketplaceReviewEvent(Base):
    """Immutable history for every verified marketplace rating revision."""
    __tablename__ = "marketplace_review_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketrevevt"))
    review_id = Column(String(64), ForeignKey("marketplace_reviews.id", ondelete="RESTRICT"), nullable=False, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    action = Column(String(16), nullable=False, index=True)
    from_rating = Column(Integer, nullable=True)
    to_rating = Column(Integer, nullable=False)
    body_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (CheckConstraint("action IN ('created','updated') AND to_rating BETWEEN 1 AND 5", name="ck_marketplace_review_event"),)


class DBMarketplaceImpactEvent(Base):
    """Immutable marketplace version or withdrawal impact over acquired copies."""
    __tablename__ = "marketplace_impact_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketimpact"))
    source_listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    target_listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=True, index=True)
    impact_type = Column(String(32), nullable=False, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    source_snapshot_hash = Column(String(64), nullable=False)
    target_snapshot_hash = Column(String(64), nullable=True)
    evidence_snapshot = Column(JSON, nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False)
    reason_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("source_listing_id", "target_listing_id", "impact_type", "target_snapshot_hash", name="uq_marketplace_impact_transition"),
        CheckConstraint("impact_type IN ('withdrawn','new_version','severe_fix','license_changed')", name="ck_marketplace_impact_type"),
    )


class DBMarketplaceImpactNotification(Base):
    """Durable local inbox item for one acquisition affected by an impact event."""
    __tablename__ = "marketplace_impact_notifications"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketnotice"))
    impact_event_id = Column(String(64), ForeignKey("marketplace_impact_events.id", ondelete="RESTRICT"), nullable=False, index=True)
    acquisition_id = Column(String(64), ForeignKey("marketplace_acquisitions.id", ondelete="RESTRICT"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    source_listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    target_listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=True, index=True)
    notification_type = Column(String(32), nullable=False, index=True)
    idempotency_key = Column(String(160), nullable=False)
    title = Column(String(256), nullable=False)
    body = Column(Text, nullable=False)
    source_route = Column(String(256), nullable=False)
    status = Column(String(16), nullable=False, default="unread", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    action = Column(String(32), nullable=True)
    read_at = Column(DateTime, nullable=True)
    actioned_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("owner_public_id", "idempotency_key", name="uq_marketplace_impact_notice_owner_key"),
        CheckConstraint("status IN ('unread','read','actioned') AND lock_version >= 1", name="ck_marketplace_impact_notice_state"),
        CheckConstraint("action IS NULL OR action IN ('view_source','keep_copy','review_update')", name="ck_marketplace_impact_notice_action"),
    )


class DBMarketplaceFork(Base):
    """Recipient-owned version line derived from one marketplace acquisition."""
    __tablename__ = "marketplace_forks"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketfork"))
    acquisition_id = Column(String(64), ForeignKey("marketplace_acquisitions.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    source_listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    applied_upstream_listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    derived_course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    baseline_snapshot = Column(JSON, nullable=False)
    baseline_license_snapshot = Column(JSON, nullable=False)
    baseline_hash = Column(String(64), nullable=False)
    current_version_id = Column(String(64), nullable=True, index=True)
    upstream_status = Column(String(24), nullable=False, default="current", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        CheckConstraint("upstream_status IN ('current','update_available','withdrawn') AND lock_version >= 1", name="ck_marketplace_fork_state"),
    )


class DBMarketplaceForkVersion(Base):
    """Immutable local snapshot on an independent marketplace fork version line."""
    __tablename__ = "marketplace_fork_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketforkver"))
    fork_id = Column(String(64), ForeignKey("marketplace_forks.id", ondelete="RESTRICT"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    parent_version_id = Column(String(64), ForeignKey("marketplace_fork_versions.id", ondelete="RESTRICT"), nullable=True)
    baseline_listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False)
    baseline_snapshot_hash = Column(String(64), nullable=False)
    baseline_snapshot = Column(JSON, nullable=False)
    inherited_license_snapshot = Column(JSON, nullable=False)
    local_snapshot = Column(JSON, nullable=False)
    local_snapshot_hash = Column(String(64), nullable=False, index=True)
    modification_summary = Column(Text, nullable=False)
    modification_summary_hash = Column(String(64), nullable=False)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("fork_id", "version_number", name="uq_marketplace_fork_version_number"),
        UniqueConstraint("fork_id", "baseline_listing_id", "local_snapshot_hash", name="uq_marketplace_fork_baseline_local_snapshot"),
        CheckConstraint("version_number >= 1", name="ck_marketplace_fork_version_number"),
    )


class DBMarketplaceForkDecision(Base):
    """Immutable explicit decision over a three-way marketplace fork update."""
    __tablename__ = "marketplace_fork_decisions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketforkdec"))
    fork_id = Column(String(64), ForeignKey("marketplace_forks.id", ondelete="RESTRICT"), nullable=False, index=True)
    upstream_listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    action = Column(String(32), nullable=False)
    conflict_snapshot = Column(JSON, nullable=False)
    resulting_version_id = Column(String(64), ForeignKey("marketplace_fork_versions.id", ondelete="RESTRICT"), nullable=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    reason = Column(Text, nullable=False)
    reason_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("fork_id", "upstream_listing_id", name="uq_marketplace_fork_decision_upstream"),
        CheckConstraint("action IN ('accept_non_conflicting','keep_local','ignore')", name="ck_marketplace_fork_decision_action"),
    )


class DBMarketplaceRecommendationRun(Base):
    """Immutable, owner-scoped execution of the deterministic marketplace ranker."""
    __tablename__ = "marketplace_recommendation_runs"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketrec"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    algorithm_version = Column(String(64), nullable=False)
    profile_snapshot_id = Column(String(64), ForeignKey("profile_snapshots.id", ondelete="RESTRICT"), nullable=True, index=True)
    profile_snapshot = Column(JSON, nullable=False)
    target_snapshot = Column(JSON, nullable=False)
    weights_snapshot = Column(JSON, nullable=False)
    evidence_snapshot = Column(JSON, nullable=False)
    input_hash = Column(String(64), nullable=False, index=True)
    result_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("owner_public_id", "algorithm_version", "input_hash", name="uq_marketplace_recommendation_run_input"),
        CheckConstraint("result_count >= 0", name="ck_marketplace_recommendation_run_count"),
    )


class DBMarketplaceRecommendationResult(Base):
    """Immutable listing score with feature-level evidence and explanations."""
    __tablename__ = "marketplace_recommendation_results"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("marketrecitem"))
    run_id = Column(String(64), ForeignKey("marketplace_recommendation_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_snapshot_hash = Column(String(64), nullable=False)
    rank = Column(Integer, nullable=False)
    total_score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    suitability = Column(String(24), nullable=False, index=True)
    feature_contributions = Column(JSON, nullable=False)
    recommendation_reasons = Column(JSON, nullable=False)
    unsuitable_reasons = Column(JSON, nullable=False)
    evidence_state = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("run_id", "listing_id", name="uq_marketplace_recommendation_run_listing"),
        UniqueConstraint("run_id", "rank", name="uq_marketplace_recommendation_run_rank"),
        CheckConstraint("rank >= 1 AND total_score >= 0 AND total_score <= 1 AND confidence >= 0 AND confidence <= 1", name="ck_marketplace_recommendation_result_score"),
        CheckConstraint("suitability IN ('recommended','consider','limited','not_applicable')", name="ck_marketplace_recommendation_result_state"),
    )


class DBOrganizationResourceListing(Base):
    """Organization-private frozen learning resource listing."""
    __tablename__ = "organization_resource_listings"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("orgres"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    course_version = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    summary = Column(Text, nullable=False)
    category = Column(String(128), nullable=False, index=True)
    tags = Column(JSON, nullable=False, default=list)
    snapshot_data = Column(JSON, nullable=False)
    license_snapshot = Column(JSON, nullable=False)
    snapshot_hash = Column(String(64), nullable=False, index=True)
    policy_snapshot = Column(JSON, nullable=False)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(24), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    withdrawn_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("organization_id", "course_id", "course_version", "snapshot_hash", name="uq_org_resource_snapshot"),
        CheckConstraint("status IN ('active','withdrawn') AND lock_version >= 1", name="ck_org_resource_state"),
    )


class DBOrganizationResourceAcquisition(Base):
    """Immutable organization-member acquisition with preserved source status."""
    __tablename__ = "organization_resource_acquisitions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("orgget"))
    listing_id = Column(String(64), ForeignKey("organization_resource_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    recipient_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    derived_course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, unique=True)
    listing_snapshot_hash = Column(String(64), nullable=False)
    source_status = Column(String(24), nullable=False, default="available")
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("listing_id", "recipient_public_id", name="uq_org_resource_acquisition_recipient"),
        CheckConstraint("source_status IN ('available','withdrawn')", name="ck_org_resource_acquisition_status"),
    )


class DBSpatialWorkspace(Base):
    """Owner-scoped spatial workspace with an optimistic current-version pointer."""
    __tablename__ = "spatial_workspaces"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("space"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    current_version_id = Column(String(64), nullable=True, index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    status = Column(String(24), nullable=False, default="active", index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        CheckConstraint("lock_version >= 1 AND status IN ('active','archived')", name="ck_spatial_workspace_state"),
    )


class DBSpatialLayoutVersion(Base):
    """Immutable layout snapshot; undo creates another version from a prior snapshot."""
    __tablename__ = "spatial_layout_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("layout"))
    workspace_id = Column(String(64), ForeignKey("spatial_workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    parent_version_id = Column(String(64), ForeignKey("spatial_layout_versions.id", ondelete="RESTRICT"), nullable=True)
    restored_from_version_id = Column(String(64), ForeignKey("spatial_layout_versions.id", ondelete="RESTRICT"), nullable=True)
    action_type = Column(String(32), nullable=False)
    action_summary = Column(String(512), nullable=False)
    layout_data = Column(JSON, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("workspace_id", "version_number", name="uq_spatial_layout_version"),
        CheckConstraint("version_number >= 1", name="ck_spatial_layout_version_number"),
    )


class DBPluginRegistration(Base):
    """Persistent verified data-plugin registration; never stores executable code."""
    __tablename__ = "plugin_registrations"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("plugin"))
    plugin_id = Column(String(64), nullable=False, unique=True, index=True)
    plugin_version = Column(String(32), nullable=False)
    domain_key = Column(String(128), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    status = Column(String(24), nullable=False, default="available", index=True)
    manifest_snapshot = Column(JSON, nullable=False)
    verification_snapshot = Column(JSON, nullable=False)
    package_hash = Column(String(64), nullable=False, index=True)
    license = Column(String(128), nullable=False)
    attribution = Column(Text, nullable=False)
    source_url = Column(Text, nullable=False)
    source_version = Column(String(128), nullable=False)
    allowed_actions = Column(JSON, nullable=False)
    domain_pack_id = Column(String(64), ForeignKey("domain_packs.id", ondelete="SET NULL"), nullable=True, index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    installed_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (CheckConstraint("status IN ('available','installed','disabled') AND lock_version >= 1", name="ck_plugin_registration_state"),)


class DBPluginLifecycleEvent(Base):
    """Append-only plugin validation, installation and removal responsibility record."""
    __tablename__ = "plugin_lifecycle_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("pluginevt"))
    registration_id = Column(String(64), ForeignKey("plugin_registrations.id", ondelete="RESTRICT"), nullable=True, index=True)
    plugin_id = Column(String(64), nullable=False, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    action = Column(String(32), nullable=False)
    outcome = Column(String(24), nullable=False)
    reason = Column(Text, nullable=False)
    evidence_snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class DBTeachingAnalyticsReport(Base):
    """Immutable, explainable analytics snapshot for one academic class and period."""

    __tablename__ = "teaching_analytics_reports"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("tareport"))
    class_id = Column(String(64), ForeignKey("teaching_classes.id", ondelete="RESTRICT"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    period_start = Column(DateTime, nullable=False, index=True)
    period_end = Column(DateTime, nullable=False, index=True)
    metric_version = Column(String(64), nullable=False)
    report_version = Column(Integer, nullable=False, default=1)
    status = Column(String(24), nullable=False, default="frozen", index=True)
    report_data = Column(JSON, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("class_id", "period_start", "period_end", "metric_version", name="uq_teaching_analytics_period_version"),
        CheckConstraint("period_end > period_start", name="ck_teaching_analytics_period"),
        CheckConstraint("report_version >= 1 AND status IN ('frozen','withdrawn')", name="ck_teaching_analytics_state"),
    )


class DBContentReviewCase(Base):
    __tablename__ = "content_review_cases"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("review"))
    artifact_id = Column(String(64), ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, index=True)
    submitted_version_id = Column(String(64), ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    submitted_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    evidence_snapshot = Column(JSON, nullable=False, default=dict)
    submission_note = Column(Text, default="")
    lock_version = Column(Integer, nullable=False, default=1)
    submitted_at = Column(DateTime, default=_utcnow)
    resolved_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("artifact_id", "submitted_version_id", name="uq_content_review_artifact_version"),
        CheckConstraint("status IN ('pending','changes_requested','approved','published','withdrawn') AND lock_version >= 1", name="ck_content_review_state"),
    )


class DBContentReviewDecision(Base):
    """Immutable responsibility record for review and publication transitions."""
    __tablename__ = "content_review_decisions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("reviewdec"))
    review_case_id = Column(String(64), ForeignKey("content_review_cases.id", ondelete="RESTRICT"), nullable=False, index=True)
    action = Column(String(32), nullable=False, index=True)
    from_status = Column(String(32), nullable=False)
    to_status = Column(String(32), nullable=False)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    actor_role = Column(String(32), nullable=False)
    reason = Column(Text, nullable=False)
    reason_sha256 = Column(String(64), nullable=False)
    evidence_snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (CheckConstraint("action IN ('submit','request_changes','approve','publish','withdraw')", name="ck_content_review_action"),)


class DBCourseDocument(Base):
    """A source document belonging to a versioned course, not to a student."""

    __tablename__ = "course_documents"

    id = Column(String(64), primary_key=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    chapter_order = Column(Integer, nullable=False)
    filename = Column(String(256), nullable=False)
    file_type = Column(String(16), default="md")
    file_size = Column(Integer, default=0)
    title = Column(String(256), default="")
    content = Column(Text, default="")
    tags = Column(JSON, default=list)
    chunk_count = Column(Integer, default=0)
    content_hash = Column(String(64), nullable=False, index=True)
    source_path = Column(String(512), default="")
    license_text = Column(Text, default="")
    status = Column(String(32), default="published", index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class DBSourceDocument(Base):
    """Canonical source identity independent from parser output and legacy UI tables."""

    __tablename__ = "source_documents"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("src"))
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    legacy_document_id = Column(String(64), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    filename = Column(String(256), nullable=False)
    file_format = Column(String(32), nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    source_sha256 = Column(String(64), nullable=False, default="", index=True)
    processed_sha256 = Column(String(64), nullable=False, default="", index=True)
    file_size = Column(Integer, default=0)
    source_url = Column(String(1024), default="")
    source_path = Column(String(512), default="")
    license_text = Column(Text, default="")
    uploader_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    parser_version = Column(String(64), nullable=False, default="edumatrix-parser-v1")
    parser_metadata = Column(JSON, default=dict)
    parse_warnings = Column(JSON, default=list)
    processing_error_code = Column(String(64), default="")
    processing_status = Column(String(32), nullable=False, default="ready", index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("course_id", "legacy_document_id", name="uq_source_document_legacy"),
    )


class DBChapter(Base):
    __tablename__ = "chapters"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ch"))
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    source_document_id = Column(String(64), ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = Column(String(64), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True)
    stable_key = Column(String(256), nullable=False)
    title = Column(String(256), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    heading_level = Column(Integer, nullable=False, default=1)
    char_start = Column(Integer, nullable=False, default=0)
    char_end = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("course_id", "stable_key", name="uq_chapter_stable_key"),)


class DBKnowledgePoint(Base):
    __tablename__ = "knowledge_points"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("kp"))
    domain_pack = Column(String(128), nullable=False, index=True)
    code = Column(String(64), nullable=False)
    version = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    level = Column(String(32), nullable=False, default="core")
    prerequisites = Column(JSON, default=list)
    status = Column(String(32), nullable=False, default="active", index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (UniqueConstraint("domain_pack", "code", "version", name="uq_knowledge_point_version"),)


class DBChapterKnowledgePoint(Base):
    __tablename__ = "chapter_knowledge_points"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ckp"))
    chapter_id = Column(String(64), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_point_id = Column(String(64), ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type = Column(String(32), nullable=False, default="teaches")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("chapter_id", "knowledge_point_id", "relation_type", name="uq_chapter_kp_relation"),)


class DBSourceRef(Base):
    """Versioned locator supporting text, page and image-region citations."""

    __tablename__ = "source_refs"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ref"))
    source_document_id = Column(String(64), ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(String(64), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True)
    parser_version = Column(String(64), nullable=False)
    page_number = Column(Integer, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    image_region = Column(JSON, nullable=True)
    location_kind = Column(String(32), nullable=False, default="section")
    location_index = Column(Integer, nullable=True)
    location_label = Column(String(256), default="")
    location_metadata = Column(JSON, default=dict)
    content_hash = Column(String(64), nullable=False)
    quote = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("source_document_id", "chapter_id", "parser_version", name="uq_source_ref_chapter_version"),)


class DBWebSourceCandidate(Base):
    """Owner-scoped web material kept outside the canonical course source graph."""

    __tablename__ = "web_source_candidates"

    id = Column(String(64), primary_key=True, default=lambda: new_public_id("webcand"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    query = Column(String(500), nullable=False, default="")
    title = Column(String(512), nullable=False)
    url = Column(String(2048), nullable=False)
    url_sha256 = Column(String(64), nullable=False)
    source_domain = Column(String(256), nullable=False)
    author_or_organization = Column(String(256), nullable=False, default="")
    file_format = Column(String(32), nullable=False, default="html")
    snippet = Column(Text, nullable=False, default="")
    license_status = Column(String(32), nullable=False, default="unknown")
    license_text = Column(Text, nullable=False, default="")
    usage_hint = Column(Text, nullable=False, default="")
    parsing_impact = Column(JSON, nullable=False, default=dict)
    trust_level = Column(String(32), nullable=False, default="unverified")
    review_status = Column(String(32), nullable=False, default="pending_review", index=True)
    imported_version = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("owner_public_id", "url_sha256", name="uq_web_candidate_owner_url"),
        CheckConstraint(
            "license_status IN ('unknown','personal_use_allowed','open_permissive','restricted')",
            name="ck_web_candidate_license",
        ),
        CheckConstraint(
            "trust_level IN ('unverified','source_declared','verified')",
            name="ck_web_candidate_trust",
        ),
        CheckConstraint(
            "review_status IN ('pending_review','license_required','imported','rejected','withdrawn')",
            name="ck_web_candidate_review",
        ),
    )


class DBDocumentReadingPosition(Base):
    __tablename__ = "document_reading_positions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("drp"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    source_document_id = Column(String(64), ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version = Column(String(64), nullable=False)
    page_number = Column(Integer, nullable=True)
    section_id = Column(String(64), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True)
    char_offset = Column(Integer, nullable=False, default=0)
    scroll_ratio = Column(Float, nullable=False, default=0.0)
    zoom = Column(Float, nullable=False, default=1.0)
    lock_version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("owner_public_id", "source_document_id", name="uq_document_reading_position_owner_source"),
        CheckConstraint("page_number IS NULL OR page_number >= 1", name="ck_document_reading_page"),
        CheckConstraint("char_offset >= 0", name="ck_document_reading_char_offset"),
        CheckConstraint("scroll_ratio >= 0.0 AND scroll_ratio <= 1.0", name="ck_document_reading_scroll_ratio"),
        CheckConstraint("zoom >= 0.5 AND zoom <= 2.0", name="ck_document_reading_zoom"),
        CheckConstraint("lock_version >= 1", name="ck_document_reading_lock_version"),
    )


class DBDocumentSelection(Base):
    __tablename__ = "document_selections"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("sel"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    source_document_id = Column(String(64), ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    source_ref_id = Column(String(64), ForeignKey("source_refs.id", ondelete="SET NULL"), nullable=True, index=True)
    document_version = Column(String(64), nullable=False)
    selection_type = Column(String(16), nullable=False)
    section_id = Column(String(64), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True)
    page_number = Column(Integer, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    quote = Column(Text, default="")
    page_width = Column(Integer, nullable=True)
    page_height = Column(Integer, nullable=True)
    normalized_rect = Column(JSON, nullable=True)
    crop_ref = Column(String(512), default="")
    ocr_status = Column(String(32), nullable=False, default="not_required")
    ocr_text = Column(Text, default="")
    ocr_error_code = Column(String(64), default="")
    question_draft = Column(Text, default="")
    answer_status = Column(String(32), nullable=False, default="idle")
    answer_text = Column(Text, default="")
    answer_source_ref_id = Column(String(64), ForeignKey("source_refs.id", ondelete="SET NULL"), nullable=True)
    answer_idempotency_key = Column(String(128), default="")
    note_id = Column(String(64), ForeignKey("notes.id", ondelete="SET NULL"), nullable=True)
    generation_task_id = Column(String(64), ForeignKey("generation_tasks.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(16), nullable=False, default="active", index=True)
    idempotency_key = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("owner_public_id", "idempotency_key", name="uq_document_selection_owner_idempotency"),
        CheckConstraint("selection_type IN ('text','image')", name="ck_document_selection_type"),
        CheckConstraint("status IN ('active','stale')", name="ck_document_selection_status"),
        CheckConstraint("page_number IS NULL OR page_number >= 1", name="ck_document_selection_page"),
        CheckConstraint("char_start IS NULL OR char_start >= 0", name="ck_document_selection_char_start"),
        CheckConstraint("char_end IS NULL OR char_end > char_start", name="ck_document_selection_char_end"),
        CheckConstraint("page_width IS NULL OR page_width > 0", name="ck_document_selection_page_width"),
        CheckConstraint("page_height IS NULL OR page_height > 0", name="ck_document_selection_page_height"),
        CheckConstraint("ocr_status IN ('not_required','processing','ready','failed')", name="ck_document_selection_ocr_status"),
        CheckConstraint("answer_status IN ('idle','ready','failed')", name="ck_document_selection_answer_status"),
    )


class DBChatConversation(Base):
    """Owner-scoped conversation independent from course knowledge authority."""

    __tablename__ = "chat_conversations"

    id = Column(String(64), primary_key=True, default=lambda: new_public_id("chat"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(256), nullable=False, default="新对话")
    status = Column(String(16), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    archived_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active','archived')", name="ck_chat_conversation_status"),
        CheckConstraint("lock_version >= 1", name="ck_chat_conversation_lock_version"),
    )


class DBChatAttachment(Base):
    """A parsed chat attachment that never becomes canonical course content implicitly."""

    __tablename__ = "chat_attachments"

    id = Column(String(64), primary_key=True, default=lambda: new_public_id("chatatt"))
    conversation_id = Column(String(64), ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(256), nullable=False)
    file_format = Column(String(16), nullable=False)
    mime_type = Column(String(128), nullable=False, default="application/octet-stream")
    file_size = Column(Integer, nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    raw_bytes = Column(LargeBinary, nullable=False)
    parsed_text = Column(Text, nullable=False, default="")
    parser_version = Column(String(64), nullable=False, default="")
    locations = Column(JSON, nullable=False, default=list)
    parse_metadata = Column(JSON, nullable=False, default=dict)
    warnings = Column(JSON, nullable=False, default=list)
    status = Column(String(24), nullable=False, default="queued", index=True)
    stage = Column(String(24), nullable=False, default="queued")
    progress = Column(Float, nullable=False, default=0.0)
    error_code = Column(String(64), nullable=False, default="")
    error_message = Column(Text, nullable=False, default="")
    retryable = Column(Boolean, nullable=False, default=False)
    partial_confirmed = Column(Boolean, nullable=False, default=False)
    parse_version = Column(Integer, nullable=False, default=0)
    lock_version = Column(Integer, nullable=False, default=1)
    idempotency_key = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    removed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("owner_public_id", "idempotency_key", name="uq_chat_attachment_owner_idempotency"),
        CheckConstraint("file_size >= 0", name="ck_chat_attachment_size"),
        CheckConstraint(
            "status IN ('queued','parsing','ready','partial_failed','failed','removed')",
            name="ck_chat_attachment_status",
        ),
        CheckConstraint(
            "stage IN ('queued','validating','parsing','ocr','ready','failed','removed')",
            name="ck_chat_attachment_stage",
        ),
        CheckConstraint("progress >= 0.0 AND progress <= 1.0", name="ck_chat_attachment_progress"),
        CheckConstraint("parse_version >= 0 AND lock_version >= 1", name="ck_chat_attachment_versions"),
    )


class DBChatMessage(Base):
    """Canonical recoverable user or assistant message for the focused chat workspace."""

    __tablename__ = "chat_messages"

    id = Column(String(64), primary_key=True, default=lambda: new_public_id("chatmsg"))
    conversation_id = Column(String(64), ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    reply_to_message_id = Column(String(64), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    sequence = Column(Integer, nullable=False)
    role = Column(String(16), nullable=False)
    status = Column(String(24), nullable=False, default="completed", index=True)
    content = Column(Text, nullable=False, default="")
    content_sha256 = Column(String(64), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    context_refs = Column(JSON, nullable=False, default=list)
    attachment_ids = Column(JSON, nullable=False, default=list)
    source_refs = Column(JSON, nullable=False, default=list)
    resource_links = Column(JSON, nullable=False, default=list)
    stream_checkpoint = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(64), nullable=False, default="")
    error_message = Column(Text, nullable=False, default="")
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_chat_message_sequence"),
        UniqueConstraint("owner_public_id", "idempotency_key", name="uq_chat_message_owner_idempotency"),
        CheckConstraint("sequence >= 1", name="ck_chat_message_sequence"),
        CheckConstraint("role IN ('user','assistant')", name="ck_chat_message_role"),
        CheckConstraint(
            "status IN ('queued','streaming','completed','stopped','failed')",
            name="ck_chat_message_status",
        ),
        CheckConstraint("lock_version >= 1", name="ck_chat_message_lock_version"),
    )


class DBGenerationTask(Base):
    __tablename__ = "generation_tasks"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("task"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    progress = Column(Float, nullable=False, default=0.0)
    capability = Column(String(128), nullable=False)
    model = Column(String(128), default="")
    idempotency_key = Column(String(128), nullable=False)
    estimated_cost = Column(Float, default=0.0)
    actual_cost = Column(Float, default=0.0)
    failure_code = Column(String(64), default="")
    failure_reason = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("owner_public_id", "idempotency_key", name="uq_generation_task_idempotency"),
        CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_generation_task_status"),
        CheckConstraint("progress >= 0.0 AND progress <= 1.0", name="ck_generation_task_progress"),
    )


class DBArtifact(Base):
    __tablename__ = "artifacts"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("art"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    artifact_type = Column(String(64), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="draft", index=True)
    current_version_id = Column(String(64), nullable=True, index=True)
    creating_task_id = Column(String(64), ForeignKey("generation_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    lock_version = Column(Integer, nullable=False, default=1)
    archived_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        CheckConstraint("status IN ('draft','reviewing','approved','published','archived','withdrawn')", name="ck_artifact_status"),
        CheckConstraint("lock_version >= 1", name="ck_artifact_lock_version"),
    )


class DBArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("av"))
    artifact_id = Column(String(64), ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_format = Column(String(32), nullable=False, default="markdown")
    content_hash = Column(String(64), nullable=False, index=True)
    metadata_json = Column(JSON, default=dict)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    created_task_id = Column(String(64), ForeignKey("generation_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("artifact_id", "version_number", name="uq_artifact_version_number"),)


class DBArtifactRelation(Base):
    __tablename__ = "artifact_relations"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ar"))
    source_artifact_id = Column(String(64), ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True)
    target_artifact_id = Column(String(64), ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type = Column(String(32), nullable=False)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("source_artifact_id", "target_artifact_id", "relation_type", name="uq_artifact_relation"),)


class DBTaskStep(Base):
    __tablename__ = "task_steps"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("step"))
    task_id = Column(String(64), ForeignKey("generation_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_step_id = Column(String(64), ForeignKey("task_steps.id", ondelete="SET NULL"), nullable=True, index=True)
    sequence = Column(Integer, nullable=False)
    agent_role = Column(String(128), default="")
    tool_name = Column(String(128), default="")
    status = Column(String(32), nullable=False, default="pending", index=True)
    attempt = Column(Integer, nullable=False, default=1)
    input_summary = Column(Text, default="")
    output_artifact_version_id = Column(String(64), ForeignKey("artifact_versions.id", ondelete="SET NULL"), nullable=True)
    error_code = Column(String(64), default="")
    error_message = Column(Text, default="")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("task_id", "sequence", "attempt", name="uq_task_step_attempt"),)


class DBTaskEvent(Base):
    __tablename__ = "task_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("evt"))
    task_id = Column(String(64), ForeignKey("generation_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id = Column(String(64), ForeignKey("task_steps.id", ondelete="SET NULL"), nullable=True, index=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(128), nullable=False, index=True)
    schema_version = Column(String(32), nullable=False, default="1.0")
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("task_id", "sequence", name="uq_task_event_sequence"),)


class DBPlanDraft(Base):
    __tablename__ = "plan_drafts"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("pd"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="draft", index=True)
    idempotency_key = Column(String(128), nullable=True)
    current_version_id = Column(String(64), nullable=True, index=True)
    confirmed_version_id = Column(String(64), nullable=True, index=True)
    confirmed_at = Column(DateTime, nullable=True)
    lock_version = Column(Integer, nullable=False, default=1)
    archived_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class DBPlanVersion(Base):
    __tablename__ = "plan_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("pv"))
    plan_draft_id = Column(String(64), ForeignKey("plan_drafts.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    profile_snapshot_id = Column(String(64), nullable=True, index=True)
    content = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("plan_draft_id", "version_number", name="uq_plan_version_number"),)


class DBLearningPath(Base):
    __tablename__ = "learning_paths"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("path"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    source_plan_version_id = Column(String(64), ForeignKey("plan_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    supersedes_path_id = Column(String(64), ForeignKey("learning_paths.id", ondelete="SET NULL"), nullable=True, index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    paused_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    completed_at = Column(DateTime, nullable=True)


class DBPathNode(Base):
    __tablename__ = "path_nodes"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("node"))
    learning_path_id = Column(String(64), ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False, index=True)
    node_key = Column(String(128), nullable=False, default="", index=True)
    sequence = Column(Integer, nullable=False)
    node_type = Column(String(32), nullable=False)
    target_object_id = Column(String(64), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    prerequisites = Column(JSON, default=list)
    is_extension = Column(Boolean, nullable=False, default=False)
    resource_status = Column(String(32), nullable=False, default="existing")
    estimate_min_minutes = Column(Integer, nullable=False, default=1)
    estimate_max_minutes = Column(Integer, nullable=False, default=1)
    actual_minutes = Column(Integer, nullable=True)
    blocked_reason = Column(String(256), default="")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("learning_path_id", "sequence", name="uq_path_node_sequence"),)


class DBLearningEvent(Base):
    __tablename__ = "learning_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("le"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    legacy_student_id = Column(String(64), nullable=True, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type = Column(String(128), nullable=False, index=True)
    schema_version = Column(String(32), nullable=False, default="1.0")
    idempotency_key = Column(String(128), nullable=True)
    source = Column(String(64), nullable=False, default="api")
    trace_id = Column(String(64), nullable=False, index=True)
    object_type = Column(String(64), default="")
    object_id = Column(String(64), default="", index=True)
    action = Column(String(64), nullable=False, default="", index=True)
    context_ref = Column(JSON, default=dict)
    evidence_strength = Column(Float, nullable=False, default=0.0)
    evidence_status = Column(String(16), nullable=False, default="none", index=True)
    evidence_reason = Column(String(256), default="")
    mastery_eligible = Column(Boolean, nullable=False, default=False, index=True)
    completion_effect = Column(String(16), nullable=False, default="none")
    payload_version = Column(String(32), nullable=False, default="1")
    payload = Column(JSON, default=dict)
    occurred_at = Column(DateTime, default=_utcnow, index=True)
    recorded_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "evidence_strength >= 0.0 AND evidence_strength <= 1.0",
            name="ck_learning_event_evidence_strength",
        ),
        CheckConstraint(
            "evidence_status IN ('none','accepted','rejected')",
            name="ck_learning_event_evidence_status",
        ),
        CheckConstraint(
            "completion_effect IN ('none','progress','complete')",
            name="ck_learning_event_completion_effect",
        ),
        CheckConstraint(
            "NOT mastery_eligible OR (evidence_status = 'accepted' AND evidence_strength > 0.0)",
            name="ck_learning_event_mastery_eligibility",
        ),
        CheckConstraint(
            "evidence_status != 'accepted' OR mastery_eligible",
            name="ck_learning_event_accepted_is_eligible",
        ),
    )


class DBLearningEventConsumption(Base):
    __tablename__ = "learning_event_consumptions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("lec"))
    learning_event_id = Column(String(64), ForeignKey("learning_events.id", ondelete="CASCADE"), nullable=False, index=True)
    consumer = Column(String(64), nullable=False)
    processor_version = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    attempt = Column(Integer, nullable=False, default=1)
    result = Column(JSON, default=dict)
    error_code = Column(String(64), default="")
    created_at = Column(DateTime, default=_utcnow)
    processed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("learning_event_id", "consumer", "processor_version", name="uq_learning_event_consumer_version"),
        CheckConstraint("status IN ('pending','processed','failed')", name="ck_learning_event_consumption_status"),
        CheckConstraint("attempt >= 1", name="ck_learning_event_consumption_attempt"),
    )


class DBTutorContextSession(Base):
    __tablename__ = "tutor_context_sessions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("tctx"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    idempotency_key = Column(String(128), nullable=False)
    context_mode = Column(String(32), nullable=False, default="current_resource", index=True)
    primary_object_type = Column(String(32), nullable=False)
    primary_object_id = Column(String(64), nullable=False, index=True)
    context_snapshot = Column(JSON, nullable=False, default=dict)
    teaching_style = Column(String(32), nullable=False, default="progressive")
    explanation_depth = Column(String(16), nullable=False, default="standard")
    guidance_mode = Column(String(16), nullable=False, default="socratic")
    status = Column(String(16), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    last_used_at = Column(DateTime, default=_utcnow, index=True)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("owner_public_id", "idempotency_key", name="uq_tutor_context_owner_idempotency"),
        CheckConstraint(
            "context_mode IN ('current_resource','current_course','personal_resources','external_allowed')",
            name="ck_tutor_context_mode",
        ),
        CheckConstraint("status IN ('active','archived')", name="ck_tutor_context_status"),
        CheckConstraint("lock_version >= 1", name="ck_tutor_context_lock_version"),
    )


class DBMemoryItem(Base):
    __tablename__ = "memory_items"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mem"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    memory_key = Column(String(192), nullable=False, default="", index=True)
    title = Column(String(256), nullable=False, default="")
    memory_type = Column(String(32), nullable=False, index=True)
    content = Column(Text, nullable=False)
    source_type = Column(String(64), nullable=False)
    source_id = Column(String(64), nullable=False, index=True)
    confidence = Column(Float, nullable=False, default=0.0)
    sensitivity = Column(String(32), nullable=False, default="personal", index=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    expires_at = Column(DateTime, nullable=True, index=True)
    last_used_at = Column(DateTime, nullable=True)
    withdrawn_at = Column(DateTime, nullable=True, index=True)
    withdrawal_reason = Column(Text, default="")
    archived_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class DBReviewDecision(Base):
    __tablename__ = "review_decisions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("review"))
    artifact_version_id = Column(String(64), ForeignKey("artifact_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    review_type = Column(String(32), nullable=False)
    reviewer_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    decision = Column(String(32), nullable=False, index=True)
    rationale = Column(Text, default="")
    checks = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)


class DBPublication(Base):
    __tablename__ = "publications"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("pub"))
    artifact_version_id = Column(String(64), ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    review_decision_id = Column(String(64), ForeignKey("review_decisions.id", ondelete="RESTRICT"), nullable=True, index=True)
    visibility = Column(String(32), nullable=False, default="private", index=True)
    status = Column(String(32), nullable=False, default="published", index=True)
    published_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    published_at = Column(DateTime, default=_utcnow)
    withdrawn_at = Column(DateTime, nullable=True)
    withdrawal_reason = Column(Text, default="")


class DBAuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("audit"))
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(128), nullable=False, index=True)
    object_type = Column(String(64), nullable=False, index=True)
    object_id = Column(String(64), nullable=False, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    outcome = Column(String(32), nullable=False, default="success", index=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow, index=True)


class DBLegacyObjectMigration(Base):
    """Recoverable mapping from one protected legacy object to its canonical target."""

    __tablename__ = "legacy_object_migrations"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("lom"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    legacy_student_id = Column(String(64), nullable=False, index=True)
    old_type = Column(String(32), nullable=False, index=True)
    old_id = Column(String(128), nullable=False, index=True)
    target_type = Column(String(32), nullable=False, index=True)
    target_id = Column(String(128), nullable=True, index=True)
    version = Column(String(32), nullable=False, default="1")
    status = Column(String(24), nullable=False, default="pending", index=True)
    error_code = Column(String(64), default="")
    rollback_token = Column(String(64), nullable=False, unique=True, index=True)
    created_objects = Column(JSON, default=list)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    verified_at = Column(DateTime, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "owner_public_id", "old_type", "old_id", "version",
            name="uq_legacy_object_migration_source_version",
        ),
        CheckConstraint(
            "status IN ('pending','mapped','copied','verified','failed','rolled_back')",
            name="ck_legacy_object_migration_status",
        ),
    )


class DBSchemaMigration(Base):
    __tablename__ = "schema_migrations"
    version = Column(String(64), primary_key=True)
    description = Column(String(256), nullable=False)
    checksum = Column(String(64), nullable=False)
    applied_at = Column(DateTime, default=_utcnow)


class DBDomainPack(Base):
    __tablename__ = "domain_packs"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("dp"))
    domain_key = Column(String(128), nullable=False, unique=True, index=True)
    title = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="active", index=True)
    current_version_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow)


class DBDomainVersion(Base):
    __tablename__ = "domain_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("dv"))
    domain_pack_id = Column(String(64), ForeignKey("domain_packs.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(String(64), nullable=False)
    ontology = Column(JSON, default=dict)
    rules = Column(JSON, default=dict)
    templates = Column(JSON, default=dict)
    checkers = Column(JSON, default=list)
    evaluation_set = Column(JSON, default=dict)
    dependencies = Column(JSON, default=list)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("domain_pack_id", "version", name="uq_domain_version"),)


class DBJobTask(Base):
    __tablename__ = "job_tasks"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("job"))
    domain_version_id = Column(String(64), ForeignKey("domain_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    inputs = Column(JSON, default=list)
    outputs = Column(JSON, default=list)
    acceptance_rules = Column(JSON, default=list)
    risk_level = Column(String(32), nullable=False, default="normal")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("domain_version_id", "code", name="uq_job_task_code"),)


class DBSkillStandard(Base):
    __tablename__ = "skill_standards"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("skill"))
    domain_version_id = Column(String(64), ForeignKey("domain_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    level = Column(String(32), nullable=False)
    prerequisites = Column(JSON, default=list)
    job_task_codes = Column(JSON, default=list)
    evidence_requirements = Column(JSON, default=list)
    acceptance_rules = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("domain_version_id", "code", "level", name="uq_skill_standard_level"),)


class DBProfileSnapshot(Base):
    __tablename__ = "profile_snapshots"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ps"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    legacy_student_id = Column(String(64), nullable=True, index=True)
    profile_version = Column(String(64), nullable=False)
    snapshot = Column(JSON, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow)


class DBProfileEvidence(Base):
    """Versioned evidence item supporting a profile conclusion.

    The legacy JSON array on ``student_profiles`` remains the compatibility
    source. This table gives each evidence item a stable identity, ownership,
    provenance and trace boundary without exposing its body through M1 APIs.
    """
    __tablename__ = "profile_evidence_items"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("pe"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=True, index=True)
    legacy_student_id = Column(String(64), nullable=False, index=True)
    legacy_key = Column(String(64), nullable=False)
    source_type = Column(String(64), nullable=False, index=True)
    source_object_id = Column(String(64), nullable=True, index=True)
    features = Column(JSON, default=list)
    weight = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=0.0)
    evidence_summary = Column(Text, default="")
    observed_at = Column(DateTime, default=_utcnow, index=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    evidence_version = Column(String(32), nullable=False, default="1")
    trace_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("legacy_student_id", "legacy_key", name="uq_profile_evidence_legacy_key"),
        CheckConstraint("weight >= 0 AND weight <= 1", name="ck_profile_evidence_weight"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_profile_evidence_confidence"),
        CheckConstraint(
            "status IN ('active','superseded','archived','legacy_unresolved')",
            name="ck_profile_evidence_status",
        ),
    )


class DBAgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("run"))
    task_id = Column(String(64), ForeignKey("generation_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_run_id = Column(String(64), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    role = Column(String(128), nullable=False)
    agent_version = Column(String(64), nullable=False)
    input_summary = Column(Text, default="")
    output_artifact_version_id = Column(String(64), ForeignKey("artifact_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    tool_names = Column(JSON, default=list)
    model = Column(String(128), default="")
    duration_ms = Column(Integer, default=0)
    status = Column(String(32), nullable=False, default="running", index=True)
    created_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)


class DBModelCall(Base):
    __tablename__ = "model_calls"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mcall"))
    trace_id = Column(String(64), nullable=False, index=True)
    task_id = Column(String(64), ForeignKey("generation_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    capability = Column(String(64), nullable=False, index=True)
    prompt_version = Column(String(64), nullable=False)
    provider = Column(String(64), nullable=False)
    model = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="running", index=True)
    input_summary = Column(JSON, nullable=False, default=dict)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    token_source = Column(String(32), nullable=False, default="estimated")
    retry_count = Column(Integer, nullable=False, default=0)
    estimated_cost = Column(Float, nullable=False, default=0.0)
    pricing_version = Column(String(64), nullable=False, default="unpriced")
    cost_currency = Column(String(8), nullable=False, default="USD")
    cost_basis = Column(String(32), nullable=False, default="estimate")
    duration_ms = Column(Integer, nullable=False, default=0)
    output_hash = Column(String(64), nullable=False, default="")
    error_code = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('running','completed','failed')", name="ck_model_call_status"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="ck_model_call_tokens"),
        CheckConstraint("retry_count >= 0 AND estimated_cost >= 0 AND duration_ms >= 0", name="ck_model_call_metrics"),
    )


class DBModelQuotaBucket(Base):
    __tablename__ = "model_quota_buckets"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mqb"))
    scope_type = Column(String(16), nullable=False)
    scope_key = Column(String(256), nullable=False)
    utc_day = Column(String(10), nullable=False)
    call_count = Column(Integer, nullable=False, default=0)
    reserved_tokens = Column(Integer, nullable=False, default=0)
    reserved_cost = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("scope_type", "scope_key", "utc_day", name="uq_model_quota_bucket_scope_day"),
        CheckConstraint("scope_type IN ('user','course','model')", name="ck_model_quota_bucket_scope"),
        CheckConstraint("call_count >= 0 AND reserved_tokens >= 0 AND reserved_cost >= 0", name="ck_model_quota_bucket_values"),
    )


class DBQualityCheck(Base):
    __tablename__ = "quality_checks"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("qc"))
    artifact_version_id = Column(String(64), ForeignKey("artifact_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_run_id = Column(String(64), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    check_type = Column(String(32), nullable=False, index=True)
    checker_version = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    score = Column(Float, nullable=True)
    details = Column(JSON, default=dict)
    source_ref_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)


class DBClaimCheck(Base):
    __tablename__ = "claim_checks"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("claim"))
    artifact_version_id = Column(String(64), ForeignKey("artifact_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    atomic_claim = Column(Text, nullable=False)
    source_ref_id = Column(String(64), ForeignKey("source_refs.id", ondelete="SET NULL"), nullable=True, index=True)
    support_status = Column(String(32), nullable=False, index=True)
    verdict = Column(String(32), nullable=False)
    rationale = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)


class DBDebateRound(Base):
    __tablename__ = "debate_rounds"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("debate"))
    task_id = Column(String(64), ForeignKey("generation_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_version_id = Column(String(64), ForeignKey("artifact_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    round_number = Column(Integer, nullable=False)
    max_rounds = Column(Integer, nullable=False)
    prover_claim = Column(Text, nullable=False)
    challenger_response = Column(Text, nullable=False)
    judge_decision = Column(String(32), nullable=False)
    evidence_ref_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("task_id", "round_number", name="uq_debate_task_round"),)


class DBDecisionRecord(Base):
    __tablename__ = "decision_records"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("decision"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(64), ForeignKey("generation_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    profile_snapshot_id = Column(String(64), ForeignKey("profile_snapshots.id", ondelete="RESTRICT"), nullable=False, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    decision_type = Column(String(64), nullable=False, index=True)
    candidates = Column(JSON, default=list)
    rules = Column(JSON, default=list)
    evidence_ids = Column(JSON, default=list)
    confidence = Column(Float, nullable=False, default=0.0)
    execution_impact = Column(JSON, default=dict)
    user_confirmed = Column(Boolean, nullable=False, default=False)
    before_version_id = Column(String(64), nullable=True)
    after_version_id = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="proposed", index=True)
    created_at = Column(DateTime, default=_utcnow)


class DBEvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ec"))
    case_code = Column(String(64), nullable=False)
    case_version = Column(String(64), nullable=False)
    domain_version_id = Column(String(64), ForeignKey("domain_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    input_data = Column(JSON, nullable=False)
    gold_data = Column(JSON, nullable=False)
    data_version = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("case_code", "case_version", name="uq_evaluation_case_version"),)


class DBEvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("er"))
    trace_id = Column(String(64), nullable=False, unique=True, index=True)
    code_version = Column(String(64), nullable=False)
    data_version = Column(String(64), nullable=False)
    model_version = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="running", index=True)
    started_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)


class DBEvaluationResult(Base):
    __tablename__ = "evaluation_results"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("eres"))
    evaluation_run_id = Column(String(64), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    evaluation_case_id = Column(String(64), ForeignKey("evaluation_cases.id", ondelete="RESTRICT"), nullable=False, index=True)
    output_data = Column(JSON, nullable=False)
    scores = Column(JSON, default=dict)
    passed = Column(Boolean, nullable=False, default=False, index=True)
    failure_reason = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("evaluation_run_id", "evaluation_case_id", name="uq_evaluation_run_case"),)


class DBEvaluationAnnotation(Base):
    __tablename__ = "evaluation_annotations"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("eann"))
    evaluation_result_id = Column(String(64), ForeignKey("evaluation_results.id", ondelete="CASCADE"), nullable=False, index=True)
    annotation_type = Column(String(32), nullable=False, index=True)
    annotation_key = Column(String(128), nullable=False)
    annotator_ref = Column(String(128), nullable=False, index=True)
    annotation_version = Column(Integer, nullable=False, default=1)
    supersedes_id = Column(String(64), ForeignKey("evaluation_annotations.id", ondelete="RESTRICT"), nullable=True)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="draft", index=True)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "evaluation_result_id", "annotation_type", "annotation_key", "annotator_ref", "annotation_version",
            name="uq_evaluation_annotation_version",
        ),
        CheckConstraint("annotation_version >= 1", name="ck_evaluation_annotation_version"),
        CheckConstraint("annotation_type IN ('atomic_fact','adaptation','coverage')", name="ck_evaluation_annotation_type"),
        CheckConstraint("status IN ('draft','final','adjudicated')", name="ck_evaluation_annotation_status"),
    )


class DBEvaluationReport(Base):
    __tablename__ = "evaluation_reports"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("erep"))
    evaluation_run_id = Column(String(64), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_version = Column(String(64), nullable=False)
    report_version = Column(Integer, nullable=False, default=1)
    report_data = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="draft", index=True)
    approval_ref = Column(String(128), nullable=False, default="")
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("evaluation_run_id", "metric_version", "report_version", name="uq_evaluation_report_version"),
        CheckConstraint("report_version >= 1", name="ck_evaluation_report_version"),
        CheckConstraint("status IN ('draft','approved','superseded')", name="ck_evaluation_report_status"),
    )


class DBOrganization(Base):
    __tablename__ = "organizations"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("org"))
    name = Column(String(256), nullable=False)
    organization_type = Column(String(32), nullable=False, default="enterprise")
    status = Column(String(32), nullable=False, default="active", index=True)
    sharing_policy = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)


class DBOrganizationMembership(Base):
    __tablename__ = "organization_memberships"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("om"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), nullable=False, default="learner")
    status = Column(String(32), nullable=False, default="active", index=True)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("organization_id", "user_public_id", name="uq_organization_member"),
        CheckConstraint("role IN ('learner','mentor','manager','admin')", name="ck_organization_member_role"),
        CheckConstraint("status IN ('invited','active','suspended','removed')", name="ck_organization_member_status"),
    )


class DBDepartment(Base):
    __tablename__ = "departments"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("dept"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = Column(String(64), ForeignKey("departments.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class DBJobFamily(Base):
    __tablename__ = "job_families"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("jf"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_job_family_code"),)


class DBJobLevel(Base):
    __tablename__ = "job_levels"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("jl"))
    job_family_id = Column(String(64), ForeignKey("job_families.id", ondelete="CASCADE"), nullable=False, index=True)
    level_code = Column(String(64), nullable=False)
    version = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    responsibilities = Column(JSON, default=list)
    effective_from = Column(DateTime, nullable=True)
    effective_to = Column(DateTime, nullable=True)
    status = Column(String(32), nullable=False, default="draft", index=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("job_family_id", "level_code", "version", name="uq_job_level_version"),)


class DBCompetencyStandard(Base):
    __tablename__ = "competency_standards"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("cs"))
    job_level_id = Column(String(64), ForeignKey("job_levels.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_standard_id = Column(String(64), ForeignKey("skill_standards.id", ondelete="RESTRICT"), nullable=False, index=True)
    requirement_level = Column(String(32), nullable=False)
    version = Column(String(64), nullable=False, default="1")
    evidence_requirements = Column(JSON, default=list)
    mandatory = Column(Boolean, nullable=False, default=True)
    risk_level = Column(String(32), nullable=False, default="normal", index=True)
    exemption_policy = Column(String(32), nullable=False, default="allowed")
    acceptance_rules = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("job_level_id", "skill_standard_id", name="uq_competency_standard_skill"),)


class DBTrainingProgram(Base):
    __tablename__ = "training_programs"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("tp"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    target_job_level_id = Column(String(64), ForeignKey("job_levels.id", ondelete="RESTRICT"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    version = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="draft", index=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("organization_id", "title", "version", name="uq_training_program_version"),)


class DBTrainingCohort(Base):
    __tablename__ = "training_cohorts"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("cohort"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    training_program_id = Column(String(64), ForeignKey("training_programs.id", ondelete="RESTRICT"), nullable=False, index=True)
    standard_snapshot = Column(JSON, nullable=False)
    course_versions = Column(JSON, default=list)
    resource_version_ids = Column(JSON, default=list)
    assessment_versions = Column(JSON, default=list)
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    status = Column(String(32), nullable=False, default="planned", index=True)
    created_at = Column(DateTime, default=_utcnow)


class DBTrainingAssignment(Base):
    __tablename__ = "training_assignments"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ta"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    cohort_id = Column(String(64), ForeignKey("training_cohorts.id", ondelete="CASCADE"), nullable=False, index=True)
    learner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_source = Column(String(32), nullable=False)
    source_reference = Column(String(128), default="")
    status = Column(String(32), nullable=False, default="assigned", index=True)
    assigned_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("cohort_id", "learner_public_id", name="uq_training_assignment_learner"),
        CheckConstraint(
            "assignment_source IN ('organization','job_requirement','personal_application','transfer_plan','retraining')",
            name="ck_training_assignment_source",
        ),
    )


class DBExemptionRequest(Base):
    __tablename__ = "exemption_requests"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ex"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id = Column(String(64), ForeignKey("training_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    competency_standard_id = Column(String(64), ForeignKey("competency_standards.id", ondelete="RESTRICT"), nullable=False, index=True)
    requester_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False)
    evidence_ids = Column(JSON, default=list)
    rule_result = Column(String(32), nullable=False, default="pending")
    status = Column(String(32), nullable=False, default="pending", index=True)
    approver_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class DBSkillEvidence(Base):
    __tablename__ = "skill_evidence"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("se"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    learner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    competency_standard_id = Column(String(64), ForeignKey("competency_standards.id", ondelete="RESTRICT"), nullable=False, index=True)
    evidence_type = Column(String(32), nullable=False)
    source_object_id = Column(String(64), nullable=False, index=True)
    result = Column(String(32), nullable=False)
    score = Column(Float, nullable=True)
    prompt_dependency = Column(String(32), nullable=False, default="independent")
    hidden_test_result = Column(JSON, default=dict)
    expert_signer_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    observed_at = Column(DateTime, default=_utcnow)
    valid_until = Column(DateTime, nullable=True)


class DBCertification(Base):
    __tablename__ = "certifications"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("cert"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    learner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    job_level_id = Column(String(64), ForeignKey("job_levels.id", ondelete="RESTRICT"), nullable=False, index=True)
    standard_snapshot = Column(JSON, nullable=False)
    evidence_ids = Column(JSON, default=list)
    issuer_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    issued_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)
    retraining_rule = Column(JSON, default=dict)
    revoked_at = Column(DateTime, nullable=True)
    lock_version = Column(Integer, nullable=False, default=1)


class DBCertificationLifecycleEvent(Base):
    __tablename__ = "certification_lifecycle_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("cevt"))
    certification_id = Column(String(64), ForeignKey("certifications.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    actor_role = Column(String(32), nullable=False)
    action = Column(String(32), nullable=False, index=True)
    from_status = Column(String(32), nullable=False)
    to_status = Column(String(32), nullable=False)
    reason = Column(Text, nullable=False)
    reason_hash = Column(String(64), nullable=False)
    evidence_snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=_utcnow)


class DBRetrainingTask(Base):
    __tablename__ = "retraining_tasks"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("retrain"))
    certification_id = Column(String(64), ForeignKey("certifications.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    learner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    trigger_type = Column(String(32), nullable=False)
    trigger_key = Column(String(128), nullable=False)
    title = Column(String(256), nullable=False)
    due_at = Column(DateTime, nullable=True)
    status = Column(String(32), nullable=False, default="assigned", index=True)
    rule_snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("certification_id", "trigger_key", name="uq_retraining_certificate_trigger"),
        CheckConstraint("status IN ('assigned','in_progress','completed','cancelled')", name="ck_retraining_task_status"),
    )


class DBLocalNotification(Base):
    __tablename__ = "local_notifications"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("notice"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    notification_type = Column(String(64), nullable=False, index=True)
    idempotency_key = Column(String(160), nullable=False)
    title = Column(String(256), nullable=False)
    body = Column(Text, nullable=False)
    object_type = Column(String(64), nullable=False)
    object_id = Column(String(64), nullable=False, index=True)
    delivery_channel = Column(String(32), nullable=False, default="local_inbox")
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("owner_public_id", "idempotency_key", name="uq_local_notification_owner_key"),)


class DBMultilevelReviewCase(Base):
    __tablename__ = "multilevel_review_cases"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mreview"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    submitter_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    object_type = Column(String(64), nullable=False)
    object_id = Column(String(64), nullable=False, index=True)
    object_version = Column(String(128), nullable=False)
    evidence_snapshot = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="level1_pending", index=True)
    current_level = Column(Integer, nullable=False, default=1)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    resolved_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("organization_id","object_type","object_id","object_version",name="uq_multilevel_review_object_version"),)


class DBMultilevelReviewDecision(Base):
    __tablename__ = "multilevel_review_decisions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mrdec"))
    review_case_id = Column(String(64), ForeignKey("multilevel_review_cases.id", ondelete="RESTRICT"), nullable=False, index=True)
    level = Column(Integer, nullable=False)
    action = Column(String(32), nullable=False)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    actor_role = Column(String(32), nullable=False)
    from_status = Column(String(32), nullable=False)
    to_status = Column(String(32), nullable=False)
    reason = Column(Text, nullable=False)
    reason_hash = Column(String(64), nullable=False)
    evidence_snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=_utcnow)


class DBJobStandardImpactPreview(Base):
    __tablename__ = "job_standard_impact_previews"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("jsimpact"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_job_level_id = Column(String(64), ForeignKey("job_levels.id", ondelete="RESTRICT"), nullable=False, index=True)
    target_job_level_id = Column(String(64), ForeignKey("job_levels.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    standard_source = Column(String(64), nullable=False, default="frozen_synthetic_demo")
    diff_snapshot = Column(JSON, nullable=False)
    impact_snapshot = Column(JSON, nullable=False)
    preview_hash = Column(String(64), nullable=False, unique=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, default=_utcnow)
    confirmed_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("organization_id", "source_job_level_id", "target_job_level_id", name="uq_job_standard_impact_pair"),
        CheckConstraint("status IN ('pending','confirmed')", name="ck_job_standard_impact_status"),
    )


class DBJobStandardImpactConfirmation(Base):
    __tablename__ = "job_standard_impact_confirmations"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("jsconfirm"))
    preview_id = Column(String(64), ForeignKey("job_standard_impact_previews.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    actor_role = Column(String(32), nullable=False)
    preview_hash = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False)
    reason_hash = Column(String(64), nullable=False)
    scheduling_snapshot = Column(JSON, nullable=False)
    confirmation_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, default=_utcnow)


class DBEnterpriseRiskReport(Base):
    __tablename__ = "enterprise_risk_reports"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("erisk"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    period_start = Column(DateTime, nullable=False, index=True)
    period_end = Column(DateTime, nullable=False, index=True)
    metric_version = Column(String(64), nullable=False)
    minimum_sample = Column(Integer, nullable=False, default=3)
    report_data = Column(JSON, nullable=False)
    content_hash = Column(String(64), nullable=False, unique=True)
    status = Column(String(32), nullable=False, default="open", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    closed_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("organization_id", "period_start", "period_end", "metric_version", name="uq_enterprise_risk_period_version"),
        CheckConstraint("period_end > period_start", name="ck_enterprise_risk_period"),
        CheckConstraint("minimum_sample >= 3", name="ck_enterprise_risk_minimum_sample"),
        CheckConstraint("status IN ('open','acknowledged','closed')", name="ck_enterprise_risk_status"),
    )


class DBEnterpriseRiskDecision(Base):
    __tablename__ = "enterprise_risk_decisions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("erdec"))
    report_id = Column(String(64), ForeignKey("enterprise_risk_reports.id", ondelete="RESTRICT"), nullable=False, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    actor_role = Column(String(32), nullable=False)
    action = Column(String(32), nullable=False)
    from_status = Column(String(32), nullable=False)
    to_status = Column(String(32), nullable=False)
    reason = Column(Text, nullable=False)
    reason_hash = Column(String(64), nullable=False)
    evidence_snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class DBExternalIdentityMapping(Base):
    __tablename__ = "external_identity_mappings"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("eid"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(64), nullable=False)
    external_subject = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="active", index=True)
    bound_at = Column(DateTime, default=_utcnow)
    revoked_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("organization_id", "provider", "external_subject", name="uq_external_identity_subject"),)


class DBLocalSSOProvider(Base):
    """Organization-scoped configuration for the deterministic local IdP simulator."""
    __tablename__ = "local_sso_providers"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ssop"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_key = Column(String(64), nullable=False)
    display_name = Column(String(128), nullable=False)
    protocol_style = Column(String(16), nullable=False)
    issuer = Column(String(256), nullable=False)
    status = Column(String(24), nullable=False, default="active", index=True)
    current_mapping_version = Column(Integer, nullable=False, default=1)
    lock_version = Column(Integer, nullable=False, default=1)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("organization_id", "provider_key", name="uq_local_sso_provider_key"),
        CheckConstraint("protocol_style IN ('oidc','saml')", name="ck_local_sso_provider_protocol"),
        CheckConstraint("status IN ('active','disabled') AND current_mapping_version >= 1 AND lock_version >= 1", name="ck_local_sso_provider_state"),
    )


class DBLocalSSOMappingVersion(Base):
    """Immutable claim and group-to-role rule snapshot for a local SSO provider."""
    __tablename__ = "local_sso_mapping_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ssomap"))
    provider_id = Column(String(64), ForeignKey("local_sso_providers.id", ondelete="RESTRICT"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    subject_claim = Column(String(64), nullable=False, default="sub")
    groups_claim = Column(String(64), nullable=False, default="groups")
    group_role_map = Column(JSON, nullable=False)
    default_role = Column(String(32), nullable=False, default="learner")
    mapping_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("provider_id", "version_number", name="uq_local_sso_mapping_version"),
        CheckConstraint("version_number >= 1", name="ck_local_sso_mapping_version_number"),
        CheckConstraint("default_role IN ('learner','mentor','manager','admin')", name="ck_local_sso_mapping_default_role"),
    )


class DBLocalSSOSession(Base):
    """Short-lived local demonstration session; it is not an application access token."""
    __tablename__ = "local_sso_sessions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ssosess"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = Column(String(64), ForeignKey("local_sso_providers.id", ondelete="RESTRICT"), nullable=True, index=True)
    mapping_id = Column(String(64), ForeignKey("external_identity_mappings.id", ondelete="RESTRICT"), nullable=True, index=True)
    user_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    assertion_id = Column(String(128), nullable=False)
    assertion_hash = Column(String(64), nullable=False)
    resolved_organization_role = Column(String(32), nullable=False)
    login_mode = Column(String(24), nullable=False)
    status = Column(String(24), nullable=False, default="active", index=True)
    issued_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("organization_id", "assertion_id", name="uq_local_sso_session_assertion"),
        CheckConstraint("resolved_organization_role IN ('learner','mentor','manager','admin')", name="ck_local_sso_session_role"),
        CheckConstraint("login_mode IN ('simulated_sso','emergency_admin')", name="ck_local_sso_session_mode"),
        CheckConstraint("status IN ('active','revoked','expired')", name="ck_local_sso_session_status"),
    )


class DBLocalSSOEvent(Base):
    """Append-only decision record for previews, binding, login and revocation."""
    __tablename__ = "local_sso_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ssoevt"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = Column(String(64), ForeignKey("local_sso_providers.id", ondelete="RESTRICT"), nullable=True, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    action = Column(String(32), nullable=False)
    outcome = Column(String(32), nullable=False, index=True)
    external_subject = Column(String(256), nullable=False, default="")
    assertion_id = Column(String(128), nullable=False, default="")
    evidence_snapshot = Column(JSON, nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class DBHRFieldMappingVersion(Base):
    """Immutable mapping contract for one organization's synthetic HR feed."""
    __tablename__ = "hr_field_mapping_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("hrmap"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_key = Column(String(64), nullable=False)
    version_number = Column(Integer, nullable=False)
    field_map = Column(JSON, nullable=False)
    mapping_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("organization_id", "source_key", "version_number", name="uq_hr_mapping_version"),
        CheckConstraint("version_number >= 1", name="ck_hr_mapping_version"),
    )


class DBHRSyncBatch(Base):
    """Frozen preview and apply lifecycle for an inbound synthetic HR snapshot."""
    __tablename__ = "hr_sync_batches"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("hrbatch"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_key = Column(String(64), nullable=False)
    source_snapshot_id = Column(String(128), nullable=False)
    source_sequence = Column(Integer, nullable=False)
    mapping_version_id = Column(String(64), ForeignKey("hr_field_mapping_versions.id", ondelete="RESTRICT"), nullable=False)
    source_snapshot = Column(JSON, nullable=False)
    preview_snapshot = Column(JSON, nullable=False)
    source_hash = Column(String(64), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="previewed", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    applied_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("organization_id", "source_key", "source_snapshot_id", name="uq_hr_sync_snapshot"),
        CheckConstraint("source_sequence >= 1 AND lock_version >= 1", name="ck_hr_sync_batch_sequence"),
        CheckConstraint("status IN ('previewed','applied','rejected')", name="ck_hr_sync_batch_status"),
    )


class DBHREmployeeProjection(Base):
    """Current organization projection of one external synthetic employee record."""
    __tablename__ = "hr_employee_projections"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("hremp"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_key = Column(String(64), nullable=False)
    external_employee_id = Column(String(128), nullable=False)
    user_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    department_id = Column(String(64), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True, index=True)
    job_level_id = Column(String(64), ForeignKey("job_levels.id", ondelete="RESTRICT"), nullable=True, index=True)
    employment_status = Column(String(24), nullable=False, default="active", index=True)
    source_sequence = Column(Integer, nullable=False)
    source_record_hash = Column(String(64), nullable=False)
    last_batch_id = Column(String(64), ForeignKey("hr_sync_batches.id", ondelete="RESTRICT"), nullable=False)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("organization_id", "source_key", "external_employee_id", name="uq_hr_employee_external_id"),
        CheckConstraint("employment_status IN ('active','leave') AND source_sequence >= 1 AND lock_version >= 1", name="ck_hr_employee_state"),
    )


class DBHRSyncRecord(Base):
    """Append-only per-record decision made during HR preview or apply."""
    __tablename__ = "hr_sync_records"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("hrrec"))
    batch_id = Column(String(64), ForeignKey("hr_sync_batches.id", ondelete="RESTRICT"), nullable=False, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    external_employee_id = Column(String(128), nullable=False)
    action = Column(String(32), nullable=False)
    outcome = Column(String(24), nullable=False, index=True)
    user_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=True)
    evidence_snapshot = Column(JSON, nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class DBLocalLMSConnection(Base):
    """Organization-scoped deterministic LMS adapter configuration."""
    __tablename__ = "local_lms_connections"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("lmsconn"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_key = Column(String(64), nullable=False)
    display_name = Column(String(128), nullable=False)
    adapter_version = Column(String(32), nullable=False, default="local-lms-1.0")
    status = Column(String(24), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("organization_id", "connection_key", name="uq_local_lms_connection_key"),
        CheckConstraint("status IN ('active','disabled') AND lock_version >= 1", name="ck_local_lms_connection_state"),
    )


class DBLMSCatalogExport(Base):
    """Immutable course or cohort snapshot exported to the local LMS adapter."""
    __tablename__ = "lms_catalog_exports"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("lmsexp"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = Column(String(64), ForeignKey("local_lms_connections.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_type = Column(String(24), nullable=False)
    source_object_id = Column(String(128), nullable=False, index=True)
    external_catalog_key = Column(String(160), nullable=False)
    snapshot = Column(JSON, nullable=False)
    snapshot_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("connection_id", "source_type", "source_object_id", "snapshot_hash", name="uq_lms_catalog_export_snapshot"),
        CheckConstraint("source_type IN ('course','cohort')", name="ck_lms_catalog_export_type"),
    )


class DBLMSAssignmentExchange(Base):
    """Current idempotent projection of a canonical training assignment in LMS."""
    __tablename__ = "lms_assignment_exchanges"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("lmsasg"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = Column(String(64), ForeignKey("local_lms_connections.id", ondelete="RESTRICT"), nullable=False, index=True)
    training_assignment_id = Column(String(64), ForeignKey("training_assignments.id", ondelete="RESTRICT"), nullable=False, index=True)
    external_assignment_key = Column(String(160), nullable=False)
    payload = Column(JSON, nullable=False)
    payload_hash = Column(String(64), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="assigned", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    synced_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("connection_id", "training_assignment_id", name="uq_lms_assignment_exchange"),
        UniqueConstraint("connection_id", "external_assignment_key", name="uq_lms_external_assignment_key"),
        CheckConstraint("status IN ('assigned','withdrawn') AND lock_version >= 1", name="ck_lms_assignment_exchange_state"),
    )


class DBLMSGradeSummary(Base):
    """Immutable external completion/grade summary retained as candidate evidence only."""
    __tablename__ = "lms_grade_summaries"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("lmsgrade"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = Column(String(64), ForeignKey("local_lms_connections.id", ondelete="RESTRICT"), nullable=False, index=True)
    external_record_key = Column(String(160), nullable=False)
    training_assignment_id = Column(String(64), ForeignKey("training_assignments.id", ondelete="RESTRICT"), nullable=False, index=True)
    learner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    completion_status = Column(String(24), nullable=False)
    score = Column(Float, nullable=True)
    occurred_at = Column(DateTime, nullable=False)
    source_payload = Column(JSON, nullable=False)
    payload_hash = Column(String(64), nullable=False, index=True)
    evidence_status = Column(String(24), nullable=False, default="candidate", index=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("connection_id", "external_record_key", name="uq_lms_grade_external_record"),
        CheckConstraint("completion_status IN ('in_progress','completed','failed','withdrawn')", name="ck_lms_grade_completion"),
        CheckConstraint("score IS NULL OR (score >= 0.0 AND score <= 1.0)", name="ck_lms_grade_score"),
        CheckConstraint("evidence_status IN ('candidate','rejected')", name="ck_lms_grade_evidence_status"),
    )


class DBLMSSyncEvent(Base):
    """Append-only audit event for LMS exports, assignment sync and inbound summaries."""
    __tablename__ = "lms_sync_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("lmsevt"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = Column(String(64), ForeignKey("local_lms_connections.id", ondelete="RESTRICT"), nullable=False, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    action = Column(String(40), nullable=False, index=True)
    outcome = Column(String(24), nullable=False, index=True)
    object_type = Column(String(32), nullable=False)
    object_id = Column(String(160), nullable=False, index=True)
    evidence_snapshot = Column(JSON, nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class DBIntegrationDelivery(Base):
    __tablename__ = "integration_deliveries"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("idel"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    adapter_type = Column(String(32), nullable=False, index=True)
    adapter_version = Column(String(32), nullable=False)
    destination_key = Column(String(128), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=False)
    source_object_type = Column(String(64), nullable=False)
    source_object_id = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    payload_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error_code = Column(String(64), default="")
    next_attempt_at = Column(DateTime, nullable=True, index=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("organization_id", "destination_key", "idempotency_key", name="uq_integration_delivery_idempotency"),
        CheckConstraint("adapter_type IN ('xapi','webhook','lms','hr')", name="ck_integration_delivery_adapter"),
        CheckConstraint("status IN ('pending','delivering','delivered','failed','dead_letter')", name="ck_integration_delivery_status"),
        CheckConstraint("attempt_count >= 0", name="ck_integration_delivery_attempt"),
    )

class DBQuizRecord(Base):
    """持久化物理表：存储测验记录与置信度反馈"""
    __tablename__ = "quiz_records"

    id = Column(String(64), primary_key=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), index=True)
    question = Column(Text)
    student_answer = Column(Text)
    correct_answer = Column(Text, default="")
    ai_confidence = Column(Float, default=0.0)
    student_confidence = Column(Float, default=0.0)
    accuracy_score = Column(Float, default=0.0)
    target_concept = Column(String(128), default="")
    feedback = Column(Text, default="")
    next_action = Column(String(64), default="review")  # review / practice / advance
    attempt_number = Column(Integer, default=1)
    session_id = Column(String(64), default="")
    options = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)

    # === 任务 6 核心扩展：存取答题时的 IRT 参数数值 ===
    irt_alpha = Column(Float, default=1.0)
    irt_beta = Column(Float, default=0.0)
    irt_gamma = Column(Float, default=0.25)
    irt_alpha_vec = Column(JSON, nullable=True)
    irt_beta_vec = Column(JSON, nullable=True)

    student_profile = relationship("DBStudentProfile", back_populates="quiz_records")

class DBQuizItem(Base):
    """持久化物理表：本地预置种子题库"""
    __tablename__ = "quiz_items"

    id = Column(String(64), primary_key=True)
    concept = Column(String(128), index=True)
    question = Column(Text, nullable=False)
    options = Column(JSON, default=list)
    correct_answer = Column(Text, default="")
    explanation = Column(Text, default="")
    difficulty = Column(String(32), default="medium")
    irt_alpha = Column(Float, default=1.0)
    irt_beta = Column(Float, default=0.0)
    irt_gamma = Column(Float, default=0.25)
    irt_alpha_vec = Column(JSON, nullable=True)
    irt_beta_vec = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class DBAssessmentQuestion(Base):
    """Canonical assessment identity; content lives in immutable versions."""
    __tablename__ = "assessment_questions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("aq"))
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    question_type = Column(String(32), nullable=False, index=True)
    origin = Column(String(32), nullable=False, default="manual", index=True)
    status = Column(String(32), nullable=False, default="draft", index=True)
    current_version_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        CheckConstraint("question_type IN ('single_choice','multiple_choice','true_false','fill_blank','short_answer','code','open_task')", name="ck_assessment_question_type"),
        CheckConstraint("origin IN ('manual','textbook','ai_generated','derived','legacy')", name="ck_assessment_question_origin"),
        CheckConstraint("status IN ('draft','reviewing','approved','retired')", name="ck_assessment_question_status"),
    )


class DBLocalLRSStatement(Base):
    """Immutable xAPI statement accepted by the organization-local LRS simulator."""
    __tablename__ = "local_lrs_statements"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("lrsstmt"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    destination_key = Column(String(128), nullable=False, index=True)
    statement_id = Column(String(128), nullable=False)
    delivery_id = Column(String(64), ForeignKey("integration_deliveries.id", ondelete="RESTRICT"), nullable=False, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=True, index=True)
    verb_id = Column(String(512), nullable=False)
    object_id = Column(String(512), nullable=False)
    statement = Column(JSON, nullable=False)
    statement_hash = Column(String(64), nullable=False, index=True)
    received_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("organization_id", "destination_key", "statement_id", name="uq_local_lrs_statement_id"),
        UniqueConstraint("delivery_id", name="uq_local_lrs_delivery"),
    )


class DBIntegrationDeliveryEvent(Base):
    """Append-only delivery transition and explicit requeue audit record."""
    __tablename__ = "integration_delivery_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("idevt"))
    delivery_id = Column(String(64), ForeignKey("integration_deliveries.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    action = Column(String(32), nullable=False, index=True)
    from_status = Column(String(16), nullable=False)
    to_status = Column(String(16), nullable=False)
    attempt_count = Column(Integer, nullable=False)
    error_code = Column(String(64), default="")
    evidence_snapshot = Column(JSON, nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class DBCmi5Session(Base):
    """Recoverable local cmi5-subset demonstration session."""
    __tablename__ = "cmi5_sessions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("cmi5"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    learner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    registration = Column(String(128), nullable=False)
    launch_key = Column(String(128), nullable=False)
    status = Column(String(24), nullable=False, default="launched", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    launched_at = Column(DateTime, default=_utcnow)
    activated_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    exited_at = Column(DateTime, nullable=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    __table_args__ = (
        UniqueConstraint("organization_id", "launch_key", name="uq_cmi5_launch_key"),
        UniqueConstraint("organization_id", "registration", name="uq_cmi5_registration"),
        CheckConstraint("status IN ('launched','active','completed','exited') AND lock_version >= 1", name="ck_cmi5_session_state"),
    )


class DBCmi5SessionEvent(Base):
    """Immutable state transition evidence for the supported cmi5 subset."""
    __tablename__ = "cmi5_session_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("cmi5evt"))
    session_id = Column(String(64), ForeignKey("cmi5_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    action = Column(String(24), nullable=False)
    from_status = Column(String(24), nullable=False)
    to_status = Column(String(24), nullable=False)
    event_snapshot = Column(JSON, nullable=False)
    event_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class DBLocalWebhookEndpoint(Base):
    """Organization-local signed webhook receiver used only by the competition simulator."""
    __tablename__ = "local_webhook_endpoints"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("whend"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    destination_key = Column(String(128), nullable=False)
    signing_secret = Column(String(128), nullable=False)
    secret_fingerprint = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="active", index=True)
    replay_window_seconds = Column(Integer, nullable=False, default=300)
    lock_version = Column(Integer, nullable=False, default=1)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("organization_id", "destination_key", name="uq_local_webhook_destination"),
        CheckConstraint("status IN ('active','disabled')", name="ck_local_webhook_endpoint_status"),
        CheckConstraint("replay_window_seconds BETWEEN 30 AND 900 AND lock_version >= 1", name="ck_local_webhook_endpoint_limits"),
    )


class DBWebhookEvent(Base):
    """Immutable minimal-field event envelope derived from canonical training facts."""
    __tablename__ = "webhook_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("whevt"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    source_object_type = Column(String(32), nullable=False)
    source_object_id = Column(String(64), nullable=False, index=True)
    schema_version = Column(String(32), nullable=False, default="webhook-envelope-v1")
    payload = Column(JSON, nullable=False)
    payload_hash = Column(String(64), nullable=False, index=True)
    occurred_at = Column(DateTime, nullable=False)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("organization_id", "event_type", "source_object_type", "source_object_id", name="uq_webhook_event_source"),
        CheckConstraint(
            "event_type IN ('training.assignment.created','training.assignment.completed','certification.issued','certification.revoked')",
            name="ck_webhook_event_type",
        ),
    )


class DBWebhookAcceptedNonce(Base):
    """Replay guard committed only after a signed request passes all receiver checks."""
    __tablename__ = "webhook_accepted_nonces"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("whnonce"))
    endpoint_id = Column(String(64), ForeignKey("local_webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(String(64), ForeignKey("webhook_events.id", ondelete="RESTRICT"), nullable=False, index=True)
    nonce = Column(String(128), nullable=False)
    signature_hash = Column(String(64), nullable=False)
    accepted_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("endpoint_id", "nonce", name="uq_webhook_endpoint_nonce"),
        UniqueConstraint("endpoint_id", "event_id", name="uq_webhook_endpoint_event"),
    )


class DBWebhookReceipt(Base):
    """Append-only receiver decision log, including rejected signature and replay attempts."""
    __tablename__ = "webhook_receipts"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("whrcpt"))
    endpoint_id = Column(String(64), ForeignKey("local_webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    delivery_id = Column(String(64), ForeignKey("integration_deliveries.id", ondelete="SET NULL"), nullable=True, index=True)
    event_id = Column(String(64), nullable=False, index=True)
    nonce = Column(String(128), nullable=False)
    timestamp_value = Column(Integer, nullable=False)
    signature_prefix = Column(String(24), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    outcome = Column(String(16), nullable=False, index=True)
    reason_code = Column(String(64), nullable=False)
    received_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        CheckConstraint("outcome IN ('accepted','rejected')", name="ck_webhook_receipt_outcome"),
    )


class DBIntegrationReconciliationRun(Base):
    """Immutable cross-adapter mapping, count and discrepancy snapshot."""
    __tablename__ = "integration_reconciliation_runs"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("recon"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    run_key = Column(String(128), nullable=False)
    schema_version = Column(String(32), nullable=False, default="integration-reconciliation-v1")
    mapping_versions = Column(JSON, nullable=False)
    source_preview = Column(JSON, nullable=False)
    count_snapshot = Column(JSON, nullable=False)
    discrepancies = Column(JSON, nullable=False)
    status = Column(String(24), nullable=False, default="open", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    snapshot_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    closed_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("organization_id", "run_key", name="uq_integration_reconciliation_run_key"),
        CheckConstraint("status IN ('open','resolved') AND lock_version >= 1", name="ck_integration_reconciliation_run_state"),
    )


class DBIntegrationRepairDecision(Base):
    """Append-only administrator decision for one frozen reconciliation discrepancy."""
    __tablename__ = "integration_repair_decisions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("reconfix"))
    run_id = Column(String(64), ForeignKey("integration_reconciliation_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    discrepancy_key = Column(String(160), nullable=False)
    action = Column(String(24), nullable=False)
    actor_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    reason = Column(Text, nullable=False)
    before_snapshot = Column(JSON, nullable=False)
    after_snapshot = Column(JSON, nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("run_id", "discrepancy_key", name="uq_integration_repair_discrepancy"),
        CheckConstraint("action IN ('acknowledge','requeue','dismiss')", name="ck_integration_repair_action"),
    )


class DBIntegrationFaultDrill(Base):
    """Recoverable seven-scenario integration fault drill."""
    __tablename__ = "integration_fault_drills"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ifdrill"))
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    run_key = Column(String(128), nullable=False)
    status = Column(String(24), nullable=False, default="planned", index=True)
    current_scenario = Column(Integer, nullable=False, default=0)
    lock_version = Column(Integer, nullable=False, default=1)
    authority_before_hash = Column(String(64), nullable=False)
    authority_after_hash = Column(String(64), nullable=False)
    scenario_plan = Column(JSON, nullable=False)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("organization_id", "run_key", name="uq_integration_fault_drill_run_key"),
        CheckConstraint("status IN ('planned','running','passed','failed') AND current_scenario >= 0 AND lock_version >= 1", name="ck_integration_fault_drill_state"),
    )


class DBIntegrationFaultDrillStep(Base):
    """Append-only evidence for one executed fault and recovery scenario."""
    __tablename__ = "integration_fault_drill_steps"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ifstep"))
    drill_id = Column(String(64), ForeignKey("integration_fault_drills.id", ondelete="RESTRICT"), nullable=False, index=True)
    organization_id = Column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_index = Column(Integer, nullable=False)
    scenario_key = Column(String(32), nullable=False)
    outcome = Column(String(16), nullable=False)
    fault_code = Column(String(64), nullable=False)
    before_snapshot = Column(JSON, nullable=False)
    after_snapshot = Column(JSON, nullable=False)
    recovery_snapshot = Column(JSON, nullable=False)
    authority_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("drill_id", "scenario_index", name="uq_integration_fault_drill_step"),
        CheckConstraint("outcome IN ('passed','failed') AND scenario_index >= 1", name="ck_integration_fault_drill_step_outcome"),
    )


class DBCompetitionJourneyRun(Base):
    """Owner and course scoped judge journey with evidence-derived progress."""
    __tablename__ = "competition_journey_runs"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("journey"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    journey_type = Column(String(32), nullable=False, index=True)
    run_key = Column(String(128), nullable=False)
    status = Column(String(24), nullable=False, default="active", index=True)
    baseline_snapshot = Column(JSON, nullable=False)
    baseline_hash = Column(String(64), nullable=False)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    completed_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("owner_public_id", "journey_type", "run_key", name="uq_competition_journey_run_key"),
        CheckConstraint("journey_type IN ('student','media','teacher','enterprise','marketplace','integration') AND status IN ('active','completed','abandoned') AND lock_version >= 1", name="ck_competition_journey_run_state"),
    )


class DBCompetitionJourneyVisit(Base):
    """Append-only navigation evidence; never sufficient for step completion."""
    __tablename__ = "competition_journey_visits"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("jvisit"))
    run_id = Column(String(64), ForeignKey("competition_journey_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    step_key = Column(String(32), nullable=False)
    route = Column(String(128), nullable=False)
    evidence_snapshot = Column(JSON, nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (CheckConstraint("step_key IN ('profile','diagnosis','path','resource','lab','formal_exam','retest','path_update','chapter','handout','deck','avatar_audio','video','video_practice','bundle','course','class_group','task','analytics','intervention','content_review','effect_review','job_standard','role_gap','training_cohort','practical','demo_signoff','certification','retraining','submission','review_publish','search','engagement','acquisition','fork','update_notification','withdrawal_impact','sso','hr_lms','xapi_webhook','fault','retry','reconciliation')", name="ck_competition_journey_visit_step"),)


class DBMarketplaceJourneySearchVerification(Base):
    """Immutable proof that the frozen listing was discoverable through real search."""
    __tablename__ = "marketplace_journey_search_verifications"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mktsearchproof"))
    run_id = Column(String(64), ForeignKey("competition_journey_runs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    listing_id = Column(String(64), ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    listing_snapshot_hash = Column(String(64), nullable=False)
    recipient_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False, index=True)
    query = Column(String(256), nullable=False)
    result_snapshot = Column(JSON, nullable=False)
    result_hash = Column(String(64), nullable=False)
    verified_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class DBMemorySubscription(Base):
    __tablename__ = "memory_subscriptions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("msub"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    subscriber_type = Column(String(32), nullable=False, default="tutor", index=True)
    subscriber_key = Column(String(128), nullable=False, default="default")
    profile_fields = Column(JSON, nullable=False, default=list)
    memory_types = Column(JSON, nullable=False, default=list)
    status = Column(String(32), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    last_synced_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoke_reason = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("owner_public_id", "subscriber_type", "subscriber_key", name="uq_memory_subscription_owner_consumer"),
        CheckConstraint("status IN ('active','revoked')", name="ck_memory_subscription_status"),
        CheckConstraint("lock_version >= 1", name="ck_memory_subscription_lock_version"),
    )


class DBModelPriceVersion(Base):
    __tablename__ = "model_price_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mpr"))
    provider = Column(String(64), nullable=False, index=True)
    model = Column(String(128), nullable=False, index=True)
    version = Column(String(64), nullable=False)
    currency = Column(String(8), nullable=False, default="USD")
    input_cost_per_million = Column(Float, nullable=False, default=0.0)
    output_cost_per_million = Column(Float, nullable=False, default=0.0)
    source_url = Column(Text, nullable=False, default="")
    source_label = Column(String(256), nullable=False, default="")
    effective_at = Column(DateTime, nullable=False)
    recorded_at = Column(DateTime, default=_utcnow)
    active = Column(Boolean, nullable=False, default=True, index=True)

    __table_args__ = (
        UniqueConstraint("provider", "model", "version", name="uq_model_price_version"),
        CheckConstraint("input_cost_per_million >= 0 AND output_cost_per_million >= 0", name="ck_model_price_nonnegative"),
    )


class DBWorkerLease(Base):
    __tablename__ = "worker_leases"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("lease"))
    task_id = Column(String(64), ForeignKey("generation_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id = Column(String(128), nullable=False, index=True)
    lease_token = Column(String(64), nullable=False, unique=True)
    status = Column(String(16), nullable=False, default="active", index=True)
    attempt = Column(Integer, nullable=False, default=1)
    leased_at = Column(DateTime, nullable=False, default=_utcnow)
    heartbeat_at = Column(DateTime, nullable=False, default=_utcnow)
    leased_until = Column(DateTime, nullable=False, index=True)
    released_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("task_id", "attempt", name="uq_worker_lease_task_attempt"),
        CheckConstraint("status IN ('active','released','expired','cancelled')", name="ck_worker_lease_status"),
        CheckConstraint("attempt >= 1", name="ck_worker_lease_attempt"),
    )


class DBSpeechSession(Base):
    __tablename__ = "speech_sessions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("speech"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(64), ForeignKey("generation_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(256), nullable=False, default="语音训练记录")
    status = Column(String(32), nullable=False, default="uploaded", index=True)
    language = Column(String(16), nullable=False, default="auto")
    source_sha256 = Column(String(64), nullable=False, index=True)
    source_bytes = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    sample_rate = Column(Integer, nullable=False, default=16000)
    channel_count = Column(Integer, nullable=False, default=1)
    transcript = Column(Text, default="")
    transcript_sha256 = Column(String(64), default="")
    runtime_version = Column(String(64), default="")
    binary_sha256 = Column(String(64), default="")
    model_name = Column(String(128), default="")
    model_sha256 = Column(String(64), default="")
    failure_code = Column(String(64), default="")
    truth_state = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime, default=_utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        CheckConstraint("status IN ('uploaded','queued','processing','completed','failed','cancelled','unavailable')", name="ck_speech_session_status"),
        CheckConstraint("truth_state IN ('pending','real_offline','unavailable','failed','cancelled')", name="ck_speech_truth_state"),
        CheckConstraint("source_bytes >= 0 AND duration_ms >= 0", name="ck_speech_source_nonnegative"),
    )


class DBSpeechSegment(Base):
    __tablename__ = "speech_segments"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("segment"))
    session_id = Column(String(64), ForeignKey("speech_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    segment_index = Column(Integer, nullable=False)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    text_sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("session_id", "segment_index", name="uq_speech_segment_index"),
        CheckConstraint("segment_index >= 0 AND start_ms >= 0 AND end_ms >= start_ms", name="ck_speech_segment_timeline"),
    )


class DBMediaContextResource(Base):
    __tablename__ = "media_context_resources"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mres"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    resource_type = Column(String(16), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    language = Column(String(32), nullable=False, default="")
    locator = Column(String(2048), nullable=False, default="")
    content = Column(Text, nullable=False, default="")
    content_sha256 = Column(String(64), nullable=False, index=True)
    duration_ms = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        CheckConstraint("resource_type IN ('code','video')", name="ck_media_context_resource_type"),
        CheckConstraint("duration_ms >= 0", name="ck_media_context_duration"),
    )


class DBMediaReadingPosition(Base):
    __tablename__ = "media_reading_positions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mpos"))
    resource_id = Column(String(64), ForeignKey("media_context_resources.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    line_number = Column(Integer, nullable=False, default=1)
    column_number = Column(Integer, nullable=False, default=1)
    playback_ms = Column(Integer, nullable=False, default=0)
    scroll_ratio = Column(Float, nullable=False, default=0.0)
    lock_version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        CheckConstraint("line_number >= 1 AND column_number >= 1 AND playback_ms >= 0", name="ck_media_position_nonnegative"),
        CheckConstraint("scroll_ratio >= 0.0 AND scroll_ratio <= 1.0 AND lock_version >= 1", name="ck_media_position_ratio_version"),
    )


class DBMediaConversation(Base):
    __tablename__ = "media_conversations"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mconv"))
    resource_id = Column(String(64), ForeignKey("media_context_resources.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    status = Column(String(16), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    archived_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active','archived') AND lock_version >= 1", name="ck_media_conversation_state"),
    )


class DBMediaMessage(Base):
    __tablename__ = "media_messages"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mmsg"))
    conversation_id = Column(String(64), ForeignKey("media_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    position_snapshot = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_media_message_sequence"),
        CheckConstraint("sequence >= 1 AND role IN ('user','assistant','note')", name="ck_media_message_role_sequence"),
    )


class DBVideoProject(Base):
    __tablename__ = "video_projects"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("vproj"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    status = Column(String(24), nullable=False, default="active", index=True)
    current_script_version_id = Column(String(64), nullable=True, index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        CheckConstraint("status IN ('active','archived') AND lock_version >= 1", name="ck_video_project_state"),
    )


class DBVideoAsset(Base):
    """Owner-scoped imported video identity with an explicit current immutable version."""

    __tablename__ = "video_assets"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("vasset"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    chapter_id = Column(String(64), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    language = Column(String(32), nullable=False, default="")
    source_url = Column(String(2048), nullable=False, default="")
    source_author = Column(String(256), nullable=False, default="")
    license_status = Column(String(64), nullable=False, default="owner_provided")
    license_text = Column(Text, nullable=False, default="")
    status = Column(String(24), nullable=False, default="active", index=True)
    current_version_id = Column(String(64), nullable=True, index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        CheckConstraint("status IN ('active','archived') AND lock_version >= 1", name="ck_video_asset_state"),
    )


class DBVideoAssetVersion(Base):
    """Immutable imported media/subtitle snapshot stored outside the database."""

    __tablename__ = "video_asset_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("vav"))
    asset_id = Column(String(64), ForeignKey("video_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    original_filename = Column(String(256), nullable=False)
    media_format = Column(String(16), nullable=False)
    media_type = Column(String(128), nullable=False)
    file_size = Column(Integer, nullable=False)
    source_sha256 = Column(String(64), nullable=False, index=True)
    stored_path = Column(Text, nullable=False)
    duration_ms = Column(Integer, nullable=False, default=0)
    width = Column(Integer, nullable=False, default=0)
    height = Column(Integer, nullable=False, default=0)
    video_codec = Column(String(64), nullable=False, default="")
    probe_status = Column(String(32), nullable=False, default="unavailable")
    subtitle_filename = Column(String(256), nullable=False, default="")
    subtitle_format = Column(String(16), nullable=False, default="")
    subtitle_sha256 = Column(String(64), nullable=False, default="", index=True)
    subtitle_path = Column(Text, nullable=False, default="")
    subtitle_version = Column(Integer, nullable=False, default=0)
    import_key = Column(String(64), nullable=False, unique=True, index=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("asset_id", "version_number", name="uq_video_asset_version_number"),
        CheckConstraint("version_number >= 1 AND file_size > 0 AND duration_ms >= 0", name="ck_video_asset_version_values"),
        CheckConstraint("subtitle_version >= 0 AND width >= 0 AND height >= 0", name="ck_video_asset_media_values"),
    )


class DBVideoScriptVersion(Base):
    __tablename__ = "video_script_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("vscript"))
    project_id = Column(String(64), ForeignKey("video_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    scenes = Column(JSON, nullable=False)
    total_duration_ms = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("project_id", "version_number", name="uq_video_script_project_version"),
        CheckConstraint("version_number >= 1 AND total_duration_ms > 0", name="ck_video_script_values"),
    )


class DBVideoRenderTask(Base):
    __tablename__ = "video_render_tasks"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("vrender"))
    project_id = Column(String(64), ForeignKey("video_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    script_version_id = Column(String(64), ForeignKey("video_script_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=False)
    status = Column(String(24), nullable=False, default="queued", index=True)
    progress = Column(Integer, nullable=False, default=0)
    attempt = Column(Integer, nullable=False, default=1)
    audio_status = Column(String(32), nullable=False, default="text_only")
    error_code = Column(String(64), default="")
    error_message = Column(Text, default="")
    output_version_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("owner_public_id", "idempotency_key", name="uq_video_render_owner_idempotency"),
        CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_video_render_status"),
        CheckConstraint("progress >= 0 AND progress <= 100 AND attempt >= 1", name="ck_video_render_progress"),
    )


class DBVideoOutputVersion(Base):
    __tablename__ = "video_output_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("vout"))
    project_id = Column(String(64), ForeignKey("video_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    render_task_id = Column(String(64), ForeignKey("video_render_tasks.id", ondelete="RESTRICT"), nullable=False, unique=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    output_manifest = Column(JSON, nullable=False)
    output_dir = Column(Text, nullable=False)
    mp4_sha256 = Column(String(64), nullable=False)
    duration_ms = Column(Integer, nullable=False)
    quality_report = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("project_id", "version_number", name="uq_video_output_project_version"),
        CheckConstraint("version_number >= 1 AND duration_ms > 0", name="ck_video_output_values"),
    )


class DBWrongQuestionVideoLink(Base):
    """Immutable snapshot linking a governed explanation video to its source mistake."""

    __tablename__ = "wrong_question_video_links"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("wqvideo"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), nullable=False, index=True)
    wrong_question_id = Column(Integer, ForeignKey("wrong_questions.id", ondelete="SET NULL"), nullable=True, index=True)
    source_wrong_question_id = Column(Integer, nullable=False)
    quiz_record_id = Column(String(64), ForeignKey("quiz_records.id", ondelete="SET NULL"), nullable=True, index=True)
    review_plan_id = Column(Integer, ForeignKey("review_plans.id", ondelete="SET NULL"), nullable=True, index=True)
    video_project_id = Column(String(64), ForeignKey("video_projects.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    input_hash = Column(String(64), nullable=False, index=True)
    evidence_refs = Column(JSON, nullable=False, default=list)
    snapshot_json = Column(JSON, nullable=False, default=dict)
    truth_boundary = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "owner_public_id", "student_id", "source_wrong_question_id", "input_hash",
            name="uq_wrong_question_video_input",
        ),
        CheckConstraint("source_wrong_question_id >= 1", name="ck_wrong_question_video_source_id"),
    )


class DBChapterVideoLink(Base):
    """Immutable course evidence and personalization snapshot behind a chapter video."""

    __tablename__ = "chapter_video_links"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("chvideo"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    chapter_id = Column(String(64), ForeignKey("chapters.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_snapshot_id = Column(String(64), ForeignKey("profile_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    video_project_id = Column(String(64), ForeignKey("video_projects.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    input_hash = Column(String(64), nullable=False, index=True)
    source_ref_ids = Column(JSON, nullable=False, default=list)
    knowledge_point_ids = Column(JSON, nullable=False, default=list)
    learning_objectives = Column(JSON, nullable=False, default=list)
    personalization_snapshot = Column(JSON, nullable=False, default=dict)
    source_snapshot = Column(JSON, nullable=False, default=list)
    quality_snapshot = Column(JSON, nullable=False, default=dict)
    truth_boundary = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "owner_public_id", "course_id", "chapter_id", "input_hash",
            name="uq_chapter_video_input",
        ),
    )


class DBVideoPracticeSet(Base):
    """Owner-scoped practice identity attached to one immutable chapter-video link."""

    __tablename__ = "video_practice_sets"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("vpset"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_video_link_id = Column(String(64), ForeignKey("chapter_video_links.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    current_version_id = Column(String(64), nullable=True, index=True)
    status = Column(String(24), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        CheckConstraint("status IN ('active','archived') AND lock_version >= 1", name="ck_video_practice_set_state"),
    )


class DBVideoPracticeVersion(Base):
    """Immutable ordered question-version binding for a video practice set."""

    __tablename__ = "video_practice_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("vpver"))
    practice_set_id = Column(String(64), ForeignKey("video_practice_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    question_version_ids = Column(JSON, nullable=False, default=list)
    interactive_lab_instance_ids = Column(JSON, nullable=False, default=list)
    binding_snapshot = Column(JSON, nullable=False, default=list)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("practice_set_id", "version_number", name="uq_video_practice_set_version"),
        CheckConstraint("version_number >= 1", name="ck_video_practice_version_number"),
    )


class DBVideoWatchProgress(Base):
    """Mutable viewing progress that is explicitly weak evidence only."""

    __tablename__ = "video_watch_progress"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("vwatch"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_video_link_id = Column(String(64), ForeignKey("chapter_video_links.id", ondelete="CASCADE"), nullable=False, index=True)
    watched_seconds = Column(Float, nullable=False, default=0.0)
    duration_seconds = Column(Float, nullable=False, default=0.0)
    completed = Column(Boolean, nullable=False, default=False, index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("owner_public_id", "chapter_video_link_id", name="uq_video_watch_owner_link"),
        CheckConstraint("watched_seconds >= 0 AND duration_seconds >= 0 AND lock_version >= 1", name="ck_video_watch_values"),
    )


class DBVideoPracticeAttemptLink(Base):
    """Immutable strong-evidence backlink from a graded assessment attempt to a video."""

    __tablename__ = "video_practice_attempt_links"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("vpat"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_video_link_id = Column(String(64), ForeignKey("chapter_video_links.id", ondelete="CASCADE"), nullable=False, index=True)
    practice_version_id = Column(String(64), ForeignKey("video_practice_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    assessment_attempt_id = Column(String(64), ForeignKey("assessment_attempts.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    grading_result_id = Column(String(64), ForeignKey("assessment_grading_results.id", ondelete="RESTRICT"), nullable=False, index=True)
    learning_event_id = Column(String(64), ForeignKey("learning_events.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    evidence_snapshot = Column(JSON, nullable=False, default=dict)
    next_action = Column(String(32), nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        CheckConstraint("next_action IN ('proceed','review_and_retry','await_review')", name="ck_video_practice_next_action"),
    )


class DBVideoPracticeLabLink(Base):
    """Immutable strong-evidence backlink from a passed interactive lab to a video."""

    __tablename__ = "video_practice_lab_links"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("vplab"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_video_link_id = Column(String(64), ForeignKey("chapter_video_links.id", ondelete="CASCADE"), nullable=False, index=True)
    practice_version_id = Column(String(64), ForeignKey("video_practice_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    lab_instance_id = Column(String(64), ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, index=True)
    lab_version_id = Column(String(64), ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    learning_event_id = Column(String(64), ForeignKey("learning_events.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    evidence_snapshot = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow)


class DBTeachingAnimation(Base):
    """Owner-scoped teaching animation project with recoverable playback state."""

    __tablename__ = "teaching_animations"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("tanim"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    template_id = Column(String(64), nullable=False, index=True)
    current_version_id = Column(String(64), nullable=True, index=True)
    current_frame = Column(Integer, nullable=False, default=0)
    playback_status = Column(String(16), nullable=False, default="paused", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        CheckConstraint("current_frame >= 0 AND lock_version >= 1", name="ck_teaching_animation_position"),
        CheckConstraint("playback_status IN ('playing','paused')", name="ck_teaching_animation_playback"),
    )


class DBTeachingAnimationVersion(Base):
    """Immutable server-computed parameters, formula and frame sequence."""

    __tablename__ = "teaching_animation_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("tanver"))
    animation_id = Column(String(64), ForeignKey("teaching_animations.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    parameters = Column(JSON, nullable=False, default=dict)
    frame_data = Column(JSON, nullable=False, default=list)
    formula_snapshot = Column(JSON, nullable=False, default=dict)
    quality_snapshot = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("animation_id", "version_number", name="uq_teaching_animation_version"),
        UniqueConstraint("animation_id", "content_hash", name="uq_teaching_animation_content"),
        CheckConstraint("version_number >= 1", name="ck_teaching_animation_version_number"),
    )


class DBWebDeck(Base):
    """Owner-scoped browser presentation with one current immutable version."""

    __tablename__ = "web_decks"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("deck"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    theme_id = Column(String(64), nullable=False, default="evidence-light-v1")
    current_version_id = Column(String(64), nullable=True, index=True)
    current_slide = Column(Integer, nullable=False, default=0)
    playback_status = Column(String(16), nullable=False, default="stopped")
    status = Column(String(24), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        CheckConstraint("current_slide >= 0 AND lock_version >= 1", name="ck_web_deck_position"),
        CheckConstraint("playback_status IN ('playing','stopped')", name="ck_web_deck_playback"),
        CheckConstraint("status IN ('active','archived')", name="ck_web_deck_status"),
    )


class DBWebSlide(Base):
    """Stable slide identity retained across immutable deck versions and reorders."""

    __tablename__ = "web_slides"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("slide"))
    deck_id = Column(String(64), ForeignKey("web_decks.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_key = Column(String(64), nullable=False)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("deck_id", "stable_key", name="uq_web_slide_stable_key"),
    )


class DBWebDeckVersion(Base):
    """Immutable ordered slide content, notes and export contract snapshot."""

    __tablename__ = "web_deck_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("deckver"))
    deck_id = Column(String(64), ForeignKey("web_decks.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    slides_snapshot = Column(JSON, nullable=False, default=list)
    theme_snapshot = Column(JSON, nullable=False, default=dict)
    source_version_id = Column(String(64), ForeignKey("web_deck_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    change_summary = Column(String(256), nullable=False, default="")
    content_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("deck_id", "version_number", name="uq_web_deck_version"),
        UniqueConstraint("deck_id", "content_hash", name="uq_web_deck_content"),
        CheckConstraint("version_number >= 1", name="ck_web_deck_version_number"),
    )


class DBLocalAdapterSession(Base):
    """Owner-scoped session connected only to a deterministic local simulator."""

    __tablename__ = "local_adapter_sessions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("las"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    adapter_id = Column(String(64), nullable=False, index=True)
    environment = Column(String(32), nullable=False, default="local_simulation")
    credential_placeholder = Column(String(128), nullable=False)
    status = Column(String(24), nullable=False, default="disconnected", index=True)
    parameters = Column(JSON, nullable=False, default=dict)
    metrics = Column(JSON, nullable=False, default=dict)
    active_fault = Column(String(32), nullable=False, default="none")
    diagnosis = Column(Text, nullable=False, default="")
    recovery_action = Column(String(64), nullable=False, default="")
    recovery_verified = Column(Boolean, nullable=False, default=False)
    hidden_acceptance = Column(JSON, nullable=False, default=dict)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        CheckConstraint("environment = 'local_simulation' AND lock_version >= 1", name="ck_local_adapter_environment"),
        CheckConstraint("status IN ('disconnected','connected','running','failed','diagnosed','recovered','passed')", name="ck_local_adapter_status"),
        CheckConstraint("active_fault IN ('none','sensor_timeout','quality_drift','queue_backpressure')", name="ck_local_adapter_fault"),
    )


class DBLocalAdapterEvent(Base):
    """Immutable action and state-transition evidence for a local adapter session."""

    __tablename__ = "local_adapter_events"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("laevt"))
    session_id = Column(String(64), ForeignKey("local_adapter_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=False)
    action = Column(String(32), nullable=False, index=True)
    from_status = Column(String(24), nullable=False)
    to_status = Column(String(24), nullable=False)
    request_hash = Column(String(64), nullable=False)
    snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("owner_public_id", "idempotency_key", name="uq_local_adapter_event_idempotency"),)


class DBResourceBundle(Base):
    """Owner-scoped learning objective that points to one immutable bundle version."""

    __tablename__ = "resource_bundles"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("bundle"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    knowledge_point_id = Column(String(64), ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    learning_objective = Column(Text, nullable=False)
    current_version_id = Column(String(64), nullable=True, index=True)
    status = Column(String(24), nullable=False, default="active", index=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        CheckConstraint("status IN ('active','archived') AND lock_version >= 1", name="ck_resource_bundle_state"),
    )


class DBResourceBundleVersion(Base):
    """Immutable ordered bundle composition and audience/quality summary."""

    __tablename__ = "resource_bundle_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("bundlever"))
    bundle_id = Column(String(64), ForeignKey("resource_bundles.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    profile_snapshot = Column(JSON, nullable=False, default=dict)
    quality_summary = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False, index=True)
    change_summary = Column(String(256), nullable=False, default="")
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("bundle_id", "version_number", name="uq_resource_bundle_version"),
        UniqueConstraint("bundle_id", "content_hash", name="uq_resource_bundle_content"),
        CheckConstraint("version_number >= 1", name="ck_resource_bundle_version_number"),
    )


class DBResourceBundleItem(Base):
    """Immutable typed reference with a server-resolved evidence snapshot."""

    __tablename__ = "resource_bundle_items"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("bundleitem"))
    bundle_version_id = Column(String(64), ForeignKey("resource_bundle_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    resource_type = Column(String(24), nullable=False, index=True)
    resource_id = Column(String(64), nullable=False, index=True)
    resource_version_id = Column(String(64), nullable=False, index=True)
    frozen_snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("bundle_version_id", "position", name="uq_resource_bundle_item_position"),
        UniqueConstraint("bundle_version_id", "resource_type", name="uq_resource_bundle_item_type"),
        CheckConstraint("position >= 0", name="ck_resource_bundle_item_position"),
        CheckConstraint("resource_type IN ('handout','mind_map','code','exercise','video','ppt','animation','lab')", name="ck_resource_bundle_item_type"),
    )


class DBAssessmentQuestionVersion(Base):
    __tablename__ = "assessment_question_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("aqv"))
    question_id = Column(String(64), ForeignKey("assessment_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    prompt = Column(Text, nullable=False)
    options = Column(JSON, default=list)
    answer_key = Column(JSON, nullable=False, default=dict)
    scoring_rule = Column(JSON, nullable=False, default=dict)
    explanation = Column(Text, default="")
    misconception_tags = Column(JSON, default=list)
    primary_knowledge_point_id = Column(String(64), ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True, index=True)
    secondary_knowledge_point_ids = Column(JSON, default=list)
    bloom_level = Column(String(32), nullable=False, default="understand")
    expert_difficulty = Column(Float, nullable=True)
    measured_difficulty = Column(Float, nullable=True)
    irt_parameters = Column(JSON, default=dict)
    sample_size = Column(Integer, nullable=False, default=0)
    source_ref_ids = Column(JSON, default=list)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("question_id", "version_number", name="uq_assessment_question_version"),
        CheckConstraint("sample_size >= 0", name="ck_assessment_question_sample_size"),
        CheckConstraint("bloom_level IN ('remember','understand','apply','analyze','evaluate','create')", name="ck_assessment_question_bloom"),
    )


class DBAssessmentAttempt(Base):
    __tablename__ = "assessment_attempts"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("aat"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    question_version_id = Column(String(64), ForeignKey("assessment_question_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=False)
    mode = Column(String(32), nullable=False, default="practice", index=True)
    answer = Column(JSON, nullable=False, default=dict)
    # Subjective attempts are created before the live grader returns.  A
    # nullable score keeps that pending state distinct from a real zero.
    score = Column(Float, nullable=True, default=None)
    correct = Column(Boolean, nullable=True)
    confidence = Column(Float, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    grading_status = Column(String(32), nullable=False, default="graded", index=True)
    feedback_policy = Column(String(32), nullable=False, default="immediate")
    submitted_at = Column(DateTime, default=_utcnow, index=True)
    __table_args__ = (
        UniqueConstraint("owner_public_id", "idempotency_key", name="uq_assessment_attempt_idempotency"),
        CheckConstraint("mode IN ('practice','diagnostic','formal','retest')", name="ck_assessment_attempt_mode"),
        CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_assessment_attempt_score"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)", name="ck_assessment_attempt_confidence"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_assessment_attempt_duration"),
        CheckConstraint("grading_status IN ('pending','graded','manual_required','invalid')", name="ck_assessment_attempt_grading"),
        CheckConstraint("feedback_policy IN ('immediate','after_submission','after_close','teacher_only')", name="ck_assessment_feedback_policy"),
    )


class DBAssessmentGradingResult(Base):
    """Immutable grading evidence attached to an immutable learner attempt."""
    __tablename__ = "assessment_grading_results"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("agr"))
    attempt_id = Column(String(64), ForeignKey("assessment_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    grader_type = Column(String(32), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="completed", index=True)
    rubric_version = Column(String(64), nullable=False, default="deterministic-v1")
    rubric_snapshot = Column(JSON, nullable=False, default=dict)
    criterion_results = Column(JSON, nullable=False, default=list)
    score = Column(Float, nullable=True)
    correct = Column(Boolean, nullable=True)
    confidence = Column(Float, nullable=True)
    evidence = Column(JSON, nullable=False, default=dict)
    feedback = Column(Text, default="")
    improvement_advice = Column(JSON, nullable=False, default=list)
    trace_id = Column(String(64), nullable=False, default="", index=True)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("attempt_id", "grader_type", "rubric_version", name="uq_assessment_grade_attempt_rubric"),
        CheckConstraint("grader_type IN ('deterministic','ai','code','human')", name="ck_assessment_grade_type"),
        CheckConstraint("status IN ('completed','failed','needs_review')", name="ck_assessment_grade_status"),
        CheckConstraint("score IS NULL OR (score >= 0.0 AND score <= 1.0)", name="ck_assessment_grade_score"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)", name="ck_assessment_grade_confidence"),
    )


class DBAssessmentAbilityState(Base):
    """Canonical owner/course MIRT state with optimistic concurrency."""
    __tablename__ = "assessment_ability_states"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("abs"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_scope = Column(String(128), nullable=False, default="__global__", index=True)
    theta = Column(JSON, nullable=False, default=lambda: [0.0, 0.0, 0.0])
    theta_std = Column(JSON, nullable=False, default=lambda: [1.0, 1.0, 1.0])
    theta_cov = Column(JSON, nullable=False, default=list)
    response_count = Column(Integer, nullable=False, default=0)
    lock_version = Column(Integer, nullable=False, default=1)
    last_attempt_id = Column(String(64), ForeignKey("assessment_attempts.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("owner_public_id", "course_scope", name="uq_assessment_ability_owner_course"),
        CheckConstraint("response_count >= 0 AND lock_version >= 1", name="ck_assessment_ability_versions"),
    )


class DBAssessmentSelectionTrace(Base):
    """Immutable CAT candidate and selection evidence."""
    __tablename__ = "assessment_selection_traces"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("ast"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_scope = Column(String(128), nullable=False, default="__global__", index=True)
    selected_question_version_id = Column(String(64), ForeignKey("assessment_question_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    algorithm_version = Column(String(64), nullable=False, default="mirt-d-optimal-v1")
    ability_before = Column(JSON, nullable=False, default=dict)
    candidate_metrics = Column(JSON, nullable=False, default=list)
    excluded_version_ids = Column(JSON, nullable=False, default=list)
    trace_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow)


class DBDiagnosticBlueprint(Base):
    """Owner-scoped, versioned selection of approved questions for one entry diagnostic."""

    __tablename__ = "diagnostic_blueprints"

    id = Column(String(64), primary_key=True, default=lambda: new_public_id("diagbp"))
    owner_public_id = Column(
        String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True,
    )
    course_id = Column(
        String(128), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    idempotency_key = Column(String(128), nullable=False)
    version_number = Column(Integer, nullable=False, default=1)
    status = Column(String(24), nullable=False, default="ready", index=True)
    profile_snapshot_id = Column(
        String(64), ForeignKey("profile_snapshots.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    question_version_ids = Column(JSON, nullable=False, default=list)
    knowledge_point_coverage = Column(JSON, nullable=False, default=list)
    difficulty_bands = Column(JSON, nullable=False, default=dict)
    source_refs = Column(JSON, nullable=False, default=list)
    review_decision = Column(JSON, nullable=False, default=dict)
    generation_stages = Column(JSON, nullable=False, default=list)
    question_count = Column(Integer, nullable=False)
    estimated_minutes = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "owner_public_id", "course_id", "idempotency_key",
            name="uq_diagnostic_blueprint_owner_course_key",
        ),
        CheckConstraint(
            "status IN ('ready','insufficient_sources','failed')",
            name="ck_diagnostic_blueprint_status",
        ),
        CheckConstraint(
            "version_number >= 1 AND question_count >= 1 AND estimated_minutes >= 1",
            name="ck_diagnostic_blueprint_counts",
        ),
    )


class DBDiagnosticSession(Base):
    """Owner-scoped mutable work session for one frozen diagnostic blueprint."""

    __tablename__ = "diagnostic_sessions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("diagsess"))
    owner_public_id = Column(
        String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True,
    )
    blueprint_id = Column(
        String(64), ForeignKey("diagnostic_blueprints.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    status = Column(String(24), nullable=False, default="active", index=True)
    current_question_version_id = Column(
        String(64), ForeignKey("assessment_question_versions.id", ondelete="RESTRICT"), nullable=False,
    )
    submission_idempotency_key = Column(String(128), nullable=True)
    started_at = Column(DateTime, default=_utcnow)
    last_saved_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("owner_public_id", "blueprint_id", name="uq_diagnostic_session_owner_blueprint"),
        CheckConstraint("status IN ('active','submitted')", name="ck_diagnostic_session_status"),
    )


class DBDiagnosticResponseDraft(Base):
    """Latest recoverable learner input for one question in a diagnostic session."""

    __tablename__ = "diagnostic_response_drafts"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("diagresp"))
    session_id = Column(
        String(64), ForeignKey("diagnostic_sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    owner_public_id = Column(
        String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True,
    )
    question_version_id = Column(
        String(64), ForeignKey("assessment_question_versions.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    answer = Column(JSON, nullable=False, default=dict)
    understanding_level = Column(String(24), nullable=True)
    confidence = Column(Float, nullable=True)
    duration_seconds = Column(Integer, nullable=False, default=0)
    idempotency_key = Column(String(128), nullable=False)
    client_saved_at = Column(DateTime, nullable=False)
    saved_at = Column(DateTime, default=_utcnow, index=True)
    __table_args__ = (
        UniqueConstraint("session_id", "question_version_id", name="uq_diagnostic_response_session_question"),
        UniqueConstraint("owner_public_id", "idempotency_key", name="uq_diagnostic_response_owner_key"),
        CheckConstraint(
            "understanding_level IS NULL OR understanding_level IN ('unfamiliar','partial','mostly','clear')",
            name="ck_diagnostic_response_understanding",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_diagnostic_response_confidence",
        ),
        CheckConstraint("duration_seconds >= 0", name="ck_diagnostic_response_duration"),
    )


class DBDiagnosticReport(Base):
    """Immutable diagnostic conclusion built from one submitted session."""

    __tablename__ = "diagnostic_reports"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("diagreport"))
    session_id = Column(
        String(64), ForeignKey("diagnostic_sessions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True,
    )
    owner_public_id = Column(
        String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True,
    )
    course_id = Column(
        String(128), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    idempotency_key = Column(String(128), nullable=False)
    report_version = Column(String(64), nullable=False, default="f3.diagnostic-report.v1")
    attempt_ids = Column(JSON, nullable=False, default=list)
    profile_snapshot_id = Column(
        String(64), ForeignKey("profile_snapshots.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    report_data = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("owner_public_id", "idempotency_key", name="uq_diagnostic_report_owner_key"),
    )


class DBAssessmentExam(Base):
    """Formal exam identity and mutable release lifecycle."""
    __tablename__ = "assessment_exams"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("aex"))
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    generation_key = Column(String(128), nullable=True)
    title = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="draft", index=True)
    current_version_id = Column(String(64), nullable=True, index=True)
    scheduled_open_at = Column(DateTime, nullable=True)
    scheduled_close_at = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=False, default=60)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("owner_public_id", "generation_key", name="uq_assessment_exam_owner_generation"),
        CheckConstraint("status IN ('draft','published','open','closed','archived')", name="ck_assessment_exam_status"),
        CheckConstraint("duration_minutes >= 1 AND lock_version >= 1", name="ck_assessment_exam_versions"),
    )


class DBAssessmentExamVersion(Base):
    """Immutable formal exam instructions and scoring policy."""
    __tablename__ = "assessment_exam_versions"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("aev"))
    exam_id = Column(String(64), ForeignKey("assessment_exams.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    instructions = Column(Text, default="")
    feedback_policy = Column(String(32), nullable=False, default="after_close")
    total_points = Column(Float, nullable=False)
    manifest_hash = Column(String(64), nullable=False, index=True)
    configuration = Column(JSON, nullable=False, default=dict)
    generation_context = Column(JSON, nullable=False, default=dict)
    coverage = Column(JSON, nullable=False, default=dict)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("exam_id", "version_number", name="uq_assessment_exam_version"),
        CheckConstraint("version_number >= 1 AND total_points > 0", name="ck_assessment_exam_version_values"),
        CheckConstraint("feedback_policy IN ('after_submission','after_close','teacher_only')", name="ck_assessment_exam_feedback_policy"),
    )


class DBAssessmentExamItem(Base):
    """Immutable ordered link to an exact canonical question version."""
    __tablename__ = "assessment_exam_items"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("aei"))
    exam_version_id = Column(String(64), ForeignKey("assessment_exam_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    question_version_id = Column(String(64), ForeignKey("assessment_question_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    points = Column(Float, nullable=False)
    required = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("exam_version_id", "position", name="uq_assessment_exam_item_position"),
        UniqueConstraint("exam_version_id", "question_version_id", name="uq_assessment_exam_item_question"),
        CheckConstraint("position >= 1 AND points > 0", name="ck_assessment_exam_item_values"),
    )


class DBAssessmentExamSitting(Base):
    """Owner-bound recoverable formal exam sitting."""
    __tablename__ = "assessment_exam_sittings"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("aes"))
    exam_id = Column(String(64), ForeignKey("assessment_exams.id", ondelete="RESTRICT"), nullable=False, index=True)
    exam_version_id = Column(String(64), ForeignKey("assessment_exam_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="assigned", index=True)
    started_at = Column(DateTime, nullable=True)
    due_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("exam_id", "owner_public_id", name="uq_assessment_exam_sitting_owner"),
        CheckConstraint("status IN ('assigned','in_progress','submitted','released','cancelled')", name="ck_assessment_exam_sitting_status"),
        CheckConstraint("lock_version >= 1", name="ck_assessment_exam_sitting_lock"),
    )


class DBAssessmentExamResponse(Base):
    """Immutable link from one sitting item to one canonical formal attempt."""
    __tablename__ = "assessment_exam_responses"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("aer"))
    sitting_id = Column(String(64), ForeignKey("assessment_exam_sittings.id", ondelete="CASCADE"), nullable=False, index=True)
    exam_item_id = Column(String(64), ForeignKey("assessment_exam_items.id", ondelete="RESTRICT"), nullable=False, index=True)
    attempt_id = Column(String(64), ForeignKey("assessment_attempts.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("sitting_id", "exam_item_id", name="uq_assessment_exam_response_item"),)


class DBAssessmentExamResponseDraft(Base):
    """Immutable learner save for one formal-exam item before final submission."""

    __tablename__ = "assessment_exam_response_drafts"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("aed"))
    sitting_id = Column(String(64), ForeignKey("assessment_exam_sittings.id", ondelete="CASCADE"), nullable=False, index=True)
    exam_item_id = Column(String(64), ForeignKey("assessment_exam_items.id", ondelete="RESTRICT"), nullable=False, index=True)
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=False)
    revision = Column(Integer, nullable=False)
    answer = Column(JSON, nullable=False, default=dict)
    confidence = Column(Float, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    content_hash = Column(String(64), nullable=False, index=True)
    saved_at = Column(DateTime, default=_utcnow, index=True)
    __table_args__ = (
        UniqueConstraint("owner_public_id", "idempotency_key", name="uq_exam_response_draft_owner_key"),
        UniqueConstraint("sitting_id", "exam_item_id", "revision", name="uq_exam_response_draft_revision"),
        CheckConstraint("revision >= 1", name="ck_exam_response_draft_revision"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)", name="ck_exam_response_draft_confidence"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_exam_response_draft_duration"),
    )


class DBAssessmentReviewCase(Base):
    """Optional human-review workflow; completed grading remains append-only evidence."""
    __tablename__ = "assessment_review_cases"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("arc"))
    sitting_id = Column(String(64), ForeignKey("assessment_exam_sittings.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_id = Column(String(64), ForeignKey("assessment_attempts.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    reviewer_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="requested", index=True)
    reason = Column(Text, default="")
    decision_note = Column(Text, default="")
    human_grading_result_id = Column(String(64), ForeignKey("assessment_grading_results.id", ondelete="RESTRICT"), nullable=True)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow)
    decided_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("sitting_id", "attempt_id", name="uq_assessment_review_case_attempt"),
        CheckConstraint("status IN ('requested','assigned','completed','rejected','cancelled')", name="ck_assessment_review_case_status"),
        CheckConstraint("lock_version >= 1", name="ck_assessment_review_case_lock"),
    )


class DBAssessmentExamReport(Base):
    """Immutable versioned report snapshot and export authority."""
    __tablename__ = "assessment_exam_reports"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("arep"))
    sitting_id = Column(String(64), ForeignKey("assessment_exam_sittings.id", ondelete="CASCADE"), nullable=False, index=True)
    report_version = Column(Integer, nullable=False, default=1)
    report_data = Column(JSON, nullable=False)
    input_hash = Column(String(64), nullable=False, index=True)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("sitting_id", "report_version", name="uq_assessment_exam_report_version"),
        UniqueConstraint("sitting_id", "input_hash", name="uq_assessment_exam_report_input"),
        CheckConstraint("report_version >= 1", name="ck_assessment_exam_report_version"),
    )


class DBMisconceptionReview(Base):
    __tablename__ = "misconception_reviews"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mis"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_id = Column(String(64), ForeignKey("assessment_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_category = Column(String(64), nullable=False)
    candidate_rationale = Column(Text, default="")
    evidence = Column(JSON, default=dict)
    model_confidence = Column(Float, nullable=True)
    status = Column(String(32), nullable=False, default="proposed", index=True)
    confirmed_category = Column(String(64), default="")
    decision_note = Column(Text, default="")
    decided_by_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("attempt_id", name="uq_misconception_attempt"),
        CheckConstraint("status IN ('proposed','accepted','modified','rejected','teacher_confirmed')", name="ck_misconception_status"),
        CheckConstraint("model_confidence IS NULL OR (model_confidence >= 0.0 AND model_confidence <= 1.0)", name="ck_misconception_confidence"),
    )


class DBAssessmentRetestTask(Base):
    """A delayed retest scheduled only after a misconception is confirmed."""
    __tablename__ = "assessment_retest_tasks"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("rtt"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    misconception_review_id = Column(String(64), ForeignKey("misconception_reviews.id", ondelete="CASCADE"), nullable=False, unique=True)
    source_attempt_id = Column(String(64), ForeignKey("assessment_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    question_version_id = Column(String(64), ForeignKey("assessment_question_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    due_at = Column(DateTime, nullable=False, index=True)
    status = Column(String(32), nullable=False, default="scheduled", index=True)
    completion_attempt_id = Column(String(64), ForeignKey("assessment_attempts.id", ondelete="SET NULL"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        CheckConstraint("status IN ('scheduled','due','completed','cancelled')", name="ck_assessment_retest_status"),
    )

class DBWebSearchHistory(Base):
    """持久化物理表：存储联网搜索与文档加载记录"""
    __tablename__ = "web_search_history"

    id = Column(String(64), primary_key=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), index=True)
    query = Column(String(512))
    source_type = Column(String(32))  # web_search / url_load
    source_url = Column(Text, default="")
    title = Column(String(256), default="")
    content_preview = Column(Text, default="")
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)

    student_profile = relationship("DBStudentProfile", back_populates="web_search_history")

class DBCodeExecution(Base):
    """持久化物理表：存储代码执行记录"""
    __tablename__ = "code_executions"

    id = Column(String(64), primary_key=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), index=True)
    code = Column(Text)
    language = Column(String(32), default="python")
    output = Column(Text, default="")
    error = Column(Text, default="")
    execution_time_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)

    student_profile = relationship("DBStudentProfile", back_populates="code_executions")

class DBWrongQuestion(Base):
    """持久化物理表：存储错题记录 (Task 6.2)"""
    __tablename__ = "wrong_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), index=True)
    quiz_record_id = Column(String(64), ForeignKey("quiz_records.id", ondelete="CASCADE"), nullable=True)
    source_event_id = Column(
        String(64),
        ForeignKey("learning_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_object_id = Column(String(64), nullable=True, index=True)
    concept_name = Column(String(128), index=True)
    wrong_reason_category = Column(String(128), nullable=True)
    pinned = Column(Boolean, default=False, index=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    student_profile = relationship("DBStudentProfile", back_populates="wrong_questions")
    quiz_record = relationship("DBQuizRecord")

    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "source_object_id",
            name="uq_wrong_question_student_question_version",
        ),
    )


class DBCheckinLog(Base):
    """持久化物理表：复习打卡日志 (Task 7.4)"""
    __tablename__ = "checkin_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(64), ForeignKey("student_profiles.student_id", ondelete="CASCADE"), index=True)
    checkin_date = Column(DateTime, default=_utcnow)
    duration_minutes = Column(Integer, default=10)
    concepts_reviewed = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)

    student_profile = relationship("DBStudentProfile", back_populates="checkin_logs")


class DBArxivCache(Base):
    """持久化物理表：arXiv 学术检索本地缓存 (Task 2.4)"""
    __tablename__ = "arxiv_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_hash = Column(String(64), index=True, nullable=False)
    arxiv_id = Column(String(64))
    title = Column(String(512))
    authors = Column(String(1024), default="")
    abstract = Column(Text, default="")
    pdf_url = Column(String(512), default="")
    published_at = Column(DateTime)
    cached_at = Column(DateTime, default=_utcnow)


class DBConceptCoordinate(Base):
    """持久化物理表：存储概念在庞加莱圆盘中的2D投影坐标缓存 (MDS 投影缓存)"""
    __tablename__ = "concept_coordinates"

    concept_name = Column(String(128), primary_key=True, index=True)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# 物理并网：自动创建所有本地 SQLite 数据库表
def init_db():
    Base.metadata.create_all(bind=engine)
    # 增量迁移：为新添加的列做兼容
    _migrate_schema()
    from app.migrations import apply_registered_migrations
    apply_registered_migrations(engine)

def _migrate_schema():
    """SQLite 增量迁移：添加新列（如存在则跳过）"""
    import sqlalchemy as sa
    inspector = sa.inspect(engine)
    columns = [c["name"] for c in inspector.get_columns("users")]
    if "public_id" not in columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE users ADD COLUMN public_id VARCHAR(64)"))
            conn.commit()
        columns = [c["name"] for c in sa.inspect(engine).get_columns("users")]
    # SQLite requires the parent key's unique index before validating a child
    # foreign key. Create it before backfilling legacy rows.
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_public_id ON users(public_id)"))
        # Backfill legacy users once. Values are generated by the server, never
        # from a request or a predictable username.
        legacy_users = conn.execute(sa.text("SELECT id FROM users WHERE public_id IS NULL OR public_id = ''")).fetchall()
        for (user_id,) in legacy_users:
            conn.execute(
                sa.text("UPDATE users SET public_id = :public_id WHERE id = :user_id"),
                {"public_id": new_public_id("usr"), "user_id": user_id},
            )
    if "role" not in columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE users ADD COLUMN role VARCHAR(16) DEFAULT 'student'"))
            conn.commit()
    if "display_name" not in columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE users ADD COLUMN display_name VARCHAR(64) DEFAULT ''"))
            conn.commit()

    course_columns = [c["name"] for c in inspector.get_columns("courses")]
    if "subject" not in course_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE courses ADD COLUMN subject VARCHAR(128) DEFAULT ''"))
            conn.commit()
    if "owner_public_id" not in course_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE courses ADD COLUMN owner_public_id VARCHAR(64)"))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_courses_owner_public_id ON courses(owner_public_id)"))
            conn.commit()

    artifact_columns = [c["name"] for c in inspector.get_columns("artifacts")] if inspector.has_table("artifacts") else []
    if artifact_columns and "lock_version" not in artifact_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE artifacts ADD COLUMN lock_version INTEGER NOT NULL DEFAULT 1"))
            conn.commit()
    if artifact_columns and "archived_at" not in artifact_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE artifacts ADD COLUMN archived_at DATETIME"))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_artifacts_archived_at ON artifacts(archived_at)"))
            conn.commit()

    competency_columns = [c["name"] for c in inspector.get_columns("competency_standards")] if inspector.has_table("competency_standards") else []
    if competency_columns and "version" not in competency_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE competency_standards ADD COLUMN version VARCHAR(64) NOT NULL DEFAULT '1'"))
            conn.commit()
            
    profile_columns = [c["name"] for c in inspector.get_columns("student_profiles")]
    if "narrative_report" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN narrative_report TEXT DEFAULT ''"))
            conn.commit()
    if "motivation_type" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN motivation_type VARCHAR(64) DEFAULT '未诊断'"))
            conn.commit()
    if "frustration_index" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN frustration_index FLOAT DEFAULT 0.0"))
            conn.commit()
    if "customized_fields" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN customized_fields TEXT DEFAULT '[]'"))
            conn.commit()
    if "rl_q_table" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN rl_q_table TEXT DEFAULT '{}'"))
            conn.commit()
    if "mental_state_history" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN mental_state_history TEXT DEFAULT '[]'"))
            conn.commit()
    if "concept_layers" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN concept_layers TEXT DEFAULT '{}'"))
            conn.commit()
    if "bkt_states" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN bkt_states TEXT DEFAULT '{}'"))
            conn.commit()
    if "dkt_bias" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN dkt_bias TEXT DEFAULT '[]'"))
            conn.commit()
    if "cognitive_map" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN cognitive_map TEXT DEFAULT '{}'"))
            conn.commit()
    if "fsm_mode" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN fsm_mode VARCHAR(64) DEFAULT 'normal'"))
            conn.commit()
    if "fsm_accuracy_history" not in profile_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE student_profiles ADD COLUMN fsm_accuracy_history TEXT DEFAULT '{}'"))
            conn.commit()

    # 迁移 conversation_history
    history_columns = [c["name"] for c in inspector.get_columns("conversation_history")]
    if "profile_snapshot" not in history_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE conversation_history ADD COLUMN profile_snapshot TEXT"))
            conn.commit()

    # 迁移 quiz_records 和 wrong_questions
    quiz_columns = [c["name"] for c in inspector.get_columns("quiz_records")]
    if "options" not in quiz_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE quiz_records ADD COLUMN options TEXT DEFAULT '[]'"))
            conn.commit()
    if "irt_alpha" not in quiz_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE quiz_records ADD COLUMN irt_alpha FLOAT DEFAULT 1.0"))
            conn.commit()
    if "irt_beta" not in quiz_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE quiz_records ADD COLUMN irt_beta FLOAT DEFAULT 0.0"))
            conn.commit()
    if "irt_gamma" not in quiz_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE quiz_records ADD COLUMN irt_gamma FLOAT DEFAULT 0.25"))
            conn.commit()

    wrong_columns = [c["name"] for c in inspector.get_columns("wrong_questions")]
    if "pinned" not in wrong_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE wrong_questions ADD COLUMN pinned BOOLEAN DEFAULT 0"))
            conn.commit()
    if "notes" not in wrong_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE wrong_questions ADD COLUMN notes TEXT DEFAULT ''"))
            conn.commit()

    # 迁移 irt_alpha_vec 和 irt_beta_vec
    if "irt_alpha_vec" not in quiz_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE quiz_records ADD COLUMN irt_alpha_vec TEXT"))
            conn.commit()
    if "irt_beta_vec" not in quiz_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE quiz_records ADD COLUMN irt_beta_vec TEXT"))
            conn.commit()

    item_columns = [c["name"] for c in inspector.get_columns("quiz_items")]
    if "irt_alpha_vec" not in item_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE quiz_items ADD COLUMN irt_alpha_vec TEXT"))
            conn.commit()
    if "irt_beta_vec" not in item_columns:
        with engine.connect() as conn:
            conn.execute(sa.text("ALTER TABLE quiz_items ADD COLUMN irt_beta_vec TEXT"))
            conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
