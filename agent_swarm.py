from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
import json
import re

from config import CONFIG
from concurrency import AsyncWorkerPool
from drag_debate import DebateAugmentedRAG
from instruct_rag import AsyncInstructRAGGenerator, InstructRAGGenerator
from learning_strategy import LearningStrategyEngine
from llm_client import (
    AsyncLLMBackend,
    DEFAULT_ASYNC_LLM,
    DEFAULT_LLM,
    LLMBackend,
)
from manifold_alignment import ManifoldAlignmentVerifier
from models import AgentOutput, LearningSignal, LearningStrategyPlan, ResourcePackage, StudentProfile
from observability import TELEMETRY, timed_span
from rag_engine import HybridRAGPipeline, hybrid_rag


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    band: str
    responsibility: str


AGENT_MATRIX: tuple[AgentSpec, ...] = (
    AgentSpec("tutor", "苏格拉底导师", "Interaction Hub", "唯一前台入口、意图识别、Handoff 路由"),
    AgentSpec("profile", "画像探针", "Cognitive Governance", "自然语言抽取 10 维动态画像、证据、置信度与不会原因占比"),
    AgentSpec("planner", "路径规划师", "Cognitive Governance", "基于 GraphRAG 与 ZPD 规划学习路径"),
    AgentSpec("evaluator", "量化评估师", "Cognitive Governance", "回收题目、沙盒、学生反馈与画像状态，触发重规划"),
    AgentSpec("theory", "理论教授", "Resource Factory", "生成证据驱动专业讲义"),
    AgentSpec("mapper", "逻辑画师", "Resource Factory", "生成 Mermaid 思维导图"),
    AgentSpec("coder", "极客助教", "Resource Factory", "生成可运行代码实操案例"),
    AgentSpec("quiz", "考官智能体", "Resource Factory", "生成分层练习题与解析"),
    AgentSpec("director", "虚拟导演", "Resource Factory", "生成讯飞虚拟人/TTS 脚本"),
)


def _build_conversation_memory(profile: StudentProfile, max_turns: int = 6) -> str:
    if not profile.history:
        return ""
    recent = profile.history[-(max_turns * 2):]
    turns = []
    for i in range(0, len(recent), 2):
        user_msg = recent[i]
        turns.append(f"学生: {user_msg[:200]}")
    return "\n".join(turns[-max_turns:])


# 口语指代消解知识库：模糊指代 -> 可能映射的核心知识点前缀
_COREFERENCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "这个": ("逻辑回归", "池化层", "卷积核", "反向传播", "梯度下降", "Transformer",
             "线性回归", "决策树", "支持向量机", "过拟合", "正则化"),
    "这类": ("逻辑回归", "池化层", "卷积核", "反向传播", "梯度下降",
             "分类算法", "回归算法", "优化方法"),
    "这个代码": ("PyTorch", "TensorFlow", "代码实操", "编程实现"),
    "这个公式": ("链式法则", "梯度下降", "损失函数", "激活函数", "Softmax"),
    "怎么算": ("梯度下降", "反向传播", "链式法则", "卷积运算", "池化计算"),
    "怎么用": ("逻辑回归", "线性回归", "决策树", "支持向量机"),
    "为什么": ("反向传播", "梯度下降", "过拟合", "损失函数"),
    "应用场景": ("逻辑回归", "决策树", "支持向量机", "卷积神经网络"),
    "它的": (),
    "这个图": ("特征图", "计算图", "网络结构图"),
    "梯度下降这类": ("梯度下降", "优化算法", "SGD", "Adam"),
}


def _resolve_coreference(
    message: str,
    existing_concepts: list[str],
    history_context: str,
) -> str:
    """口语指代消解：将模糊指代归一化为已追踪的核心知识点。

    Args:
        message: 学生最新输入
        existing_concepts: 已追踪的知识点列表
        history_context: 最近 N 条历史对话文本

    Returns:
        消解后的消息文本（模糊指代被替换为具体概念名）
    """
    resolved = message

    # 策略1：基于关键词知识库的直接替换
    for fuzzy_phrase, targets in _COREFERENCE_KEYWORDS.items():
        if fuzzy_phrase in resolved:
            # 在已有的知识点中查找最可能的匹配
            candidates = [c for c in existing_concepts if c.lower() in history_context.lower()]
            if not candidates and targets:
                # 从知识库的目标列表中找历史上下文里出现过的
                candidates = [t for t in targets if t.lower() in history_context.lower()]
            if not candidates and targets:
                # 兜底：使用知识库的第一个
                candidates = [targets[0]]
            if candidates:
                resolved = resolved.replace(fuzzy_phrase, candidates[0], 1)

    # 策略2：对独立的模糊代词 "它" "这个" "这类" 进行上下文推断
    # 从历史上下文中提取最后3个提及的知识点
    history_concepts = [c for c in existing_concepts if c.lower() in history_context.lower()]
    for pronoun in ("它", "这个", "这类"):
        # 仅当代词以独立词出现时才替换（非嵌入在其他词中）
        pattern = re.compile(rf'(?<!\w){pronoun}(?!\w)')
        if pattern.search(resolved) and history_concepts:
            # 用最近提及的知识点替换
            resolved = pattern.sub(history_concepts[-1], resolved, count=1)

    return resolved


