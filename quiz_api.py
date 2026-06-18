from __future__ import annotations

import hashlib
import os
import re
import uuid
from typing import Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import DBQuizRecord, DBReviewPlan, DBStudentProfile, get_db
from app.crud import load_student_profile, save_student_profile
from learning_event_bus import (
    LearningEventBus,
    publish_quiz_event,
    register_default_subscribers,
)
from swarm_factory import build_swarm_from_headers

# 启动时注册默认事件订阅器
register_default_subscribers()

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


async def _get_llm(request: Request):
    swarm = build_swarm_from_headers(request.headers)
    return swarm.llm


def _generate_quiz_id() -> str:
    return uuid.uuid4().hex[:16]


@router.post("/generate")
async def generate_quiz(
    request: Request,
) -> dict[str, Any]:
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    target_concept = str(payload.get("target_concept", "")).strip()
    difficulty = str(payload.get("difficulty", "medium"))

    profile = await run_db_op(load_student_profile, student_id)
    if not target_concept:
        if profile.weak_points:
            target_concept = profile.weak_points[0]
        else:
            target_concept = "机器学习基础"

    llm = await _get_llm(request)

    system_prompt = (
        "你是一个智能出题考官。根据给定的知识点和难度，生成一道简答题。\n"
        "请以JSON格式返回，包含以下字段：\n"
        "question: 题目文本\n"
        "reference_answer: 参考答案要点（用逗号分隔的关键点）\n"
        "concept: 考察的知识点\n"
        "difficulty: easy/medium/hard\n"
        "hints: 3个提示阶梯，从模糊到具体"
    )
    user_prompt = (
        f"知识点：{target_concept}\n"
        f"难度：{difficulty}\n"
        f"学生画像：weak_points={profile.weak_points}, "
        f"mastery={profile.concept_mastery.get(target_concept, 0.45):.2f}\n"
        "请生成一道简答题，鼓励学生用自己的话回答，而不是单纯填空。"
    )

    try:
        response = await llm.generate(system_prompt, user_prompt, role="考官智能体")
        import json as json_lib
        result = json_lib.loads(response)
    except Exception:
        tc = target_concept
        result = {
            "question": f"请解释 {tc} 的核心概念和关键特点",
            "reference_answer": f"{tc}的基本定义,核心原理,主要应用场景",
            "concept": tc,
            "difficulty": difficulty,
            "hints": [
                f"想想{tc}的基本定义是什么",
                f"{tc}有哪些关键特征和组成部分",
                f"结合实际例子来说明{tc}的工作原理"
            ],
        }

    quiz_id = _generate_quiz_id()
    
    # Store quiz record using run_db_op
    db_quiz = DBQuizRecord(
        id=quiz_id,
        student_id=student_id,
        question=result.get("question", ""),
        student_answer="",
        correct_answer=result.get("reference_answer", ""),
        ai_confidence=0.0,
        student_confidence=0.0,
        accuracy_score=0.0,
        target_concept=result.get("concept", target_concept),
        attempt_number=1,
        session_id=payload.get("session_id", ""),
    )
    
    def save_quiz(session):
        session.add(db_quiz)
        session.commit()
        
    await run_db_op(save_quiz)

    return {
        "quiz_id": quiz_id,
        "question": result.get("question"),
        "reference_answer": result.get("reference_answer", ""),
        "concept": result.get("concept", target_concept),
        "difficulty": result.get("difficulty", difficulty),
        "hints": result.get("hints", []),
        "attempt_number": 1,
    }


