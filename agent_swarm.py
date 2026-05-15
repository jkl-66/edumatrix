from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import re

from config import CONFIG
from drag_debate import DebateAugmentedRAG
from instruct_rag import InstructRAGGenerator
from learning_strategy import LearningStrategyEngine
from llm_client import DEFAULT_LLM, LLMBackend
from manifold_alignment import ManifoldAlignmentVerifier
from models import AgentOutput, LearningSignal, ResourcePackage, StudentProfile
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


class ProfileProbeAgent:
    def __init__(self, llm: LLMBackend = DEFAULT_LLM) -> None:
        self.llm = llm

    def update(self, profile: StudentProfile, message: str) -> StudentProfile:
        profile.update_from_message(message)
        extracted = self._extract_with_llm(message)
        profile.apply_llm_features(extracted, source_text=message)
        return profile

    def _extract_with_llm(self, message: str) -> dict:
        system_prompt = (
            "你是 EduMatrix 的画像抽取器，只能输出 JSON。"
            "字段包括 course, major, goals, weak_points, preferences, learning_state_causes。"
            "learning_state_causes 只能使用 prerequisite_gap, misconception, cognitive_load, "
            "strategy_gap, metacognitive_mismatch, affective_barrier, interaction_mismatch。"
        )
        user_prompt = f"固定课程为机器学习导论。请从学生话语中抽取画像特征：{message}"
        try:
            raw = self.llm.generate(system_prompt, user_prompt, role="画像抽取器")
            match = re.search(r"\{.*\}", raw, flags=re.S)
            if not match:
                return {}
            data = json.loads(match.group(0))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}


class ZPDPlannerAgent:
    def plan(self, rag: HybridRAGPipeline, query: str, profile: StudentProfile):
        if "最大池化与平均池化混淆" in profile.misconception_patterns:
            target = "池化层"
        else:
            target = profile.weak_points[-1] if profile.weak_points else None
        return rag.retrieve(query, target=target)


class EffectEvaluatorAgent:
    def evaluate(self, profile: StudentProfile, resources: tuple[AgentOutput, ...]) -> LearningSignal:
        load_penalty = max(0.0, profile.cognitive_load - 0.5) * 0.18
        strategy_gap = profile.learning_state_causes.get("strategy_gap")
        misconception = profile.learning_state_causes.get("misconception")
        prerequisite_gap = profile.learning_state_causes.get("prerequisite_gap")
        state_penalty = 0.0
        for cause in (strategy_gap, misconception, prerequisite_gap):
            if cause is not None:
                state_penalty += cause.percentage / 100 * 0.035
        has_code = any(resource.resource_type == "代码实操案例" for resource in resources)
        has_quiz = any(resource.resource_type == "练习题" for resource in resources)
        profile_bonus = 0.03 if profile.dimension_states else 0.0
        accuracy = 0.78 + profile_bonus + (0.06 if has_code else 0.0) + (0.04 if has_quiz else 0.0) - load_penalty - state_penalty
        sandbox_error_rate = 0.18 if has_code else 0.42
        dwell_seconds = 420 if profile.cognitive_style.startswith("视觉") else 360
        return LearningSignal(
            accuracy=max(0.0, min(1.0, accuracy)),
            dwell_seconds=dwell_seconds,
            sandbox_error_rate=sandbox_error_rate,
        )


class ResourceFactory:
    def __init__(self, generator: InstructRAGGenerator) -> None:
        self.generator = generator
        self.jobs: tuple[tuple[str, str], ...] = (
            ("理论教授", "专业讲义"),
            ("逻辑画师", "思维导图"),
            ("极客助教", "代码实操案例"),
            ("考官智能体", "练习题"),
            ("虚拟导演", "虚拟人视频脚本"),
        )

    def generate_all(
        self,
        *,
        query: str,
        retrieval,
        clean_evidence,
        profile: StudentProfile,
        correction: str = "",
    ) -> tuple[AgentOutput, ...]:
        outputs: list[AgentOutput] = []
        with ThreadPoolExecutor(max_workers=len(self.jobs)) as executor:
            futures = [
                executor.submit(
                    self.generator.generate,
                    role=role,
                    resource_type=resource_type,
                    query=query,
                    graph_context=retrieval.graph_context,
                    evidence=clean_evidence,
                    profile=profile,
                    correction=correction,
                )
                for role, resource_type in self.jobs
            ]
            for future in as_completed(futures):
                outputs.append(future.result())
        order = {resource_type: index for index, (_, resource_type) in enumerate(self.jobs)}
        return tuple(sorted(outputs, key=lambda item: order[item.resource_type]))


