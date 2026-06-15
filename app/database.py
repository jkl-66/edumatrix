import json
import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Float, Integer, Text, DateTime, JSON, Boolean, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from contextvars import ContextVar
from contextlib import contextmanager
from sqlalchemy.pool import Pool

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
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edumatrix.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# 初始化引擎并锁定 WAL 模式提高并发性能
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30.0}, # 允许 FastAPI 多线程访问并提供 30 秒超时锁队列
    echo=False
)

# 物理连接池触发 WAL（Write-Ahead Logging）模式，实现读写非阻塞
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
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

class DBStudentProfile(Base):
    """持久化物理表：存储学生 10 维画像、掌握度、认知负荷与学习偏好"""
    __tablename__ = "student_profiles"

    student_id = Column(String(64), primary_key=True, index=True)
    target_course = Column(String(128), default="机器学习导论")
    knowledge_base = Column(String(64), default="初级")
    cognitive_style = Column(String(128), default="视觉+代码导向")
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
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class DBUser(Base):
    """用户表：存储登录凭证"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, index=True, nullable=False) # 通常与 student_id 一致
    hashed_password = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class DBAlignmentLog(Base):
    __tablename__ = "alignment_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(64), index=True)
    target_concept = Column(String(128))
    passed = Column(Boolean, default=False)
    distance = Column(Float)
    threshold = Column(Float)
    conflicts = Column(JSON, default=list)
    advice = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


class DBNote(Base):
    __tablename__ = "notes"

    id = Column(String(64), primary_key=True)
    student_id = Column(String(64), index=True)
    source = Column(String(128), default="conversation")
    content = Column(Text)
    tags = Column(JSON, default=list)
    concepts = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DBReviewPlan(Base):
    __tablename__ = "review_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(64), index=True)
    concept = Column(String(128))
    interval_days = Column(Integer, default=1)
    next_review_at = Column(DateTime)
    mastery = Column(Float, default=0.0)
    review_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class DBConversationHistory(Base):
    __tablename__ = "conversation_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(64), index=True)
    query = Column(Text)
    response_summary = Column(Text)
    target = Column(String(128))
    resources_count = Column(Integer, default=0)
    alignment_passed = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DBKnowledgeDocument(Base):
    """持久化物理表：存储用户上传的知识库文档"""
    __tablename__ = "knowledge_documents"

    id = Column(String(64), primary_key=True)
    student_id = Column(String(64), index=True)
    filename = Column(String(256))
    file_type = Column(String(16))  # md / txt / pdf / pptx / mp4
    file_size = Column(Integer, default=0)
    title = Column(String(256), default="")
    content = Column(Text, default="")
    tags = Column(JSON, default=list)
    chunk_count = Column(Integer, default=0)
    is_multimodal = Column(Boolean, default=False)
    multimodal_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class DBQuizRecord(Base):
    """持久化物理表：存储测验记录与置信度反馈"""
    __tablename__ = "quiz_records"

    id = Column(String(64), primary_key=True)
    student_id = Column(String(64), index=True)
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
    created_at = Column(DateTime, default=datetime.utcnow)


class DBWebSearchHistory(Base):
    """持久化物理表：存储联网搜索与文档加载记录"""
    __tablename__ = "web_search_history"

    id = Column(String(64), primary_key=True)
    student_id = Column(String(64), index=True)
    query = Column(String(512))
    source_type = Column(String(32))  # web_search / url_load
    source_url = Column(Text, default="")
    title = Column(String(256), default="")
    content_preview = Column(Text, default="")
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class DBCodeExecution(Base):
    """持久化物理表：存储代码执行记录"""
    __tablename__ = "code_executions"

    id = Column(String(64), primary_key=True)
    student_id = Column(String(64), index=True)
    code = Column(Text)
    language = Column(String(32), default="python")
    output = Column(Text, default="")
    error = Column(Text, default="")
    execution_time_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

# 物理并网：自动创建所有本地 SQLite 数据库表
def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
