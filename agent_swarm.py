from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
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
from models import AgentOutput, AlignmentReport, LearningSignal, ResourcePackage, StudentProfile
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


class ProfileProbeAgent:
    def __init__(self, llm: AsyncLLMBackend = DEFAULT_ASYNC_LLM):
        self.llm = llm

    def update(self, profile: StudentProfile, message: str) -> StudentProfile:
        profile.update_from_message(message)
        return profile

    async def async_update(self, profile: StudentProfile, message: str) -> StudentProfile:
        profile.update_from_message(message)
        
        # 获取当前画像中已有的知识点列表
        existing_concepts = list(profile.concept_mastery.keys())
        
        # 👇 核心升级：提取最近的 3 条历史对话记录（排除当前最新的一条）
        recent_history = profile.history[-4:-1] if len(profile.history) > 1 else []
        history_context = " | ".join([h.replace('\n', '')[:100] for h in recent_history])
        
        # 将知识点列表和【历史上下文】一起传给大模型
        extracted = await self._async_extract_with_llm(message, existing_concepts, history_context)
        profile.apply_llm_features(extracted, source_text=message)
        return profile

    async def _async_extract_with_llm(self, message: str, existing_concepts: list[str] = None, history_context: str = "") -> dict:
        import re
        import json
        
        # 将已有的知识点拼接成字符串，如果为空就写“暂无”
        existing_keys_str = ", ".join(existing_concepts) if existing_concepts else "暂无"
        
        system_prompt = ( 
            "你是 EduMatrix 的画像抽取器，只能输出 JSON。\n" 
            "字段包括 course, major, goals, weak_points(必须是字符串数组), preferences, learning_state_causes, mastery_updates。\n" 
            "learning_state_causes 只能使用 prerequisite_gap, misconception, cognitive_load, "
            "strategy_gap, metacognitive_mismatch, affective_barrier, interaction_mismatch。\n" 
            "【核心任务】：深入分析学生的语义倾向和情绪，并在 mastery_updates 中打分（正值代表掌握，负值代表受挫）。\n" 
            "⚠️ 【极其重要的实体归一化与指代消解规则】：\n" 
            f"1. 当前系统已追踪的字典为：[{existing_keys_str}]\n" 
            "2. 🚨【上下文指代消解】：如果学生说“应用场景还是不懂”、“这个怎么算”、“代码怎么写”等带有指代或附属属性的话，你必须结合【历史对话上下文】推断出他们指代的具体是哪个【核心知识点】！\n"
            "3. 绝对禁止提取出“应用场景”、“这个概念”、“它的代码”等无效附属词汇，必须强行把打分归一化到对应的核心名词上（例如归一化为 \"逻辑回归\"）。\n" 
            "4. weak_points 和 mastery_updates 里的实体，必须是最精简的名词。\n" 
            "5. 优先从已追踪字典中选择，只有遇到真正的全新专业名词时，再创建新的精简名词。\n" 
            "示例输出格式：{\"weak_points\": [\"逻辑回归\", \"Transformer\"], \"mastery_updates\": {\"逻辑回归\": 0.35, \"Transformer\": -0.2}}" 
        )
        
        # 👇 把历史记录放进用户的提问前缀里，让大模型联系上下文
        context_str = f"【最近历史上下文】：{history_context}\n" if history_context else ""
        user_prompt = f"{context_str}固定课程为机器学习导论。请结合上下文，从学生最新话语中抽取画像特征：{message}"
        
        try:
            raw = await self.llm.generate(system_prompt, user_prompt, role="画像抽取器")
            match = re.search(r"\{.*\}", raw, flags=re.S)
            if not match:
                return {}
            data = json.loads(match.group(0))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}


