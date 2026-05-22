from __future__ import annotations

from dataclasses import dataclass

from llm_client import AsyncLLMBackend, DEFAULT_ASYNC_LLM, LLMBackend
from models import AgentOutput, Evidence, GraphContext, StudentProfile


@dataclass(frozen=True)
class InstructionPlan:
    private_rationale: str
    system_prompt: str
    user_prompt: str


class InstructRAGGenerator:
    def __init__(self, llm: LLMBackend) -> None:
        self.llm = llm

    def generate(
        self,
        *,
        role: str,
        resource_type: str,
        query: str,
        graph_context: GraphContext,
        evidence: tuple[Evidence, ...],
        profile: StudentProfile,
        correction: str = "",
        conversation_memory: str = "",
    ) -> AgentOutput:
        plan = self._build_plan(
            role=role,
            resource_type=resource_type,
            query=query,
            graph_context=graph_context,
            evidence=evidence,
            profile=profile,
            correction=correction,
            conversation_memory=conversation_memory,
        )
        content = self.llm.generate(plan.system_prompt, plan.user_prompt, role=role)
        return AgentOutput(
            agent=role,
            resource_type=resource_type,
            content=content.strip(),
            citations=tuple(item.id for item in evidence),
            private_rationale=plan.private_rationale,
        )

    def _build_plan(
        self,
        *,
        role: str,
        resource_type: str,
        query: str,
        graph_context: GraphContext,
        evidence: tuple[Evidence, ...],
        profile: StudentProfile,
        correction: str,
        conversation_memory: str,
    ) -> InstructionPlan:
        evidence_prompt = "\n".join(
            f"- {item.id}: {item.title}｜{item.content}｜来源={item.source}"
            for item in evidence
        )
        evidence_ids = ", ".join(item.id for item in evidence)
        private_rationale = (
            f"角色={role}; 资源={resource_type}; 目标={graph_context.target}; "
            f"覆盖路径={' -> '.join(graph_context.learning_path)}; "
            f"引用证据={evidence_ids}; 用户风格={profile.cognitive_style}; "
            f"画像状态={profile.profile_prompt()}; "
            f"纠偏={correction or '无'}。"
        )
        system_prompt = (
            f"你是 EduMatrix 的{role}。"
            "必须严格基于给定证据作答；若证据不足，明确说明边界。"
            "先在内部完成证据对齐、前置概念补齐、结论校验，再输出最终内容。"
            "必须依据学生动态画像调整讲解深度、提示方式、练习类型和复习安排。"
            "遇到画像显示误概念、前置缺口、认知负荷或学习策略不足时，要给出对应教学动作。"
            "不要泄露内部推理草稿，只输出可交付内容。"
        )
        memory_section = ""
        if conversation_memory:
            memory_section = f"历史对话摘要（按时间倒序）：\n{conversation_memory}\n"
        user_prompt = (
            f"任务：围绕\u201c{query}\u201d生成{resource_type}。\n"
            f"学生画像摘要：{profile.profile_prompt()}。\n"
            f"学生画像明细：\n{profile.state_report()}\n"
            f"{memory_section}"
            f"{graph_context.to_prompt()}\n"
            f"可用证据：\n{evidence_prompt}\n"
            f"额外纠偏要求：{correction or '无'}\n"
            "输出要求：结构完整、术语统一、不得把最大池化与平均池化混写；"
            "必须包含画像驱动的下一步行动，例如补前置、反例辨析、提示阶梯、检索练习或间隔复习。"
        )
        return InstructionPlan(
            private_rationale=private_rationale,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )


class AsyncInstructRAGGenerator:
    def __init__(self, llm: AsyncLLMBackend = DEFAULT_ASYNC_LLM) -> None:
        self.llm = llm

    async def generate(
        self,
        *,
        role: str,
        resource_type: str,
        query: str,
        graph_context: GraphContext,
        evidence: tuple[Evidence, ...],
        profile: StudentProfile,
        correction: str = "",
        conversation_memory: str = "",
    ) -> AgentOutput:
        plan = self._build_plan(
            role=role,
            resource_type=resource_type,
            query=query,
            graph_context=graph_context,
            evidence=evidence,
            profile=profile,
            correction=correction,
            conversation_memory=conversation_memory,
        )
        content = await self.llm.generate(plan.system_prompt, plan.user_prompt, role=role)
        return AgentOutput(
            agent=role,
            resource_type=resource_type,
            content=content.strip(),
            citations=tuple(item.id for item in evidence),
            private_rationale=plan.private_rationale,
        )

    def _build_plan(
        self,
        *,
        role: str,
        resource_type: str,
        query: str,
        graph_context: GraphContext,
        evidence: tuple[Evidence, ...],
        profile: StudentProfile,
        correction: str,
        conversation_memory: str,
    ) -> InstructionPlan:
        evidence_prompt = "\n".join(
            f"- {item.id}: {item.title}｜{item.content}｜来源={item.source}"
            for item in evidence
        )
        evidence_ids = ", ".join(item.id for item in evidence)
        private_rationale = (
            f"角色={role}; 资源={resource_type}; 目标={graph_context.target}; "
            f"覆盖路径={' -> '.join(graph_context.learning_path)}; "
            f"引用证据={evidence_ids}; 用户风格={profile.cognitive_style}; "
            f"画像状态={profile.profile_prompt()}; "
            f"纠偏={correction or '无'}。"
        )
        system_prompt = (
            f"你是 EduMatrix 的{role}。"
            "必须严格基于给定证据作答；若证据不足，明确说明边界。"
            "先在内部完成证据对齐、前置概念补齐、结论校验，再输出最终内容。"
            "必须依据学生动态画像调整讲解深度、提示方式、练习类型和复习安排。"
            "遇到画像显示误概念、前置缺口、认知负荷或学习策略不足时，要给出对应教学动作。"
            "不要泄露内部推理草稿，只输出可交付内容。"
        )
        memory_section = ""
        if conversation_memory:
            memory_section = f"历史对话摘要（按时间倒序）：\n{conversation_memory}\n"
        user_prompt = (
            f"任务：围绕\u201c{query}\u201d生成{resource_type}。\n"
            f"学生画像摘要：{profile.profile_prompt()}。\n"
            f"学生画像明细：\n{profile.state_report()}\n"
            f"{memory_section}"
            f"{graph_context.to_prompt()}\n"
            f"可用证据：\n{evidence_prompt}\n"
            f"额外纠偏要求：{correction or '无'}\n"
            "输出要求：结构完整、术语统一、不得把最大池化与平均池化混写；"
            "必须包含画像驱动的下一步行动，例如补前置、反例辨析、提示阶梯、检索练习或间隔复习。"
        )
        return InstructionPlan(
            private_rationale=private_rationale,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
