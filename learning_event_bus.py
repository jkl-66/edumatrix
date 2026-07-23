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
import threading

_DB_WRITE_LOCK = threading.Lock()


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
    answer: str = ""         # 学生答案（摘要)
    session_id: str = ""     # 会话 ID
    quiz_id: str = ""        # 测验记录 ID
    duration_seconds: float | None = None  # 答题时长
    timestamp: str = field(default_factory=lambda: (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ))

    def to_profile_log(self) -> str:
        """格式化为可追加到 StudentProfile.history 的日志字符串。"""
        dur_str = f" 耗时={self.duration_seconds:.1f}秒" if self.duration_seconds is not None else ""
        return (
            f"[Quiz:{self.quiz_id or 'manual'}] "
            f"概念={self.concept} "
            f"正确率={self.accuracy:.2f} "
            f"AI置信度={self.ai_confidence:.2f} "
            f"自评置信度={self.student_confidence:.2f} "
            f"第{self.attempt_number}次"
            f"{dur_str} "
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

        # M1 compatibility layer: preserve the in-process API while recording
        # a durable, versioned event envelope. Persistence failure must not
        # break existing subscribers, but is logged for diagnosis.
        try:
            from app.database import run_db_op
            from app.m1_lifecycle import persist_legacy_learning_event

            await run_db_op(persist_legacy_learning_event, event, event_type)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Learning event persistence failed for %s: %s", event_type, exc
            )

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


from concurrent.futures import ThreadPoolExecutor

_ALGO_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="EduMatrix_Algo_Worker")


def _run_offline_cognition_pipeline(profile: StudentProfile, event: QuizAttemptedEvent) -> StudentProfile:
    """在后台线程中计算 DKT + BKT 状态，并保存至数据库（解决同步锁 and 高并发响应延迟）"""
    from app.database import SessionLocal, DBQuizRecord
    from app.crud import save_student_profile
    from models import ProfileEvidence, ProfileEvidenceSource, LearningStateCause
    
    # 动态追加答题行为特征至 10 维画像证据链中
    features = {event.concept}
    if event.accuracy < 0.55:
        features.add(LearningStateCause.PREREQUISITE_GAP.value)
    if event.duration_seconds and event.duration_seconds > 45:
        features.add(LearningStateCause.COGNITIVE_LOAD.value)
    if abs(event.student_confidence - event.accuracy) >= 0.28:
        features.add(LearningStateCause.METACOGNITIVE_MISMATCH.value)
        
    evidence = ProfileEvidence(
        source=ProfileEvidenceSource.STUDENT_FEEDBACK,
        text=f"自适应评测 [{event.concept}]: 得分={event.accuracy:.2f}, 耗时={event.duration_seconds or 0:.1f}s",
        features=tuple(sorted(features)),
        weight=0.82,
        confidence=event.ai_confidence,
        timestamp=event.timestamp
    )
    if not hasattr(profile, "profile_evidence") or profile.profile_evidence is None:
        profile.profile_evidence = []
    profile.profile_evidence.append(evidence)
    
    session = SessionLocal()
    try:
        # A. 运行 DKT (深度知识追踪) 时序前瞻预测
        from bkt_engine import DktService
        
        # 结构化从数据库中查询该学生的最新 50 次答题序列，彻底免除脆弱的正则提取
        records = (
            session.query(DBQuizRecord)
            .filter(DBQuizRecord.student_id == event.student_id)
            .order_by(DBQuizRecord.created_at.asc())
            .limit(50)
            .all()
        )
        dkt_history = []
        for r in records:
            if not r.target_concept:
                continue
            if "与" in r.target_concept:
                for sub in r.target_concept.split("与"):
                    if sub.strip():
                        dkt_history.append((sub.strip(), r.accuracy_score >= 0.6))
            elif "和" in r.target_concept:
                for sub in r.target_concept.split("和"):
                    if sub.strip():
                        dkt_history.append((sub.strip(), r.accuracy_score >= 0.6))
            else:
                dkt_history.append((r.target_concept, r.accuracy_score >= 0.6))
        
        # 运行 DKT 推理与增量微调
        dkt_service = DktService()
        extra_concepts = list(profile.concept_mastery.keys()) if (profile and getattr(profile, "concept_mastery", None)) else []
        dkt_mastery_preds = dkt_service.predict_mastery(dkt_history, extra_concepts=extra_concepts, student_bias=getattr(profile, "dkt_bias", None))
        try:
            dkt_service.train_incremental(dkt_history, profile=profile)
        except Exception as t_err:
            import logging
            logging.getLogger(__name__).warning(f"DKT incremental training failed: {t_err}")
        
        # 软融合：20% DKT时序预测值 + 80% 原始/BKT 结果
        for concept, dkt_val in dkt_mastery_preds.items():
            if concept in profile.concept_mastery:
                current_val = profile.concept_mastery[concept]
                profile.concept_mastery[concept] = round(current_val * 0.8 + dkt_val * 0.2, 4)

        # B. 运行 BKT + 1D 自适应卡尔曼去噪
        from agent_swarm import _get_bkt_engine
        bkt = _get_bkt_engine()
        
        question_text = (event.question or "").lower()
        dimension = "factual"
        if any(k in question_text for k in ("代码", "code", "def ", "import", "class", "function")):
            dimension = "code"
        elif any(k in question_text for k in ("公式", "求导", "偏导", "计算", "推导", "数学", "equation", "+", "-", "*", "/", "=")):
            dimension = "math"
        elif any(k in question_text for k in ("迁移", "类比", "比喻", "场景", "应用", "transfer", "analogy")):
            dimension = "transfer"
            
        concepts = []
        if "与" in event.concept:
            concepts = [sub.strip() for sub in event.concept.split("与") if sub.strip()]
        elif "和" in event.concept:
            concepts = [sub.strip() for sub in event.concept.split("和") if sub.strip()]
        else:
            concepts = [event.concept]

        for c in concepts:
            bkt.update(
                c,
                correct=event.accuracy >= 0.6,
                cognitive_load=getattr(profile, "cognitive_load", 0.45),
                frustration=getattr(profile, "frustration_index", 0.0),
                profile_bkt_states=profile.bkt_states,
                dimension=dimension,
                duration_seconds=event.duration_seconds,
            )
            
            snapshot = bkt.snapshot()
            if c in snapshot:
                profile.bkt_states[c] = snapshot[c]
                layers_snap = snapshot[c].get("layers", {})
                if layers_snap:
                    if not getattr(profile, "concept_layers", None):
                        profile.concept_layers = {}
                    profile.concept_layers[c] = {
                        l: round(layers_snap[l].get("smoothed_mastery", 0.3), 4)
                        for l in layers_snap
                    }

        # D. 刷新 10 维动力画像与不会成因
        profile._refresh_dynamic_profile()

        # C. 持久化写入 SQLite (WAL) - 使用全局线程锁规避 SQLite 并发写入冲突
        with _DB_WRITE_LOCK:
            try:
                save_student_profile(session, profile)
                session.commit()
            except Exception as db_err:
                session.rollback()
                import logging
                logging.getLogger(__name__).error(f"Async DB writeback failed: {db_err}")
            finally:
                session.close()
            
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(f"Offline cognition pipeline failed: {exc}")
        
    return profile


