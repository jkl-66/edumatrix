#!/usr/bin/env python3
"""Fill F10-T03's task-local atomic understanding ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ROOT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
PAYLOAD_PATH = (
    CONTEXT_ROOT
    / "loaded_context"
    / "v20260818T100653+0800"
    / "F10-T03"
    / "F10-T03.payload.json"
)
LEDGER_PATH = (
    CONTEXT_ROOT
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION"
    / "F10-T03_04882AD7275023ACB5891970F81C48706282AECBFADB8DDEAAC117A8808DA2D1.json"
)
WORKLOG_PATH = ROOT / "outputs" / "原系统融合重构执行" / "02_融合重构_WORKLOG.md"

G22_IDS = [f"G22-R{index:02d}" for index in range(1, 17)]
G25_IDS = [f"G25-R{index:02d}" for index in range(1, 5)]
G28_IDS = [f"G28-R{index:02d}" for index in range(1, 8)]
ALL_IDS = G22_IDS + G25_IDS + G28_IDS


def item(
    product_meaning: str,
    required: str,
    prohibited: str,
    scope: str,
    verification: str,
) -> dict:
    return {
        "product_meaning": product_meaning,
        "behavior_boundaries": [required, prohibited],
        "implementation_scope": [
            scope,
            "F10-T03只收口规格、证据索引、依赖部署说明、工作日志和恢复规则；不重做已关闭功能，不修改运行页面、业务接口、正式数据库、Git或交付包。",
        ],
        "verification_plan": [
            verification,
            "以结构化交叉校验、真实文件/证据路径、部署静态检查和官方恢复加载器核对；本任务不改UI，F1-DR-01至F1-DR-10逐项记为不适用并说明无页面、样式、图表、弹窗或截图变更。",
        ],
        "confirmed": True,
    }


UNDERSTANDING = {
    "G22-R01": item(
        "最终上下文必须明确：学生进入新课程后先完成基于预置课程和画像的入学诊断，再形成可信学习起点。",
        "把诊断入口、作答、报告、失败恢复及F3-T03关闭证据连成可恢复说明；已有诊断可恢复或查看。",
        "禁止把上传课程材料设为前置、把浏览写成诊断证据，或只凭文档中的未来态宣称已实现。",
        "核对09/P28、10/F3-T03与F10-T03、13/G22-R01、00/11及F3-T03证据索引的一致性。",
        "交叉校验必须定位本原子的来源、主责章节/任务和真实关闭证据；无上下文人员可从文档找到新课程诊断的入口与恢复路径。",
    ),
    "G22-R02": item(
        "最终说明必须把画像和诊断证据如何形成推荐知识点、总路径、科目路径和下一步讲清楚。",
        "保留推荐理由、课程/画像/路径版本、今日任务和刷新恢复边界，并引用F4-T03实证。",
        "禁止把无证据推荐、跨课程画像混用或前端展示值写成真实掌握结论。",
        "核对09/P11/P28、10/F4-T03与F10-T03、13/G22-R02及F4-T03验收记录。",
        "验证文档能从诊断报告追到路径对象、推荐理由和F4-T03证据，且普通查看不产生学习证据。",
    ),
    "G22-R03": item(
        "最终上下文必须说明资源包同时冻结课程、知识点、画像、掌握证据、最近事件和课程来源。",
        "记录资源包的一次创建、九类归档、幂等恢复和F5-T02关闭证据。",
        "禁止把固定模板、跨课程来源、普通浏览触发生成或文件存在当作上下文生成证明。",
        "核对09/P11/P12/P28、10/F5-T02与F10-T03、13/G22-R03及资源包证据。",
        "交叉校验应证明请求上下文、九类对象和证据索引一致，并可追到F5-T02真实测试。",
    ),
    "G22-R04": item(
        "路径任务只有在资源自身完成条件产生可信、幂等事件后才自动勾选。",
        "最终说明区分生成完成、学习完成和掌握证据，并保留F4-T04统一事件边界。",
        "禁止把打开、浏览、预览、无结果运行或重复提交记为任务完成或掌握提升。",
        "核对09/P11/P27/P28、10/F4-T04与F10-T03、13/G22-R04及事件/路径证据。",
        "文档与测试证据必须能分别证明普通浏览零写入、有效完成精确勾选和重复动作幂等。",
    ),
    "G22-R05": item(
        "智能组卷只由当日必做任务的有效完成证据解锁，可选资源不阻塞。",
        "收口锁定、缺项列表、直达动作、解锁和后端重复校验，并引用F4-T05/F6-T06证据。",
        "禁止仅靠前端按钮状态放行、把可选资源列为缺项或用含糊禁用态替代解释。",
        "核对09/P10/P11/P28、10/F4-T05/F6-T06/F10-T03、13/G22-R05及门禁报告。",
        "交叉校验要能定位锁定与解锁证据、服务端门禁和失败恢复，不以页面存在代替行为。",
    ),
    "G22-R06": item(
        "正式组卷交卷后，同一可信事件链更新画像、路径、下一日安排、错题和复习，而不止显示分数。",
        "收口报告、聚合checkpoint、下游一致性和F8-T05关闭证据。",
        "禁止固定分数增量、交卷即完全掌握、页面刷新写证据或部分聚合失败时丢测评结果。",
        "核对09/P10/P22/P27/P28、10/F8-T05与F10-T03、13/G22-R06及反馈证据。",
        "验证文档能从一次正式交卷追到六个下游投影、幂等恢复和一致性版本。",
    ),
    "G22-R07": item(
        "错题、复习、笔记和资源中心是测评后的深度学习空间，7.20丰富能力必须继续可达。",
        "记录报告到四个空间的来源深链、核心能力、失败恢复和F8阶段保护证据。",
        "禁止用空洞摘要替代错题重做、真实日历、笔记版本或资源历史，也禁止普通查看写掌握度。",
        "核对09/P12/P22/P28、10/F8-T01至F8-T03与F10-T03、13/G22-R07及保护基线。",
        "文档应逐页指向真实能力与证据，且能证明浏览零写入和原版功能未减少。",
    ),
    "G22-R08": item(
        "动态疑问进入智能对话，系统先回答并给来源，再由学生显式生成相关资源。",
        "收口上下文深链、流式恢复、资源生成动作和F7-T04证据。",
        "禁止打开对话就写学习证据、把完整测验/代码执行塞回Chat或公开私有推理。",
        "核对09/P24/P28、10/F7-T04与F10-T03、13/G22-R08及Chat关闭报告。",
        "验证对话回答、来源、资源深链和普通进入零写入均有可定位证据。",
    ),
    "G22-R09": item(
        "九类完整产物分别保存在学习空间的专用资源对象中，Chat只显示摘要、进度和深链。",
        "收口九类唯一对象、专用路由、来源、版本、历史与生成状态。",
        "禁止在对话消息中复制完整产物、形成第二资源库或留下没有归档对象的临时内容。",
        "核对09/P12至P21/P28、10/F5-T02/F7-T04/F10-T03、13/G22-R09及九类资源证据。",
        "交叉校验应定位九类正式归档和Chat投影，证明每类只有一个事实对象。",
    ),
    "G22-R10": item(
        "每种资源空间都要保留历史/版本，并能针对自定义知识点创建同类资源和恢复失败任务。",
        "收口分类历史、版本比较/恢复、自定义生成、来源和F5-T07关闭证据。",
        "禁止用一份全局历史代替分类历史、覆盖旧版本、无来源生成或重试时删除成功项。",
        "核对09/P12至P21/P28、10/F5-T07与F10-T03、13/G22-R10及资源历史证据。",
        "验证文档可从每类资源定位历史、版本、生成与恢复规则，并引用真实验收结果。",
    ),
    "G22-R11": item(
        "AI过程只展示可审计事实：职责、输入来源、候选、分歧、校验、修订和最终决策摘要。",
        "收口F2-T05/F7-T05协议、脱敏字段、失败与历史结果分离及证据。",
        "禁止展示系统提示词、私有思维链、API Key、原始Agent日志、trace、worker或lease。",
        "核对09/P24-AGENT/P27/P28、10/F7-T05与F10-T03、13/G22-R11及敏感字段扫描。",
        "交叉校验必须证明公开字段完整、禁用字段不存在，且审计过程与最终回答可对应。",
    ),
    "G22-R12": item(
        "旧Chat测验、代码和联网搜索已分别迁入测验题资源、代码沙盒和知识库联网发现。",
        "最终上下文记录唯一正式归宿、旧深链兼容、上下文保持和F10-T01迁移证据。",
        "禁止恢复第二答题面、聊天内代码运行、独立联网搜索工作台或无提示404。",
        "核对09/P15/P17/P23/P24/P28、10/F10-T01/F10-T03、13/G22-R12及路由迁移合同。",
        "验证旧/新入口均收敛到同一对象，路由报告和用户可理解失效页证据可追溯。",
    ),
    "G22-R13": item(
        "完整闭环从自然语言多轮画像开始，课程内容由团队预置知识库提供，个人资料上传只是可选辅助。",
        "收口五维对话、逐轮确认、可跳过附件、预置课程和F3-T01/F3-T02证据。",
        "禁止强制上传教材课件、把单次表单冒充对话画像或让附件失败阻塞诊断。",
        "核对09/P05/P23/P28、10/F3-T01/F3-T02/F10-T03、13/G22-R13及首次旅程证据。",
        "验证无上传的新学生仍可完成画像、诊断、路径和资源生成，文档提供明确恢复点。",
    ),
    "G22-R14": item(
        "学生在总路径点击今日知识点，一次创建可恢复资源包并把九类产物分发到各自空间。",
        "收口唯一主动作、部分成功、单项重试、离开后恢复、重复点击幂等和F4-T04/F5-T02证据。",
        "禁止在Chat逐项堆产物、失败清空成功项或重复创建同知识点资源包。",
        "核对09/P11/P12/P28、10/F4-T04/F5-T02/F10-T03、13/G22-R14及资源包旅程。",
        "交叉校验应证明一次请求对应一个包和九类唯一对象，失败恢复保持成功对象ID/版本。",
    ),
    "G22-R15": item(
        "组卷锁定时逐条显示未完成的今日必做任务、完成条件和直达入口。",
        "收口缺项名称、资源类型、状态、深链、完成后同步减少和最终解锁。",
        "禁止只显示内部状态码或无解释禁用按钮，也禁止把可选项误列为必做。",
        "核对09/P10/P11/P28、10/F4-T05/F10-T03、13/G22-R15及门禁E2E。",
        "验证每个缺项深链可达、返回后状态同步，且全部必做完成后主动作与后端同时解锁。",
    ),
    "G22-R16": item(
        "生成、保存、判分或聚合失败时保留输入和已完成结果，从最近checkpoint只重试失败步骤。",
        "收口处理中、部分成功、失败、重试、恢复和完成状态以及幂等约束。",
        "禁止整批清空、重复成功步骤、暴露工程状态码或把部分失败写成完全成功。",
        "核对09/P29、10/F1-T03/F10-T03、13/G22-R16及各阶段故障恢复证据。",
        "交叉校验应能定位资源包、保存/判分和反馈聚合三类失败恢复，证明对象与学习事实不重复。",
    ),
    "G25-R01": item(
        "任何看不清的学枢参考帧都必须按画面时间回看原视频，仍不明确时再询问用户。",
        "最终审计保留视频、时间点、提取帧或明确的无歧义结论；本任务复核既有29图证据链。",
        "禁止从模糊截图、文件名或二手摘要猜测页面文字和交互。",
        "核对09/P00/P30、10/F0-T01/F10-T03、13/G25-R01和29图语义单元/源视频索引。",
        "机器校验确认每张参考图有来源与图文语义；发现实质歧义必须阻止关闭并记录待确认项。",
    ),
    "G25-R02": item(
        "contact sheet只用于导航，不能作为读取竞品细字、按钮或状态的权威证据。",
        "最终文档引用全尺寸原图或视频帧，并保留图片哈希和可确认结构。",
        "禁止凭缩略图补造文案、控件、分栏比例或交互状态。",
        "核对13的29图视觉合同、evidence图片清单、09/10图文合同及交叉校验器。",
        "验证所有图片合同都指向实际全尺寸文件，observed/adopt/avoid不能只来自contact sheet。",
    ),
    "G25-R03": item(
        "图文证据存在会改变产品方向的实质歧义时必须明确提出，不能静默选一个解释。",
        "区分可由原图/视频解决的细节与需要用户决策的方向冲突，并把结果写入审计/状态。",
        "禁止用实现便利、代码现状或模型猜测覆盖未解决歧义。",
        "扫描29图语义单元、冲突决定和延期项，核对是否存在空白、矛盾或未解释的歧义。",
        "若无实质歧义，报告明确为零；若有则逐项给来源、影响和所需决定并阻止EVIDENCE_VERIFIED。",
    ),
    "G25-R04": item(
        "每张图片必须与图片承载段、前一非空段、后一非空段、人工语义锚点和跨主题边界联合解释。",
        "最终规格保留29个图文语义单元及observed/adopt/avoid三类视觉合同。",
        "禁止把图片脱离Word上下文单独归类，或机械把最近段落当成图片含义。",
        "运行29图绑定校验并反查13、09、10与目标页面规格中的同一语义单元。",
        "验证29/29图片均有完整上下文、哈希、综合解释和唯一页面归宿，且无错位复用。",
    ),
    "G28-R01": item(
        "最终产品是在7.20原版上按批准改进方案做保护性优化，不是采用复杂新版作为第二套主体。",
        "最终上下文明确原版主体、候选能力池、保护页和已完成融合证据。",
        "禁止把复杂版工作台、阶段代码数量或新文件数量写成产品主体。",
        "核对06、09/P00/P02/P30、10/F0-T01/F10-T01/F10-T03、13/G28-R01及保护基线。",
        "交叉校验和无上下文复述都必须得出7.20主体结论，并能定位四个保护页与回滚证据。",
    ),
    "G28-R02": item(
        "同义入口和能力应合并到一个正式路由与事实对象，旧链接只负责兼容恢复。",
        "收口目标路由矩阵、兼容重定向、上下文恢复和F10-T01迁移结果。",
        "禁止继续维护两套正式页面、重复导航或同一对象双写。",
        "核对09/P02/P30、10/F1-T02/F10-T01/F10-T03、13/G28-R02及routeMigrationContract。",
        "验证全部当前路由有唯一归宿，旧深链不404且不创建第二事实对象。",
    ),
    "G28-R03": item(
        "闭环外且对普通用户无价值的独立功能应从普通导航和产品主线移除。",
        "最终文档区分正式、合并、兼容、内部、延期和舍弃，不把隐藏代码宣传成已交付。",
        "禁止企业治理、专家认证、组织集成、评委工作台或视频生成重新进入当前比赛主线。",
        "核对06、09/P02/P30、10/F1-T02/F10-T01/F10-T03、13/G28-R03及导航/路由证据。",
        "验证三角色普通导航无闭环外入口，延期能力有诚实边界且不阻塞学生旅程。",
    ),
    "G28-R04": item(
        "当前复杂版代码只作为候选能力池，只有具备明确任务、自然入口、统一对象和闭环价值时才复用。",
        "记录已复用能力的正式归宿和未准入能力的隐藏/延期决定。",
        "禁止因为代码已经存在、测试很多或实现成本高就保留割裂工作台。",
        "核对09/P30、10/F10-T01/F10-T03、13/G28-R04及候选能力迁移清单。",
        "验证每个公开候选能力都有目标路由、事件归宿和验收证据，其他能力不在普通产品表面。",
    ),
    "G28-R05": item(
        "候选功能一旦增加理解负担、破坏闭环或削弱原版体验，就应隐藏、延期或舍弃。",
        "最终上下文记录取舍理由、保护合同和可回滚方式。",
        "禁止以沉没代码量为理由牺牲用户体验或把失败的融合写成完成。",
        "核对09/P30、10/F10-T01/F10-T03、13/G28-R05及路由舍弃/延期证据。",
        "验证正式导航无重复工作台，舍弃项不再可见且原版能力仍可达。",
    ),
    "G28-R06": item(
        "完成闭环、易用性和7.20连续性始终优先于源代码数量与功能堆叠。",
        "最终说明以可操作旅程、保护页能力和用户理解成本作为完成依据。",
        "禁止用行数、路由数、文件数或测试总数替代逐功能与逐原子证据。",
        "核对06、09/P02、10/F0-T03/F10-T03、13/G28-R06及F10-T02旅程/保护结果。",
        "无上下文审阅者必须能顺畅复述并找到完整闭环，机器报告只作逐项证据而非数量宣称。",
    ),
    "G28-R07": item(
        "目标路由和原子数量由正确产品结构生成，固定52路由或只出现G01-G28不能作为覆盖门禁。",
        "最终交叉校验检查每条路由、原子、章节、任务和证据的实质内容及反向追踪。",
        "禁止硬编码数量作为成功条件、用ID存在代替页面行为或用组级结论替代逐原子核销。",
        "核对09/P00、10/F0-T01/F10-T03、13/G28-R07及12号生成器/报告。",
        "交叉校验必须验证完整字段、唯一主责、图文绑定、状态和证据路径，并拒绝旧固定数量术语。",
    ),
}


def atomic_write(path: Path, payload: dict) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main() -> None:
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    contract = payload["task_atomic_execution_contract"]
    if contract.get("task_id") != "F10-T03":
        raise RuntimeError("F10-T03 task contract mismatch")
    if contract.get("primary_atomic_requirement_ids") != []:
        raise RuntimeError("F10-T03 unexpectedly has primary atoms")
    if contract.get("related_atomic_requirement_ids") != ALL_IDS:
        raise RuntimeError("F10-T03 related atom order mismatch")
    if payload.get("exact_task_object", {}).get("source_images") or payload.get("images"):
        raise RuntimeError("F10-T03 unexpectedly contains direct source images")

    source_by_id = {
        source["atomic_requirement_id"]: source
        for source in payload["related_atomic_requirements"]
    }
    entries = ledger.get("entries", [])
    if [entry.get("atomic_requirement_id") for entry in entries] != ALL_IDS:
        raise RuntimeError("F10-T03 ledger atom set or order mismatch")
    if len(set(ALL_IDS)) != 27 or set(UNDERSTANDING) != set(ALL_IDS):
        raise RuntimeError("F10-T03 understanding map is incomplete or duplicated")

    for entry in entries:
        atom_id = entry["atomic_requirement_id"]
        source = source_by_id[atom_id]
        if entry.get("role") != "related":
            raise RuntimeError(f"{atom_id} must be related")
        if not entry.get("requirement_sha256"):
            raise RuntimeError(f"{atom_id} has no source hash")
        expected_paragraphs = (
            [64, 65]
            if atom_id.startswith("G22-")
            else [69]
            if atom_id.startswith("G25-")
            else [73]
        )
        if source.get("word_paragraphs") != expected_paragraphs:
            raise RuntimeError(f"{atom_id} Word paragraphs mismatch")
        if source.get("source_images") != []:
            raise RuntimeError(f"{atom_id} unexpectedly references a direct image")
        if not source.get("correct_product_interpretation"):
            raise RuntimeError(f"{atom_id} has no product interpretation")
        entry["understanding"] = UNDERSTANDING[atom_id]

    atomic_write(LEDGER_PATH, ledger)

    marker = "## WL-F10-T03-001 27条相关原子理解完成"
    worklog = WORKLOG_PATH.read_text(encoding="utf-8")
    if marker not in worklog:
        addition = f"""

