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

        # === 动态提取当前知识点掌握度 ===
        current_mastery = profile.concept_mastery.get(graph_context.target, 0.48)

        # === 核心规则注入区：动态难度控制 + 智能图文排版 ===
        role_rules = ""
        
        if role == "理论教授":
            if current_mastery < 0.5:
                difficulty_prompt = "【难度：菜鸟期】绝对禁止写复杂的数学公式！请用生活中最简单、最接地气的比喻来解释概念，确保初学者都能听懂。"
            elif current_mastery > 0.75:
                difficulty_prompt = "【难度：精通期】学生已完全掌握基础。请直接跳过废话，给出核心的底层推导（使用 KaTeX），并探讨深层机制。"
            else:
                difficulty_prompt = "【难度：进阶期】正常讲解概念，公式与通俗解释各占一半。"

            role_rules = (
                "【智能图文排版规则】\n"
                "1. 默认使用标准 Markdown 纯文本解答。\n"
                "2. 允许按需自动画图（无需学生主动要求）：当且仅当讲解涉及【受力分析、几何构造、物理空间结构、网络架构】时自动输出完整的 <svg> 标签；涉及【数学函数曲线、数据分布】时自动输出 <plot>函数</plot> 标签（如 <plot>x^2</plot>）。\n"
                "3. 对于纯抽象概念或无需视觉辅助的知识点，必须保持绝对克制，仅用纯文字解答，严禁为了炫技强行凑图。\n"
                f"4. {difficulty_prompt}\n"
            )

        elif role == "极客助教":
            if current_mastery < 0.5:
                difficulty_prompt = "【难度：菜鸟期】禁止输出任何复杂的工业级代码！请只用伪代码，或者只打印最基础的演示步骤即可。"
            else:
                difficulty_prompt = "【难度：精通期】请直接给出包含第三方主流框架的可运行工业级代码，并加上详尽的硬核注释。"
            
            role_rules = (
                "【强制格式规则】\n"
                "1. 若涉及有机化学结构，必须输出 SMILES 码并用 <smiles> 标签包裹。\n"
                f"2. {difficulty_prompt}\n"
            )

        elif role == "考官智能体":
            if current_mastery < 0.5:
                difficulty_prompt = "【难度：菜鸟期】只出 1 道最基础的判断题或简单概念题，并给出详尽的鼓励性解析，帮学生建立自信心。"
            else:
                difficulty_prompt = "【难度：精通期】出 1 道极具迷惑性的综合场景辨析题，或代码找错题，解析需直击核心痛点，挑战学生的极限！"
            role_rules = f"【出题规则】\n1. {difficulty_prompt}\n"

        elif role == "逻辑画师":
            role_rules = (
                "【强制格式规则】\n"
                "1. 必须使用 Mermaid 语法生成图表 (graph TD 或 mindmap)。\n"
            )

        system_prompt = (
            f"你是 EduMatrix 的{role}。\n"
            "优先基于给定的检索证据作答；如果证据中没有相关信息，请直接调用你强大的内置数理化知识库进行详细解答，无需声明证据不足。\n"
            "先在内部完成证据对齐、前置概念补齐、结论校验，再输出最终内容。\n"
            "必须依据学生动态画像调整讲解深度和提示方式。\n"
            "不要泄露内部推理草稿，只输出可交付的 Markdown 内容。\n\n"
            f"{role_rules}"  
        )
        
        memory_section = ""
        if conversation_memory:
            memory_section = f"【历史对话摘要（仅供参考学生背景）】：\n{conversation_memory}\n\n"
            
        user_prompt = (
            f"{memory_section}"
            f"【当前核心任务】：围绕\u201c{query}\u201d生成{resource_type}。绝对不要重复解答历史记录中的问题！\n"
            f"学生画像摘要：{profile.profile_prompt()}。\n"
            f"{graph_context.to_prompt()}\n"
            f"可用证据：\n{evidence_prompt}\n"
            f"额外纠偏要求：{correction or '无'}\n"
            "输出要求：结构完整，只回答当前核心任务，不要啰嗦。"
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

        # === 动态提取当前知识点掌握度 ===
        current_mastery = profile.concept_mastery.get(graph_context.target, 0.48)

        # === 核心规则注入区：同步应用到异步生成器 ===
        role_rules = ""
        
        if role == "理论教授":
            if current_mastery < 0.5:
                difficulty_prompt = "【难度：菜鸟期】绝对禁止写复杂的数学公式！请用生活中最简单、最接地气的比喻来解释概念，确保初学者都能听懂。"
            elif current_mastery > 0.75:
                difficulty_prompt = "【难度：精通期】学生已完全掌握基础。请直接跳过废话，给出核心的底层推导（使用 KaTeX），并探讨深层机制。"
            else:
                difficulty_prompt = "【难度：进阶期】正常讲解概念，公式与通俗解释各占一半。"

            role_rules = (
                "【智能图文排版规则】\n"
                "1. 默认使用标准 Markdown 纯文本解答。\n"
                "2. 允许按需自动画图（无需学生主动要求）：当且仅当讲解涉及【受力分析、几何构造、物理空间结构、网络架构】时自动输出完整的 <svg> 标签；涉及【数学函数曲线、数据分布】时自动输出 <plot>函数</plot> 标签（如 <plot>x^2</plot>）。\n"
                "3. 对于纯抽象概念或无需视觉辅助的知识点，必须保持绝对克制，仅用纯文字解答，严禁为了炫技强行凑图。\n"
                f"4. {difficulty_prompt}\n"
            )

        elif role == "极客助教":
            if current_mastery < 0.5:
                difficulty_prompt = "【难度：菜鸟期】禁止输出任何复杂的工业级代码！请只用伪代码，或者只打印最基础的演示步骤即可。"
            else:
                difficulty_prompt = "【难度：精通期】请直接给出包含第三方主流框架的可运行工业级代码，并加上详尽的硬核注释。"
            
            role_rules = (
                "【强制格式规则】\n"
                "1. 若涉及有机化学结构，必须输出 SMILES 码并用 <smiles> 标签包裹。\n"
                f"2. {difficulty_prompt}\n"
            )

        elif role == "考官智能体":
            if current_mastery < 0.5:
                difficulty_prompt = "【难度：菜鸟期】只出 1 道最基础的判断题或简单概念题，并给出详尽的鼓励性解析，帮学生建立自信心。"
            else:
                difficulty_prompt = "【难度：精通期】出 1 道极具迷惑性的综合场景辨析题，或代码找错题，解析需直击核心痛点，挑战学生的极限！"
            role_rules = f"【出题规则】\n1. {difficulty_prompt}\n"

        elif role == "逻辑画师":
            role_rules = (
                "【强制格式规则】\n"
                "1. 必须使用 Mermaid 语法生成图表 (graph TD 或 mindmap)。\n"
            )

        system_prompt = (
            f"你是 EduMatrix 的{role}。\n"
            "优先基于给定的检索证据作答；如果证据中没有相关信息，请直接调用你强大的内置数理化知识库进行详细解答，无需声明证据不足。\n"
            "先在内部完成证据对齐、前置概念补齐、结论校验，再输出最终内容。\n"
            "必须依据学生动态画像调整讲解深度和提示方式。\n"
            "不要泄露内部推理草稿，只输出可交付的 Markdown 内容。\n\n"
            f"{role_rules}"  
        )
        
        memory_section = ""
        if conversation_memory:
            memory_section = f"【历史对话摘要（仅供参考学生背景）】：\n{conversation_memory}\n\n"
            
        user_prompt = (
            f"{memory_section}"
            f"【当前核心任务】：围绕\u201c{query}\u201d生成{resource_type}。绝对不要重复解答历史记录中的问题！\n"
            f"学生画像摘要：{profile.profile_prompt()}。\n"
            f"{graph_context.to_prompt()}\n"
            f"可用证据：\n{evidence_prompt}\n"
            f"额外纠偏要求：{correction or '无'}\n"
            "输出要求：结构完整，只回答当前核心任务，不要啰嗦。"
        )
        return InstructionPlan(
            private_rationale=private_rationale,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )