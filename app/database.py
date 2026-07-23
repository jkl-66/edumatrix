import json
import os
import asyncio
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Float, Integer, Text, DateTime, JSON, Boolean, event, ForeignKey, UniqueConstraint, CheckConstraint
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

if TESTING:
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
    target_course = Column(String(128), default="机器学习导论")
    knowledge_base = Column(String(64), default="初级")
    cognitive_style = Column(String(128), default="视觉+代码导向")
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
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    student_profile = relationship("DBStudentProfile", back_populates="notes")

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
    file_size = Column(Integer, default=0)
    source_url = Column(String(1024), default="")
    source_path = Column(String(512), default="")
    license_text = Column(Text, default="")
    uploader_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="SET NULL"), nullable=True, index=True)
    parser_version = Column(String(64), nullable=False, default="edumatrix-parser-v1")
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
    content_hash = Column(String(64), nullable=False)
    quote = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("source_document_id", "chapter_id", "parser_version", name="uq_source_ref_chapter_version"),)


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
    created_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)


class DBPathNode(Base):
    __tablename__ = "path_nodes"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("node"))
    learning_path_id = Column(String(64), ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    node_type = Column(String(32), nullable=False)
    target_object_id = Column(String(64), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    prerequisites = Column(JSON, default=list)
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
    trace_id = Column(String(64), nullable=False, index=True)
    object_type = Column(String(64), default="")
    object_id = Column(String(64), default="", index=True)
    payload = Column(JSON, default=dict)
    occurred_at = Column(DateTime, default=_utcnow, index=True)
    recorded_at = Column(DateTime, default=_utcnow)


class DBMemoryItem(Base):
    __tablename__ = "memory_items"
    id = Column(String(64), primary_key=True, default=lambda: new_public_id("mem"))
    owner_public_id = Column(String(64), ForeignKey("users.public_id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(128), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    memory_type = Column(String(32), nullable=False, index=True)
    content = Column(Text, nullable=False)
    source_type = Column(String(64), nullable=False)
    source_id = Column(String(64), nullable=False, index=True)
    confidence = Column(Float, nullable=False, default=0.0)
    sensitivity = Column(String(32), nullable=False, default="personal", index=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    last_used_at = Column(DateTime, nullable=True)
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
    concept_name = Column(String(128), index=True)
    wrong_reason_category = Column(String(128), nullable=True)
    pinned = Column(Boolean, default=False, index=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    student_profile = relationship("DBStudentProfile", back_populates="wrong_questions")
    quiz_record = relationship("DBQuizRecord")


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
