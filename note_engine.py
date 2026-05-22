from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from llm_client import DEFAULT_LLM, LLMBackend


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Note:
    id: str
    student_id: str
    source: str
    content: str
    tags: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)


@dataclass
class ReviewSchedule:
    concept: str
    interval_days: int
    next_review_at: str
    mastery: float = 0.0
    review_count: int = 0


@dataclass
class LearningProgressReport:
    student_id: str
    total_concepts: int
    mastered: int
    in_progress: int
    needs_review: int
    average_mastery: float
    recent_notes: list[Note]


class NoteGenerator:
    def __init__(self, llm: LLMBackend = DEFAULT_LLM) -> None:
        self.llm = llm

    def summarize_conversation(self, query: str, response: str, target: str) -> str:
        system_prompt = "你是一个学习笔记助手。用一两句话总结学生问题和回答，提取核心知识点。"
        user_prompt = f"问题：{query}\n回答摘要：{response[:500]}\n知识点：{target}"
        try:
            return self.llm.generate(system_prompt, user_prompt, role="笔记助手")
        except Exception:
            return f"[{target}] {query[:100]}"


class LearningProgressAnalyzer:
    def build_report(
        self,
        student_id: str,
        concept_mastery: dict[str, float],
        notes: list[Note] | None = None,
    ) -> LearningProgressReport:
        total = len(concept_mastery)
        mastered = sum(1 for v in concept_mastery.values() if v >= 0.75)
        in_progress = sum(1 for v in concept_mastery.values() if 0.45 <= v < 0.75)
        needs_review = sum(1 for v in concept_mastery.values() if v < 0.45)
        avg_mastery = sum(concept_mastery.values()) / total if total > 0 else 0.0
        return LearningProgressReport(
            student_id=student_id,
            total_concepts=total,
            mastered=mastered,
            in_progress=in_progress,
            needs_review=needs_review,
            average_mastery=round(avg_mastery, 2),
            recent_notes=notes or [],
        )


class ReviewScheduler:
    INTERVALS = [1, 3, 7, 14, 30]

    def schedule(self, concept: str, mastery: float, review_count: int = 0) -> ReviewSchedule:
        level = min(review_count, len(self.INTERVALS) - 1)
        days = self.INTERVALS[level]
        if mastery >= 0.85:
            days = max(days, 14)
        elif mastery < 0.45:
            days = 1
        from datetime import timedelta
        next_date = datetime.now(timezone.utc) + timedelta(days=days)
        return ReviewSchedule(
            concept=concept,
            interval_days=days,
            next_review_at=next_date.replace(microsecond=0).isoformat(),
            mastery=mastery,
            review_count=review_count,
        )