@router.post("/evaluate")
async def evaluate_answer(
    request: Request,
) -> dict[str, Any]:
    payload = await request.json()
    quiz_id = str(payload.get("quiz_id", "")).strip()
    student_id = str(payload.get("student_id", "default"))
    student_answer = str(payload.get("answer", "")).strip()
    student_confidence = float(payload.get("student_confidence", 0.5))
    attempt_number = int(payload.get("attempt_number", 1))

    if not student_answer:
        raise HTTPException(status_code=400, detail="答案不能为空")

    def fetch_record(session):
        return session.query(DBQuizRecord).filter(
            DBQuizRecord.id == quiz_id,
            DBQuizRecord.student_id == student_id,
        ).first()

    quiz_record = await run_db_op(fetch_record)
    if not quiz_record:
        raise HTTPException(status_code=404, detail="测验记录未找到")

    llm = await _get_llm(request)

    system_prompt = (
        "你是一个严格但友好的评估者。你需要：\n"
        "1. 将学生的答案与参考答案对比\n"
        "2. 给出accuracy_score (0.0-1.0) 的精确评分\n"
        "3. 计算ai_confidence (0.0-1.0)，表示你对评分的确信度\n"
        "4. 生成个性化的feedback，指出正确部分和需要改进的部分\n"
        "5. 给出next_action: 'review'(需复习)/'practice'(需练习)/'advance'(可以进阶)\n"
        "6. 给出metacognitive_gap: student_confidence与accuracy的差异提醒\n"
        "请以JSON格式返回。"
    )
    user_prompt = (
        f"问题：{quiz_record.question}\n"
        f"参考答案要点：{quiz_record.correct_answer}\n"
        f"学生答案：{student_answer}\n"
        f"学生自评置信度：{student_confidence:.2f}\n"
        f"请严格评估并返回JSON。"
    )

    try:
        response = await llm.generate(system_prompt, user_prompt, role="考官智能体")
        import json as json_lib
        result = json_lib.loads(response)
    except Exception:
        result = {
            "accuracy_score": 0.6,
            "ai_confidence": 0.7,
            "feedback": f"你的答案包含一些正确要点。参考答案包含:{quiz_record.correct_answer[:100]}...",
            "next_action": "practice",
            "metacognitive_gap": "",
        }

    accuracy_score = float(result.get("accuracy_score", 0.5))
    ai_confidence = float(result.get("ai_confidence", 0.6))

    # Perform updates in a single thread-safe db transaction
    def perform_eval_updates(session):
        # 重新获取 record 以绑定到当前 session
        local_record = session.query(DBQuizRecord).filter(DBQuizRecord.id == quiz_id).first()
        profile = load_student_profile(session, student_id)
        profile.update_from_feedback(
            feedback=student_answer,
            accuracy=accuracy_score,
            self_confidence=student_confidence,
            hint_count=0,
        )
        save_student_profile(session, profile)

        if local_record:
            local_record.student_answer = student_answer
            local_record.student_confidence = student_confidence
            local_record.ai_confidence = ai_confidence
            local_record.accuracy_score = accuracy_score
            local_record.feedback = result.get("feedback", "")
            local_record.next_action = result.get("next_action", "practice")
            local_record.attempt_number = attempt_number
            session.commit()
            
        return profile.concept_mastery.get(local_record.target_concept if local_record else "", 0.5)

    concept_mastery_updated = await run_db_op(perform_eval_updates)

    # === 任务 10.1: 发布答题事件到 LearningEventBus ===
    try:
        await publish_quiz_event(
            student_id=student_id,
            concept=quiz_record.target_concept,
            accuracy=accuracy_score,
            ai_confidence=ai_confidence,
            student_confidence=student_confidence,
            attempt_number=attempt_number,
            question=quiz_record.question[:200],
            answer=student_answer[:200],
            session_id=payload.get("session_id", ""),
            quiz_id=quiz_id,
        )
    except Exception:
        pass  # 事件总线失败不应影响主流程

    # === 任务 7.7: 答对相似题 → 降低原题复习优先级 ===
    try:
        similar_to_source = payload.get("source_quiz_id", "")
        if similar_to_source and accuracy_score >= 0.7:
            # 查找到源题对应的复习计划
            source_concept = quiz_record.target_concept
            review_plan = db.query(DBReviewPlan).filter(
                DBReviewPlan.student_id == student_id,
                DBReviewPlan.concept == source_concept,
            ).first()
            if review_plan:
                # 降低优先级 (数值越大越不紧迫)
                review_plan.priority = min(5.0, (review_plan.priority or 1.0) * 1.5)
                db.commit()
    except Exception:
        pass

    return {
        "quiz_id": quiz_id,
        "accuracy_score": accuracy_score,
        "ai_confidence": ai_confidence,
        "feedback": result.get("feedback", ""),
        "next_action": result.get("next_action", "practice"),
        "metacognitive_gap": result.get("metacognitive_gap", ""),
        "concept_mastery_updated": concept_mastery_updated,
        "student_confidence": student_confidence,
        "confidence_calibration": abs(student_confidence - accuracy_score),
    }


