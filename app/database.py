import json
import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Float, Integer, Text, DateTime, JSON, Boolean, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 锁定本地 SQLite 单文件物理路径
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edumatrix.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# 初始化引擎并锁定 WAL 模式提高并发性能
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}, # 允许 FastAPI 多线程访问
    echo=False
)

# 物理连接池触发 WAL（Write-Ahead Logging）模式，实现读写非阻塞
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

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

class DBAlignmentLog(Base):
    """持久化审计表：存储 Swarm 智能体每一轮的流形测地线对齐记录，供时间轴与图表展现"""
    __tablename__ = "alignment_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(64), index=True)
    target_concept = Column(String(128))                 # 对齐的知识点
    passed = Column(Boolean, default=False)
    distance = Column(Float)
    threshold = Column(Float)
    conflicts = Column(JSON, default=list)               # 具体的冲突点描述
    advice = Column(Text)                                # 对齐回滚建议
    timestamp = Column(DateTime, default=datetime.utcnow)

# 物理并网：自动创建所有本地 SQLite 数据库表
def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
