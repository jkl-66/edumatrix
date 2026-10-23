#!/usr/bin/env python3
"""Record F7-T05's independent per-atom product understanding."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ROOT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
LEDGER_DIR = (
    CONTEXT_ROOT
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
)


def item(
    meaning: str,
    boundaries: list[str],
    scope: list[str],
    verification: list[str],
) -> dict[str, object]:
    return {
        "product_meaning": meaning,
        "behavior_boundaries": boundaries,
        "implementation_scope": scope,
        "verification_plan": verification,
    }


UNDERSTANDING = {
    "G07-R07": item(
        "文档选区问答、普通Chat回答、生成资源和校验结果都必须携带可验证的sourceRefId或selectionId；学生从引用可以回到确切文档版本、页码或章节、文字范围或图片区域。",
        [
            "无有效来源时必须明确说明依据不足，不能补造引用；已撤回来源只保留历史引用，不能继续支持新回答或新生成。",
            "正文仍由F7-T02的20/58/22阅读器承载，F7-T05只统一引用身份、状态和跨页面反查，不把正文缩成来源卡。",
            "查看来源、反向定位和展开证据属于只读行为，不写学习事件、掌握度或任务完成证据。",
        ],
        [
            "建立统一SourceRef投影与解析服务，让selection、Chat message、resource version、validation result共享稳定引用结构和owner/course权限校验。",
            "在文档阅读器、Chat回答和资源来源卡中复用同一引用组件及反向路由，保存失效、撤回和版本漂移状态。",
        ],
        [
            "API测试有效、撤回、无权限、版本漂移和不存在的sourceRefId/selectionId，并递归扫描回答不存在无来源事实条目。",
            "双桌面E2E从回答和资源引用回到精确原文位置，确认普通查看前后学习事件不变。",
        ],
    ),
    "G12-R04": item(
        "Chat回答应提供真实、公开、可审计的AI处理摘要，使学生知道哪些阶段实际发生、用了什么来源、当前结果是否经过校验。",
        [
            "只展示已发生的职责、输入和业务结果，不把进度文案、模型流式token或界面动画伪装成Agent工作事实。",
            "不得返回或展示系统提示词、API Key、私有思维链、reasoning_content、原始trace和Agent原始日志。",
            "Agent审计默认收敛为分析、生成、校验、决策四阶段摘要，详细候选、分歧和修订按需展开。",
        ],
        [
            "复用F2-T05既有agent_audit协议，把Chat回答和来源校验的真实业务事件投影为公开四阶段审计记录。",
            "在F7-T04的右侧292px上下文栏加入紧凑Agent摘要，不新建独立技术说明页或第二套对话工作台。",
        ],
        [
            "协议测试验证四阶段、真实输入引用、状态和敏感字段白名单，未发生的阶段不得出现在completed结果中。",
            "E2E展开一条完成回答和一条失败回答的Agent摘要，检查阶段事实、来源和失败语义准确。",
        ],
    ),
    "G12-R05": item(
        "产品把Word中的‘思考和处理过程’解释为公开处理事实与决策摘要，任何页面和接口都不能声称暴露模型私有思维链。",
        [
            "禁止响应中出现prompt、secret、chain_of_thought、reasoning_content、raw_trace、raw_log或供应商内部字段。",
            "候选摘要和分歧只陈述公开结论、证据与修订，不复述隐藏推理步骤或内部token。",
            "错误清洗后仍需保留面向学生的阶段、原因和下一步，不能用安全边界作为隐藏真实失败的借口。",
        ],
        [
            "在统一Agent公开投影和Chat/source响应序列化处采用允许字段白名单，复用F2 agent_audit清洗函数。",
            "前端只渲染职责、输入来源、候选摘要、分歧、校验、修订和最终决定字段。",
        ],
        [
            "构造嵌套敏感字段测试，确认API响应和持久化公开投影均不泄漏；静态检查前端不存在私有推理标签。",
            "浏览器检查公开说明使用‘协作摘要/处理记录’等诚实名称，不出现‘完整思维链’宣称。",
        ],
    ),
    "G12-R07": item(
        "流式回答与结构化Agent审计必须并行恢复：回答正文持续可读，右栏按分析、生成、校验、决策展示职责、来源、候选、分歧、修订和最终摘要。",
        [
            "Agent阶段状态只能来自服务端事实，停止、继续、刷新恢复和失败不能把未完成阶段改成完成。",
            "默认只展示四阶段一行摘要，候选、分歧和修订按阶段展开，避免图15式日志墙增加理解负担。",
            "流式正文、来源卡和审计摘要必须引用同一message/run/source身份，不能形成三套互相矛盾的状态。",
        ],
        [
            "扩展Chat消息投影返回agentAudit摘要和引用；继续使用F7-T04会话、streamCheckpoint和右栏布局。",
            "新增可复用AgentTimeline组件，稳定显示运行中、已校验、需修订、失败和冻结演示五类诚实状态。",
        ],
        [
            "API测试流式中断/继续/刷新后的同一审计run，验证阶段顺序、引用一致和失败不完成。",
            "双尺寸E2E检查摘要默认紧凑、展开可读、正文仍是主体且没有小字、溢出或卡片嵌套。",
        ],
    ),
    "G22-R11": item(
        "完整学生旅程中的动态提问必须落到真实Chat回答、来源反查和可审计AI协作，而不是在旅程说明或技术页中口头宣称多智能体能力。",
        [
            "本任务只连接对话、来源和Agent审计，不改变F4路径门禁、F5资源归档、F6正式作答或未来F8反馈规则。",
            "从任意学习资源进入Chat后，返回路径、当前课程、知识点和来源必须保持；普通提问不直接更新画像或完成任务。",
            "完整资源仍归档学习空间，Chat只显示回答、来源、审计摘要和紧凑资源深链。",
        ],
        [
            "让旅程中的文档选区、资源追问和普通动态问题统一进入/learn，并返回同一SourceRef与AgentAudit协议。",
            "保护F7-T04的会话恢复和F7-T02的精确定位，使学生可从回答打开来源、再返回对话继续学习。",
        ],
        [
            "组合E2E从文档选区进入Chat、查看公开审计、打开来源并返回，确认会话和来源位置均恢复。",
            "隔离SQLite确认浏览、提问和展开审计不新增掌握事件，正式测验等既有证据路径不受影响。",
        ],
    ),
    "G27-R05": item(
        "多Agent、交叉验证和来源审核要嵌入真实问答与资源生成结果旁边，学生在需要判断可信度时就地看到，而不是跳到独立技术介绍页。",
        [
            "不得新增Agent一级导航、技术演示路由或与真实消息无关的固定动画；没有真实run就不展示完成流程。",
            "Chat只展示当前回答的审计摘要，资源页只展示当前资源版本的审计摘要，二者共享协议而不复制完整工作台。",
            "比赛技术呈现服从用户主线：正文和下一动作优先，技术细节默认折叠。",
        ],
        [
            "将F2-T05的Agent证据投影接入Chat message和资源/校验引用协议，并提供同一可复用公开审计组件。",
            "删除或拒绝任何脱离真实run的静态Agent完成数据，保留诚实空态和来源不足提示。",
        ],
        [
            "前端合同测试确认Agent摘要仅出现在有真实auditRunId的问答/资源上下文，且不存在独立技术说明入口。",
            "E2E验证回答旁可展开协作摘要，折叠后主线仍清楚，来源可反查且没有伪造完成状态。",
        ],
    ),
    "G27-R07": item(
        "外部模型或Agent运行不可用时，系统可以明确展示之前已经生成的资源或标记为冻结演示的结果，但本次失败必须保持失败，不能伪装成刚刚完成。",
        [
            "冻结结果必须有清晰标签、生成时间/版本和非实时说明；不得借用它写入本次run的completed状态或学习证据。",
            "存在可用历史结果时学生可以打开来源和资源；不存在时显示诚实空态、重试和返回学习空间动作。",
            "自动验收使用本地确定性路径，不调用外部模型；正式运行是否调用模型仍遵循当前.env和用户授权。",
        ],
        [
            "在Agent审计投影中区分live、failed、historical和frozen_demo，失败run与展示结果使用不同身份和状态。",
            "Chat右栏与资源来源区渲染清晰降级标签、失败原因、重试和已有结果深链。",
        ],
        [
            "API故障注入验证模型失败时run仍failed、历史/冻结结果只读且不生成新完成事件。",
            "E2E检查失败、重试、历史结果和冻结演示标签，确认学生不会误认为本次Agent已完成。",
        ],
    ),
    "G07-R01": item(
        "F7-T05必须保持F7-T02已经交付的清晰三栏文档工作区，来源统一后不能挤压正文或增加并列技术面板。",
        [
            "目录、正文、上下文侧栏职责不变，正文仍是视觉主体；不得恢复旧窄弹窗或卡片式PDF。",
            "新增引用与Agent摘要只能进入现有右栏的渐进展开区。",
        ],
        ["复用KnowledgeDocumentReader现有布局和定位协议，只适配统一来源组件。"],
        ["重跑F7-T02前端合同和双尺寸阅读器保护检查。"],
    ),
    "G07-R02": item(
        "统一来源时必须继续展示真实课程正文或个人PDF页，来源卡不能替代、遮挡或伪造原文。",
        [
            "来源失效时保留历史引用和当前可读内容，不能回退到未经审核的raw仓库或同名文件。",
            "没有原始二进制时仍诚实标注解析文本。",
        ],
        ["SourceRef解析复用文档版本、格式和正文事实，不创建第二份文档内容。"],
        ["保护测试验证canonical哈希、权限、撤回状态和大阅读器正文仍可读。"],
    ),
    "G07-R03": item(
        "文本划选和图片框选仍由F7-T02创建精确SelectionContext，F7-T05只让它们成为回答、资源和审计的统一可反查引用。",
        [
            "不得改变字符范围、归一化矩形、OCR重试和owner隔离语义。",
            "无效、过期或跨用户selectionId不能支持回答或资源生成。",
        ],
        ["统一selectionId到SourceCitation投影，保留原文quote、页码/章节和图片区域定位。"],
        ["重跑文字/图片选区、缩放恢复、OCR失败和跨用户拒绝测试。"],
    ),
    "G07-R04": item(
        "来源统一不能破坏F7-T02的真实原文或解析文本导出，导出仍是阅读器次级只读动作。",
        ["不得绕过权限、撤回和路径边界；导出失败不清空位置、选区或回答。"],
        ["保持现有导出接口，只验证统一SourceRef没有改变文件身份和MIME。"],
        ["保护测试导出内容、文件名、权限和导出前后学习事件不变。"],
    ),
    "G07-R05": item(
        "查看来源继续显示课程、文档版本、章节/页码、许可和处理状态，统一引用进一步让回答与资源可以回到同一位置。",
        [
            "内部哈希和索引字段默认折叠；撤回或漂移必须显式不可用。",
            "查看和定位不写学习证据。",
        ],
        ["复用DBSourceDocument/DBSourceRef事实，增加统一引用状态和反向深链。"],
        ["验证回答、资源和阅读器来源字段一致且撤回状态同步。"],
    ),
    "G07-R06": item(
        "文件或选区生成资源继续沿用统一GenerationJob和资源中心，F7-T05只保证产物版本保留同一来源引用和公开校验摘要。",
        [
            "不得创建第二套资源表、自动生成完整资源或在Chat/阅读器展开完整产物。",
            "来源撤回后历史资源保留引用，但不能基于该来源创建新版本。",
        ],
        ["把sourceRefId/selectionId和agentAuditRunId写入既有资源版本来源投影。"],
        ["资源生成保护测试验证幂等、归档、撤回阻断和来源反查。"],
    ),
    "G07-R08": item(
        "页码、章节、搜索和阅读位置仍是所有引用反查的唯一定位协议，F7-T05不能另建只适用于Chat的模糊锚点。",
        ["Markdown语义页和PDF真实页继续区分；旧版本定位不得静默套到新版本。"],
        ["SourceCitation导航调用现有Location协议并保留returnTo。"],
        ["保护测试搜索、翻页、章节、刷新和来源回跳均恢复同一位置。"],
    ),
    "G07-R09": item(
        "现有选区笔记继续保留文档、页码/章节和区域来源，统一SourceRef为F8-T03完整笔记来源卡提供稳定身份。",
        [
            "F7-T05不提前重构笔记本；来源失效不能删除用户正文。",
            "保存、查看和回跳笔记不改变掌握度。",
        ],
        ["验证现有笔记来源元数据可解析为统一引用，并保持owner隔离。"],
        ["兼容测试选区笔记保存、来源失效和回跳；F8-T03仍保留主责。"],
    ),
    "G07-R10": item(
        "来源统一必须保护阅读位置、选区和OCR局部失败恢复，学生从Chat返回文档时仍回到同一版本和区域。",
        ["失败重试只重放失败步骤，不清空正文、选区、问题草稿或成功引用。"],
        ["统一深链携带现有Location/Selection身份，不改变F7-T02恢复状态机。"],
        ["故障注入验证刷新、离开返回、版本漂移、OCR失败和来源回跳恢复。"],
    ),
    "G12-R01": item(
        "F7-T04已经支持的PDF、PPTX、DOCX、图片和文本附件必须继续可用，F7-T05只把附件解析来源纳入统一引用和审计。",
        ["不得新增客户端密钥上传、未授权外部发送或把附件变成canonical课程事实。"],
        ["复用chat attachment parse对象，在回答SourceRef中记录附件版本和可定位片段。"],
        ["重跑五类附件、格式拒绝、owner隔离和不写学习事件测试。"],
    ),
    "G12-R02": item(
        "附件仍必须解析到可发送终态后才能参与回答；统一审计只记录实际参与的解析版本。",
        ["queued/parsing/failed附件不能被审计摘要宣称已使用；重复发送不得创建重复消息或run。"],
        ["从F7-T04消息冻结的attachmentParseIds生成真实输入来源列表。"],
        ["测试未解析拒绝、部分失败确认、幂等发送和审计输入一致。"],
    ),
    "G12-R03": item(
        "附件解析阶段、失败位置和重试动作继续对学生可见，Agent审计不得覆盖或美化这些真实附件状态。",
        ["错误不直出trace、路径、提示词或密钥；单项失败不清空其他附件和草稿。"],
        ["公开审计引用附件业务阶段和清洗后的错误，不替换F7-T04附件状态机。"],
        ["故障注入验证解析失败、单项重试和Agent输入状态一致。"],
    ),
    "G12-R06": item(
        "等待、解析中、可发送、部分失败、失败可重试和已移除六类附件状态必须在加入审计后继续准确恢复。",
        ["状态不能只靠颜色；removed附件不得出现在回答来源或Agent输入中。"],
        ["统一来源读取服务端附件终态，不从前端缓存猜测。"],
        ["重跑附件状态机、旧版本冲突、removed排除和双尺寸状态可读性。"],
    ),
    "G12-R08": item(
        "附件、回答和后续资源生成共享同一可定位上下文，F7-T05负责把已有字段统一为稳定SourceRef并支持反向导航。",
        ["无权限、已移除或版本漂移附件不能继续作为有效来源；完整资源仍只在学习空间。"],
        ["统一contextRefs、attachmentParseIds、sourceRefs、resourceLinks和selectionIds的投影。"],
        ["API与E2E验证附件到回答到资源的引用身份一致和失效语义。"],
    ),
    "G27-R01": item(
        "F2-T05已经决定的画像适配仍由真实生成结果体现；F7-T05只在公开审计中说明使用了哪些画像摘要，不重新计算或伪造个性化差异。",
        ["不得展示敏感画像原文、固定示例差异或把Agent面板变成画像编辑器。"],
        ["公开输入来源只显示允许公开的画像摘要引用和当前资源适配结果。"],
        ["兼容测试不同冻结画像产生的已有结果仍不同，审计不泄漏私密字段。"],
    ),
    "G27-R02": item(
        "分析、生成、校验、决策四阶段协作继续以F2-T05事实协议为准，F7-T05负责在真实问答和资源旁展示其公开投影。",
        ["不得另建第二套Agent状态机或用前端定时器模拟阶段。"],
        ["复用AgentAuditRun/step数据并统一映射到AgentTimeline。"],
        ["协议测试四阶段顺序、状态和跨问答/资源复用一致。"],
    ),
    "G27-R03": item(
        "公开审计要突出真实交叉验证发现的分歧、采用的修订和最终结论；没有分歧时明确写无实质分歧而不补造辩论。",
        ["只显示候选摘要和证据差异，不展示隐藏推理或冗长逐token辩论。"],
        ["从既有audit step中的候选、disagreement和revision字段生成可展开摘要。"],
        ["测试有分歧、无分歧、修订失败和最终采用结果四种事实。"],
    ),
    "G27-R04": item(
        "来源和校验结果必须与Agent摘要并列，使学生能判断回答或资源是否经过有效来源审核。",
        ["校验失败或来源撤回不能显示为已通过；内部评分数字默认不替代业务结论。"],
        ["将统一SourceRef状态和validation summary接入Agent校验阶段。"],
        ["测试有效、缺失、撤回和冲突来源对应的校验结果与UI状态。"],
    ),
    "G27-R06": item(
        "既有私有思维链边界必须在F7-T05继续生效，所有公开Agent视图只呈现职责、来源、候选摘要、分歧、校验、修订和决策。",
        ["不得返回提示词、密钥、raw log、trace、reasoning_content或chain_of_thought。"],
        ["复用F2清洗和字段白名单，并在共享组件中只接收公开协议。"],
        ["敏感字段递归扫描、前端静态扫描和浏览器文本检查全部通过。"],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F7-T05_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F7-T05 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    for entry in ledger["entries"]:
        entry["understanding"] = {
            "confirmed": True,
            **UNDERSTANDING[entry["atomic_requirement_id"]],
        }
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(ROOT / "scripts"))
    from context_recovery_atomic_gate import (
        expected_entries,
        load_task_payload,
        validate_ledger_identity,
        validate_understanding,
    )

    active = json.loads((CONTEXT_ROOT / "active_manifest.json").read_text(encoding="utf-8"))
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F7-T05")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F7-T05",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F7-T05 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
