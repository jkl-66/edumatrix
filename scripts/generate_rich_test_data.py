"""scripts/generate_rich_test_data.py — 全维度测试数据多功能生成器

使用方法：
    python scripts/generate_rich_test_data.py --all
    python scripts/generate_rich_test_data.py --user lzz --plans 10 --notes 5
    python scripts/generate_rich_test_data.py --students 20
    python scripts/generate_rich_test_data.py --clean

功能：
1. 自动生成多专业、多认知状态（高负荷/低专注/概念误解）的差异化学生画像。
2. 批量生成基于 SM-2 算法的复习计划、易度因子及连续打卡历史（Checkin Log）。
3. 自动生成结构化错题本、系统诊断反馈与反思小记。
4. 填充分布式概念拓扑坐标（GraphRAG）与自适应试题库。
"""

from __future__ import annotations

import argparse
import random
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import (
    SessionLocal, init_db, DBUser, DBStudentProfile, DBReviewPlan,
    DBCheckinLog, DBNote, DBWrongQuestion, DBQuizRecord, DBConceptCoordinate
)
from app.auth import get_password_hash
from app.crud import save_student_profile, review_plan_to_dict
from models import StudentProfile, CauseBreakdown, DimensionState

CONCEPTS = [
    "梯度下降", "逻辑回归", "神经网络", "卷积核", "机器学习", "过拟合",
    "反向传播", "SVM支持向量机", "决策树", "随机森林", "L1/L2正则化",
    "Transformer", "自注意力机制", "主成分分析PCA", "K-Means聚类",
    "数据标准化", "交叉验证", "ROC与AUC曲线", "残差网络ResNet", "BERT预训练"
]

MAJORS = [
    "计算机科学与技术", "软件工程", "人工智能", "数据科学与大数据技术",
    "数学与应用数学", "自动化", "电子信息工程", "金融工程", "生物信息学", "统计学"
]

WRONG_REASONS = [
    ("misconception", "概念误解"),
    ("calculation_error", "计算错误"),
    ("carelessness", "粗心大意"),
    ("outlier_sensitivity", "对异常值敏感"),
    ("review", "需复习"),
]

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def seed_user_rich_data(db, username: str, plan_count: int = 8, note_count: int = 5):
    """为特定用户生成丰富的复习计划、打卡历史与错题笔记"""
    print(f"  [Generator] 为目标账号 '{username}' 生成多维测试数据...")
    
    # 1. 确保用户存在
    user = db.query(DBUser).filter(DBUser.username == username).first()
    if not user:
        user = DBUser(
            username=username,
            hashed_password=get_password_hash("demo-password"),
            role="student",
            display_name=f"学生_{username}"
        )
        db.add(user)
        db.commit()

    # 2. 确保画像存在
    profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == username).first()
    if not profile:
        sp = StudentProfile(student_id=username)
        sp.major = random.choice(MAJORS)
        save_student_profile(db, sp)
        profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == username).first()

    # 3. 批量更新复习计划
    selected_concepts = random.sample(CONCEPTS, min(plan_count, len(CONCEPTS)))
    for concept in selected_concepts:
        existing = db.query(DBReviewPlan).filter_by(student_id=username, concept=concept).first()
        mastery = round(random.uniform(0.25, 0.95), 2)
        interval = random.choice([1, 2, 3, 5, 7, 14])
        next_review = _utcnow() + timedelta(days=random.choice([-1, 0, 1, 2, 5]))
        
        if existing:
            existing.mastery = mastery
            existing.interval_days = interval
            existing.next_review_at = next_review
        else:
            plan = DBReviewPlan(
                student_id=username,
                concept=concept,
                interval_days=interval,
                next_review_at=next_review,
                mastery=mastery,
                review_count=random.randint(1, 10),
                easiness_factor=round(random.uniform(1.8, 2.8), 2),
                last_quality=random.choice([2, 4, 5]),
                priority=1.0 if mastery < 0.5 else 0.5
            )
            db.add(plan)
    db.commit()

    # 4. 生成连续打卡记录 (Checkin Logs)
    for i in range(15):
        log_date = _utcnow() - timedelta(days=i)
        checkin = DBCheckinLog(
            student_id=username,
            checkin_date=log_date,
            duration_minutes=random.choice([10, 15, 20, 30, 45]),
            concepts_reviewed=[random.choice(selected_concepts)]
        )
        db.add(checkin)
    db.commit()

    # 5. 生成错题本与反思笔记
    for i in range(note_count):
        concept = random.choice(selected_concepts)
        reason_key, reason_label = random.choice(WRONG_REASONS)
        note_id = f"note-{username}-{i+1:03d}"

        existing_note = db.query(DBNote).filter_by(id=note_id).first()
        if not existing_note:
            note_content = (
                f"# {concept} 错题集与反思\n\n"
                f"> [!IMPORTANT]\n"
                f"> **💡 系统诊断反馈**\n"
                f"> 该知识点在做题时模型判分置信度偏低，对 `{reason_label}` 归因敏感，建议结合代码验证。[证据: test_record_#00{i+1}]\n\n"
                f"- **核心概念**：`{concept}`\n"
                f"- **错因分类**：`{reason_label}` ({reason_key})\n\n"
                f"#### **📝 错题题目**\n"
                f"已知使用二分类模型处理数据，当正负样本比例极度不平衡 (1:9) 时，以下哪个指标最能客观反映召回率与精确度的折中？\n\n"
                f"#### **👤 我的回答**\n"
                f"`使用 Accuracy (准确率) 进行主指标判定`\n\n"
                f"#### **🎯 参考答案与解析**\n"
                f"PR 曲线（Precision-Recall Curve）或 F1-Score。在不平衡数据集中，Accuracy 会产生高分假象。"
            )
            new_note = DBNote(
                id=note_id,
                student_id=username,
                source="错题本反思",
                content=note_content,
                tags=["错题整理", "反思", concept],
                concepts=[concept],
            )
            db.add(new_note)
    db.commit()
    print(f"  [Generator] 账号 '{username}' 数据生成完成：{plan_count} 条复习计划，15 天打卡历史，{note_count} 篇错题反思！")


