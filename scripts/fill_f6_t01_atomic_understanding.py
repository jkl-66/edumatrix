#!/usr/bin/env python3
"""Record F6-T01's independent per-atom product understanding."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ROOT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
LEDGER_DIR = CONTEXT_ROOT / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"


UNDERSTANDING = {
    "G04-R01": {
        "product_meaning": "图4中的单题不是静态文本；学生在题卡内选择选项并提交，系统在原位进入判分结果。",
        "behavior_boundaries": [
            "只把明确提交的答题行为视为可评估学习行为，浏览题干、展开选项或打开资源不改变掌握度。",
            "单题卡保持紧凑的题干、纵向选项和主提交按钮，不增加与当前题无关的复杂技术栏。",
        ],
        "implementation_scope": [
            "在测验题资源工作区和智能对话的单题卡中复用同一题目协议，渲染题干、选项、选择状态和提交状态。",
            "服务端接收课程、知识点、资源版本、画像和当前尝试上下文，返回可判分题目及稳定题目 ID。",
        ],
        "verification_plan": [
            "自动测试验证题目协议、所有权、题目 ID、选项和提交状态；拒绝没有题干或没有可判分选项的结构。",
            "桌面按图4在1440x900和1366x768选择一个选项并提交，确认判分结果原位出现且无页面跳转或布局溢出。",
        ],
    },
    "G04-R02": {
        "product_meaning": "提交答案后立即给出正确/错误判定、正确答案和可读解析，让学生知道下一步如何理解。",
        "behavior_boundaries": [
            "判分结果必须绑定当前题目和当前尝试，不能使用上一题的答案或固定全局结果。",
            "解析只展示学生可见的结论、依据和改进建议，不展示私有思维链或原始 Agent 日志。",
        ],
        "implementation_scope": [
            "题目提交接口返回判定、正确答案、解析、来源/知识点上下文和下一步动作；前端在题卡内展开反馈区。",
            "历史答题记录保存尝试结果及证据强度，便于错题和复习模块读取。",
        ],
        "verification_plan": [
            "自动覆盖正确答案、错误答案、缺失答案和重复提交，并检查返回结果与题目版本一致。",
            "人工分别提交正确和错误选项，确认判定、正确答案和解析可见，失败时保留答案并可重试。",
        ],
    },
    "G04-R03": {
        "product_meaning": "学生看完判分和解析后可以修改选项，再次提交以验证自己是否真正理解。",
        "behavior_boundaries": [
            "改答只更新当前题目的新尝试，不覆盖原始答题证据；重复提交不能制造重复完成事件。",
            "改答本身不自动提高掌握度，只有服务端判定为有效的学习证据才进入聚合。",
        ],
        "implementation_scope": [
            "前端在已判分题卡中保留选项编辑能力和再次提交主动作，显示当前尝试/历史尝试状态。",
            "后端以题目版本和尝试 ID 做幂等约束，记录新答案与判定而不是篡改旧尝试。",
        ],
        "verification_plan": [
            "自动测试验证同一题多次提交、答案变化、幂等重放和旧尝试不可变。",
            "人工先提交错误选项再改为正确选项，确认两次结果可区分、解析更新且错题/画像只按有效证据聚合。",
        ],
    },
    "G04-R04": {
        "product_meaning": "学生可以针对题目、自己的答案或解析继续追问，而不是离开当前学习上下文重新描述问题。",
        "behavior_boundaries": [
            "追问必须携带课程、知识点、题目、题目版本、尝试结果和来源上下文；不能把无关对话当作题目解释。",
            "追问回答是辅助理解，不直接替代作答、判分或掌握证据。",
        ],
        "implementation_scope": [
            "题卡提供‘追问解析/继续提问’动作，进入智能对话或内嵌对话区域并保留返回题目的深链。",
            "服务端只投影用户可见的题目、解析、来源和对话摘要，不暴露私有提示词或思维链。",
        ],
        "verification_plan": [
            "自动检查追问深链包含课程、资源、题目和版本上下文，且不创建虚假的测评记录。",
            "人工从错误答案和解析点击追问，确认回答围绕当前题目，返回后题目尝试状态仍被保留。",
        ],
    },
    "G04-R05": {
        "product_meaning": "答题判分和改答形成可追溯证据，按可信程度回流学习画像、错题本和复习安排。",
        "behavior_boundaries": [
            "只有提交并完成服务端判分的答题证据进入画像聚合；看题、看解析、追问和普通资源浏览不改变掌握度。",
            "错误结果进入错题/复习候选，正确结果也要保留知识点证据，不能用单次正确直接宣称完全掌握。",
        ],
        "implementation_scope": [
            "将题目、课程、知识点、画像版本、答题结果和证据强度写入统一学习事件协议。",
            "由既有画像、错题和复习聚合器读取事件，题目模块不自行改写画像快照或路径计划。",
        ],
        "verification_plan": [
            "自动测试验证有效提交产生一条可聚合事件、浏览不产生事件、幂等重放不重复写入。",
            "人工完成错误题和正确重答，检查画像、错题和复习入口出现相应变化，并确认普通打开前后状态不变。",
        ],
    },
    "G04-R07": {
        "product_meaning": "每道题都根据当前课程、知识点、学生画像、掌握证据和最近学习事件动态生成；图4的题目只能作为展示样例。",
        "behavior_boundaries": [
            "产品不得固定 accuracy/recall 或任何示例题作为所有学生的永久问题；固定夹具只能用于测试并明确标识。",
            "生成失败、来源不足或模型不可用时必须诚实显示失败并允许重试，不能伪造已生成题目。",
        ],
        "implementation_scope": [
            "从当前知识点、课程来源、画像摘要、最近答题/错题事件和难度目标构造生成上下文，再经过题目 Schema 校验。",
            "持久题组生成结果归档为 quiz Artifact/ArtifactVersion；对话单题使用同一上下文但不把完整题组塞进聊天记录。",
        ],
        "verification_plan": [
            "自动测试使用两个不同画像/知识点上下文验证题目上下文确实进入生成请求，并拒绝固定示例和非法 Schema。",
            "人工切换知识点或画像薄弱点重新生成，确认题干和难度随上下文变化；注入失败后重试不清空已有题目。",
        ],
    },
    "G04-R08": {
        "product_meaning": "对话生成的单题可以在对话附近直接作答，但需要保存的题组进入学习空间的测验题资源并拥有历史。",
        "behavior_boundaries": [
            "紧凑题卡只承载当前单题的作答和反馈，不把完整资源中心、路径或正式测评中心嵌进对话。",
            "持久化题组必须使用 quiz 资源身份，不能把对话消息当作唯一存储，也不能把测验题误放入测评中心。",
        ],
        "implementation_scope": [
            "在 Chat/智能对话中渲染可提交的单题卡，并通过资源深链打开已归档测验题资源。",
            "测验题资源页面保存题目、答案、解析、来源、版本、尝试和错题回流；测评中心仍只有入学诊断和智能组卷。",
        ],
        "verification_plan": [
            "自动验证对话单题提交、题组归档、资源深链和测评中心边界互不混淆。",
            "人工从对话生成题目就地作答，再打开学习空间测验题资源，确认历史、解析和下一步入口均可用。",
        ],
    },
    "G04-R06": {
        "product_meaning": "对话中生成的单题仍然是可以立即完成的学习动作，而不是只读的 AI 文本。",
        "behavior_boundaries": [
            "单题卡的作答状态属于当前对话上下文，刷新或离开前必须明确是否保存为测验题资源。",
            "单题作答不新增测评中心入口，也不绕过统一学习事件和证据聚合协议。",
        ],
        "implementation_scope": [
            "复用 G04-R01 至 G04-R04 的题目渲染、判分、改答和追问协议到 Chat 消息卡。",
            "通过 save-to-resource 动作把题目及解析写入 quiz Artifact，而不是复制一套聊天专用数据库。",
        ],
        "verification_plan": [
            "自动验证 Chat 题卡拥有选择、提交和追问事件，并能安全深链到 quiz 资源。",
            "人工在对话中完成一次题目，检查结果原位出现、可追问、可保存，且返回学习空间后状态一致。",
        ],
    },
    "G21-R01": {
        "product_meaning": "测验题资源是学习空间的正式子模块之一，与讲义、导图、实训等资源并列。",
        "behavior_boundaries": ["不新增学生一级导航或重复的测评中心入口。", "测验题资源与其他资源共享课程和学习空间壳，但保留题目专属交互。"],
        "implementation_scope": ["复用资源中心、资源版本和专用路由，补齐 quiz 工作区及题目交互。"],
        "verification_plan": ["自动检查 quiz artifact/type/route 与其他资源分离。", "桌面从学习空间资源中心进入测验题并完成单题闭环。"],
    },
    "G21-R02": {
        "product_meaning": "测验题拥有可刷新、可深链的专用学习页面，离开对话后仍能继续。",
        "behavior_boundaries": ["路由必须携带资源和版本身份，不能依赖聊天内存。", "浏览历史版本不创建答题证据。"],
        "implementation_scope": ["新增或复用 quiz workspace，接入资源详情、版本、来源、尝试和返回上下文。"],
        "verification_plan": ["自动验证深链刷新恢复同一资源和版本。", "人工从资源中心打开、刷新、切换历史并返回，确认题目状态可解释。"],
    },
    "G21-R03": {
        "product_meaning": "测验题、画像、路径、资源和对话都围绕同一课程/知识点/今日任务上下文工作。",
        "behavior_boundaries": ["不能使用与当前课程无关的题源或画像摘要。", "普通查看只读上下文，不改变学习证据。"],
        "implementation_scope": ["题目请求携带课程、知识点、资源版本、画像和任务上下文，返回来源和适配摘要。"],
        "verification_plan": ["自动断言请求与资源投影的上下文字段一致。", "人工从今日知识点生成并打开测验题，确认标题、来源和下一步一致。"],
    },
    "G21-R04": {
        "product_meaning": "答题中遇到困难可以带着题目和解析上下文即时进入智能对话。",
        "behavior_boundaries": ["对话解释不能替代题目提交或正式测评。", "完整题目资源仍留在学习空间，不把资源内容永久堆到聊天。"],
        "implementation_scope": ["统一生成题目、资源、版本和题目尝试的安全深链参数。"],
        "verification_plan": ["自动检查深链参数白名单和归属校验。", "人工点击题目追问后返回，验证题目选择和反馈仍在。"],
    },
    "G21-R05": {
        "product_meaning": "测验题资源服务于日常学习，正式测评仍只有入学诊断和智能组卷。",
        "behavior_boundaries": ["不把即时练习放进测评中心。", "不以练习题完成直接绕过智能组卷的今日必做门禁。"],
        "implementation_scope": ["quiz workspace 只处理生成、作答、判分、解析和证据回流；assessment routes 保持独立。"],
        "verification_plan": ["自动扫描测评中心入口和 quiz route 的职责边界。", "人工确认测评中心没有新增‘学习中练习’，资源空间能独立完成测验。"],
    },
    "G21-R06": {
        "product_meaning": "测验题从总路径/今日知识点进入时保留原版科目路径和任务安排上下文。",
        "behavior_boundaries": ["答题模块不能重排路径或改变预算。", "只有有效答题证据通过统一聚合后才影响路径。"],
        "implementation_scope": ["资源深链保存 course/task/knowledge-point/return_to；完成事件交给 F4 聚合器。"],
        "verification_plan": ["自动验证答题前后路径节点和预算未被普通浏览改变。", "人工从总路径进入今日知识点测验并返回，确认路径状态按事件更新。"],
    },
    "G21-R07": {
        "product_meaning": "错题和复习可读取测验结果，但测验页面不取代真实月历/复习中心。",
        "behavior_boundaries": ["看解析、追问和改答不直接标记复习完成。", "复习安排由复习聚合器生成，题目模块只写规范证据。"],
        "implementation_scope": ["错误题目写入错题候选和复习证据引用，提供安全返回复习入口。"],
        "verification_plan": ["自动验证错误提交生成可关联事件而非直接改日历。", "人工检查错题/复习入口能定位到题目和知识点。"],
    },
    "G21-R08": {
        "product_meaning": "复习知识点可以生成配套测验题资源，也可进入智能组卷；两者不是同一动作。",
        "behavior_boundaries": ["单项测验生成不解锁组卷；组卷仍要求今日必做任务完成。", "生成失败显示重试，不伪造题目。"],
        "implementation_scope": ["复用 F5 资源包单项生成任务，增加 quiz 解析/归档和复习深链。"],
        "verification_plan": ["自动覆盖复习到资源生成和组卷门禁的分支。", "人工从复习知识点分别点击生成测验题和进入组卷，确认条件不同。"],
    },
    "G21-R09": {
        "product_meaning": "复习中的题目完成状态可以勾选并反馈画像，但反馈必须基于有效答题证据。",
        "behavior_boundaries": ["不能用打开题目或看答案代替复习完成。", "画像反馈遵循证据强度和幂等规则，不由前端主观改分。"],
        "implementation_scope": ["提交判分事件关联复习任务和知识点，完成/回流由统一学习事件聚合器负责。"],
        "verification_plan": ["自动验证有效提交、重复提交、普通浏览的事件差异。", "人工完成题目后检查复习勾选、画像摘要和错题变化。"],
    },
    "G21-R10": {
        "product_meaning": "测验题资源和答题尝试保留历史，并能按自定义知识点重新生成同类题目。",
        "behavior_boundaries": ["历史题目只读，编辑/生成创建新版本，不覆盖已有解析或证据。", "新题仍需绑定当前课程、来源和画像上下文。"],
        "implementation_scope": ["quiz Artifact/ArtifactVersion 接入统一版本、来源、生成任务和专用工作区。"],
        "verification_plan": ["自动验证历史不可变、生成幂等和新版本来源可追溯。", "人工在题目资源中查看历史并按新的知识点生成同类题。"],
    },
    "G21-R11": {
        "product_meaning": "测评中心页面只显示入学诊断和智能组卷；学习中练习统一归入测验题资源。",
        "behavior_boundaries": ["不得新增‘学习中练习’标签、第三个测评入口或把 quiz 路由挂到 AssessmentCenter。", "即时判分只能在题卡/测验题资源中发生。"],
        "implementation_scope": ["清理/保护路由映射和页面文案，quiz workspace 独立承载练习。"],
        "verification_plan": ["自动扫描旧冲突术语、AssessmentCenter 入口数量和 quiz route 独立性。", "人工打开测评中心与测验题资源，确认两者信息架构清晰分开。"],
    },
    "G21-R12": {
        "product_meaning": "测验题与实训任务书、代码沙盒、可交互模型是不同资源类型，不互相伪装。",
        "behavior_boundaries": ["测验题页不承担代码运行、参数实验或工程评分。", "相关资源通过深链关联，不能合并成一张超长页面。"],
        "implementation_scope": ["保持 quiz/training_task/code_sandbox/interactive_model 的 artifact_type、Schema 和路由独立。"],
        "verification_plan": ["自动验证类型和路由唯一归属。", "人工从题目进入相关实训/沙盒，确认页面职责和完成条件不同。"],
    },
    "G21-R13": {
        "product_meaning": "所有资源可以生成并归档，但智能组卷只要求总路径标为今日必做的任务完成，不要求完成全部可选资源。",
        "behavior_boundaries": ["题目阅读、查看解析、生成可选资源不能自动解锁组卷。", "组卷门禁读取 F4 的今日必做状态，不读取资源中心是否全部浏览。"],
        "implementation_scope": ["题目提交产生可信完成事件并回流路径；组卷按钮和门禁继续由 F4 负责。"],
        "verification_plan": ["自动验证可选资源和普通题目浏览不改变 exam gate，今日必做证据完成后才解锁。", "人工对比未完成/完成今日任务两种状态，确认组卷按钮状态和缺失任务提示。"],
    },
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T01_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T01 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    for entry in ledger["entries"]:
        entry["understanding"] = {"confirmed": True, **UNDERSTANDING[entry["atomic_requirement_id"]]}
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    sys.path.insert(0, str(ROOT / "scripts"))
    from context_recovery_atomic_gate import expected_entries, load_task_payload, validate_ledger_identity, validate_understanding

    active = json.loads((CONTEXT_ROOT / "active_manifest.json").read_text(encoding="utf-8"))
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T01")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T01",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError(f"F6-T01 understanding gate failed: {failures}")
    print(f"Updated and validated understanding for {len(actual_ids)} F6-T01 atoms: {ledger_path}")


if __name__ == "__main__":
    main()