class ProfileProbeAgent:
    """画像探针智能体。

    任务 7.2 升级：3轮滑动上下文窗口 + 口语指代消解。
    """

    def __init__(self, llm: AsyncLLMBackend = DEFAULT_ASYNC_LLM):
        self.llm = llm
        # 滑动上下文窗口：保存最近 3 轮的消息对 (user, assistant)
        self._context_window: list[tuple[str, str]] = []

    def update(self, profile: StudentProfile, message: str) -> StudentProfile:
        profile.update_from_message(message)
        return profile

    def _get_sliding_context(self, profile: StudentProfile, window_size: int = 3) -> str:
        """构建 3 轮滑动上下文窗口。

        从 profile.history 中取最近 (window_size * 2) 条消息，
        排除当前的最后一条，组合成可读的上下文文本。
        """
        if len(profile.history) < 2:
            return ""
        # 取倒数第 2 到倒数第 (window_size*2) 条消息
        context_size = min(window_size * 2, len(profile.history) - 1)
        recent = profile.history[-(context_size + 1):-1]
        lines = []
        for i, msg in enumerate(recent):
            role = "学生" if i % 2 == 0 else "系统"
            lines.append(f"[{role}]: {msg.replace(chr(10), ' ')[:120]}")
        return "\n".join(lines[-6:])  # 最多 3 轮对话

    async def async_update(self, profile: StudentProfile, message: str) -> StudentProfile:
        # Step 1: 基础更新（触发情感推断、特征提取等）
        profile.update_from_message(message)

        # Step 2: 获取已追踪的知识点列表
        existing_concepts = list(profile.concept_mastery.keys())

        # Step 3: 构建 3 轮滑动上下文窗口
        sliding_context = self._get_sliding_context(profile, window_size=3)

        # Step 4: ✅ 口语指代消解：将模糊代词归一化为已追踪的知识点
        resolved_message = _resolve_coreference(message, existing_concepts, sliding_context)

        # Step 5: 用消解后的消息 + 滑动上下文 调用 LLM 抽取
        extracted = await self._async_extract_with_llm(
            resolved_message, existing_concepts, sliding_context,
        )
        profile.apply_llm_features(extracted, source_text=message)
        return profile

    async def _async_extract_with_llm(
        self,
        message: str,
        existing_concepts: list[str] | None = None,
        history_context: str = "",
    ) -> dict:
        import re
        import json

        # 将已有的知识点拼接成字符串
        existing_keys_str = ", ".join(existing_concepts) if existing_concepts else "暂无"

        system_prompt = (
            "你是 EduMatrix 的画像抽取器，只能输出 JSON。\n"
            "字段包括 course, major, goals, weak_points(必须是字符串数组), preferences, "
            "learning_state_causes, mastery_updates。\n"
            "learning_state_causes 只能使用 prerequisite_gap, misconception, cognitive_load, "
            "strategy_gap, metacognitive_mismatch, affective_barrier, interaction_mismatch。\n"
            "【核心任务】：深入分析学生的语义倾向和情绪，并在 mastery_updates 中打分。\n"
            "⚠️ 【指代已消解】：输入中的模糊指代已由前置处理器归一化为具体实体词。\n"
            "⚠️ 【上下文对齐规则】：\n"
            f"1. 当前系统已追踪的知识点字典为：[{existing_keys_str}]\n"
            "2. weak_points 和 mastery_updates 中的实体必须从已追踪字典中选取，\n"
            "   除非遇到完全全新的专业名词，否则禁止创建新实体。\n"
            "3. 所有实体必须是最精简的核心名词。\n"
            "示例输出：{\"weak_points\": [\"逻辑回归\"], \"mastery_updates\": {\"逻辑回归\": 0.35}}"
        )

        context_str = f"【历史上下文(3轮滑动窗口)】：\n{history_context}\n" if history_context else ""
        user_prompt = (
            f"{context_str}"
            f"固定课程为机器学习导论。\n"
            f"【已指代消解的学生输入】：{message}\n"
            "请从中抽取画像特征，仅输出 JSON。"
        )

        try:
            raw = await self.llm.generate(system_prompt, user_prompt, role="画像抽取器")
            match = re.search(r"\{.*\}", raw, flags=re.S)
            if not match:
                return {}
            data = json.loads(match.group(0))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}