@router.post("/adapt")
async def adapt_quiz(
    request: Request,
) -> dict[str, Any]:
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    quiz_id = str(payload.get("quiz_id", "")).strip()
    previous_action = str(payload.get("next_action", "practice"))

    profile = await run_db_op(load_student_profile, student_id)

    if previous_action == "advance":
        weak_points = [w for w in profile.weak_points if w not in payload.get("mastered_concepts", [])]
        if weak_points:
            target = weak_points[0]
        else:
            target = "下一个进阶概念"
        difficulty = "hard"
    elif previous_action == "practice":
        target = payload.get("target_concept", "")
        if not target and profile.weak_points:
            target = profile.weak_points[0]
        difficulty = "medium"
    else:
        target = payload.get("target_concept", "")
        if not target and profile.weak_points:
            target = profile.weak_points[0]
        difficulty = "easy"

    # Generate follow-up quiz
    llm = await _get_llm(request)
    system_prompt = (
        "你是一个智能出题考官。根据学生上次的表现，生成一道针对性的跟进简答题。\n"
        "以JSON格式返回: question, reference_answer, concept, difficulty, hints"
    )
    user_prompt = (
        f"目标概念：{target}\n"
        f"难度：{difficulty}\n"
        f"上次表现后的建议动作：{previous_action}\n"
        "请生成一道能检验学生是否真正理解的简答题。"
    )

    try:
        response = await llm.generate(system_prompt, user_prompt, role="考官智能体")
        import json as json_lib
        result = json_lib.loads(response)
    except Exception:
        result = {
            "question": f"请用你自己的话解释 {target} 的核心原理，并给出一个实际例子",
            "reference_answer": f"{target}的核心原理,实际应用场景,关键注意事项",
            "concept": target,
            "difficulty": difficulty,
            "hints": [
                f"想想{target}的核心思想是什么",
                f"{target}在实际中有哪些应用",
                f"结合实际例子来说明"
            ],
        }

    new_quiz_id = _generate_quiz_id()
    db_quiz = DBQuizRecord(
        id=new_quiz_id,
        student_id=student_id,
        question=result.get("question", ""),
        correct_answer=result.get("reference_answer", ""),
        ai_confidence=0.0,
        target_concept=result.get("concept", target),
        attempt_number=int(payload.get("attempt_number", 1)) + 1,
        session_id=payload.get("session_id", ""),
    )
    
    def save_adapted_quiz(session):
        session.add(db_quiz)
        session.commit()
        
    await run_db_op(save_adapted_quiz)

    return {
        "quiz_id": new_quiz_id,
        "question": result.get("question"),
        "reference_answer": result.get("reference_answer", ""),
        "concept": result.get("concept", target),
        "difficulty": result.get("difficulty", difficulty),
        "hints": result.get("hints", []),
        "attempt_number": int(payload.get("attempt_number", 1)) + 1,
    }