async def _on_quiz_attempted(event: QuizAttemptedEvent) -> None:
    """答题事件订阅器：将标准化答题记录写入 StudentProfile.history。
    
    采用异步线程池隔离 heavy 算法（DKT/BKT）与 DB IO，保障接口响应时间不超过 1ms。
    """
    from swarm_factory import build_swarm_from_headers, _swarm_cache
    from app.crud import load_student_profile
    from app.database import SessionLocal

    # 1. 找到所有缓存了该学生 profile 的 swarm 实例，保证多实例内存一致性
    profiles_to_update = []
    for sw in _swarm_cache.values():
        p = sw.profile_store.get(event.student_id)
        if p is not None:
            profiles_to_update.append(p)
            
    # 如果内存缓存中没有任何该学生的 profile，从 DB 加载一个临时的
    db_loaded = False
    if not profiles_to_update:
        session = SessionLocal()
        try:
            p = load_student_profile(session, event.student_id)
            if p:
                profiles_to_update.append(p)
                db_loaded = True
        finally:
            session.close()

    if not profiles_to_update:
        return

    # 2. 快速写入内存画像历史与近 3 次答题正确率，保证同步读请求一致性
    for profile in profiles_to_update:
        log_entry = event.to_profile_log()
        profile.history.append(log_entry)

        concepts = []
        if "与" in event.concept:
            concepts = [sub.strip() for sub in event.concept.split("与") if sub.strip()]
        elif "和" in event.concept:
            concepts = [sub.strip() for sub in event.concept.split("和") if sub.strip()]
        else:
            concepts = [event.concept]

        for c in concepts:
            if c not in profile.recent_quiz_accuracy:
                profile.recent_quiz_accuracy[c] = []
            profile.recent_quiz_accuracy[c].append(event.accuracy)
            if len(profile.recent_quiz_accuracy[c]) > 3:
                profile.recent_quiz_accuracy[c] = profile.recent_quiz_accuracy[c][-3:]

    # 3. 拷贝一份副本并在异步线程池中运行 DKT/BKT 算法以保证内存一致性 (Copy-on-Write)
    primary_profile = profiles_to_update[0]
    import copy
    profile_copy = copy.deepcopy(primary_profile)

    import sys
    is_testing = "pytest" in sys.modules or "unittest" in sys.modules
    
    if is_testing:
        updated = _run_offline_cognition_pipeline(profile_copy, event)
        if updated:
            for p in profiles_to_update:
                p.concept_mastery.update(updated.concept_mastery)
                p.bkt_states.update(updated.bkt_states)
                p.concept_layers.update(updated.concept_layers)
                p.profile_evidence = list(updated.profile_evidence)
                p.dimension_states = dict(updated.dimension_states)
                p.learning_state_causes = dict(updated.learning_state_causes)
                if hasattr(updated, "dkt_bias"):
                    p.dkt_bias = updated.dkt_bias
    else:
        async def run_bg():
            loop = asyncio.get_running_loop()
            updated = await loop.run_in_executor(_ALGO_EXECUTOR, _run_offline_cognition_pipeline, profile_copy, event)
            # 在主协程线程中安全合并画像状态更新，规避字典多线程写冲突
            if updated:
                for p in profiles_to_update:
                    p.concept_mastery.update(updated.concept_mastery)
                    p.bkt_states.update(updated.bkt_states)
                    p.concept_layers.update(updated.concept_layers)
                    p.profile_evidence = list(updated.profile_evidence)
                    p.dimension_states = dict(updated.dimension_states)
                    p.learning_state_causes = dict(updated.learning_state_causes)
                    if hasattr(updated, "dkt_bias"):
                        p.dkt_bias = updated.dkt_bias
        asyncio.create_task(run_bg())