# 全局 BKT 引擎单例（惰性初始化）
_BKT_ENGINE: "BKTEngine | None" = None


def _get_bkt_engine():
    """获取全局 BKT 引擎单例。"""
    global _BKT_ENGINE
    if _BKT_ENGINE is None:
        from bkt_engine import BKTEngine
        _BKT_ENGINE = BKTEngine()
    return _BKT_ENGINE


# DAG 知识依赖图谱：concept -> [prerequisites]
DEFAULT_KNOWLEDGE_DAG: dict[str, list[str]] = {
    "池化层": ["卷积核", "特征图"],
    "最大池化": ["池化层"],
    "平均池化": ["池化层"],
    "卷积核": ["反向传播"],
    "特征图": ["卷积核"],
    "反向传播": ["链式法则", "梯度下降"],
    "链式法则": ["梯度下降"],
    "梯度下降": ["线性回归"],
    "逻辑回归": ["线性回归", "梯度下降"],
    "线性回归": ["机器学习"],
    "决策树": ["机器学习"],
    "支持向量机": ["线性回归", "机器学习"],
    "过拟合": ["正则化", "交叉验证"],
    "正则化": ["线性回归"],
    "交叉验证": ["机器学习"],
    "机器学习": [],
    "监督学习": ["机器学习"],
    "数据预处理": ["机器学习"],
    "特征工程": ["数据预处理"],
    "模型评估": ["机器学习"],
    "混淆矩阵": ["模型评估"],
    "Transformer": ["注意力机制", "反向传播"],
    "注意力机制": ["神经网络"],
    "神经网络": ["反向传播", "梯度下降"],
    "卷积神经网络": ["神经网络", "卷积核", "池化层"],
}


class ZPDPlannerAgent:
    """ZPD（最近发展区）路径规划智能体。

    任务 7.1 核心升级：
    - 使用 BKT 引擎计算掌握概率（替代简单的 concept_mastery 查询）
    - ZPD 区间 [0.3, 0.75] + 前置依赖回滚机制
    - Poincaré 双曲距离过渡跳转
    - 返回 ZPD 路径计划供后续处置
    """

    def __init__(self):
        self._last_path_plan: dict | None = None

    def plan(self, rag: HybridRAGPipeline, query: str, profile: StudentProfile):
        """执行 ZPD 路径规划。"""
        from bkt_engine import (
            BKTEngine,
            get_zpd_path_plan,
            find_nearest_concept,
            poincare_to_2d_coordinates,
            poincare_distance,
            project_to_ball,
        )

        # 确定目标知识点
        target = self._infer_target(profile)

        # Step 1: 使用 BKT 引擎获取掌握度
        bkt = _get_bkt_engine()
        target_mastery = bkt.get_mastery(target) if target else 0.48

        # 同时也从 profile.concept_mastery 获取参考值
        profile_mastery = profile.concept_mastery.get(target, 0.48) if target else 0.48
        # 取 BKT 和 profile 的加权平均（BKT 权重更高）
        mastery = target_mastery * 0.6 + profile_mastery * 0.4

        # Step 2: 获取前置依赖掌握度
        prereqs = DEFAULT_KNOWLEDGE_DAG.get(target, []) if target else []
        prereq_masteries: dict[str, float] = {}
        for p in prereqs:
            prereq_masteries[p] = bkt.get_mastery(p) * 0.6 + profile.concept_mastery.get(p, 0.3) * 0.4

        # Step 3: 执行 ZPD 路径规划
        path_plan = get_zpd_path_plan(
            target=target or query,
            target_mastery=mastery,
            graph_neighbors=DEFAULT_KNOWLEDGE_DAG,
            prereq_masteries=prereq_masteries,
        )
        self._last_path_plan = path_plan

        # Step 4: 增强查询词
        difficulty = path_plan.get("difficulty", "intermediate")
        rollback = path_plan.get("rollback_to")

        if difficulty == "basic":
            enhanced_query = f"{query} 基础 前置知识"
            if rollback:
                enhanced_query = f"{' '.join(rollback)} 基础概念 {query}"
        elif difficulty == "advanced":
            enhanced_query = f"{query} 进阶 应用"
        else:
            enhanced_query = query

        # Step 5: 执行检索
        retrieval = rag.retrieve(enhanced_query, target=target, profile=profile)
        return retrieval

    def get_path_plan(self) -> dict | None:
        return self._last_path_plan

    def _infer_target(self, profile: StudentProfile) -> str | None:
        if "最大池化与平均池化混淆" in profile.misconception_patterns:
            return "池化层"
        if profile.weak_points:
            for point in ("池化层", "逻辑回归", "过拟合", "反向传播", "链式法则"):
                if point in profile.weak_points:
                    return point
            return profile.weak_points[-1]
        return None


