#!/usr/bin/env python3
"""Fill and validate F5-T05's task-local atomic understanding ledger."""

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
    product_meaning: str,
    behavior_boundaries: list[str],
    implementation_scope: list[str],
    verification_plan: list[str],
) -> dict[str, object]:
    return {
        "confirmed": True,
        "product_meaning": product_meaning,
        "behavior_boundaries": behavior_boundaries,
        "implementation_scope": implementation_scope,
        "verification_plan": verification_plan,
    }


UNDERSTANDING = {
    "G26-R03": item(
        "实训任务书必须把当前课程理论连接到学生可执行的工程任务，并把后续真实运行或参数实验作为技能证据入口，而不是继续停留在阅读和理论测验。",
        [
            "只阅读、滚动、展开步骤、查看来源或打开关联资源不能自动完成学习任务或改变掌握度。",
            "F5-T05只提供工程任务说明与真实资源深链，不提前实现F6代码运行、交互实验或它们的证据提交。",
            "任务书不能用泛化项目描述代替当前课程、知识点和画像上下文。",
        ],
        [
            "建立结构化TrainingTaskContent并将目标、前置条件、环境、数据、步骤、检查点、提交物和评分标准投影到专用页面。",
            "页面明确提供进入关联代码沙盒或可交互模型的动作，并解释完成证据来自这些真实操作或规定提交。",
        ],
        [
            "协议测试验证理论知识点能够映射到至少一个明确工程任务和后续执行资源。",
            "E2E打开、阅读和展开任务书后比较学习事件、画像、路径与组卷门禁均不变。",
        ],
    ),
    "G26-R04": item(
        "AI/ML课程的理论内容要转写为数据处理、模型选择、训练、评估和排错等可操作阶段，任务书必须明确当前任务实际覆盖哪些阶段和产出。",
        [
            "阶段集合必须由当前知识点和任务目标决定，不要求每份任务书机械包含全部五种活动。",
            "不得把示例数据集、模型或指标写成所有课程的固定产品行为；演示内容必须明确是当前冻结任务。",
            "任务书说明做什么和怎样检查，不在页面内伪造训练结果、评估分数或错误日志。",
        ],
        [
            "TrainingTaskContent步骤使用受控kind区分data/model/train/evaluate/debug等工程活动，并保留每步输入、动作、预期结果和失败提示。",
            "确定性演示生成器根据当前知识点创建与该主题相关的任务阶段，而不是通用三行Markdown。",
        ],
        [
            "结构测试验证每个步骤都有工程活动类型、动作、检查方法和可验证结果。",
            "用不同知识点/画像上下文生成任务书，确认目标、步骤或评分权重存在真实差异。",
        ],
    ),
    "G26-R06": item(
        "每份实训任务书都必须完整说明环境、执行步骤、检查点、预期与错误结果、提交物和评分标准，让学生知道怎样做、怎样判断做到以及失败后怎样恢复。",
        [
            "环境和数据不可用时必须显示具体缺失项、替代准备或返回动作，不能假装可以开始。",
            "检查点只能说明验证规则或待提交状态，不能因浏览页面自动标记通过。",
            "评分标准必须有项目、权重和可观察证据，权重总和必须一致且不能使用空泛主观描述。",
        ],
        [
            "严格schema要求prerequisites、environment、data、steps、checkpoints、deliverables、rubric和sourceRefs均非空且内部ID唯一。",
            "专用页面按准备、步骤、检查点、提交物、评分标准组织正文，并显示依赖缺失、内容损坏和来源不可用状态。",
        ],
        [
            "测试拒绝缺字段、重复ID、无检查点、无提交物、评分权重不合法和无来源的结构化任务书。",
            "双桌面E2E逐项展开内容并验证失败态、恢复态、空态和下一步均可操作。",
        ],
    ),
    "G26-R07": item(
        "实训任务书、代码沙盒和可交互模型是理论到技能转化的三段协作：任务书负责工程指导，沙盒负责真实代码编辑运行，交互模型负责参数探索与观察，三者必须各有独立资源身份和页面。",
        [
            "任务书页面不得嵌入代码编辑器、运行/停止、标准输出、参数滑块或实验结果来伪装后续能力。",
            "关联资源不存在、失效或无权访问时必须禁用入口并说明原因，不能生成假深链。",
            "完成证据由任务要求和真实沙盒/模型提交产生，进入关联页面本身不是完成。",
        ],
        [
            "linkedSandboxId和linkedModelId经过统一资源所有者、课程、类型和可用性投影后显示独立入口。",
            "任务书页用说明性任务正文加右侧关联资源区，代码沙盒与模型继续走各自专用路由。",
        ],
        [
            "API测试覆盖正确、缺失、跨所有者、跨课程和错误类型的两个关联资源。",
            "E2E从任务书分别进入关联沙盒/模型占位或真实路由，确认页面职责不重合且返回上下文稳定。",
        ],
    ),
    "G03-R01": item(
        "实训任务书是九类资源之一，并与可交互模型和PPT/网页课件并列存在；它只负责工程任务说明，不能替代其他资源。",
        [
            "F5-T05不实现F5-T06课件/视频工作区，也不提前实现F6交互模型。",
            "吸收图3的类型可发现性和专业产物感，不复制十二个胶囊按钮或蓝紫主题。",
            "关联入口打开真实兄弟资源，不能将模型或课件完整内容复制进任务书形成第二事实源。",
        ],
        [
            "保持九类资源类型、状态和路由不变，只为training_task增加严格内容投影和专用页面。",
            "ResourceCenter与资源包仍展示实训任务书、交互模型和课件为不同条目。",
        ],
        [
            "F5-T02资源包回归确认九类完整且兄弟资源入口未改变。",
            "DOM检查确认任务书页没有伪模型、伪课件或大按钮墙。",
        ],
    ),
    "G03-R02": item(
        "任务书必须根据当前课程、知识点、学习目标、画像适配和最近可信证据生成，使任务难度、支架、步骤和评分重点与学生当前状态相关。",
        [
            "打开、刷新或查看历史版本只读取已归档内容，不重新生成任务书。",
            "最近普通浏览事件不得作为难度适配证据；只使用冻结的可信学习事件摘要。",
            "画像或证据不足时如实使用通用支架并显示适配依据不足，不伪造高度个性化。",
        ],
        [
            "结构化任务书保留adaptationSummary、difficulty、estimatedMinutes、knowledgePointId及生成上下文摘要。",
            "确定性生成器从F5-T02冻结manifest读取知识点、目标、画像安全摘要和可信事件形成内容。",
        ],
        [
            "用不同画像或知识点生成任务书，验证目标、支架、步骤或rubric存在可解释差异。",
            "测试确认响应不暴露内部事件ID、私有画像或原始提示。",
        ],
    ),
    "G03-R03": item(
        "已关闭的高质量讲义继续保持完整；实训任务书也必须专业易读，但采用工程执行文档结构，不能退化为纯文本墙或复制讲义布局。",
        [
            "F5-T05不修改f5.handout.v1、讲义三栏阅读、编辑、版本或导出合同。",
            "任务书视觉重点是目标、步骤、检查点和提交物，不把图3的讲解报告外观机械套用。",
            "关联讲义只能通过真实深链打开，任务书内不复制完整讲义正文。",
        ],
        [
            "复用F1浅色极简令牌和文档排版尺度，为任务书建立独立的执行清单与评分结构。",
            "右侧来源/关联区可打开讲义或其他真实资源，但保持任务书正文独立。",
        ],
        [
            "F5-T03聚焦回归保持全绿。",
            "视觉验收确认任务书专业可扫读且与讲义、导图职责清楚分离。",
        ],
    ),
    "G03-R04": item(
        "任务书只在用户从路径、资源包或资源中心明确进入后加载；普通浏览不自动生成新任务、弹窗干扰或改写归档版本。",
        [
            "加载、滚动、展开、查看来源和返回都只能读取现有training_task资源。",
            "资源缺失或损坏时提供重新加载与返回资源中心，不要求学生上传课程材料。",
            "自定义生成和统一重试仍由F5-T02/F5-T07协议处理，本任务不增加隐式生成入口。",
        ],
        [
            "TrainingTaskWorkspace按resourceId调用统一资源详情GET端点。",
            "正文折叠状态只保存在前端，不调用资源生成、学习事件或任务完成POST。",
        ],
        [
            "E2E网络记录确认普通操作无生成和证据写入请求。",
            "错误态保留已加载内容和页面框架，重新加载只重读同一资源。",
        ],
    ),
    "G03-R05": item(
        "任务书继续由统一资源中心归档、检索和再次打开，专用页面只是同一artifact/version的执行阅读视图，不建立平行任务库。",
        [
            "不得复制artifact、另建任务书列表或绕过F5-T01资源筛选。",
            "页面返回资源中心后课程、类型、来源和生成状态上下文继续有效。",
            "折叠、阅读位置或本地偏好不能写入正文或创建新资源版本。",
        ],
        [
            "复用DBArtifact/DBArtifactVersion、统一详情、来源和版本投影。",
            "TrainingTaskResource路由从通用ResourceCenter切换到专用workspace，但resourceId不变。",
        ],
        [
            "资源中心回归确认training_task条目数量、搜索和ID无重复。",
            "E2E从统一目录打开、返回并刷新同一任务书。",
        ],
    ),
    "G03-R06": item(
        "实训任务书必须作为完整九类资源包中的稳定条目存在，F5-T05只完善这一项的内容和学习视图，不改变其他八项的生成、状态或完成规则。",
        [
            "不得修改九类资源集合、生成顺序、兄弟资源ID、单项重试和中断恢复。",
            "任务书生成成功、打开或阅读都不等于学习完成，也不标记其他资源完成。",
            "代码、模型、测验和费曼的真实交互按F6任务实现。",
        ],
        [
            "确定性training_task分支输出严格结构化内容并保留F5-T02任务协议。",
            "专用页面只消费已归档training_task资源及安全关联投影。",
        ],
        [
            "F5-T02资源包协议回归确认九项、幂等、恢复和状态不变。",
            "数据库前后对比确认阅读任务书不改变兄弟资源或完成状态。",
        ],
    ),
    "G03-R07": item(
        "个性化讲义的全部高级结构仍由F5-T03保留；任务书可以引用讲义作为准备材料，但不能把讲义降级成前置说明或破坏其版本、来源和导出。",
        [
            "F5-T05不修改讲义结构、版本和编辑接口。",
            "只有真实可访问讲义才显示为准备资源，无权或缺失时显示不可用状态。",
            "任务书中的概念摘要不能替代讲义正文。",
        ],
        [
            "可选关联资源投影保留类型、标题和专用深链。",
            "讲义打开动作继续使用/workspace/resources/handouts/:resourceId。",
        ],
        [
            "F5-T03组合回归确认讲义完整能力不变。",
            "关联资源测试覆盖存在、缺失、跨所有者和错误类型。",
        ],
    ),
    "G03-R08": item(
        "完整任务书、来源、版本和状态保存在统一学习资源对象；智能对话或路径只显示摘要和深链，不把任务书全文堆进消息或任务卡。",
        [
            "不把完整任务书写入Chat消息、URL查询参数或新的平行后端表。",
            "页面不得暴露提示词、API Key、私有思维链、原始Agent日志或内部事件ID。",
            "版本内容以统一artifact为唯一事实源，本地折叠状态不成为内容来源。",
        ],
        [
            "TrainingTaskWorkspace从统一artifact version读取结构、sourceRefs和linked资源。",
            "向智能对话提问只携带resourceId、versionId、步骤/检查点ID和紧凑摘要。",
        ],
        [
            "接口和DOM扫描确认全文只在专用任务书路由展示。",
            "安全回归确认响应和页面不含私有模型上下文或原始日志。",
        ],
    ),
    "G26-R01": item(
        "任务书必须基于团队预置并已冻结的垂直领域课程知识库生成，学生首次使用无需上传课程材料。",
        [
            "F5-T05不新增课程资料上传、教材选择或联网抓取作为开始实训的必需步骤。",
            "来源必须来自已准入课程sourceRefs，缺少来源时不得宣称任务具有课程依据或发布就绪。",
            "未经许可的联网材料不能被任务书自动引用。",
        ],
        [
            "结构化任务书要求sourceRefs并投影真实课程标题、章节与定位。",
            "页面首屏显示当前预置课程和知识点来源，不显示上传课程材料主动作。",
        ],
        [
            "API测试验证无有效课程来源时发布状态受限但原内容仍可诚实阅读。",
            "E2E使用冻结合成AI/ML课程直接打开任务书且不经过上传。",
        ],
    ),
    "G26-R02": item(
        "当前主垂直领域固定为人工智能/机器学习工程技能，任务书的术语、数据、步骤和评分必须体现该领域，而不是无领域的通用待办清单。",
        [
            "本周期不扩展第二真实行业领域，也不宣称已完成跨行业泛化。",
            "任务书不能硬编码单一算法或指标为所有AI/ML任务；内容跟随当前知识点。",
            "演示数据和任务标准必须明确为冻结合成教学数据，不冒充真实企业标准。",
        ],
        [
            "确定性示例围绕AI/ML知识点生成数据准备、模型训练/评估或排错任务。",
            "页面显示课程、知识点、工程能力阶段和演示数据说明。",
        ],
        [
            "测试检查不同AI/ML知识点生成的工程动作不同且无固定accuracy/recall产品行为。",
            "文案扫描确认不宣称真实企业验证或第二领域完成。",
        ],
    ),
    "G26-R05": item(
        "实训任务书必须由今日知识点的统一资源包生成并归档，能够从总路径进入，并把后续真实沙盒/模型操作接回同一学习闭环。",
        [
            "F5-T05不修改总路径选择、资源包幂等键或今日必做任务门禁。",
            "生成完成和阅读任务书都不能自动勾选路径任务或解锁组卷。",
            "关联沙盒/模型完成后怎样写证据由F6与统一聚合协议负责，本任务只保留任务/资源引用。",
        ],
        [
            "资源manifest中的courseId、knowledgePointId、path/task上下文投影到任务书详情。",
            "专用页面提供返回资源包/路径和进入关联执行资源的清晰下一步。",
        ],
        [
            "F4路径、资源生成和组卷门禁回归确认状态机不变。",
            "E2E从资源包进入任务书并返回，路径任务和exam gate前后保持一致。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F5-T05_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F5-T05 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    for entry in ledger["entries"]:
        entry["understanding"] = UNDERSTANDING[entry["atomic_requirement_id"]]
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F5-T05")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T05",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError(f"F5-T05 atomic understanding gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F5-T05 atomic understandings: {ledger_path}")


if __name__ == "__main__":
    main()
