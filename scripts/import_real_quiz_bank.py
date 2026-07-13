"""import_real_quiz_bank.py — 真实题库 JSONL 导入器

读取 scripts/data/quiz_bank/ 目录下所有 .jsonl 文件，
将 750 道真实专家级题目导入 SQLite 数据库。
"""

import glob
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, DBQuizItem, init_db

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "quiz_bank")


def import_all():
    if not os.path.isdir(DATA_DIR):
        print(f"ERROR: 数据目录不存在: {DATA_DIR}")
        sys.exit(1)

    jsonl_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.jsonl")))
    if not jsonl_files:
        print(f"ERROR: 在 {DATA_DIR} 中未找到 .jsonl 文件")
        sys.exit(1)

    print(f"找到 {len(jsonl_files)} 个数据文件，开始导入...")

    init_db()
    db = SessionLocal()
    try:
        total = 0
        mcq_count = 0
        subj_count = 0
        concept_set = set()

        for filepath in jsonl_files:
            basename = os.path.basename(filepath)
            file_lines = 0
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError as e:
                        print(f"  WARN [{basename}]: JSON 解析失败: {e}")
                        continue

                    quiz_id = uuid.uuid4().hex[:16]
                    concept = item["concept"]
                    question_type = item["question_type"]
                    difficulty = item["difficulty"]

                    irt_beta = {"easy": -1.0, "medium": 0.0, "hard": 1.0}.get(difficulty, 0.0)
                    irt_alpha = 1.0 + (0.25 if difficulty == "hard" else -0.15 if difficulty == "easy" else 0.0)
                    irt_gamma = 0.25 if question_type == "mcq" else 0.0

                    db_item = DBQuizItem(
                        id=quiz_id,
                        concept=concept,
                        question=item["question"],
                        options=item.get("options", []),
                        correct_answer=item["correct_answer"],
                        explanation=item.get("explanation", ""),
                        difficulty=difficulty,
                        irt_alpha=irt_alpha,
                        irt_beta=irt_beta,
                        irt_gamma=irt_gamma,
                    )
                    db.add(db_item)
                    total += 1
                    file_lines += 1
                    concept_set.add(concept)
                    if question_type == "mcq":
                        mcq_count += 1
                    else:
                        subj_count += 1

            print(f"  [{basename}]: {file_lines} 题")

        db.commit()
        print(f"\n  === IMPORT DONE! ===")
        print(f"  总计: {total} 道题")
        print(f"  选择题 (MCQ): {mcq_count} 道")
        print(f"  主观题 (Subjective): {subj_count} 道")
        print(f"  覆盖概念: {len(concept_set)} 个")

    finally:
        db.close()


def clean_and_import():
    """清空题库后重新导入。"""
    init_db()
    db = SessionLocal()
    try:
        count = db.query(DBQuizItem).count()
        db.query(DBQuizItem).delete()
        db.commit()
        print(f"  CLEANED: {count} 条旧记录")
    finally:
        db.close()
    import_all()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="真实题库导入")
    parser.add_argument("--clean", action="store_true", help="清空后重新导入")
    args = parser.parse_args()

    if args.clean:
        clean_and_import()
    else:
        import_all()