# === 任务 7.3: 多门控自适应教学策略路由器 FSM ===

class SwarmMediationMode(str, Enum):
    """Swarm 全局运行模式。"""
    NORMAL = "normal"              # 默认模式
    DEBATE_MODE = "debate_mode"   # 降维思辨讲解模式
    CHALLENGE_MODE = "challenge_mode"  # 代码进阶挑战模式


class SwarmMediationRouter:
    """多门控自适应 FSM 路由器 (SwarmMediationRouter)。

    任务 7.3 核心设计：
    剥离大模型决策层不确定性，通过硬规则切换多智能体 Swarm 全局运行模式。

    Mode 1 - DEBATE_MODE:
        触发条件：同一薄弱点连续 2 次答题正确率 < 0.55
        动作：强制切换为辩论模式，激活 VisualizerAgent + SocraticDebaterAgent

    Mode 2 - CHALLENGE_MODE:
        触发条件：目标概念连续 2 次正确率 >= 0.85 且 cognitive_load < 0.40
        动作：跳过基础讲解，切换挑战模式，激活 SandboxEvaluator
    """

    def __init__(self):
        self._current_mode: SwarmMediationMode = SwarmMediationMode.NORMAL
        # 记录每个知识点的答题正确率序列 (concept -> [accuracy, ...])
        self._accuracy_history: dict[str, list[float]] = {}
        # 计数器：连续触发保持次数
        self._mode_hold_count: int = 0

    @property
    def current_mode(self) -> SwarmMediationMode:
        return self._current_mode

    def record_attempt(self, concept: str, accuracy: float) -> None:
        """记录一次答题结果。"""
        if concept not in self._accuracy_history:
            self._accuracy_history[concept] = []
        self._accuracy_history[concept].append(accuracy)
        # 只保留最近 10 条
        if len(self._accuracy_history[concept]) > 10:
            self._accuracy_history[concept] = self._accuracy_history[concept][-10:]

    def decide_mode(
        self,
        profile: StudentProfile,
        target: str | None = None,
    ) -> SwarmMediationMode:
        """基于硬规则决策当前运行模式。

        Args:
            profile: 学生画像
            target: 当前目标知识点

        Returns:
            决策后的 Swarm 运行模式
        """
        # ——— 规则 1: DEBATE_MODE ———
        # 同一薄弱点连续 2 次答题正确率 < 0.55
        debate_triggered = False
        for concept, accuracies in self._accuracy_history.items():
            if len(accuracies) >= 2:
                last_two = accuracies[-2:]
                if all(a < 0.55 for a in last_two):
                    debate_triggered = True
                    break

        # ——— 规则 2: CHALLENGE_MODE ———
        # 目标概念连续 2 次正确率 >= 0.85 且 cognitive_load < 0.40
        challenge_triggered = False
        check_concept = target or (profile.weak_points[0] if profile.weak_points else None)
        if check_concept and check_concept in self._accuracy_history:
            accuracies = self._accuracy_history[check_concept]
            if len(accuracies) >= 2:
                last_two = accuracies[-2:]
                if all(a >= 0.85 for a in last_two) and profile.cognitive_load < 0.40:
                    challenge_triggered = True

        # ——— 模式优先级：DEBATE > CHALLENGE > NORMAL ———
        new_mode: SwarmMediationMode
        if debate_triggered:
            new_mode = SwarmMediationMode.DEBATE_MODE
        elif challenge_triggered:
            new_mode = SwarmMediationMode.CHALLENGE_MODE
        else:
            new_mode = SwarmMediationMode.NORMAL

        # 模式保持：连续 3 次相同则保持不变（防止抖动）
        if new_mode == self._current_mode:
            self._mode_hold_count += 1
        else:
            self._mode_hold_count = 0

        # 仅在模式稳定后才切换（防抖）
        if self._mode_hold_count >= 2:
            return new_mode

        self._current_mode = new_mode
        return new_mode

    def get_forced_instructions(self, mode: SwarmMediationMode) -> dict[str, str]:
        """根据当前模式返回强制注入各智能体的指令。"""
        instructions: dict[str, str] = {}

        if mode == SwarmMediationMode.DEBATE_MODE:
            instructions["visualizer"] = (
                "【系统强制指令: DEBATE_MODE】学生在此知识点连续 2 次答错。"
                "请生成 Mermaid 拓扑图或对比表，帮助学生可视化理解该概念的内部结构和边界条件。"
            )
            instructions["debater"] = (
                "【系统强制指令: DEBATE_MODE】学生在此知识点连续 2 次答错。"
                "请启动苏格拉底辩论模式，先引导学生自己解释已有理解，再反向举例暴露认知盲区。"
            )
            instructions["theory"] = (
                "【系统强制指令: DEBATE_MODE】学生在此知识点连续 2 次答错。"
                "请降低概念讲解深度，使用类比和具体例子，避免抽象公式堆砌。"
            )

        elif mode == SwarmMediationMode.CHALLENGE_MODE:
            instructions["coder"] = (
                "【系统强制指令: CHALLENGE_MODE】学生已连续 2 次高正确率且认知负荷低。"
                "请生成高难度 Python 边界测试实操任务，设计非常规边界条件（如空输入、极端值、溢出、类型转换陷阱）。"
                "禁止给出完整答案，仅提供测试框架和需求规格。"
            )
            instructions["quiz"] = (
                "【系统强制指令: CHALLENGE_MODE】学生已连续 2 次高正确率且认知负荷低。"
                "请跳过基础题，直接生成 2-3 道高级综合应用题，要求跨知识点组合运用。"
            )

        return instructions

    def to_prompt(self, mode: SwarmMediationMode) -> str:
        """生成可注入 Swarm 系统提示词的模式描述。"""
        if mode == SwarmMediationMode.NORMAL:
            return ""
        descriptions = {
            SwarmMediationMode.DEBATE_MODE: (
                "⚠️ 当前 Swarm 运行模式: 降维思辨讲解模式 (DEBATE_MODE)\n"
                "触发原因：同一薄弱点连续 2 次答题正确率 < 0.55\n"
                "强制动作：可视化智能体生成 Mermaid 拓扑图 + 苏格拉底辩论智能体双主体对撞\n"
                "目标：通过可视化降低认知门槛，通过反例辩论暴露认知盲区"
            ),
            SwarmMediationMode.CHALLENGE_MODE: (
                "⚠️ 当前 Swarm 运行模式: 代码进阶挑战模式 (CHALLENGE_MODE)\n"
                "触发原因：目标概念连续 2 次正确率 >= 0.85 且认知负荷 < 0.40\n"
                "强制动作：跳过基础讲解，沙盒评测智能体生成高难度边界测试实操任务\n"
                "目标：通过高难度实操检验深层理解，预防过度自信"
            ),
        }
        return descriptions.get(mode, "")