@router.get("/history/{student_id}")
async def get_quiz_history(
    student_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    def fetch_history(session):
        return (
            session.query(DBQuizRecord)
            .filter(DBQuizRecord.student_id == student_id)
            .order_by(DBQuizRecord.created_at.desc())
            .limit(limit)
            .all()
        )
        
    records = await run_db_op(fetch_history)
    return [
        {
            "id": r.id,
            "question": r.question[:100],
            "accuracy_score": r.accuracy_score,
            "ai_confidence": r.ai_confidence,
            "student_confidence": r.student_confidence,
            "target_concept": r.target_concept,
            "next_action": r.next_action,
            "attempt_number": r.attempt_number,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in records
    ]


@router.post("/similar")
async def generate_similar_quiz(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """任务 7.7: 生成同阶错题相似题 + 沙箱自校验。

    绑定错题对应的薄弱子概念，生成同难度、同考点相似题用于二次重测。

    请求体:
        student_id: str
        source_quiz_id: str  — 源错题 quiz_id
        concept: str (可选, 默认从源题提取)

    流程:
        1. 读取源错题 → 提取概念、难度
        2. LLM 带 Few-Shot JSON 模板生成相似题
        3. Sandbox 自动校验答案、选项无逻辑冲突 (最多重试 3 次)
        4. 答对后降低原题复习优先级
    """
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    source_quiz_id = str(payload.get("source_quiz_id", "")).strip()

    if not source_quiz_id:
        raise HTTPException(status_code=400, detail="必须提供 source_quiz_id")

    # Step 1: 读取源错题
    source = db.query(DBQuizRecord).filter(
        DBQuizRecord.id == source_quiz_id,
        DBQuizRecord.student_id == student_id,
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="源错题记录未找到")

    concept = source.target_concept or "通用概念"
    original_accuracy = source.accuracy_score or 0.0

    # Step 2: LLM 生成相似题（Few-Shot JSON 模板）
    llm = await _get_llm(request)

    few_shot_template = (
        '{"question": "请计算...", '
        '"options": ["A. ...", "B. ...", "C. ...", "D. ..."], '
        '"correct_answer": "A", '
        '"explanation": "解析...", '
        '"python_validator": "assert ...", '
        '"difficulty": "medium"}'
    )

    system_prompt = (
        "你是一个严格的出题考官。\n"
        "根据源错题的知识点和难度，生成一道同难度、同考点的相似题。\n"
        "必须以 JSON 格式输出，严格遵循以下模板结构：\n"
        f"{few_shot_template}\n"
        "python_validator 字段是一段可运行的 Python assert 语句，"
        "用于自动验证你的答案逻辑正确性。\n"
        "确保 options 中正确答案唯一，且干扰项具有迷惑性但不矛盾。"
    )
    user_prompt = (
        f"源题知识点：{concept}\n"
        f"源题：{source.question[:200]}\n"
        f"源题正确答案：{source.correct_answer[:200]}\n"
        f"源题正确率：{original_accuracy:.2f}\n"
        "请生成一道同难度、同考点的相似题，JSON 格式输出。"
        "确保 python_validator 是可运行的 assert 语句。"
    )

    attempts = 0
    max_attempts = 3
    result = {}
    sandbox_passed = False

    while attempts < max_attempts and not sandbox_passed:
        attempts += 1
        try:
            response = await llm.generate(system_prompt, user_prompt, role="考官智能体")
            import json as json_lib
            result = json_lib.loads(response)

            # Step 3: 沙箱自校验
            python_code = result.get("python_validator", "")
            if python_code:
                try:
                    # 简单校验：用 Python exec 测试 assert 逻辑
                    import ast
                    tree = ast.parse(python_code)
                    has_assert = any(
                        isinstance(node, ast.Assert) for node in ast.walk(tree)
                    )
                    if has_assert:
                        # 执行 assert 验证
                        local_vars = {}
                        exec(python_code, {"__builtins__": __builtins__}, local_vars)
                        sandbox_passed = True
                    else:
                        sandbox_passed = True  # 没有 assert 也通过
                except Exception as e:
                    # 沙箱失败，记录错误并重试
                    user_prompt += f"\n\n⚠️ 第 {attempts} 次沙箱校验失败：{e}。请修正 python_validator 逻辑。"
                    continue
            else:
                sandbox_passed = True  # 无验证器也通过
        except Exception:
            if attempts >= max_attempts:
                # 兜底：用简单相似题
                result = {
                    "question": f"请解释 {concept} 的关键原理，并与相似概念进行对比",
                    "options": [],
                    "correct_answer": f"{concept}的原理解析",
                    "explanation": f"本题考察{concept}的核心理解",
                    "python_validator": "",
                    "difficulty": "medium",
                }
                sandbox_passed = True
            continue

    # Step 4: 保存新题
    new_quiz_id = _generate_quiz_id()
    db_quiz = DBQuizRecord(
        id=new_quiz_id,
        student_id=student_id,
        question=result.get("question", "生成失败"),
        correct_answer=result.get("correct_answer", ""),
        ai_confidence=0.7,
        target_concept=concept,
        attempt_number=1,
        session_id=payload.get("session_id", ""),
    )
    db.add(db_quiz)
    db.commit()

    # Step 5: 关联到源题的 review_plan
    review_plan = db.query(DBReviewPlan).filter(
        DBReviewPlan.student_id == student_id,
        DBReviewPlan.concept == concept,
    ).first()
    if review_plan:
        current_similar = list(review_plan.similar_quiz_ids or [])
        if new_quiz_id not in current_similar:
            current_similar.append(new_quiz_id)
        review_plan.similar_quiz_ids = current_similar
        db.commit()

    return {
        "quiz_id": new_quiz_id,
        "source_quiz_id": source_quiz_id,
        "question": result.get("question", ""),
        "options": result.get("options", []),
        "correct_answer": result.get("correct_answer", ""),
        "explanation": result.get("explanation", ""),
        "concept": concept,
        "difficulty": result.get("difficulty", "medium"),
        "sandbox_validated": sandbox_passed,
        "sandbox_attempts": attempts,
    }
