"""任务 10.1: 学情交互诊断事件总线 (LearningEventBus)

消除答题评测系统与对话大模型之间的数据隔离，
引入进程内异步事件总线统一分发学情事件。

核心组件：
1. QuizAttemptedEvent — 标准化答题事件
2. LearningEventBus — 进程内异步事件总线 (pub/sub)
3. ProfileHistorySubscriber — 全局订阅器，自动写入 StudentProfile.history
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine


# ============================================================
# 标准化事件定义
# ============================================================


@dataclass(frozen=True)
class QuizAttemptedEvent:
    """标准化答题事件。

    由答题评测接口在计算完成后自动发布。
    """
    student_id: str
    concept: str
    accuracy: float          # 正确率 0.0~1.0
    ai_confidence: float     # AI 对评分的确信度 0.0~1.0
    student_confidence: float  # 学生自评置信度 0.0~1.0
    attempt_number: int      # 答题次数
    question: str = ""       # 题目内容（摘要）
    answer: str = ""         # 学生答案（摘要）
    session_id: str = ""     # 会话 ID
    quiz_id: str = ""        # 测验记录 ID
    timestamp: str = field(default_factory=lambda: (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ))

    def to_profile_log(self) -> str:
        """格式化为可追加到 StudentProfile.history 的日志字符串。"""
        return (
            f"[Quiz:{self.quiz_id or 'manual'}] "
            f"概念={self.concept} "
            f"正确率={self.accuracy:.2f} "
            f"AI置信度={self.ai_confidence:.2f} "
            f"自评置信度={self.student_confidence:.2f} "
            f"第{self.attempt_number}次 "
            f"时间={self.timestamp}"
        )


@dataclass(frozen=True)
class ProfileUpdatedEvent:
    """画像更新事件：当 StudentProfile 发生变更时触发。"""
    student_id: str
    field: str               # 变更的字段名
    old_value: Any = None
    new_value: Any = None
    timestamp: str = field(default_factory=lambda: (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ))


# 所有支持的事件类型
EventType = QuizAttemptedEvent | ProfileUpdatedEvent


# ============================================================
# 异步事件订阅器类型
# ============================================================

EventHandler = Callable[[EventType], Coroutine[Any, Any, None]]


# ============================================================
# LearningEventBus — 进程内异步事件总线
# ============================================================


class LearningEventBus:
    """进程内异步事件总线 (单例模式)。

    用法:
        bus = LearningEventBus.get_instance()
        bus.subscribe("quiz_attempted", my_handler)
        await bus.publish(QuizAttemptedEvent(...))
    """

    _instance: LearningEventBus | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._event_log: list[EventType] = []  # 事件日志（用于调试/回溯）

    @classmethod
    def get_instance(cls) -> LearningEventBus:
        """获取全局单例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """订阅指定类型的事件。

        Args:
            event_type: 事件类型名称，如 "quiz_attempted", "profile_updated"
            handler: 异步回调函数，接收 EventType 参数
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """取消订阅。"""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h is not handler
            ]

    async def publish(self, event: EventType) -> None:
        """发布事件到总线，触发所有已注册的订阅器。

        所有订阅器并发执行，单个失败不影响其他。
        """
        # 确定事件类型名称
        event_type = self._resolve_event_type(event)

        # 记录事件日志
        self._event_log.append(event)
        if len(self._event_log) > 1000:
            self._event_log = self._event_log[-500:]

        # 并发触发订阅器
        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            return

        results = await asyncio.gather(
            *[handler(event) for handler in handlers],
            return_exceptions=True,
        )

        # 记录失败但不抛出
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                import logging
                logging.getLogger(__name__).warning(
                    "EventBus handler %s failed for event %s: %s",
                    handlers[i].__name__,
                    event_type,
                    result,
                )

    def get_event_log(self, max_count: int = 50) -> list[EventType]:
        """获取最近的事件日志。"""
        return self._event_log[-max_count:]

    @staticmethod
    def _resolve_event_type(event: EventType) -> str:
        """将事件对象映射到字符串类型名。"""
        if isinstance(event, QuizAttemptedEvent):
            return "quiz_attempted"
        if isinstance(event, ProfileUpdatedEvent):
            return "profile_updated"
        return "unknown"


# ============================================================
# 全局订阅器：ProfileHistorySubscriber
# ============================================================


async def _on_quiz_attempted(event: QuizAttemptedEvent) -> None:
    """答题事件订阅器：将标准化答题记录写入 StudentProfile.history。

    此订阅器被 LearningEventBus 自动注册。
    当 Quiz API 发布 QuizAttemptedEvent 后，自动格式化并追加到画像历史。
    """
    # 导入推迟以避免循环依赖
    from swarm_factory import build_swarm_from_headers

    # 构建 swarm 以获取 profile_store
    swarm = build_swarm_from_headers({})
    profile = swarm.profile_store.get(event.student_id)
    if profile is None:
        return

    # 写入 history
    log_entry = event.to_profile_log()
    profile.history.append(log_entry)

    # 更新 recent_quiz_accuracy
    if event.concept not in profile.recent_quiz_accuracy:
        profile.recent_quiz_accuracy[event.concept] = []
    profile.recent_quiz_accuracy[event.concept].append(event.accuracy)
    # 只保留最近 3 次
    if len(profile.recent_quiz_accuracy[event.concept]) > 3:
        profile.recent_quiz_accuracy[event.concept] = (
            profile.recent_quiz_accuracy[event.concept][-3:]
        )

    # 同步到 BKT 引擎
    try:
        from agent_swarm import _get_bkt_engine
        bkt = _get_bkt_engine()
        
        # 1. 动态对答题分类到不同认知层级
        question_text = (event.question or "").lower()
        dimension = "factual"
        if any(k in question_text for k in ("代码", "code", "def ", "import", "class", "function")):
            dimension = "code"
        elif any(k in question_text for k in ("公式", "求导", "偏导", "计算", "推导", "数学", "equation", "+", "-", "*", "/", "=")):
            dimension = "math"
        elif any(k in question_text for k in ("迁移", "类比", "比喻", "场景", "应用", "transfer", "analogy")):
            dimension = "transfer"
            
        bkt.update(
            event.concept,
            correct=event.accuracy >= 0.6,
            cognitive_load=getattr(profile, "cognitive_load", 0.45),
            frustration=getattr(profile, "frustration_index", 0.0),
            profile_bkt_states=profile.bkt_states,
            dimension=dimension
        )
        # 也同步到 profile.bkt_states 和 profile.concept_layers
        snapshot = bkt.snapshot()
        if event.concept in snapshot:
            profile.bkt_states[event.concept] = snapshot[event.concept]
            layers_snap = snapshot[event.concept].get("layers", {})
            if layers_snap:
                if not getattr(profile, "concept_layers", None):
                    profile.concept_layers = {}
                profile.concept_layers[event.concept] = {
                    l: round(layers_snap[l].get("smoothed_mastery", 0.3), 4)
                    for l in layers_snap
                }
    except Exception:
        pass


def register_default_subscribers(bus: LearningEventBus | None = None) -> LearningEventBus:
    """注册全局默认订阅器。

    在系统启动时调用一次即可。
    """
    if bus is None:
        bus = LearningEventBus.get_instance()

    bus.subscribe("quiz_attempted", _on_quiz_attempted)
    return bus


# ============================================================
# 便捷包装函数（供 quiz_api 直接调用）
# ============================================================


async def publish_quiz_event(
    student_id: str,
    concept: str,
    accuracy: float,
    ai_confidence: float,
    student_confidence: float,
    attempt_number: int = 1,
    question: str = "",
    answer: str = "",
    session_id: str = "",
    quiz_id: str = "",
) -> None:
    """便捷函数：发布答题事件。

    供 quiz_api.py 的 evaluate_answer 端点调用。
    """
    event = QuizAttemptedEvent(
        student_id=student_id,
        concept=concept,
        accuracy=accuracy,
        ai_confidence=ai_confidence,
        student_confidence=student_confidence,
        attempt_number=attempt_number,
        question=question,
        answer=answer,
        session_id=session_id,
        quiz_id=quiz_id,
    )
    bus = LearningEventBus.get_instance()
    await bus.publish(event)
