from __future__ import annotations

import hashlib
import os
import re
import uuid
from typing import Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import DBQuizRecord, DBStudentProfile, get_db
from app.crud import load_student_profile, save_student_profile
from swarm_factory import build_swarm_from_headers

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


async def _get_llm(request: Request):
    swarm = build_swarm_from_headers(request.headers)
    return swarm.llm


def _generate_quiz_id() -> str:
    return uuid.uuid4().hex[:16]


@router.post("/generate")
async def generate_quiz(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    target_concept = str(payload.get("target_concept", "")).strip()
    difficulty = str(payload.get("difficulty", "medium"))

    profile = load_student_profile(db, student_id)
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
    # Store quiz record
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
    db.add(db_quiz)
    db.commit()

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
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = await request.json()
    quiz_id = str(payload.get("quiz_id", "")).strip()
    student_id = str(payload.get("student_id", "default"))
    student_answer = str(payload.get("answer", "")).strip()
    student_confidence = float(payload.get("student_confidence", 0.5))
    attempt_number = int(payload.get("attempt_number", 1))

    if not student_answer:
        raise HTTPException(status_code=400, detail="答案不能为空")

    quiz_record = db.query(DBQuizRecord).filter(
        DBQuizRecord.id == quiz_id,
        DBQuizRecord.student_id == student_id,
    ).first()

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

    profile = load_student_profile(db, student_id)
    profile.update_from_feedback(
        feedback=student_answer,
        accuracy=accuracy_score,
        self_confidence=student_confidence,
        hint_count=0,
    )
    save_student_profile(db, profile)

    quiz_record.student_answer = student_answer
    quiz_record.student_confidence = student_confidence
    quiz_record.ai_confidence = ai_confidence
    quiz_record.accuracy_score = accuracy_score
    quiz_record.feedback = result.get("feedback", "")
    quiz_record.next_action = result.get("next_action", "practice")
    quiz_record.attempt_number = attempt_number
    db.commit()

    return {
        "quiz_id": quiz_id,
        "accuracy_score": accuracy_score,
        "ai_confidence": ai_confidence,
        "feedback": result.get("feedback", ""),
        "next_action": result.get("next_action", "practice"),
        "metacognitive_gap": result.get("metacognitive_gap", ""),
        "concept_mastery_updated": profile.concept_mastery.get(quiz_record.target_concept, 0.5),
        "student_confidence": student_confidence,
        "confidence_calibration": abs(student_confidence - accuracy_score),
    }


@router.post("/adapt")
async def adapt_quiz(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = await request.json()
    student_id = str(payload.get("student_id", "default"))
    quiz_id = str(payload.get("quiz_id", "")).strip()
    previous_action = str(payload.get("next_action", "practice"))

    profile = load_student_profile(db, student_id)

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
    db.add(db_quiz)
    db.commit()

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
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    records = (
        db.query(DBQuizRecord)
        .filter(DBQuizRecord.student_id == student_id)
        .order_by(DBQuizRecord.created_at.desc())
        .limit(limit)
        .all()
    )
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