def generate_batch_students(db, count: int = 10):
    """批量生成差异化学生画像与认知状态矩阵"""
    print(f"  [Generator] 正在批量生成 {count} 名差异化测试学生账号...")
    for i in range(1, count + 1):
        uname = f"stu-batch-{i:03d}"
        dname = f"测试学生_{i:03d}"
        major = random.choice(MAJORS)

        user = db.query(DBUser).filter_by(username=uname).first()
        if not user:
            user = DBUser(
                username=uname,
                hashed_password=get_password_hash("123456"),
                role="student",
                display_name=dname
            )
            db.add(user)

        # 随机分配掌握度分布
        mastery_map = {c: round(random.uniform(0.1, 0.98), 2) for c in random.sample(CONCEPTS, random.randint(5, 12))}
        weak_list = [k for k, v in mastery_map.items() if v < 0.5]

        sp = StudentProfile(student_id=uname)
        sp.major = major
        sp.target_course = "机器学习与智能工程"
        sp.concept_mastery = mastery_map
        sp.weak_points = weak_list
        sp.focus_level = round(random.uniform(0.4, 0.95), 2)
        sp.cognitive_load = round(random.uniform(0.2, 0.85), 2)
        sp.frustration_index = round(random.uniform(0.0, 0.6), 2)

        save_student_profile(db, sp)

        # 生成 2-5 条复习计划
        for concept in random.sample(list(mastery_map.keys()), min(3, len(mastery_map))):
            p = DBReviewPlan(
                student_id=uname,
                concept=concept,
                interval_days=random.choice([1, 3, 7]),
                next_review_at=_utcnow() + timedelta(days=random.randint(-2, 3)),
                mastery=mastery_map[concept],
                review_count=random.randint(1, 5),
                easiness_factor=2.5,
                priority=1.0 if mastery_map[concept] < 0.5 else 0.5
            )
            db.add(p)

    db.commit()
    print(f"  [Generator] {count} 名批次学生账号及画像初始化完毕。")


def generate_concept_coordinates(db):
    """为全量 20 个核心概念生成二维庞加莱流形对齐坐标"""
    print("  [Generator] 检查/生成庞加莱圆盘双曲流形坐标...")
    for i, concept in enumerate(CONCEPTS):
        existing = db.query(DBConceptCoordinate).filter_by(concept_name=concept).first()
        if not existing:
            # 模拟在庞加莱圆盘内 (|x|^2 + |y|^2 < 1) 的分布
            r = random.uniform(0.1, 0.85)
            x = round(r * (1.0 if i % 2 == 0 else -1.0), 4)
            y = round(r * (1.0 if i % 3 == 0 else -1.0), 4)
            
            coord = DBConceptCoordinate(
                concept_name=concept,
                x=x,
                y=y
            )
            db.add(coord)
    db.commit()
    print("  [Generator] 概念流形坐标生成完毕。")


def main():
    parser = argparse.ArgumentParser(description="EduMatrix 全维度测试数据生成器")
    parser.add_argument("--all", action="store_true", help="一键注入全套测试数据（含 lzz、demo-student 及 15 名批次学生）")
    parser.add_argument("--user", type=str, default="lzz", help="要注入详细数据的目标用户名 (默认: lzz)")
    parser.add_argument("--plans", type=int, default=10, help="为指定用户生成的复习计划数量")
    parser.add_argument("--notes", type=int, default=5, help="为指定用户生成的错题反思笔记数量")
    parser.add_argument("--students", type=int, default=10, help="要批量生成的差异化学生数量")
    parser.add_argument("--clean", action="store_true", help="清理生成数据")

    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    try:
        if args.clean:
            print("  [Clean] 清理生成测试数据...")
            db.query(DBReviewPlan).filter(DBReviewPlan.student_id.like("stu-batch-%")).delete(synchronize_session=False)
            db.query(DBUser).filter(DBUser.username.like("stu-batch-%")).delete(synchronize_session=False)
            db.query(DBStudentProfile).filter(DBStudentProfile.student_id.like("stu-batch-%")).delete(synchronize_session=False)
            db.commit()
            print("  [Clean] 清理完毕。")
            return

        if args.all:
            print("============================================================")
            print("        EduMatrix 全维度测试数据全量生成与注水程序")
            print("============================================================")
            seed_user_rich_data(db, "lzz", plan_count=10, note_count=6)
            seed_user_rich_data(db, "demo-student", plan_count=8, note_count=4)
            generate_batch_students(db, count=15)
            generate_concept_coordinates(db)
            print("============================================================")
            print("[SUCCESS] 全量测试数据库生成完毕！支持随时登录或调用 API。")
            print("============================================================")
        else:
            seed_user_rich_data(db, args.user, plan_count=args.plans, note_count=args.notes)
            if args.students > 0:
                generate_batch_students(db, count=args.students)
            generate_concept_coordinates(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
