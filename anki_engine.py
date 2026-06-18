"""任务 7.5: 自适应 Anki 间隔记忆闪卡与 SM-2 间隔重复引擎

核心公式：
1. 易度因子更新: E' = max(1.3, E + (0.1 - (5-q)) * (0.08 + (5-q) * 0.02))
2. 复习间隔迭代: I' = I * E (q>=4 时); I' = 1 (q<4 时)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


# SM-2 参数常量
SM2_E_MIN = 1.3         # 易度因子下限
SM2_E_DEFAULT = 2.5     # 默认易度因子
SM2_I0 = 1              # 初始间隔 (天)
SM2_I1 = 6              # 首次及格间隔 (天)

# 质量参数: q={2,4,5}
# 2 = 困难 (记错了), 4 = 一般 (想了一会儿), 5 = 简单 (立即反应)


def sm2_update_easiness(e: float, q: int) -> float:
    """SM-2 易度因子更新公式。

    E' = max(1.3, E + (0.1 - (5-q)) * (0.08 + (5-q) * 0.02))

    Args:
        e: 当前易度因子
        q: 质量评分 {2, 4, 5}

    Returns:
        更新后的易度因子 (>= 1.3)
    """
    delta = (0.1 - (5 - q)) * (0.08 + (5 - q) * 0.02)
    return max(SM2_E_MIN, e + delta)


def sm2_next_interval(interval: int, q: int, e: float) -> int:
    """SM-2 复习间隔迭代。

    - q >= 4 (及格): I' = round(I * E)
    - q < 4 (不及格): I' = 1 (重置到 1 天)

    Args:
        interval: 当前间隔 (天)
        q: 质量评分 {2, 4, 5}
        e: 易度因子

    Returns:
        下次复习间隔 (天)
    """
    if q < 4:
        return 1  # 不及格重置
    return max(1, round(interval * e))


def sm2_schedule(
    e: float,
    interval: int,
    q: int,
) -> tuple[float, int]:
    """完整 SM-2 调度：同时计算新易度因子和新间隔。

    Args:
        e: 当前易度因子
        interval: 当前间隔 (天)
        q: 质量评分 {2, 4, 5}

    Returns:
        (new_easiness, new_interval_days)
    """
    new_e = sm2_update_easiness(e, q)
    new_interval = sm2_next_interval(interval, q, new_e)
    return (new_e, new_interval)


@dataclass
class FlashCard:
    """记忆闪卡数据结构。"""
    concept: str
    front: str                         # 正面: 概念/问题
    back: str                          # 背面: 解析/公式/引导
    source_quiz_id: str = ""           # 来源答题记录 ID
    student_id: str = ""
    easiness: float = SM2_E_DEFAULT    # 易度因子
    interval_days: int = SM2_I0        # 当前间隔 (天)
    review_count: int = 0              # 复习次数
    last_quality: int = 0              # 上次质量评分
    next_review_at: str = ""           # ISO 格式的下次复习时间
    tags: list[str] = field(default_factory=list)

    def schedule(self, quality: int) -> None:
        """根据质量评分更新间隔参数。

        Args:
            quality: {2=困难, 4=一般, 5=简单}
        """
        if quality not in (2, 4, 5):
            raise ValueError(f"质量评分必须为 2, 4, 5, 收到 {quality}")

        self.easiness, self.interval_days = sm2_schedule(
            self.easiness, self.interval_days, quality,
        )
        self.last_quality = quality
        self.review_count += 1

        # 计算下次复习时间
        now = datetime.now(timezone.utc)
        next_review = now + timedelta(days=self.interval_days)
        self.next_review_at = next_review.replace(microsecond=0).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "front": self.front,
            "back": self.back,
            "source_quiz_id": self.source_quiz_id,
            "student_id": self.student_id,
            "easiness": round(self.easiness, 2),
            "interval_days": self.interval_days,
            "review_count": self.review_count,
            "last_quality": self.last_quality,
            "next_review_at": self.next_review_at,
            "tags": self.tags,
        }


class SM2Engine:
    """SM-2 间隔重复引擎，管理全局闪卡库。"""

    def __init__(self) -> None:
        self._cards: dict[str, FlashCard] = {}  # concept -> FlashCard

    def get_or_create(
        self,
        concept: str,
        front: str = "",
        back: str = "",
        student_id: str = "",
        source_quiz_id: str = "",
    ) -> FlashCard:
        key = f"{student_id}::{concept}"
        if key in self._cards:
            return self._cards[key]

        now = datetime.now(timezone.utc)
        card = FlashCard(
            concept=concept,
            front=front or f"请解释 {concept} 的核心概念",
            back=back or f"{concept} 的关键要点和原理解析",
            student_id=student_id,
            source_quiz_id=source_quiz_id,
            next_review_at=now.replace(microsecond=0).isoformat(),
        )
        self._cards[key] = card
        return card

    def review(self, concept: str, student_id: str, quality: int) -> FlashCard | None:
        """执行一次复习，更新 SM-2 参数。"""
        key = f"{student_id}::{concept}"
        card = self._cards.get(key)
        if card is None:
            return None
        card.schedule(quality)
        return card

    def get_due_cards(self, student_id: str, max_count: int = 20) -> list[FlashCard]:
        """获取到期待复习的闪卡。"""
        now = datetime.now(timezone.utc)
        due: list[FlashCard] = []
        for key, card in self._cards.items():
            if not key.startswith(f"{student_id}::"):
                continue
            if card.next_review_at:
                try:
                    review_time = datetime.fromisoformat(card.next_review_at)
                    if review_time <= now:
                        due.append(card)
                except (ValueError, TypeError):
                    due.append(card)
        # 按间隔从短到长排序（紧迫优先）
        due.sort(key=lambda c: c.next_review_at or "")
        return due[:max_count]

    def get_all_cards(self, student_id: str) -> list[FlashCard]:
        return [
            card for key, card in self._cards.items()
            if key.startswith(f"{student_id}::")
        ]

    def to_dict(self, student_id: str) -> list[dict[str, Any]]:
        return [card.to_dict() for card in self.get_all_cards(student_id)]


# 全局单例
_SM2_ENGINE: SM2Engine | None = None


def get_sm2_engine() -> SM2Engine:
    global _SM2_ENGINE
    if _SM2_ENGINE is None:
        _SM2_ENGINE = SM2Engine()
    return _SM2_ENGINE
