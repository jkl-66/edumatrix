"""
EduMatrix 种子数据生成脚本 — 创建教师和学生测试账号及画像

用法: python scripts/seed_students.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import DBUser, DBStudentProfile, DBQuizRecord, DBWrongQuestion, DBReviewPlan, Base, engine, SessionLocal
from app.auth import get_password_hash
from models import StudentProfile
from datetime import datetime, timedelta

def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # 教师账号
    teacher = db.query(DBUser).filter(DBUser.username == "teacher").first()
    if not teacher:
        teacher = DBUser(username="teacher", hashed_password=get_password_hash("teacher123"))
        db.add(teacher)
        print("  [创建] 教师账号: teacher / teacher123")

    students_data = [
        {"username": "student1", "password": "password123", "name": "张三", "major": "计算机科学与技术",
         "target_course": "机器学习导论", "cognitive_style": "视觉+代码导向",
         "concept_mastery": {"线性回归": 0.85, "逻辑回归": 0.6, "池化层": 0.35, "反向传播": 0.5, "梯度下降": 0.7,
                            "卷积神经网络": 0.3, "过拟合": 0.65, "决策树": 0.8},
         "weak_points": ["池化层", "卷积神经网络"], "frustration_index": 0.2,
         "cognitive_load": 0.45, "engagement_level": 0.8,
         "learning_goals": ["深度学习", "计算机视觉"],
         "bloom_levels": {"线性回归": "应用", "逻辑回归": "理解", "池化层": "记忆", "反向传播": "理解"}},

        {"username": "student2", "password": "password123", "name": "李四", "major": "数据科学",
         "target_course": "深度学习", "cognitive_style": "动手实践+代码导向",
         "concept_mastery": {"线性回归": 0.9, "逻辑回归": 0.85, "池化层": 0.7, "反向传播": 0.6, "梯度下降": 0.8,
                            "卷积神经网络": 0.55, "过拟合": 0.4, "Transformer": 0.3},
         "weak_points": ["过拟合", "Transformer"], "frustration_index": 0.35,
         "cognitive_load": 0.6, "engagement_level": 0.7,
         "learning_goals": ["自然语言处理"],
         "bloom_levels": {"线性回归": "评价", "逻辑回归": "分析", "卷积神经网络": "理解", "Transformer": "记忆"}},

        {"username": "student3", "password": "password123", "name": "王五", "major": "人工智能",
         "target_course": "机器学习导论", "cognitive_style": "文本阅读型",
         "concept_mastery": {"线性回归": 0.4, "逻辑回归": 0.3, "池化层": 0.2, "反向传播": 0.15, "梯度下降": 0.25,
                            "过拟合": 0.3, "决策树": 0.5},
         "weak_points": ["反向传播", "池化层", "梯度下降", "线性回归", "逻辑回归"],
         "frustration_index": 0.65, "cognitive_load": 0.75, "engagement_level": 0.4,
         "learning_goals": ["打好数学基础", "理解机器学习核心概念"],
         "bloom_levels": {"线性回归": "记忆", "逻辑回归": "记忆", "决策树": "理解"}},

        {"username": "student4", "password": "password123", "name": "赵六", "major": "软件工程",
         "target_course": "机器学习导论", "cognitive_style": "视觉+代码导向",
         "concept_mastery": {"线性回归": 0.75, "逻辑回归": 0.7, "池化层": 0.8, "反向传播": 0.7, "梯度下降": 0.75,
                            "卷积神经网络": 0.85, "过拟合": 0.6, "正则化": 0.55},
         "weak_points": ["过拟合", "正则化"], "frustration_index": 0.1,
         "cognitive_load": 0.35, "engagement_level": 0.9,
         "learning_goals": ["模型优化", "部署"],
         "bloom_levels": {"卷积神经网络": "创造", "反向传播": "评价"}},

        {"username": "student5", "password": "password123", "name": "孙七", "major": "数学与应用数学",
         "target_course": "机器学习数学基础", "cognitive_style": "文本阅读型",
         "concept_mastery": {"线性回归": 0.95, "逻辑回归": 0.9, "反向传播": 0.8, "梯度下降": 0.9,
                            "链式法则": 0.95, "概率论基础": 0.85, "线性代数": 0.9},
         "weak_points": ["过拟合", "正则化", "模型评估"],
         "frustration_index": 0.05, "cognitive_load": 0.25, "engagement_level": 0.95,
         "learning_goals": ["机器学习理论证明"],
         "bloom_levels": {"线性回归": "创造", "逻辑回归": "评价", "反向传播": "分析"}},
    ]

    for sd in students_data:
        existing = db.query(DBUser).filter(DBUser.username == sd["username"]).first()
        if existing:
            print(f"  [跳过] {sd['username']} 已存在")
            continue
        user = DBUser(username=sd["username"], hashed_password=get_password_hash(sd["password"]))
        db.add(user)
        db.flush()

        # 创建内存画像用于序列化
        profile = StudentProfile(student_id=sd["username"], major=sd["major"],
                                 target_course=sd["target_course"],
                                 cognitive_style=sd["cognitive_style"],
                                 concept_mastery=sd["concept_mastery"],
                                 weak_points=sd["weak_points"],
                                 frustration_index=sd["frustration_index"],
                                 cognitive_load=sd["cognitive_load"],
                                 engagement_level=sd["engagement_level"],
                                 learning_goals=sd["learning_goals"],
                                 bloom_levels=sd["bloom_levels"])
        # 触发一次状态刷新以生成 dimension_states
        profile.update_from_message(f"我是{sd['major']}专业的学生，想学习{sd['target_course']}")

        # 保存到 DBStudentProfile
        db_profile = DBStudentProfile(
            student_id=sd["username"],
            target_course=sd["target_course"],
            cognitive_style=sd["cognitive_style"],
            concept_mastery=sd["concept_mastery"],
            weak_points=sd["weak_points"],
            learning_goals=sd["learning_goals"],
            cognitive_load=sd["cognitive_load"],
            major=sd["major"],
            last_updated=datetime.utcnow(),
        )
        db.add(db_profile)
        print(f"  [创建] 学生 {sd['username']} ({sd['name']}) - {sd['major']}")

    db.commit()
    db.close()
    print(f"\nDone. Created {len(students_data)} students + 1 teacher")

if __name__ == "__main__":
    seed()
