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


def sm2_update_easiness(e: float, q: float) -> float:
    """SM-2 易度因子更新公式。

    E' = max(1.3, E + (0.1 - (5-q)) * (0.08 + (5-q) * 0.02))

    Args:
        e: 当前易度因子
        q: 质量评分 [0.0, 5.0]

    Returns:
        更新后的易度因子 (>= 1.3)
    """
    delta = 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)
    return max(SM2_E_MIN, e + delta)


def calculate_act_r_decay(cognitive_load: float, frustration: float) -> float:
    """根据 ACT-R 理论计算动态记忆衰减率 d (通常范围在 0.3 到 0.7 之间，默认值为 0.5)"""
    # 结合认知负荷与情感状态，利用 Sigmoid 映射到 [0.3, 0.7] 区间
    # 负荷和挫败感越高，大脑的瞬时记忆半衰期越短，表现为衰减率 d 升高
    x = (cognitive_load + frustration) - 0.5
    sigmoid_val = 1.0 / (1.0 + math.exp(-6.0 * x))
    d = 0.3 + 0.4 * sigmoid_val
    return max(0.3, min(0.7, d))


def sm2_next_interval(
    interval: int,
    q: float,
    e: float,
    cognitive_load: float = 0.45,
    frustration: float = 0.0,
) -> int:
    """自适应复习间隔：底层切换为 FSRS (DSR) 核心记忆状态方程，并通过 ACT-R 情感状态自适应调节。

    - q < 4.0: 记错/困难，重置为 1 天。
    - q >= 4.0: 正常/简单，利用 FSRS 核心稳定性公式演进并结合心智状态缩放。
    """
    if q < 4.0:
        return 1  # 重置

    # 1. 易度因子 e 映射为 FSRS 难度 D (e越大代表难度越低，映射到 1.0~10.0 空间)
    D = max(1.0, min(10.0, 11.0 - 2.0 * e))

    # 2. 当前复习间隔作为当前稳定性 S
    S = max(0.1, float(interval))

    # 3. 映射评分 q 为 FSRS rating r (Again=1, Good=3, Easy=4)
    #    q = 4.0 -> r = 3 (Good); q = 5.0 -> r = 4 (Easy)
    r = 4 if q >= 4.5 else 3

    # 4. 计算 Retrievability R = 0.9 ** (t / S)
    #    设在到期日复习，故 t = S, R = 0.9
    R = 0.9

    # 5. 考虑情绪状态（挫败感）对难度的动态惩罚
    D_adj = max(1.0, min(10.0, D + frustration * 2.0))
    
    # 6. 计算 FSRS 稳定性 S' (FSRS 核心公式：Good/Easy 稳定性增长，Difficulty 越大增长越慢)
    S_new = S * (1.0 + math.exp(2.0 - 0.2 * D_adj) * (S ** -0.2) * (0.9 - R + 1.0))

    # 7. 结合 ACT-R 记忆衰减模型计算最终间隔缩放
    d = calculate_act_r_decay(cognitive_load, frustration)
    multiplier = (0.5 / d) ** 1.5
    multiplier = max(0.5, min(2.0, multiplier))

    return max(1, round(S_new * multiplier))


def sm2_schedule(
    e: float,
    interval: int,
    q: float,
    cognitive_load: float = 0.45,
    frustration: float = 0.0,
) -> tuple[float, int]:
    """完整自适应 SM-2 调度：同时考虑作答质量与认知负荷、挫败感。"""
    new_e = sm2_update_easiness(e, q)

    # 情感自适应调节：当挫败感过高时，平滑地对易度因子进行负向减调以防双重惩罚
    if frustration > 0.4:
        new_e = max(SM2_E_MIN, new_e - (frustration - 0.4) * 0.15)

    new_interval = sm2_next_interval(
        interval, q, new_e,
        cognitive_load=cognitive_load,
        frustration=frustration,
    )
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

    def schedule(
        self,
        quality: float,
        cognitive_load: float = 0.45,
        frustration: float = 0.0,
    ) -> None:
        """根据质量评分与学生画像状态（认知负荷、挫败感）动态更新复习参数。"""
        try:
            q = max(0.0, min(5.0, float(quality)))
        except (TypeError, ValueError):
            q = 4.0

        self.easiness, self.interval_days = sm2_schedule(
            self.easiness,
            self.interval_days,
            q,
            cognitive_load=cognitive_load,
            frustration=frustration,
        )
        self.last_quality = int(round(q))
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
        from collections import OrderedDict
        class BoundedDict(OrderedDict):
            def __init__(self, max_size=500, *args, **kwargs):
                self.max_size = max_size
                super().__init__(*args, **kwargs)

            def __setitem__(self, key, value):
                super().__setitem__(key, value)
                if len(self) > self.max_size:
                    self.popitem(last=False)

        self._cards = BoundedDict(max_size=500)  # concept -> FlashCard

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
