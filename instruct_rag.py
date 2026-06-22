from __future__ import annotations

from dataclasses import dataclass

from llm_client import AsyncLLMBackend, DEFAULT_ASYNC_LLM, LLMBackend
from models import AgentOutput, Evidence, GraphContext, StudentProfile


# === P2-3 共享构建计划函数（消除同步/异步代码重复） ===
def _build_instruction_plan(
    *,
    role: str,
    resource_type: str,
    query: str,
    graph_context: GraphContext,
    evidence: tuple[Evidence, ...],
    profile: StudentProfile,
    correction: str,
    conversation_memory: str,
    forced_instruction: str = "",
) -> InstructionPlan:
    """统一的构建计划逻辑，同步/异步生成器共享。"""
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

    # === P1-3 知识反转检测：高掌握度时切换为 problem-solving-first ===
    _reversal_note = ""
    if current_mastery > 0.80:
        _reversal_note = (
            "【知识反转预警】该学生对此概念掌握度已超过 80%。请跳过基础讲解和 worked example，"
            "直接进入 problem-solving-first 模式：出一项综合性挑战题或代码任务，"
            "让学生先尝试解决，遇到困难时再针对性提示。\n"
        )

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
            "2. 允许按需自动画图（无需学生主动要求）：当且仅当讲解涉及【受力分析、几何构造、物理结构、网络架构】时自动输出完整的 <svg> 标签；涉及【数学函数曲线、损失函数】时自动输出 <plot> 标签。\n"
            "🚨 致命红线：<plot> 标签内【绝对禁止】包含任何中文、冒号或描述性文字！只能包含纯粹的数学表达式并用逗号分隔（例如正确格式：<plot>x^2, x^2 + sin(x)</plot>），否则会导致前端数学引擎崩溃！\n"
            "3. 对于纯抽象概念，必须保持绝对克制，仅用纯文字解答，严禁强行凑图。\n"
            f"4. {difficulty_prompt}\n"
        )

    elif role == "极客助教":
        if current_mastery < 0.5:
            difficulty_prompt = "【难度：菜鸟期】禁止输出任何复杂的工业级代码！请只用伪代码，或者只打印最基础的演示步骤即可。"
        elif current_mastery > 0.75:
            difficulty_prompt = "【难度：精通期】直接编码完整的高级教学案例（PyTorch），并附上关键原理的注释，代码中穿插KaTeX公式。"
        else:
            difficulty_prompt = "【难度：进阶期】输出教学区代码并打出可观察的关键变体输出。"

        role_rules = (
            f"请严格遵守以下要点：\n"
            f"1. 始终先准确读取学生给出的核心概念。\n"
            f"2. 严格以对方的核心概念作为起点进行展开，确保内容紧密围绕其核心。\n"
            f"3. 代码必须完整可运行，禁止使用省略号或其他代替。禁止在推理或演示方案中嵌入随机元素或不可控的随机方法。\n"
            f"4. 考虑学生是来学习的，输出一定要讲解细节，要多（！）多（！）输出细节，不要有保留。\n"
            f"5. {difficulty_prompt}\n"
        )

    elif role == "考官智能体":
        if current_mastery < 0.5:
            difficulty_prompt = "【难度：菜鸟期】只出最基本的记忆题和理解题，选项清晰，绝对禁止出现复杂计算。"
        elif current_mastery > 0.75:
            difficulty_prompt = "【难度：精通期】出综合应用题 + 概念推导题，考察学生的知识串联能力。"
        else:
            difficulty_prompt = "【难度：进阶期】出中等复杂度的计算题和应用题，需要学生真正理解概念。"

        role_rules = (
            f"1. 请基于当前学习目标，从多个角度（概念、计算、应用）出题。\n"
            f"2. 每道题都提供一个明确的评分标准。\n"
            f"3. {difficulty_prompt}\n"
        )

    elif role == "逻辑画师":
        role_rules = (
            f"1. 必须使用 Mermaid 语法中的 mindmap 绘制图表，并用代码块 ```mermaid 包裹。\n"
            f"2. 结构必须有严密的缩进层次感。每一行只能包含一个节点。子节点必须比父节点多缩进2个空格。\n"
            f"3. ⚠️【Mermaid Mindmap 语法结构示例】：\n"
            f"   ```mermaid\n"
            f"   mindmap\n"
            f"     root((\"根节点使用双括号加双引号包装\"))\n"
            f"       子分支一\n"
            f"         叶子节点一\n"
            f"         叶子节点二\n"
            f"       子分支二\n"
            f"         leaf_node_1[\"叶子节点三（包含特殊字符时使用ID和方括号及双引号包裹）\"]\n"
            f"   ```\n"
            f"4. ⚠️【Mermaid 语法防错致命红线】：\n"
            f"   - 'mindmap' 关键字必须独占第一行！根节点必须在第二行开始缩进！\n"
            f"   - 绝对禁止把多个节点写在同一行！每一行必须有且仅有一个节点，且必须换行。\n"
            f"   - 普通纯文本分支节点直接写即可（无需加引号，允许包含空格和中文）。\n"
            f"   - ⚠️ 绝对不要写裸双引号包裹的节点（如直接写 \"叶子节点一\" 是语法错误）。\n"
            f"   - ⚠️ 绝对禁止在 mindmap 的任何节点中输出反单引号（`）或嵌套任何 Markdown 代码块（如 ```python ... ``` 等）。如果需要展示代码，必须作为普通文本或使用节点ID加方括号及双引号包裹，绝不能使用任何反单引号或代码块！\n"
            f"   - 如果节点的文本包含任何中文标点、括号、等号、数学符号或其它特殊字符，必须无条件使用节点ID和方括号包裹，且内容用双引号括起来（例如：node_1[\"dL/dW = (y_hat - y) * X\"] ）。\n"
        )
    else:
        role_rules = f"围绕 {graph_context.target}，给出该角色视角下的核心教学输出。\n"

    forced_section = f"{forced_instruction}\n" if forced_instruction else ""

    system_prompt = (
        f"你是 EduMatrix 的{role}。\n"
        "优先基于给定的检索证据作答；如果证据中没有相关信息，请直接调用你强大的内置数理化知识库进行详细解答，无需声明证据不足。\n"
        "先在内部完成证据对齐、前置概念补齐、结论校验，再输出最终内容。\n"
        "必须依据学生动态画像调整讲解深度和提示方式。\n"
        "不要泄露内部推理草稿，只输出可交付的 Markdown 内容。\n"
        "⚠️【公式和变量 LaTeX 强制要求】：\n"
        "  所有数学公式、数学表达式、数学变量、权重/偏置参数（包括但不限于 $w$, $x$, $b$, $w_1$, $w_2$, $dL/dw$, $z = w_1x_1 + w_2x_2 + b$, \\alpha, y, \\hat{y}, z, m, n 等单个字母或表达式）在文中出现时，\n"
        "  必须无一例外地使用 LaTeX 格式包裹（即行内公式使用 $...$，独立公式使用 $$...$$）。\n"
        "  绝对禁止直接写成纯文本（如 w1 = 0.1）或用普通反单引号（如 `w1`）包裹数学变量或公式。例如，必须写成 $w_1 = 0.1$ 和 \\hat{y} 等。\n\n"
        f"{role_rules}"
        f"{_reversal_note}"
        f"{forced_section}"
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


def _edges_desc(graph_context: GraphContext) -> str:
    if not graph_context.prerequisite_edges and not graph_context.downstream_edges:
        return "（无明确依赖）"
    parts = []
    if graph_context.prerequisite_edges:
        parts.append("前置依赖：" + ", ".join(f"{s}→{t}" for s, t, _ in graph_context.prerequisite_edges[:5]))
    if graph_context.downstream_edges:
        parts.append("下游扩展：" + ", ".join(f"{s}→{t}" for s, t, _ in graph_context.downstream_edges[:5]))
    return "；".join(parts)


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
        forced_instruction: str = "",
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
            forced_instruction=forced_instruction,
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
        forced_instruction: str = "",
    ) -> InstructionPlan:
        return _build_instruction_plan(
            role=role, resource_type=resource_type, query=query,
            graph_context=graph_context, evidence=evidence,
            profile=profile, correction=correction,
            conversation_memory=conversation_memory,
            forced_instruction=forced_instruction,
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
        forced_instruction: str = "",
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
            forced_instruction=forced_instruction,
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
        forced_instruction: str = "",
    ) -> InstructionPlan:
        return _build_instruction_plan(
            role=role, resource_type=resource_type, query=query,
            graph_context=graph_context, evidence=evidence,
            profile=profile, correction=correction,
            conversation_memory=conversation_memory,
            forced_instruction=forced_instruction,
        )