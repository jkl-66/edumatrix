#!/usr/bin/env python3
"""Record F6-T03's independent per-atom product understanding."""

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
    "G16-R01": item(
        "代码沙盒是学习空间中的正式资源工作区；学生编辑资源绑定的代码并发起真实本地运行，每次运行形成可追溯的 runAttemptId。",
        ["不再把 /workspace/code/:resourceId 映射到聊天页或返回预录输出。", "只运行资源声明且本机支持的运行时；不把外部模型、Docker 或浏览器模拟当成代码执行器。"],
        ["为 code_sandbox 资源提供专用详情协议、保存接口、运行接口和正式 Vue 工作区。", "复用统一资源、来源、版本、身份和今日任务上下文，不建立第二套课程或用户事实源。"],
        ["自动验证编辑、保存、刷新恢复、运行结果与 runAttemptId 一致。", "人工修改预置代码后运行，确认结果来自修改后的代码而非固定演示数据。"],
    ),
    "G16-R02": item(
        "每次运行必须把真实标准输出、标准错误和绘图产物分别归入同一运行尝试，学生能明确判断代码做了什么、哪里失败。",
        ["不得把 stderr 混进成功输出或用假图替代绘图失败。", "没有图表时诚实显示无图表；运行失败仍保留已产生的 stdout、stderr 和状态。"],
        ["运行结果协议返回状态、退出码、stdout、stderr、图表、耗时和时间戳。", "前端右栏以稳定标签或分区显示三类结果，并为图表加载失败提供文字错误和可重试查看。"],
        ["自动覆盖正常输出、语法/运行错误和 Matplotlib 绘图。", "人工运行三种样例并核对右栏内容、退出码和状态一致。"],
    ),
    "G16-R06": item(
        "桌面代码沙盒采用固定 22/50/28 三栏：左栏是任务、文件和历史，中栏是编辑器、标准输入与运行控制，右栏是运行结果，并为 F6-T04 的点评保留诚实入口。",
        ["不复制竞品的双重全局导航、蓝紫视觉或卡片墙。", "F6-T03 不生成点评正文；未执行 F6-T04 时明确显示需要先完成真实运行。"],
        ["实现稳定的三列网格、各栏独立滚动和明确的首屏主动作。", "在 1440x900 与 1366x768 桌面视口保持编辑器、控制区和结果区可用。"],
        ["E2E 检查三栏比例、主动作可见、无横向溢出、遮挡或文本裁切。", "人工从左栏选择任务，在中栏运行，并在右栏读取结果，全程无需猜测下一步。"],
    ),
    "G16-R07": item(
        "运行生命周期必须显式区分 queued、running、stopped、success、runtime_error 和 timeout；停止或超时后清理主进程及其子进程，并把最终状态写回运行尝试。",
        ["同一资源同一学生只允许一个活动运行，重复运行请求不得创建并发孤儿进程。", "停止已结束任务返回真实终态，不伪装成新一次成功停止。"],
        ["后端维护最小活动进程注册表、超时边界和进程树终止；持久化每次尝试的终态。", "前端运行时禁用冲突操作，提供停止按钮并轮询或读取明确终态。"],
        ["自动覆盖正常结束、主动停止、无限循环超时、重复停止和子进程清理。", "人工运行无限循环后停止，确认状态结束且系统中无残留测试进程。"],
    ),
    "G16-R08": item(
        "stdout、stderr 和图表独立呈现；大输出采用有说明的保留与查看机制，必须保住开头、结尾、退出状态和核心结果，不能只显示一句无上下文的截断提示。",
        ["无限输出必须受硬上限保护，但达到上限时要显示原因、已保留字节和完整运行状态。", "前端预览限制不能丢失服务端已保留的结果或把截断误报为运行失败。"],
        ["运行协议记录 outputTruncated、capturedBytes、limitBytes 和可读取的保留输出。", "UI 提供可滚动结果、截断说明和完整保留内容查看，不让大文本撑坏三栏布局。"],
        ["自动运行超过预览上限但可正常结束的样例，校验头尾、字节统计和成功状态。", "人工确认大输出页面仍可操作，核心结果和截断原因都可见。"],
    ),
    "G16-R10": item(
        "评委在没有 Docker 的 Windows 环境中也能运行团队预置的 AI/ML Python 示例；页面同时明确这是本地研究演示模式，不宣称提供生产级恶意代码隔离。",
        ["只允许已认证用户运行其可访问的沙盒资源，并限制工作目录、时间、输出和进程生命周期。", "不把本机模式描述为安全容器，也不自动执行来源不明的联网代码。"],
        ["使用项目已有 Python 环境和隔离临时工作目录执行，暴露运行能力与边界说明。", "预置示例在无 Docker 路径完成保存、运行、停止、错误和绘图演示。"],
        ["自动验证无需 Docker 的正常运行并检查路径边界、超时和身份隔离。", "人工按评委启动方式运行预置样例，核对边界说明与真实结果。"],
    ),
    "G16-R11": item(
        "打开页面、编辑代码或单次成功退出都不自动代表掌握；完成学习必须引用至少一次可验证运行，并满足资源声明的任务完成规则后由学生明确提交。",
        ["浏览、保存、停止、运行失败和普通成功运行不得直接提高掌握度。", "完成事件必须引用资源版本和 runAttemptId，重复提交不得重复计入。"],
        ["资源协议声明 completionRule，运行尝试保存可验证结果，完成动作由服务端复核。", "通过统一学习事件回流路径和门禁；掌握度仍由既有证据聚合器计算。"],
        ["自动验证无运行不可完成、失败运行不可完成、满足规则后单次完成、幂等重放无重复证据。", "人工刷新页面后从历史运行完成任务，确认不是仅进入页面即打勾。"],
    ),
    "G16-R12": item(
        "实训任务书说明工程任务，代码沙盒承担真实编辑运行，可交互模型承担参数探索；三者是可相互深链但 Schema、路由、主动作和证据类型均独立的资源。",
        ["不在代码沙盒复制完整任务书评分表或把参数滑块实验嵌成沙盒主功能。", "不让 sandbox_run 事件冒充 interactive_model_observation 或 task_brief_completion。"],
        ["code_sandbox 使用 /workspace/code/:resourceId 和独立资源 manifest。", "仅显示关联实训任务书、交互模型的次级入口，资源中心继续作为统一归档入口。"],
        ["自动检查三类 artifact_type、专用路由、Schema 和事件类型互不混淆。", "人工依次打开三类资源，确认同一知识点下职责清楚且能返回资源中心。"],
    ),
    "G16-R03": item(
        "F6-T04 将基于真实 runAttemptId 提供代码问题、潜在风险和改进方向；F6-T03 只保存足够的真实运行证据并保留点评区域。",
        ["本任务不调用外部模型、不生成模板点评或把运行错误直接包装成 AI 结论。", "没有真实运行时点评入口保持禁用并说明原因。"],
        ["运行尝试保存代码版本、标准输入、stdout、stderr、图表和终态供 F6-T04 引用。", "右栏预留点评标签和真实空态，不新增第二个点评事实源。"],
        ["自动验证运行证据字段完整且未生成 review 记录。", "人工确认运行前后点评区都没有伪造内容，并能识别将引用的运行编号。"],
    ),
    "G16-R04": item(
        "学生指定点评重点属于 F6-T04；F6-T03 必须保留稳定的运行上下文，使后续重点能绑定一次具体运行。",
        ["本任务不把点评重点当作标准输入或运行参数。", "不得在没有 runAttemptId 时提交点评重点。"],
        ["运行详情协议提供 F6-T04 可引用的运行编号和代码快照。", "点评入口在当前阶段显示后续行为边界，不保存假请求。"],
        ["自动验证运行与点评字段命名隔离。", "人工确认标准输入只影响程序，点评区不误写运行数据。"],
    ),
    "G16-R05": item(
        "应用 AI 建议后重跑比较由 F6-T04 完成；F6-T03 先保证每次保存和运行都有独立版本与 runAttemptId，历史能够比较前后结果。",
        ["运行新代码不得覆盖旧运行快照。", "F6-T03 不提供没有建议来源的‘应用改进代码’按钮。"],
        ["保存代码版本并按时间展示运行历史，选择历史只读查看其代码、输入和结果。", "后续 F6-T04 可从建议创建新草稿再复用同一运行接口。"],
        ["自动验证多次运行历史不可变且可按 ID 恢复。", "人工连续修改并运行两次，确认两个结果均可查看。"],
    ),
    "G16-R09": item(
        "F6-T04 的点评必须分区展示问题定位、点评重点、潜在风险、改进代码和应用建议；F6-T03 只建立能容纳该结果的右栏和真实运行引用。",
        ["本任务不把这五类内容写成固定演示文本。", "运行结果与 AI 点评保持两个清晰标签，点评失败不得遮蔽真实输出。"],
        ["右栏结果区保留运行/点评分区与 F6-T04 接口落点。", "运行服务独立于模型服务，确保外部模型不可用时仍可编辑和运行。"],
        ["自动验证运行 API 不依赖模型配置且点评记录为空。", "人工在无模型配置下运行代码，确认结果可用且点评区诚实说明未生成。"],
    ),
    "G26-R01": item(
        "代码沙盒沿用团队预置、已解析的垂直领域课程与来源，学生无需先上传课程材料即可进入实操。",
        ["不在 F6-T03 创建新的课程库或接受未审核联网材料作为权威来源。", "来源不可用时诚实显示状态，不静默换成另一课程。"],
        ["资源详情绑定既有 courseId、knowledgePointId、sourceRefs 和资源版本。", "沙盒从资源中心或今日路径深链打开。"],
        ["自动验证资源来源属于当前预置课程且跨课程不可访问。", "人工从今日知识点打开沙盒并查看来源入口。"],
    ),
    "G26-R02": item(
        "当前代码沙盒聚焦人工智能/机器学习工程技能，以 Python 数据处理、模型实验、评估和排错任务作为预置演示，不扩成无边界在线 IDE。",
        ["本任务不新增第二垂直领域、企业岗位体系或通用多语言云执行平台。", "演示数据必须标注为课程演示上下文，不宣称真实企业数据。"],
        ["首个正式 code_sandbox manifest 使用既有 AI/ML 课程、知识点和来源。", "任务描述、示例代码和完成规则服务于当前知识点。"],
        ["自动检查资源课程、语言、任务和来源上下文一致。", "人工确认页面标题、任务、代码和输出均属于 AI/ML 学习场景。"],
    ),
    "G26-R03": item(
        "理论资源通过真实代码编辑、输入、运行、排错和结果复核连接实际操作，运行尝试成为可验证技能证据的输入。",
        ["仅阅读任务说明或代码不形成操作证据。", "运行证据不直接等同于最终掌握度，仍需满足完成规则并由聚合器评估。"],
        ["记录代码快照、输入、运行终态、输出和资源版本。", "显式完成动作把合格运行引用写入统一学习事件。"],
        ["自动验证浏览无事件、运行失败无完成、合格运行可被完成事件引用。", "人工完成一次编辑-运行-排错-再运行流程并查看历史。"],
    ),
    "G26-R04": item(
        "课程理论被转化为可执行的 AI/ML 编程任务，覆盖数据处理、模型选择、训练、评估或排错中的当前知识点目标。",
        ["一个资源只承担声明的当前任务，不用固定代码宣称覆盖全部产业流程。", "模型参数规律观察仍由可交互模型负责。"],
        ["code_sandbox manifest 保存任务目标、起始文件、标准输入、检查点、完成规则和来源。", "任务切换从资源或任务列表读取，不在前端硬编码为所有课程通用。"],
        ["自动验证不同任务 manifest 驱动不同代码、输入和完成条件。", "人工选择两个任务，确认编辑器和任务要求同步切换且历史不串联。"],
    ),
    "G26-R05": item(
        "代码沙盒作为九类资源包中的实操资源从今日知识点生成、归档并深链打开；完成后只通过统一事件回流路径和组卷门禁。",
        ["沙盒页面不直接修改路径节点或主观增加掌握度。", "单项失败或重跑不得清空资源包中的其他产物。"],
        ["复用 F5 资源归档、F4 今日任务和统一事件聚合协议。", "保留 returnTo、todayTaskId 和资源版本引用。"],
        ["回归资源包单项重试、任务隔离和完成事件关联。", "人工从总路径进入沙盒、完成后返回并查看对应今日任务状态。"],
    ),
    "G26-R06": item(
        "完整工程目标、环境、步骤、检查点、提交物和评分标准由关联实训任务书负责；沙盒显示执行所需的任务摘要、运行环境、当前检查点、结果、错误和完成条件。",
        ["代码沙盒不复制整份任务书或自造另一套评分标准。", "服务端完成校验不能只依赖前端勾选。"],
        ["资源 manifest 引用 training_brief_resource_id，并包含沙盒专属起始文件、运行约束和 completionRule。", "页面提供打开任务书的次级动作和当前检查点状态。"],
        ["自动验证关联资源、完成规则和错误恢复。", "人工从任务书进入沙盒，运行失败后修正并满足检查点。"],
    ),
    "G26-R07": item(
        "实训任务书负责说明，代码沙盒负责真实运行，可交互模型负责参数探索；三类资源通过同一课程、知识点和来源关联，形成理论到技能的连续链路。",
        ["三类资源保持独立详情页、状态、版本和证据。", "任何一类完成都不自动替代另外两类今日必做任务。"],
        ["沙盒只实现自身运行与历史，并提供关联资源深链。", "资源中心、路径和聚合器使用既有统一身份关联三类产物。"],
        ["自动回归三类资源身份、路由和事件类型唯一。", "人工在同一知识点依次打开任务书、沙盒和模型，确认主动作分别是阅读任务、运行代码和提交观察。"],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T03_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T03 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T03")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T03",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError(f"F6-T03 understanding gate failed: {failures}")
    print(f"Updated and validated understanding for {len(actual_ids)} F6-T03 atoms: {ledger_path}")


if __name__ == "__main__":
    main()