class ZPDPlannerAgent:
    async def plan_async(self, rag: HybridRAGPipeline, query: str, profile: StudentProfile):
        if "最大池化与平均池化混淆" in profile.misconception_patterns:
            target = "池化层"
        elif profile.weak_points:
            target = profile.weak_points[-1]
            for point in ("池化层", "逻辑回归", "过拟合", "反向传播", "链式法则"):
                if point in profile.weak_points:
                    target = point
                    break
        else:
            target = None
        return await rag.retrieve_async(query, target=target)

    def plan(self, rag: HybridRAGPipeline, query: str, profile: StudentProfile):
        if "最大池化与平均池化混淆" in profile.misconception_patterns:
            target = "池化层"
        elif profile.weak_points:
            target = profile.weak_points[-1]
            for point in ("池化层", "逻辑回归", "过拟合", "反向传播", "链式法则"):
                if point in profile.weak_points:
                    target = point
                    break
        else:
            target = None
        return rag.retrieve(query, target=target)


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
    ) -> tuple[AgentOutput, ...]:
        import asyncio

        async def _generate_one(role: str, resource_type: str) -> AgentOutput:
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

    async def async_process(self, user_input: str, *, student_id: str = "demo-student") -> ResourcePackage:
        with timed_span(TELEMETRY, "swarm.process", student_id=student_id):
            profile = self.profile_store.setdefault(student_id, StudentProfile(student_id=student_id))
            profile = await self.profile_probe.async_update(profile, user_input)

            retrieval = await self.planner.plan_async(self.rag, user_input, profile)
            debate_result = self.debate.clean(retrieval)
            TELEMETRY.record_metric(
                "debate.keep_rate",
                len(debate_result.clean_evidence) / max(1, len(retrieval.evidence)),
                target=retrieval.target,
            )

            if debate_result.low_confidence or retrieval.low_confidence:
                refusal_msg = "抱歉，系统在知识库中未检索到与您提问相关的充足高置信度证据，为避免幻觉，建议您在‘课件管理’页面中上传包含该概念的教学资料。"
                resources = (
                    AgentOutput(agent="理论教授", resource_type="专业讲义", content=refusal_msg, citations=()),
                    AgentOutput(agent="逻辑画师", resource_type="思维导图", content=refusal_msg, citations=()),
                    AgentOutput(agent="极客助教", resource_type="代码实操案例", content=refusal_msg, citations=()),
                    AgentOutput(agent="考官智能体", resource_type="练习题", content=refusal_msg, citations=()),
                    AgentOutput(agent="虚拟导演", resource_type="虚拟人视频脚本", content=refusal_msg, citations=()),
                )
                alignment_report = AlignmentReport(passed=True, distance=0.0, threshold=0.35, advice="低置信度拒绝生成。")
                learning_signal = LearningSignal(accuracy=1.0, dwell_seconds=60, sandbox_error_rate=0.0)
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
                )
                alignment_report = self.alignment.verify(resources)
                if alignment_report.passed:
                    break
                rollback_count += 1
                previous_resources = resources
                correction = (
                    f"第 {attempt + 1} 次对齐失败：{alignment_report.advice} "
                    "重写时必须统一池化类型、变量名 and 图示节点。"
                )
            TELEMETRY.record_metric("alignment.rollback_count", rollback_count, target=retrieval.target)

            if retrieval.out_of_domain:
                degradation_msg = "\n\n*(提示：EduMatrix 标准学科大纲知识图谱暂未涵盖该领域，系统已自动切换至多模态混合文本检索与实时互联网检索模式进行解答，您可以上传相关课件以扩充图谱。)*"
                new_resources = []
                for res in resources:
                    if res.resource_type == "专业讲义":
                        new_content = res.content + degradation_msg
                        new_resources.append(
                            AgentOutput(
                                agent=res.agent,
                                resource_type=res.resource_type,
                                content=new_content,
                                citations=res.citations,
                                private_rationale=res.private_rationale,
                            )
                        )
                    else:
                        new_resources.append(res)
                resources = tuple(new_resources)

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