class EffectEvaluatorAgent:
    def evaluate(self, profile: StudentProfile, resources: tuple[AgentOutput, ...]) -> LearningSignal:
        profile_causes = profile.learning_state_causes

        cause_penalty = 0.0
        for key in ("prerequisite_gap", "misconception", "cognitive_load", "strategy_gap"):
            cause = profile_causes.get(key)
            if cause is not None:
                cause_penalty += cause.percentage / 100 * 0.04

        has_code = any(r.resource_type == "代码实操案例" for r in resources)
        has_quiz = any(r.resource_type == "练习题" for r in resources)
        has_theory = any(r.resource_type == "专业讲义" for r in resources)
        has_mermaid = any(r.resource_type == "思维导图" for r in resources)

        resource_coverage = sum([has_code, has_quiz, has_theory, has_mermaid]) / 4.0

        accuracy = 0.78
        accuracy -= cause_penalty
        accuracy += resource_coverage * 0.08
        accuracy += 0.04 if resource_coverage >= 0.75 else 0.0
        accuracy -= max(0.0, profile.cognitive_load - 0.5) * 0.12

        sandbox_error_rate = 0.42
        if has_code and profile.cognitive_load < 0.6:
            sandbox_error_rate = 0.18
        elif has_code:
            sandbox_error_rate = 0.30

        dwell_seconds = 420
        if profile.cognitive_style and "视觉" in profile.cognitive_style:
            dwell_seconds = 480
        if has_code or has_quiz:
            dwell_seconds += 60

        return LearningSignal(
            accuracy=max(0.0, min(1.0, accuracy)),
            dwell_seconds=dwell_seconds,
            sandbox_error_rate=sandbox_error_rate,
        )


