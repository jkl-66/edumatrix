#!/usr/bin/env python3
"""Fill and validate F5-T06's task-local atomic understanding ledger."""

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


G03_SHARED_BOUNDARIES = [
    "吸收图3的资源类型可发现性、代表性预览和专业产物感，不复制十二个胶囊按钮、蓝紫配色或营销式页面。",
    "视频与课件只读取统一资源对象及其版本；普通打开、播放、跳段、翻页、查看来源、记本地草稿和导出不写掌握证据。",
    "F5-T06不生成视频文件，不实现F6测验、交互模型、代码沙盒或费曼的完整学习行为。",
]

G21_SHARED_BOUNDARIES = [
    "视频推荐和PPT/网页课件使用统一课程、知识点、资源与版本上下文，不建立第二套学习空间或媒体事实源。",
    "本任务不修改测评中心、总路径、复习、错题、笔记和智能组卷状态机，只验证其既有边界未被资源浏览破坏。",
    "完整内容只在专用资源深链展示；其他模块只显示摘要、状态和进入动作。",
]


UNDERSTANDING = {
    "G03-R01": item(
        "九类资源中的视频推荐和PPT/网页课件必须拥有正式专用页面；视频提供合法来源的观看体验，课件提供结构化预览、编辑和导出，并与可交互模型保持独立。",
        G03_SHARED_BOUNDARIES,
        [
            "为video和deck统一Artifact内容建立严格、安全的F5结构化投影及专用详情接口。",
            "将/workspace/resources/videos/:resourceId和/decks/:resourceId分别接入视频推荐页与课件页。",
        ],
        [
            "资源目录与九类资源包回归确认video、deck、interactive_model仍是三个独立条目和深链。",
            "双桌面E2E确认两个专用页面均可从统一资源中心打开且没有按钮墙或蓝紫主题。",
        ],
    ),
    "G03-R02": item(
        "视频推荐理由、章节排序和课件内容必须可追溯到当前课程、知识点、学习目标、画像支架和冻结来源，而不是通用素材列表或固定模板。",
        G03_SHARED_BOUNDARIES + [
            "画像只调整解释顺序、支架和推荐理由，不能修改课程事实、许可信息或来源内容。",
            "画像或证据不足时显示基线推荐依据，不伪造高度个性化。",
        ],
        [
            "结构化视频和课件内容保存courseId、knowledgePointId、learningGoal、adaptationSummary与sourceRefs。",
            "F5本地确定性生成器根据资源包冻结manifest生成可解释的推荐理由与课件页树。",
        ],
        [
            "用不同知识点或画像生成资源，验证推荐理由、章节重点或课件内容存在可解释差异。",
            "接口与DOM检查不暴露原始画像、事件ID、提示词或内部模型日志。",
        ],
    ),
    "G03-R03": item(
        "视频与课件页面要达到专业、清晰、易读的学习产物质量：首屏突出真实媒体或课件预览，结构与层级帮助学习，而不是把JSON或长文本直接堆给学生。",
        G03_SHARED_BOUNDARIES + [
            "F5-T06不修改已关闭的高质量讲义合同；课件采用演示文稿结构而非复制讲义正文。",
            "缺少可播放媒体或部分页面渲染失败时保留标题、章节和文字内容，不以装饰性占位冒充成功。",
        ],
        [
            "视频页使用推荐列表、主播放器/章节区和推荐理由/笔记区；课件页使用大纲、大预览和来源/版本/导出区。",
            "延续F1雾白、白色、墨蓝灰、思源字体和渐进披露规则，所有可见文字至少14px。",
        ],
        [
            "双桌面截图检查主内容优先、专业预览、稳定分栏、无文本墙、无卡片嵌套和无低对比文字。",
            "Impeccable有界检测只审查本任务改动的页面与组件。",
        ],
    ),
    "G03-R04": item(
        "视频和课件只在学生从路径、资源包或资源中心明确进入时加载已有资源；页面不自动创建媒体、弹出无关生成流程或打断当前学习。",
        G03_SHARED_BOUNDARIES + [
            "加载、刷新、跳段、翻页和返回只能读取现有资源，不能隐式创建新Artifact或版本。",
            "失效资源提供重试、替代项或返回资源中心，不要求上传课程材料。",
        ],
        [
            "两个workspace按resourceId读取统一详情接口，并以稳定加载、失败、恢复和空状态呈现。",
            "编辑课件必须由学生明确进入编辑并保存，保存才创建新版本。",
        ],
        [
            "E2E记录网络请求，确认普通浏览无生成、版本写入或学习证据POST。",
            "注入详情失败后确认当前页面骨架和已加载内容保留，重试只读取同一资源。",
        ],
    ),
    "G03-R05": item(
        "视频和课件继续由统一资源中心归档、搜索和再次打开，专用页面只是同一Artifact/Version的学习视图，不能建立平行视频库或课件库。",
        G03_SHARED_BOUNDARIES + [
            "不得复制资源身份、绕过资源中心筛选或把旧媒体对象变成第二事实源。",
            "页面级选中章节、播放位置、缩放或编辑草稿不是归档内容版本。",
        ],
        [
            "复用DBArtifact/DBArtifactVersion、统一来源、版本、导出和深链协议。",
            "目录中的video与deck条目保持原resourceId，并打开专用workspace。",
        ],
        [
            "资源中心搜索、分类、深链刷新和返回回归确认资源数量与ID无重复。",
            "数据库前后对比确认浏览没有创建平行资源或版本。",
        ],
    ),
    "G03-R06": item(
        "视频推荐和PPT/网页课件必须作为完整九类资源包中的稳定兄弟条目存在；F5-T06完善这两项而不改变其他七项的身份、状态、重试和完成规则。",
        G03_SHARED_BOUNDARIES + [
            "不得修改九类资源集合、资源包幂等键、单项失败重试、中断恢复或其他资源ID。",
            "生成成功、观看、翻页和导出均不等于今日必做任务完成。",
        ],
        [
            "F5本地确定性video与deck分支输出严格结构化内容并继续使用既有GenerationJob/Artifact协议。",
            "专用页面只消费归档资源及其安全来源和版本投影。",
        ],
        [
            "F5-T02资源包回归验证九项、部分成功、重试与恢复不变。",
            "E2E前后比较学习事件、路径任务、画像快照与组卷门禁均不变。",
        ],
    ),
    "G03-R07": item(
        "F5-T03已完成的高质量个性化讲义必须保持完整；视频和课件可引用讲义或同源材料，但不能降级、复制或覆盖讲义内容与版本。",
        G03_SHARED_BOUNDARIES + [
            "不修改f5.handout.v1、讲义三栏布局、编辑、比较、版本或导出。",
            "只有当前账号和课程可访问的真实讲义才可显示关联入口。",
        ],
        [
            "视频/课件的sourceRefs和relatedResources只投影真实可访问兄弟资源及专用深链。",
            "完整讲义继续只在/workspace/resources/handouts/:resourceId展示。",
        ],
        [
            "运行F5-T03聚焦回归，确认讲义结构、版本和导出没有变化。",
            "关联资源测试覆盖存在、缺失、跨所有者和错误类型。",
        ],
    ),
    "G03-R08": item(
        "完整视频推荐、分段信息、课件页面树、来源和版本必须保存在统一资源对象中；对话、路径和资源包只显示紧凑摘要与深链。",
        G03_SHARED_BOUNDARIES + [
            "不把完整课件、媒体清单、许可正文或编辑内容写入聊天消息、URL参数或新表。",
            "页面不得展示API Key、提示词、私有思维链、原始Agent日志或内部调度字段。",
        ],
        [
            "专用workspace从ArtifactVersion读取完整结构，对外响应只返回学生安全字段。",
            "资源包和其他入口继续使用已有标题、状态、用途和route摘要。",
        ],
        [
            "接口与DOM扫描确认完整产物只在专用资源路由出现且无私有字段。",
            "资源包回归确认紧凑摘要没有膨胀为完整视频或课件内容。",
        ],
    ),
    "G21-R01": item(
        "学习空间的正式资源集合必须包含可进入的视频推荐和PPT/网页课件，它们与测评、路径、讲义、导图、实训、代码、模型、费曼、复习、笔记和错题共同构成一个学习空间。",
        G21_SHARED_BOUNDARIES,
        [
            "保留既有一级学习空间与二级资源中心，不增加独立媒体工作台入口。",
            "为video和deck资源深链提供完整页面并维持共享应用壳。",
        ],
        [
            "路由与导航回归确认没有新增学生一级入口或重复学习空间。",
            "从资源中心和资源包分别进入视频与课件页面。",
        ],
    ),
    "G21-R02": item(
        "每个视频推荐和课件资源都必须以resourceId拥有可刷新、可返回、可直接分享内部链接的专用学习页面。",
        G21_SHARED_BOUNDARIES + [
            "深链刷新必须恢复同一资源和当前归档版本；资源不存在或越权时显示诚实错误。",
            "旧媒体功能可保留历史路由，但正式资源深链不能落到目录或生成工作台。",
        ],
        [
            "路由分别绑定视频推荐workspace与课件workspace，并从resourceId加载。",
            "保留return_to或默认返回资源中心的稳定导航。",
        ],
        [
            "双尺寸E2E直接打开深链、刷新、返回，并覆盖404/403/损坏内容。",
            "路由检查确认VideoResource不再复用视频目录页。",
        ],
    ),
    "G21-R03": item(
        "视频和课件页面必须显示并共享当前课程、知识点、学习目标、资源版本和任务上下文，使学生知道它们服务于哪一个学习步骤。",
        G21_SHARED_BOUNDARIES + [
            "上下文缺失时显示可识别的基线说明，不能把内部ID当作主要用户文案。",
            "切换媒体章节或课件页面不能改变全局课程上下文。",
        ],
        [
            "详情投影包含课程/知识点标题、学习目标、适配摘要、来源和返回上下文。",
            "页面首屏显示当前位置、当前任务、完成边界和下一步。",
        ],
        [
            "API测试验证上下文字段来自统一Artifact metadata而非重复查询源。",
            "截图确认首屏无需阅读长说明即可识别课程、知识点和主动作。",
        ],
    ),
    "G21-R04": item(
        "学生在视频章节或课件页面可把当前资源、章节/页面和来源上下文带入智能对话，但完整产物继续留在资源空间。",
        G21_SHARED_BOUNDARIES + [
            "本任务只提供紧凑的提问深链或动作，不重构F7智能对话与多模态解析。",
            "提问上下文只携带resourceId、versionId、segment/slideId和安全摘要。",
        ],
        [
            "两个页面提供针对当前章节/页面提问的真实路由动作并保留返回上下文。",
            "不在页面复制聊天线程或完整回答区。",
        ],
        [
            "DOM和路由测试确认提问动作包含最小安全上下文且无完整内容或私有字段。",
            "F7职责扫描确认未提前实现对话后端。",
        ],
    ),
    "G21-R05": item(
        "测评中心仍只承担入学诊断和学后智能组卷；视频推荐与课件是学习资源，不能成为第三种正式测评入口。",
        G21_SHARED_BOUNDARIES + [
            "视频章节中的提示或课件中的自检内容不在F5-T06提交评分证据。",
            "不修改/workspace/assessment/entry和/workspace/assessment/exam的导航与状态。",
        ],
        [
            "资源页面只提供学习、来源、笔记、编辑和导出动作，不提供正式测评按钮。",
            "保留既有测评中心路由与菜单合同。",
        ],
        [
            "导航和文案扫描确认测评中心仍只有两个正式入口。",
            "F4组卷门禁回归确认视频/课件浏览不会解锁测评。",
        ],
    ),
    "G21-R06": item(
        "视频和课件必须自然承接原版科目路径与新增总路径中的今日知识点，但F5-T06不改变路径结构、预算或每日任务编排。",
        G21_SHARED_BOUNDARIES + [
            "页面不得自行创建路径节点、修改预算或重排今日任务。",
            "返回路径时继续使用现有课程和知识点上下文。",
        ],
        [
            "资源详情保留path/task context和返回今日任务动作。",
            "复用F4总路径生成出的resourceId，不创建新路径映射。",
        ],
        [
            "F4路径回归确认节点、预算、必做状态与资源包关系不变。",
            "E2E从资源包/路径进入并返回后上下文一致。",
        ],
    ),
    "G21-R07": item(
        "复习中心的首要结构仍是日历和具体安排；视频与课件只能作为复习任务可跳转的资源，不得改写或替代复习首页。",
        G21_SHARED_BOUNDARIES + [
            "F5-T06不实施F8真实复习日历，也不把媒体页变成复习列表。",
            "普通媒体浏览不能创建或完成复习事件。",
        ],
        [
            "仅保持资源可被未来复习任务以resourceId引用的兼容字段。",
            "不修改Review与RevisionCalendar组件。",
        ],
        [
            "保护回归确认复习路由与当前数据未变化。",
            "数据库对比确认媒体浏览未写复习记录。",
        ],
    ),
    "G21-R08": item(
        "未来从复习知识点生成资源时，视频推荐和课件应复用同一九类资源协议；本任务只保证这两类资源可由统一资源包生成和打开。",
        G21_SHARED_BOUNDARIES + [
            "不提前实现F8复习一键生成或复习到组卷跳转。",
            "复习来源和今日路径来源必须共享同一资源类型与深链，不复制生成器。",
        ],
        [
            "保持resource bundle的video/deck任务可接受统一course/knowledgePoint上下文。",
            "专用页面不依赖某一种触发来源。",
        ],
        [
            "资源包协议测试验证相同类型可从不同合法context生成而路由一致。",
            "扫描确认没有新增复习专用视频或课件表。",
        ],
    ),
    "G21-R09": item(
        "复习完成必须由未来真实复习行为打勾并反馈画像；观看视频或翻阅课件本身在F5-T06中不能伪装成复习完成证据。",
        G21_SHARED_BOUNDARIES + [
            "不调用复习完成、掌握度更新或画像聚合接口。",
            "视频笔记和课件编辑只保存内容或草稿，不构成掌握证据。",
        ],
        [
            "页面所有普通动作保持只读学习边界；若保存课件版本，只写ArtifactVersion。",
            "不修改学习事件与聚合器。",
        ],
        [
            "E2E前后比较学习事件、ProfileEvidence、画像快照和复习记录数量及哈希。",
            "网络日志确认没有复习完成请求。",
        ],
    ),
    "G21-R10": item(
        "视频和课件必须显示资源历史并支持从统一生成入口按自定义知识点再次生成同类资源；F5-T06至少提供版本读取、课件另存新版本和明确的统一生成归属。",
        G21_SHARED_BOUNDARIES + [
            "自定义知识点生成仍由统一F5-T02/F5-T07协议负责，页面不得建立第二生成端点。",
            "恢复历史版本不能覆盖旧版本；课件编辑必须新建版本，视频推荐历史只读。",
        ],
        [
            "详情投影返回版本列表和当前版本；课件保存调用统一Artifact版本接口。",
            "页面提供版本选择、历史内容预览和返回资源中心生成同类资源的清晰动作。",
        ],
        [
            "测试覆盖版本切换、课件编辑新版本、冲突、失败保留当前内容和不可变旧版本。",
            "视频历史切换与课件深链刷新E2E通过。",
        ],
    ),
    "G21-R11": item(
        "视频与课件中不得出现被误称为测评中心的学习中练习；所有即时练习仍归F6测验题资源，正式测评中心仍只有入学诊断和智能组卷。",
        G21_SHARED_BOUNDARIES + [
            "不复用旧章节视频页的绑定练习、评分或实验回链界面作为正式F5视频推荐页。",
            "课件中的讲解问题只能作为静态提示，F5-T06不提交或判分。",
        ],
        [
            "正式VideoResource路由使用纯推荐/播放workspace，不使用旧ChapterVideoWorkspace的生成与练习流程。",
            "页面文案不新增测评中心第三入口。",
        ],
        [
            "路由与DOM扫描确认无课程视频生成、视频后练习、评分提交或实验回链控件。",
            "测评中心导航保护测试保持通过。",
        ],
    ),
    "G21-R12": item(
        "实训任务书、代码沙盒、可交互模型、视频推荐和课件必须保持独立资源身份与页面职责，媒体资源不能吞并工程指导、真实代码运行或参数实验。",
        G21_SHARED_BOUNDARIES + [
            "视频和课件页不嵌入代码编辑器、运行/停止、参数滑块或实验提交。",
            "关联兄弟资源只能使用真实深链，缺失时不补造。",
        ],
        [
            "保持五类资源不同artifact_type与route，媒体页面只投影关联资源摘要。",
            "不修改F5-T05任务书和F6后续沙盒/模型职责。",
        ],
        [
            "资源目录和路由测试确认类型、ID与入口独立。",
            "DOM检查媒体页没有伪沙盒、伪交互模型或实训评分表。",
        ],
    ),
    "G21-R13": item(
        "视频和课件全部生成后进入资源中心，但是否观看或编辑只有在总路径明确列为今日必做且产生规定证据时才影响智能组卷；本任务的普通媒体操作不自动完成任务。",
        G21_SHARED_BOUNDARIES + [
            "资源生成完成、视频播放、跳段、写笔记、课件翻页、编辑和导出均不自动勾选今日任务。",
            "不要求学生完成所有视频或课件才解锁组卷，继续服从F4必做任务集合。",
        ],
        [
            "媒体页面显示只读完成边界和返回今日任务动作，不调用task completion API。",
            "保留F4 exam gate对accepted evidence的唯一判断。",
        ],
        [
            "E2E完整操作视频和课件后确认今日任务状态与exam gate不变。",
            "F4-T05回归验证只有既定必做任务证据才能解锁组卷。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F5-T06_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F5-T06 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F5-T06")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T06",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError(f"F5-T06 atomic understanding gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F5-T06 atomic understandings: {ledger_path}")


if __name__ == "__main__":
    main()
