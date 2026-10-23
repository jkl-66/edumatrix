#!/usr/bin/env python3
"""Record F6-T02's independent per-atom product understanding."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ROOT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
LEDGER_DIR = CONTEXT_ROOT / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"


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
    "G03-R01": item(
        "可交互模型是学习空间中的正式资源类型，学生通过参数、图表和实验观察理解模型规律；PPT/网页课件继续由独立资源页面负责。",
        ["不把可交互模型退化为静态图片或只读 3D 演示。", "不把网页课件、代码沙盒或实训任务书合并进同一页面。"],
        ["将 interactive_model 资源接入 /workspace/resources/models/:resourceId 专用页面。", "复用现有 ManifoldVisualizer 和实验计算能力，使用统一 Artifact/ArtifactVersion 事实源。"],
        ["自动验证 interactive_model 类型、专用路由、结构协议和非空计算结果。", "桌面调节参数并观察图形变化，确认无需离开资源页即可完成实验。"],
    ),
    "G03-R02": item(
        "模型资源必须绑定当前课程、知识点、画像适配和学习目标，参数范围、提示和完成条件随该上下文生成。",
        ["不把固定演示参数宣称为所有学生的个性化资源。", "课程或来源不匹配时不得静默借用另一资源。"],
        ["InteractiveModel 保存 course、knowledgePoint、profileSummary、learningGoal、datasetRef 和 sourceRefs。", "生成与详情投影从当前资源 manifest 读取同一冻结上下文。"],
        ["自动比较不同知识点/画像上下文的结构化模型内容和来源。", "人工从今日知识点打开模型，核对标题、目标、参数提示和来源一致。"],
    ),
    "G03-R03": item(
        "交互模型页面必须专业、清晰且易读：实验目标、参数、实时结果和观察提交有明确层级，不能成为技术文本墙或卡片墙。",
        ["图 3 只吸收类型可发现性和代表性预览，不复制紫色胶囊、蓝紫主题或十二按钮墙。", "不得用装饰性 3D 画面掩盖参数含义、完成条件和下一步。"],
        ["使用雾白、白色内容面和墨蓝灰视觉；首屏先显示模型目标、完成条件、参数控件、可视化和唯一主动作。", "解释、来源、历史和低频细节按需展开。"],
        ["双桌面截图检查 0 溢出、碰撞、裁切、小字、渐变和装饰效果。", "以首次使用者视角确认不读长说明也能找到参数和提交观察动作。"],
    ),
    "G03-R04": item(
        "只有学生在路径、资源中心或明确生成动作中表达需求时才生成或打开模型，不以无关弹窗打断学习。",
        ["普通浏览、进入对话或切换课程不得自动弹出模型。", "参数变化只更新当前实验草稿，不触发新的资源生成任务。"],
        ["沿用资源包单项生成和资源中心入口；模型页不增加全局浮窗。", "重新生成同类资源使用显式动作与既有幂等任务。"],
        ["自动检查普通导航不创建 interactive_model 资源或生成任务。", "人工浏览首页/对话确认无弹窗，再从资源中心显式打开模型。"],
    ),
    "G03-R05": item(
        "生成后的交互模型必须归档到统一资源中心，能够刷新、深链、查看来源和版本后再次打开。",
        ["不把聊天消息或浏览器内存作为模型唯一存储。", "历史版本只读，编辑或重新生成必须创建新版本。"],
        ["复用 F5 资源目录、详情、历史、比较和恢复协议。", "专用页面从 resourceId 恢复参数定义、数据集引用、计算序列和完成规则。"],
        ["自动验证归档、刷新、版本不可变和所有者隔离。", "人工从资源中心打开、刷新、切换历史并返回目录。"],
    ),
    "G03-R06": item(
        "交互模型是九类完整资源包中的一项，与讲义、导图、测验题、实训任务书、代码沙盒、视频、课件和费曼任务并列。",
        ["模型任务失败不得清空其他已生成资源。", "模型完成不代表全部资源或今日任务自动完成。"],
        ["沿用 F5-T02 九项稳定资源包和单项失败重试。", "模型页显示自身归档位置和完成状态，不复制资源包总览。"],
        ["回归九类资源条目、部分成功和单项重试。", "人工从完整资源包只打开模型，再返回确认其他资源状态未变。"],
    ),
    "G03-R07": item(
        "高质量个性化讲义继续由 F5-T03 的专用工作区负责；交互模型可以引用讲义，但不能替代或删减讲义合同。",
        ["模型页不重复实现讲义目录、代码片段、小测和导出。", "不得因增加模型而修改已关闭讲义的结构化合同。"],
        ["仅提供与讲义或来源的安全关联深链。", "运行 F5-T03 保护回归确认讲义页面仍完整。"],
        ["自动回归 handout workspace 和资源类型唯一归属。", "人工从模型打开关联讲义并返回，确认两个页面职责清晰。"],
    ),
    "G03-R08": item(
        "完整模型实验必须在学习空间专用页面中保存状态、来源、历史和版本；智能对话只提供摘要、解释和打开资源的入口。",
        ["不在聊天消息中渲染完整参数工作台或长期保存实验草稿。", "对话解释不直接创建模型观察证据。"],
        ["模型页面拥有参数草稿、计算结果、观察表单和提交记录。", "Chat 只携带资源、版本、参数摘要和当前问题的安全深链。"],
        ["自动验证对话入口与模型资源共享 resourceId 且不复制状态。", "人工从模型发起提问后返回，确认参数草稿和已提交观察仍可恢复。"],
    ),
    "G26-R01": item(
        "可交互模型使用团队已预置、已解析的垂直领域知识库作为课程和来源上下文，学生无需先上传课程材料。",
        ["模型资源不得脱离预置课程来源成为通用玩具。", "来源缺失时诚实显示不可发布或不可验证状态。"],
        ["datasetRef 和 sourceRefs 绑定预置课程对象、文档或稳定数据快照。", "资源详情提供来源深链与来源可用状态。"],
        ["自动验证来源属于当前课程且可追溯。", "人工查看模型来源并定位到预置知识库文档。"],
    ),
    "G26-R02": item(
        "当前主领域固定为人工智能/机器学习工程技能，模型样例和实验语言围绕该领域，不扩成无边界通用实验平台。",
        ["本任务不添加第二业务领域或企业岗位体系。", "示例模型必须明确演示身份，不宣称来自真实企业。"],
        ["首个结构化模型聚焦可验证的机器学习机制，例如流形降维参数对嵌入和分群的影响。", "保留扩展数据协议但不为未来领域新增无调用抽象。"],
        ["自动检查课程和知识点属于 AI/ML 演示课程。", "人工确认术语、数据、参数和观察问题都服务于该垂直领域。"],
    ),
    "G26-R03": item(
        "理论资源中的模型规律必须通过可操作参数实验连接到实际观察，而不是只看文字或图。",
        ["普通拖动参数不直接记为掌握证据。", "只有提交包含结果快照和解释的观察记录才是有效实验行为。"],
        ["参数改变触发确定性重算并更新图表/表格草稿。", "提交观察保存参数、计算摘要、学生解释、来源和幂等键，再写统一学习事件。"],
        ["自动验证参数变化、确定性计算、草稿无证据和提交后单条证据。", "人工调两个参数、观察变化、填写解释并提交。"],
    ),
    "G26-R04": item(
        "书本理论通过模型参数、数据快照、结果指标和排错提示转化为技能活动；实际代码编辑和训练仍由代码沙盒承担。",
        ["交互模型不伪装成真实训练作业或代码执行器。", "计算结果必须可复现，错误需指出具体参数或数据约束。"],
        ["InteractiveModel 定义 parameters、constraints、datasetRef、computedSeries 和 observationPrompts。", "图形失败时显示同一计算结果的可读表格，不伪造图像。"],
        ["自动覆盖边界参数、非法参数、确定性输出和图形降级表格。", "人工触发一个约束错误并修正后继续实验。"],
    ),
    "G26-R05": item(
        "定制模型资源从当前路径/知识点生成并归档，完成观察后通过统一事件回流今日任务，而不是孤立在工具页。",
        ["模型页不能直接改写路径节点或主观提高掌握度。", "可选模型资源完成不应解锁要求其他必做证据的智能组卷。"],
        ["深链保留 course、knowledgePoint、todayTask 和 returnTo；证据事件关联资源版本与任务。", "路径和组卷门禁继续由 F4 聚合器判断。"],
        ["回归课程/任务隔离、普通浏览无副作用和提交观察后的事件关联。", "人工从今日任务进入模型、提交观察并返回路径查看状态。"],
    ),
    "G26-R06": item(
        "完整实操标准由实训任务书定义；交互模型在自身范围内明确实验环境、参数步骤、检查点、结果、错误和观察提交条件。",
        ["模型页不复制任务书的工程提交物和 100 分评分表。", "完成条件必须由服务端验证，不能只靠前端勾选。"],
        ["页面显示运行环境/数据快照、参数约束、观察步骤、检查点、错误区和 completionRule。", "提交记录保存计算结果摘要与解释，失败保留草稿。"],
        ["自动覆盖完成规则、错误恢复、幂等重放和草稿保持。", "人工按步骤完成一次实验并核对完成证据与归档位置。"],
    ),
    "G26-R07": item(
        "实训任务书说明工程任务，代码沙盒负责编辑运行代码，可交互模型负责参数探索和规律观察；三者通过关联资源共同完成理论到技能的转化。",
        ["三种资源保持独立 Schema、路由、完成条件和证据类型。", "模型参数计算不得调用或伪装代码沙盒执行结果。"],
        ["模型页提供关联实训任务书和代码沙盒的次级入口。", "资源类型、路由和学习事件使用各自规范身份。"],
        ["自动检查三类 artifact_type、路由和事件类型不混淆。", "人工依次打开任务书、沙盒和模型，确认各页面主动作不同且上下文一致。"],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T02_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T02 ledger, found {len(matches)}")
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
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    sys.path.insert(0, str(ROOT / "scripts"))
    from context_recovery_atomic_gate import expected_entries, load_task_payload, validate_ledger_identity, validate_understanding

    active = json.loads((CONTEXT_ROOT / "active_manifest.json").read_text(encoding="utf-8"))
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T02")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T02",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError(f"F6-T02 understanding gate failed: {failures}")
    print(f"Updated and validated understanding for {len(actual_ids)} F6-T02 atoms: {ledger_path}")


if __name__ == "__main__":
    main()