{marker}

- 任务：`F10-T03 / NOT_STARTED`；合同为0条主责、27条相关原子，零主责不跳过协议、迁移和最终文档责任。
- 来源：逐条读取Word第64、65、69、73段及非空相邻段，P00/P02/P11/P28/P29/P30、10号F10-T03合同、13号G22/G25/G28和当前任务完整账本；本任务无直接图片，但G25要求最终复核29个既有图文语义单元。
- G22：16条分别确认诊断、画像路径、上下文资源、可信完成、组卷、反馈、深度学习、Chat、归档、历史、审计、能力迁移、预置课程、资源包、缺项直达和失败恢复的最终证据收口边界。
- G25：4条分别确认原视频回看、禁止缩略图猜测、实质歧义上报和图片与Word上下文联合解释。
- G28：7条分别确认7.20主体、同义能力合并、闭环外能力移除、候选准入、宁缺毋滥、用户体验优先和禁止固定数量门禁。
- UI边界：F10-T03是文档/协议任务，不修改页面、组件、样式、图表、弹窗或截图；F1-DR-01至F1-DR-10在最终验收中逐条记录N/A理由。
- 下一步：运行逐原子理解门禁并转换到`CONTEXT_VERIFIED`；通过前不修改最终文档或测试证据。
"""
        WORKLOG_PATH.write_text(worklog.rstrip() + addition + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "UNDERSTANDING_FILLED",
                "task": "F10-T03",
                "primary_atoms": 0,
                "related_atoms": len(ALL_IDS),
                "confirmed": sum(
                    entry["understanding"].get("confirmed") is True
                    for entry in entries
                ),
                "images": 0,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