class EduMatrixSwarm:
    """1+3+5 full-band orchestration for EduMatrix."""

    def __init__(
        self,
        *,
        rag: HybridRAGPipeline = hybrid_rag,
        llm: LLMBackend = DEFAULT_LLM,
        profile_store: dict[str, StudentProfile] | None = None,
    ) -> None:
        self.rag = rag
        self.profile_store = profile_store if profile_store is not None else {}
        self.profile_probe = ProfileProbeAgent(llm)
        self.planner = ZPDPlannerAgent()
        self.debate = DebateAugmentedRAG()
        self.generator = InstructRAGGenerator(llm)
        self.factory = ResourceFactory(self.generator)
        self.alignment = ManifoldAlignmentVerifier()
        self.evaluator = EffectEvaluatorAgent()
        self.strategy_engine = LearningStrategyEngine()

    def process(self, user_input: str, *, student_id: str = "demo-student") -> ResourcePackage:
        profile = self.profile_store.setdefault(student_id, StudentProfile(student_id=student_id))
        profile = self.profile_probe.update(profile, user_input)

        retrieval = self.planner.plan(self.rag, user_input, profile)
        debate_result = self.debate.clean(retrieval)

        correction = ""
        resources: tuple[AgentOutput, ...] = ()
        alignment_report = None
        for attempt in range(CONFIG.rollback_limit + 1):
            resources = self.factory.generate_all(
                query=user_input,
                retrieval=retrieval,
                clean_evidence=debate_result.clean_evidence,
                profile=profile,
                correction=correction,
            )
            alignment_report = self.alignment.verify(resources)
            if alignment_report.passed:
                break
            correction = (
                f"第 {attempt + 1} 次对齐失败：{alignment_report.advice} "
                "重写时必须统一池化类型、变量名和图示节点。"
            )

        assert alignment_report is not None
        learning_signal = self.evaluator.evaluate(profile, resources)
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

    def agent_topology(self) -> tuple[AgentSpec, ...]:
        return AGENT_MATRIX


class EduSwarm(EduMatrixSwarm):
    """Backward-compatible alias for the previous demo entry point."""


def render_console_summary(package: ResourcePackage) -> str:
    kept = [verdict.evidence_id for verdict in package.verdicts if verdict.keep]
    resource_lines = "\n".join(
        f"- {resource.agent} / {resource.resource_type}: {resource.content[:88].replace(chr(10), ' ')}..."
        for resource in package.resources
    )
    strategy_lines = "\n".join(
        f"- {action.title}: {action.description}"
        for action in (package.strategy_plan.actions if package.strategy_plan else ())
    )
    return (
        f"目标知识点: {package.target}\n"
        f"学习路径: {' -> '.join(package.retrieval.graph_context.learning_path)}\n"
        f"{package.profile.state_report()}\n"
        f"学习策略引擎:\n{strategy_lines or '- 暂无额外策略'}\n"
        f"DRAG保留证据: {', '.join(kept)}\n"
        f"流形对齐: {'通过' if package.alignment.passed else '失败'} "
        f"(distance={package.alignment.distance:.3f}, threshold={package.alignment.threshold:.3f})\n"
        f"量化评估: accuracy={package.learning_signal.accuracy:.2f}, "
        f"sandbox_error_rate={package.learning_signal.sandbox_error_rate:.2f}\n"
        f"资源包:\n{resource_lines}"
    )


def main() -> None:
    swarm = EduMatrixSwarm()
    package = swarm.process("我还是看不懂卷积神经网络里的池化层，能用图和 PyTorch 代码演示最大池化吗？")
    print(render_console_summary(package))


if __name__ == "__main__":
    main()