async def run_async_thread(func, *args, **kwargs):
    import asyncio
    import functools
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


class AsyncResourceFactory:
    def __init__(self, generator: AsyncInstructRAGGenerator) -> None:
        self.generator = generator
        self.jobs: tuple[tuple[str, str], ...] = (
            ("理论教授", "专业讲义"),
            ("逻辑画师", "思维导图"),
            ("极客助教", "代码实操案例"),
            ("考官智能体", "练习题"),
            ("虚拟导演", "虚拟人视频脚本"),
        )

    @staticmethod
    def _build_strategy_injections(
        strategy_plan: LearningStrategyPlan | None,
    ) -> dict[str, str]:
        """将策略计划翻译为各角色的强制注入指令（任务 10.2 核心）。"""
        from models import StrategyType

        injections: dict[str, str] = {}

        if strategy_plan is None or not strategy_plan.actions:
            return injections

        for action in strategy_plan.actions:
            stype = action.strategy

            # WORKED_EXAMPLE → 注入到极客助教，强制增加完整可运行示例
            if stype == StrategyType.WORKED_EXAMPLE:
                prev = injections.get("coder", "")
                injections["coder"] = (
                    f"{prev}\n"
                    f"【系统强制指令: WORKED_EXAMPLE】{action.description}\n"
                    f"请在代码实操案例前，提供一段完整可运行的 PyTorch/Numpy 示例代码，"
                    f"包含完整的 import、数据准备、模型定义、训练循环和结果验证。"
                    f"确保代码可以直接复制运行，不得留空。"
                ).strip()

            # HINT_LADDER → 注入到考官智能体，强制分层提示禁止直接答案
            if stype == StrategyType.HINT_LADDER:
                prev = injections.get("quiz", "")
                injections["quiz"] = (
                    f"{prev}\n"
                    f"【系统强制指令: HINT_LADDER】{action.description}\n"
                    f"设计题目时，必须附带 3 层递进提示阶梯：\n"
                    f"  第1层：提示题目条件或关键概念（模糊暗示）\n"
                    f"  第2层：提示适用公式或方法（半具体）\n"
                    f"  第3层：仅给出局部步骤或伪代码框架（限制性）\n"
                    f"禁止在任何层级直接泄露完整答案。"
                ).strip()
                # 同时注入到理论教授
                prev_t = injections.get("theory", "")
                injections["theory"] = (
                    f"{prev_t}\n"
                    f"【系统强制指令: HINT_LADDER】{action.description}\n"
                    f"在讲义讲解时，先给出概念框架，再提示关键条件，最后再讲完整推导。"
                ).strip()

            # RETRIEVAL_PRACTICE → 注入到理论教授 + 考官智能体
            if stype == StrategyType.RETRIEVAL_PRACTICE:
                prev_q = injections.get("quiz", "")
                injections["quiz"] = (
                    f"{prev_q}\n"
                    f"【系统强制指令: RETRIEVAL_PRACTICE】{action.description}\n"
                    f"学习后立刻安排 2 道检索题（学生不可以看资料回答），"
                    f"并要求学生写出错因和下次识别线索。"
                ).strip()
                prev_t = injections.get("theory", "")
                injections["theory"] = (
                    f"{prev_t}\n"
                    f"【系统强制指令: RETRIEVAL_PRACTICE】在讲义末尾附加 2 个检索回顾问题，"
                    f"要求学生闭卷回答。"
                ).strip()

            # MISCONCEPTION_CONTRAST → 注入到逻辑画师 + 理论教授
            if stype == StrategyType.MISCONCEPTION_CONTRAST:
                prev_m = injections.get("mapper", "")
                injections["mapper"] = (
                    f"{prev_m}\n"
                    f"【系统强制指令: MISCONCEPTION_CONTRAST】{action.description}\n"
                    f"请生成正例、反例和相似概念对照表（如表格/对比图），"
                    f"突出学生高频混淆点的边界条件。"
                ).strip()

            # METACOGNITIVE_CALIBRATION → 注入到考官智能体
            if stype == StrategyType.METACOGNITIVE_CALIBRATION:
                prev_q = injections.get("quiz", "")
                injections["quiz"] = (
                    f"{prev_q}\n"
                    f"【系统强制指令: METACOGNITIVE_CALIBRATION】{action.description}\n"
                    f"每道关键题前先要求学生记录自评掌握度，作答后比较表现，"
                    f"帮助学生校准自我判断。"
                ).strip()

            # SPACED_REVIEW → 注入到考官智能体
            if stype == StrategyType.SPACED_REVIEW:
                prev_q = injections.get("quiz", "")
                injections["quiz"] = (
                    f"{prev_q}\n"
                    f"【系统强制指令: SPACED_REVIEW】{action.description}\n"
                    f"生成短小精悍的复习题，控制在 3 分钟内可完成，"
                    f"重点测试间隔保持率。"
                ).strip()

        return injections

    async def generate_all(
        self,
        *,
        query: str,
        retrieval,
        clean_evidence,
        profile: StudentProfile,
        correction: str = "",
        conversation_memory: str = "",
        previous_resources: tuple[AgentOutput, ...] | None = None,
        alignment_advice: str = "",
        strategy_plan: LearningStrategyPlan | None = None,
        mediation_instructions: dict[str, str] | None = None,
    ) -> tuple[AgentOutput, ...]:
        import asyncio

        # === 任务 10.2: 将教学策略翻译为角色注入指令 ===
        strategy_injections = self._build_strategy_injections(strategy_plan)

        # === 合并 FSM 路由指令（来自 SwarmMediationRouter） ===
        merged_injections: dict[str, str] = {}
        all_roles = set(role for role, _ in self.jobs)
        for role in all_roles:
            parts = []
            if mediation_instructions and role in mediation_instructions:
                parts.append(mediation_instructions[role])
            if role in strategy_injections:
                parts.append(strategy_injections[role])
            if parts:
                merged_injections[role] = "\n".join(parts)

        async def _generate_one(role: str, resource_type: str) -> AgentOutput:
            # 准备该角色的强制注入指令
            forced_instruction = merged_injections.get(role, "")

            if role == "极客助教" and previous_resources:
                prev_lecture = next((r.content for r in previous_resources if r.resource_type == "专业讲义"), "")
                prev_code = next((r.content for r in previous_resources if r.resource_type == "代码实操案例"), "")
                if prev_lecture and prev_code:
                    from app.agents.coder import async_refine_code_agent
                    refined_code = await async_refine_code_agent(prev_lecture, prev_code, alignment_advice)
                    prev_citations = next((r.citations for r in previous_resources if r.resource_type == "代码实操案例"), ())
                    return AgentOutput(
                        agent=role,
                        resource_type=resource_type,
                        content=refined_code,
                        citations=prev_citations,
                        private_rationale=f"通过 async_refine_code_agent 重构代码成功。对齐纠偏提示：{alignment_advice}",
                    )
            return await self.generator.generate(
                role=role,
                resource_type=resource_type,
                query=query,
                graph_context=retrieval.graph_context,
                evidence=clean_evidence,
                profile=profile,
                correction=correction,
                conversation_memory=conversation_memory,
                forced_instruction=forced_instruction,
            )

        tasks = [_generate_one(role, rt) for role, rt in self.jobs]
        outputs = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[AgentOutput] = []
        for i, output in enumerate(outputs):
            if isinstance(output, Exception):
                role_name = self.jobs[i][0]
                resource_type_name = self.jobs[i][1]
                TELEMETRY.record_metric(
                    "resource_factory.error", 1.0,
                    role=role_name, error=str(output)[:100],
                )
                results.append(AgentOutput(
                    agent=role_name,
                    resource_type=resource_type_name,
                    content=f"# {resource_type_name} 生成暂时不可用\n\n当前角色暂时无法生成内容，请稍后再试。",
                    citations=(),
                    private_rationale=f"生成失败: {output}",
                ))
            else:
                results.append(output)

        order = {resource_type: index for index, (_, resource_type) in enumerate(self.jobs)}
        return tuple(sorted(results, key=lambda item: order[item.resource_type]))