async def _on_profile_updated(event: ProfileUpdatedEvent) -> None:
    """画像更新事件订阅器：当学生画像手动/增量更新时，自动追加历史变动记录到 profile.history，保持多端内存和物理库的一致性。"""
    from swarm_factory import _swarm_cache
    from app.crud import load_student_profile, save_student_profile
    from app.database import SessionLocal

    # 1. 找到所有缓存了该学生 profile 的 swarm 实例，保证多实例内存一致性
    profiles_to_update = []
    for sw in _swarm_cache.values():
        p = sw.profile_store.get(event.student_id)
        if p is not None:
            profiles_to_update.append(p)
            
    # 如果内存缓存中没有任何该学生的 profile，从 DB 加载一个临时的
    if not profiles_to_update:
        session = SessionLocal()
        try:
            p = load_student_profile(session, event.student_id)
            if p:
                profiles_to_update.append(p)
        finally:
            session.close()

    if not profiles_to_update:
        return

    # 2. 格式化画像修改的痕迹日志
    log_entry = f"[ProfileUpdate:{event.field}] 新值={event.new_value} 时间={event.timestamp}"
    
    # 规避重复写入
    for profile in profiles_to_update:
        if log_entry not in profile.history:
            profile.history.append(log_entry)
            if len(profile.history) > 500:
                profile.history = profile.history[-300:]

    # 3. 异步/同步写回至 DB 存储，保证持久化一致性
    primary_profile = profiles_to_update[0]
    import sys
    is_testing = "pytest" in sys.modules or "unittest" in sys.modules

    def save_history():
        session = SessionLocal()
        try:
            with _DB_WRITE_LOCK:
                save_student_profile(session, primary_profile)
                session.commit()
        except Exception as db_err:
            session.rollback()
            import logging
            logging.getLogger(__name__).error(f"Async DB writeback failed for ProfileUpdatedEvent: {db_err}")
        finally:
            session.close()

    if is_testing:
        save_history()
    else:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_ALGO_EXECUTOR, save_history)


def register_default_subscribers(bus: LearningEventBus | None = None) -> LearningEventBus:
    """注册全局默认订阅器。

    在系统启动时调用一次即可。
    """
    if bus is None:
        bus = LearningEventBus.get_instance()

    bus.subscribe("quiz_attempted", _on_quiz_attempted)
    bus.subscribe("profile_updated", _on_profile_updated)
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
    duration_seconds: float | None = None,
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
        duration_seconds=duration_seconds,
    )
    bus = LearningEventBus.get_instance()
    await bus.publish(event)