class EduMatrixSwarm:
    """1+3+5 full-band orchestration for EduMatrix with async concurrency control."""

    def __init__(
        self,
        *,
        rag: HybridRAGPipeline = hybrid_rag,
        llm: AsyncLLMBackend | None = None,
        profile_store: dict[str, StudentProfile] | None = None,
    ) -> None:
        self.rag = rag
        self.profile_store = profile_store if profile_store is not None else {}
        use_llm = llm if llm is not None else DEFAULT_ASYNC_LLM
        self.profile_probe = ProfileProbeAgent(use_llm)
        self.planner = ZPDPlannerAgent()
        self.debate = DebateAugmentedRAG()
        self.async_generator = AsyncInstructRAGGenerator(use_llm)
        self.factory = AsyncResourceFactory(self.async_generator)
        self.alignment = ManifoldAlignmentVerifier()
        self.evaluator = EffectEvaluatorAgent()
        self.strategy_engine = LearningStrategyEngine()
        # 任务 7.3: 多门控自适应 FSM 路由器
        self.mediation_router = SwarmMediationRouter()

    async def async_process(self, user_input: str, *, student_id: str = "demo-student") -> ResourcePackage:
        with timed_span(TELEMETRY, "swarm.process", student_id=student_id):
            profile = self.profile_store.setdefault(student_id, StudentProfile(student_id=student_id))

            # === 任务 7.2: 应用 Ebbinghaus 遗忘衰减 ===
            from bkt_engine import EbbinghausDecayEngine, behavior_sanity_check
            EbbinghausDecayEngine.apply_decay_to_profile(profile)

            # === 任务 7.2: 行为信号校验 ===
            sanity_result = behavior_sanity_check(profile)
            if sanity_result["sanitized"]:
                TELEMETRY.record_metric(
                    "behavior_sanity.capped",
                    len(sanity_result["capped_concepts"]),
                    student_id=student_id,
                )

            profile = await self.profile_probe.async_update(profile, user_input)

            retrieval = self.planner.plan(self.rag, user_input, profile)
            debate_result = self.debate.clean(retrieval)
            TELEMETRY.record_metric(
                "debate.keep_rate",
                len(debate_result.clean_evidence) / max(1, len(retrieval.evidence)),
                target=retrieval.target,
            )

            # === 任务 7.3: FSM 路由决策 ===
            swarm_mode = self.mediation_router.decide_mode(
                profile, target=retrieval.target,
            )
            mediation_instructions = self.mediation_router.get_forced_instructions(swarm_mode)
            TELEMETRY.record_metric(
                "mediation.mode",
                1.0 if swarm_mode.value != "normal" else 0.0,
                mode=swarm_mode.value,
                target=retrieval.target,
            )

            conversation_memory = _build_conversation_memory(profile, max_turns=6)

            correction = ""
            resources: tuple[AgentOutput, ...] = ()
            alignment_report = None
            rollback_count = 0
            previous_resources = None
            for attempt in range(CONFIG.rollback_limit + 1):
                resources = await self.factory.generate_all(
                    query=user_input,
                    retrieval=retrieval,
                    clean_evidence=debate_result.clean_evidence,
                    profile=profile,
                    correction=correction,
                    conversation_memory=conversation_memory,
                    previous_resources=previous_resources,
                    alignment_advice=correction,
                    # 任务 10.2: 注入策略计划
                    strategy_plan=self.strategy_engine.build_plan(profile, target=retrieval.target),
                    # 任务 7.3: 注入 FSM 路由指令
                    mediation_instructions=mediation_instructions,
                )
                alignment_report = self.alignment.verify(resources)
                if alignment_report.passed:
                    break
                rollback_count += 1
                previous_resources = resources
                correction = (
                    f"第 {attempt + 1} 次对齐失败：{alignment_report.advice} "
                    "重写时必须统一池化类型、变量名和图示节点。"
                )
            TELEMETRY.record_metric("alignment.rollback_count", rollback_count, target=retrieval.target)

            assert alignment_report is not None
            learning_signal = self.evaluator.evaluate(profile, resources)
            TELEMETRY.record_metric("learning.estimated_accuracy", learning_signal.accuracy, target=retrieval.target)
            if learning_signal.needs_replan:
                profile.cognitive_load = min(1.0, profile.cognitive_load + 0.08)
                profile.update_from_feedback(
                    feedback="系统量化评估显示当前正确率或沙盒错误率触发重规划，需要降低难度并补充诊断。",
                    accuracy=learning_signal.accuracy,
                    self_confidence=None,
                    hint_count=1,
                )
            strategy_plan = self.strategy_engine.build_plan(profile, target=retrieval.target)

            return ResourcePackage(
                student_id=student_id,
                target=retrieval.target,
                profile=profile,
                retrieval=retrieval,
                verdicts=debate_result.verdicts,
                resources=resources,
                alignment=alignment_report,
                learning_signal=learning_signal,
                strategy_plan=strategy_plan,
            )

    def process(self, user_input: str, *, student_id: str = "demo-student") -> ResourcePackage:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, self.async_process(user_input, student_id=student_id))
                return future.result()
        else:
            return loop.run_until_complete(self.async_process(user_input, student_id=student_id))