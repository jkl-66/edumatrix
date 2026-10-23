#!/usr/bin/env python3
"""Fill and validate F5-T04's task-local atomic understanding ledger."""

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
    "G03-R01": item(
        "思维导图是九类学习产物中的独立一类；它必须与可交互模型和PPT/网页课件并列存在，不能吞并或代替这些资源。",
        [
            "F5-T04只实现mind_map专用页面和数据投影，不提前实现F6交互模型或F5-T06课件工作区。",
            "沿用图3的资源类型可发现性，不复制十二个大胶囊按钮、紫色主题或营销式产物墙。",
            "导图节点中的资源链接只能打开既有独立资源，不能把其他资源内容复制进导图形成第二事实源。",
        ],
        [
            "保持resource_bundles中的interactive_model和deck类型、状态及深链不变。",
            "MindmapWorkspace只读取mind_map artifact，并在节点详情中提供受约束的既有资源深链。",
        ],
        [
            "资源包回归确认九类资源仍完整且模型、课件入口未被改写。",
            "DOM与路由检查确认导图页面没有伪装成模型或课件的交互区域。",
        ],
    ),
    "G03-R02": item(
        "导图内容必须来自当前资源冻结的课程、知识点、学习目标和画像适配上下文，使层级、摘要、掌握区间与学生当前学习任务相关。",
        [
            "打开导图时读取已归档版本，不因刷新、搜索、折叠或拖动画布重新生成内容。",
            "masteryBand只能作为已有掌握证据的只读投影，不得由节点访问次数或停留时间推断。",
            "缺少画像适配时如实显示通用导图，不宣称已经完成个性化生成。",
        ],
        [
            "结构化导图协议保留课程、知识点、学习目标、profile adaptation及节点masteryBand。",
            "确定性资源包生成器使用manifest中的冻结上下文创建导图节点和摘要。",
        ],
        [
            "后端测试断言导图投影与资源manifest的课程、知识点和目标一致。",
            "检查打开与操作导图前后画像快照、学习事件和掌握度不变。",
        ],
    ),
    "G03-R03": item(
        "图3要求的高质量讲义表现仍由已关闭的F5-T03承担；新增导图必须保持同一浅色极简产品语言，但不能破坏或重做讲义页面。",
        [
            "F5-T04不得修改f5.handout.v1结构、讲义三栏布局、编辑版本或导出合同。",
            "导图采用适合图结构的工作区，而不是把讲义正文或预览卡片墙搬进画布。",
            "节点进入讲义时只能使用稳定深链，不能在导图中嵌入完整讲义文本。",
        ],
        [
            "仅复用F1视觉令牌和统一资源元数据，不改HandoutWorkspace的内容结构。",
            "节点详情提供关联讲义的名称、用途和打开动作。",
        ],
        [
            "运行F5-T03聚焦回归确认讲义结构、版本和来源能力不变。",
            "浏览器检查导图与讲义视觉一致但页面职责清楚分离。",
        ],
    ),
    "G03-R04": item(
        "学生明确从资源中心、资源包或关联资源进入导图后才开始浏览；页面打开和普通操作不能自动触发新导图生成或弹窗打扰。",
        [
            "页面加载、刷新、搜索、聚焦、缩放、折叠和查看详情都只能读取现有资源。",
            "资源不存在或内容损坏时只提供重试读取和返回资源中心，不要求上传课程材料。",
            "自定义知识点生成同类资源由F5-T07统一实现，本任务不新增隐式生成入口。",
        ],
        [
            "MindmapWorkspace使用resourceId调用现有GET资源详情端点。",
            "所有画布操作保持前端本地状态或轻量布局偏好，不调用生成POST。",
        ],
        [
            "E2E网络记录确认普通导图操作没有资源生成请求。",
            "故障场景确认错误态没有无关弹窗且输入的搜索词和已加载节点不被清空。",
        ],
    ),
    "G03-R05": item(
        "导图继续由统一资源中心归档、检索和再次打开，专用导图页只是同一artifact的学习视图，不建立平行导图库。",
        [
            "不得复制artifact、另建导图列表或改变F5-T01资源筛选事实源。",
            "页面返回资源中心后原课程、类型、来源和状态筛选仍可使用。",
            "布局偏好不能写入资源正文或创建新资源版本。",
        ],
        [
            "复用DBArtifact/DBArtifactVersion与getM5Resource详情协议。",
            "ResourceCenter的mind_map深链改为打开MindmapWorkspace中的同一artifact ID。",
        ],
        [
            "目录回归确认mind_map搜索结果与详情页artifact ID一致且无重复记录。",
            "E2E从资源中心打开、返回并再次打开同一导图。",
        ],
    ),
    "G03-R06": item(
        "思维导图必须作为完整九类资源包中的稳定条目存在，F5-T04只完成这一条目的专用学习体验，不改变其他八项的生成和状态。",
        [
            "不得修改九类资源固定集合、兄弟资源ID、生成顺序或单项重试语义。",
            "浏览导图不能自动完成导图任务，更不能标记其他资源完成。",
            "F5阶段只提供导图归档和导航，测验、沙盒、模型、费曼的完整交互仍按后续任务实施。",
        ],
        [
            "让deterministic mind_map产物输出严格结构化内容，保留F5-T02的bundle/task协议。",
            "导图专用路由只消费现有mind_map资源。",
        ],
        [
            "F5-T02资源包回归确认九项数量、状态、深链和幂等性不变。",
            "浏览器与数据库对比确认导图交互不改兄弟资源和任务完成状态。",
        ],
    ),
    "G03-R07": item(
        "个性化讲义的完整高级结构仍必须保留；导图节点可以关联并打开讲义，但不能把讲义降级成节点摘要或破坏其版本来源合同。",
        [
            "F5-T04不修改讲义标题、摘要、目录、概念、图表、正反例、代码、小测、脚注、AI伙伴、进度、编辑或导出。",
            "关联讲义深链必须指向真实handout artifact，缺失时不显示虚假可用按钮。",
            "返回导图后恢复视图只恢复导图本地偏好，不改变讲义阅读或完成证据。",
        ],
        [
            "节点linkedResourceIds经过资源详情投影为安全的标题、类型和深链。",
            "关联handout使用现有/workspace/resources/handouts/:resourceId路由。",
        ],
        [
            "专项测试覆盖存在、缺失和无权访问的关联讲义。",
            "F5-T03组合回归与E2E确认讲义完整能力仍可达。",
        ],
    ),
    "G03-R08": item(
        "完整导图、来源、版本和状态必须保存在统一学习资源对象中；智能对话或其他页面最多显示摘要和深链。",
        [
            "不把完整节点树写入Chat消息、浏览器localStorage或新的平行后端表。",
            "只允许把视图偏好保存在浏览器，偏好不能成为内容事实源或学习证据。",
            "页面不得暴露提示词、API Key、私有思维链、原始Agent日志或内部对象哈希。",
        ],
        [
            "MindmapWorkspace从统一artifact version读取节点树、sourceRefs和linkedResourceIds。",
            "节点对话动作只携带紧凑上下文和稳定资源/节点引用。",
        ],
        [
            "接口与DOM检查确认完整导图只在专用路由展示。",
            "安全回归扫描响应和页面不含私有模型或内部审计数据。",
        ],
    ),
    "G10-R01": item(
        "资源思维导图要按知识层级和知识簇组织节点，帮助理解单份资源；它可以借鉴画像图的分类表达，但不是新的学习画像。",
        [
            "节点分类来自导图内容的章节/主题层级，不写回画像知识节点。",
            "不复制图12的画像总览、AI判断统计或30天筛选到资源导图。",
            "无有效树结构时回退层级列表，不能伪造知识簇。",
        ],
        [
            "结构化节点包含稳定nodeId、label、summary、relation和depth。",
            "画布与列表回退使用同一规范化树数据。",
        ],
        [
            "树结构测试确认深度、父子关系和分类顺序稳定。",
            "视觉验收确认学生能区分资源导图与/profile/learning画像图谱。",
        ],
    ),
    "G10-R02": item(
        "导图连线必须明确表达父子、先修、组成或关联关系，且任何错误或循环关系都不能使页面崩溃或无限遍历。",
        [
            "relation是展示语义，不自动转化为画像先修边或路径依赖。",
            "未知关系使用诚实的通用关联标签，不能猜成先修。",
            "自引用、重复nodeId、孤儿节点和循环边必须被拒绝或安全降级。",
        ],
        [
            "后端严格解析节点关系并执行唯一ID、父节点存在和循环保护。",
            "前端为主要树边和辅助关系提供克制、可辨认且非颜色唯一的表达。",
        ],
        [
            "测试覆盖合法树、自引用、两节点循环、重复ID、孤儿节点和大深度。",
            "E2E确认关系标签、折叠和重新展开后结构保持一致。",
        ],
    ),
    "G10-R03": item(
        "节点可以显示由现有证据计算出的masteryBand，帮助学生判断阅读重点，但该值必须只读并保留未知状态。",
        [
            "禁止用访问、搜索命中、展开或布局操作改变或补造掌握度。",
            "masteryBand只显示区间和文字状态，不把图12的精确百分比当作无证据事实。",
            "颜色不是唯一编码，节点还需显示文字或可访问标签。",
        ],
        [
            "导图协议允许unknown、needs_work、developing、secure等受控掌握区间。",
            "节点和右侧详情以文字标签显示只读掌握提示。",
        ],
        [
            "协议测试拒绝未知band或安全归一为unknown。",
            "前后数据库快照确认所有普通导图操作不改变掌握记录。",
        ],
    ),
    "G10-R04": item(
        "点击导图节点后，右侧详情必须解释该节点内容、关系、来源、只读掌握提示和下一步关联资源，而不是只改变节点颜色。",
        [
            "详情依据导图节点与统一来源，不调用模型生成新的画像判断。",
            "提问、测验和笔记动作携带resourceId、nodeId与sourceRef，完整交互分别由后续任务实现。",
            "无来源或无关联资源时显示诚实空态，不生成虚假按钮。",
        ],
        [
            "MindmapWorkspace采用大画布加固定右侧节点详情的Operate/Read混合结构。",
            "节点详情提供关系、摘要、来源定位、关联资源打开和后续动作入口。",
        ],
        [
            "组件测试覆盖节点选择、详情切换、无来源和失效深链。",
            "双桌面E2E执行选择节点、查看来源、打开讲义并返回。",
        ],
    ),
    "G10-R05": item(
        "7.20学习画像与其知识掌握图谱必须继续保留；资源导图是单资源理解工具，不能替换、复用路由或削弱画像页面。",
        [
            "F5-T04不修改/profile/learning路由、画像标签、分析维度或证据侧栏。",
            "不能把CollapsibleMindmap改造成只适用于资源页而导致画像已有调用失效。",
            "共享组件若重构必须保持旧props与既有浏览行为，或用新组件隔离资源导图。",
        ],
        [
            "优先将通用树渲染能力抽为兼容组件，MindmapWorkspace负责资源特有详情。",
            "KnowledgeGraphExplorer继续专属画像页面，不作为资源内容事实源。",
        ],
        [
            "F4画像聚焦回归确认/profile/learning功能和路由不变。",
            "组件测试覆盖旧CollapsibleMindmap调用兼容性。",
        ],
    ),
    "G10-R06": item(
        "只有题目、复述、代码、实验、复习等可验证行为可以改变掌握度；导图浏览、搜索、缩放、拖动、折叠、选择和布局保存一律不是学习证据。",
        [
            "视图偏好与学习事件使用完全不同的存储和接口，不能复用complete或evidence端点。",
            "打开关联讲义或返回导图也不能自动完成任务。",
            "若未来完成条件要求解释节点或关联小测，必须由对应提交事件产生证据，本任务不以浏览替代。",
        ],
        [
            "所有普通导图交互保持纯GET、前端状态或localStorage布局偏好。",
            "不在MindmapWorkspace中调用学习完成、画像更新或路径聚合接口。",
        ],
        [
            "E2E操作前后比较learning_events、profile_snapshots、path_nodes和exam gate摘要。",
            "网络断言普通操作无证据写入请求。",
        ],
    ),
    "G10-R07": item(
        "7.20画像的维度查看、丰富分析、个性化建议、画像编辑和一键生成资源等实质能力必须继续可用，资源导图只增加资源学习深链。",
        [
            "F5-T04不重排或删除StudentAnalysis中的原版能力。",
            "导图上的掌握提示不能成为编辑画像的快捷方式。",
            "从画像生成资源仍走既有路径和资源包协议。",
        ],
        [
            "只在关联资源需要时提供返回画像或查看只读画像的导航，不嵌入画像编辑器。",
            "保留现有画像路由、API与视觉保护基线。",
        ],
        [
            "运行F4-T02保护测试与核心页面非空检查。",
            "浏览器确认画像原有标签和关键动作仍可达。",
        ],
    ),
    "G21-R01": item(
        "学习空间必须继续包含测评、路径、九类资源、复习、笔记、错题和资源中心；F5-T04只把其中的思维导图入口变成完整专用页面。",
        [
            "不得新增一级导航、阶段工作台或第二个学习空间。",
            "不能为了导图隐藏测评、路径、其他资源、复习、笔记或错题入口。",
            "页面继承统一AppShell与学习空间课程上下文。",
        ],
        [
            "将MindmapResource路由从通用ResourceCenter切换到MindmapWorkspace。",
            "保持其他学习空间路由和二级导航映射不变。",
        ],
        [
            "导航合同测试确认完整子模块集合未减少且无重复入口。",
            "E2E从学习空间进入导图并返回资源中心。",
        ],
    ),
    "G21-R02": item(
        "思维导图必须拥有可刷新、可收藏和可返回的稳定专用深链，resourceId唯一定位统一资源对象。",
        [
            "深链不能回落为资源中心通用列表，也不能依赖页面内临时选中项。",
            "无效或无权resourceId必须给出明确错误和返回动作。",
            "刷新后恢复同一版本、选中节点和视图偏好，但不能创建新资源。",
        ],
        [
            "新增MindmapWorkspace并绑定/workspace/resources/mindmaps/:resourceId。",
            "使用route.params.resourceId读取详情，并按resourceId隔离布局偏好。",
        ],
        [
            "路由测试覆盖直接访问、刷新、无效ID和错误资源类型。",
            "E2E确认返回后视图恢复且URL保持稳定。",
        ],
    ),
    "G21-R03": item(
        "导图必须共享当前课程、知识点、任务、资源和来源上下文，与路径和资源包形成同一闭环，而不是孤立技术演示页。",
        [
            "上下文以artifact和manifest中的稳定ID为准，不从URL标题或前端文案重新推断。",
            "课程上下文不一致时显示冲突并停止错误深链，不能静默切换到另一课程。",
            "不建立导图专属课程、知识点或任务表。",
        ],
        [
            "详情投影返回course、knowledge_point、bundle/task及source引用的学习者安全摘要。",
            "页面首屏显示当前课程、知识点、导图目的和下一步动作。",
        ],
        [
            "API测试确认详情上下文与统一资源记录一致。",
            "E2E从资源包进入导图，核对课程和知识点没有漂移。",
        ],
    ),
    "G21-R04": item(
        "学生在导图节点不理解时应能带着当前节点和来源进入智能对话，但完整导图仍留在资源空间。",
        [
            "F5-T04只提供可追踪的提问入口，不提前重构F7智能对话或多模态解析。",
            "传递的是resourceId、nodeId、sourceRef和紧凑问题，不发送完整导图、私有画像或提示词。",
            "对话返回不在导图页内展开成第二套聊天工作台。",
        ],
        [
            "节点详情提供向智能对话提问的次要动作并携带稳定查询参数/上下文。",
            "保留未来F7统一sourceRef审计的接口边界。",
        ],
        [
            "路由测试确认提问入口携带正确资源、节点和来源引用。",
            "E2E确认点击后进入既有智能对话而不是弹出完整聊天窗口。",
        ],
    ),
    "G21-R05": item(
        "测评中心仍只负责新增课程入学诊断和学后智能组卷；导图节点的练习动作属于测验题资源，不得新增第三类测评入口。",
        [
            "F5-T04不修改测评中心路由、导航或题目归属。",
            "导图节点的生成测验动作只进入测验题资源流程，不在导图中伪造正式组卷。",
            "普通导图浏览不能解锁智能组卷。",
        ],
        [
            "节点详情的练习入口使用/workspace/resources/quizzes深链或保留后续F6生成契约。",
            "保持AssessmentWorkspace与FormalExamWorkspace现有职责不变。",
        ],
        [
            "路由和导航回归确认测评中心仍只有两类正式入口。",
            "数据库对比确认导图操作不改变exam gate。",
        ],
    ),
    "G21-R06": item(
        "总路径和科目路径继续决定学生当前知识点及今日任务；导图只是由路径生成并进入的资源，不得重建路径规划界面。",
        [
            "F5-T04不修改路径预算、重建、今日任务或科目路径状态机。",
            "导图页面不能把节点树冒充为总路径或学习计划。",
            "返回路径时只保留原任务状态，浏览导图不自动打勾。",
        ],
        [
            "显示来自资源manifest的今日知识点和任务来源，并提供返回路径的次要导航。",
            "不调用路径更新或完成接口。",
        ],
        [
            "F4-T03路径回归确认预算、任务与重建行为不变。",
            "E2E从今日任务进入导图再返回，任务完成状态保持不变。",
        ],
    ),
    "G21-R07": item(
        "复习中心仍以真实日历和安排为首屏；资源导图不能替换或改变复习入口和复习任务的展示。",
        [
            "F5-T04不修改复习日历、月份切换、任务列表或复习原因。",
            "导图中的masteryBand不是复习任务状态。",
            "从复习进入导图时仍使用同一资源深链和课程上下文。",
        ],
        [
            "保留/workspace/review及其导航合同。",
            "MindmapWorkspace只接受可选的来源入口标记，不复制日历。",
        ],
        [
            "路由回归确认复习中心入口和日历组件未改变。",
            "检查导图DOM不包含伪造复习日期或完成状态。",
        ],
    ),
    "G21-R08": item(
        "复习知识点未来仍可一键生成配套资源或进入智能组卷；F5-T04提供可复用导图深链，但不提前实现或改写复习生成流程。",
        [
            "不得在导图页面自动为复习知识点生成资源包。",
            "不得把查看某节点视为完成复习或满足组卷门禁。",
            "来自复习的导图必须与资源中心中的同一artifact一致。",
        ],
        [
            "保持resourceId深链可由F8复习任务直接使用。",
            "不修改复习生成、组卷或完成事件接口。",
        ],
        [
            "深链测试确认同一resourceId从不同入口得到同一导图。",
            "数据库快照确认访问导图不新增复习或测评事件。",
        ],
    ),
    "G21-R09": item(
        "复习完成必须由真实复习提交事件打勾并反馈画像；导图浏览或节点选择不能制造复习完成记录。",
        [
            "MindmapWorkspace不显示无依据的完成复习按钮。",
            "若导图作为复习材料，完成条件仍由F8任务的可验证动作定义。",
            "布局偏好和选中节点不进入学习聚合。",
        ],
        [
            "导图页面不调用review complete、learning event或profile update端点。",
            "保留节点动作到后续可验证练习的深链边界。",
        ],
        [
            "E2E前后比较复习任务、学习事件和画像快照。",
            "网络日志确认不存在复习完成写请求。",
        ],
    ),
    "G21-R10": item(
        "思维导图需要保留统一资源版本和历史，并为F5-T07的自定义知识点同类生成预留一致入口；本任务不建立导图专属历史或生成机制。",
        [
            "F5-T04读取当前和历史版本，但恢复旧版本、跨资源统一编辑和自定义生成由F5-T07收口。",
            "布局保存不能创建content版本；只有内容修改才可产生新artifact version。",
            "不能在前端本地复制完整导图作为历史。",
        ],
        [
            "投影根据选定DBArtifactVersion解析结构化导图，保留现有versions元数据。",
            "页面显示当前版本与历史入口边界，内容编辑/恢复暂不越权实现。",
        ],
        [
            "测试确认切换版本可读且不改变current_version_id。",
            "检查缩放、折叠和布局偏好不会增加artifact version。",
        ],
    ),
    "G21-R11": item(
        "学习中练习继续归入测验题资源，测评中心只保留入学诊断和智能组卷；导图节点练习不能造成职责回退。",
        [
            "页面文案使用‘生成测验题资源’或‘打开关联测验’，不得称为新增测评中心项目。",
            "F5-T04不在导图中实现即时判分或正式考试。",
            "关联quiz不存在时显示后续生成入口状态，不伪造题目。",
        ],
        [
            "节点详情把quiz视为linked resource类型并使用专用资源深链。",
            "保持AssessmentWorkspace的测验题资源职责和FormalExamWorkspace的智能组卷职责。",
        ],
        [
            "文案和路由测试拒绝‘学习中练习属于测评中心’等旧冲突。",
            "导航回归确认测评中心结构未增加第三项。",
        ],
    ),
    "G21-R12": item(
        "实训任务书、代码沙盒和可交互模型必须继续是三种职责不同的资源；导图只通过关联资源深链连接它们。",
        [
            "导图节点摘要不能伪装成实训步骤、代码运行器或参数实验。",
            "关联资源按钮必须显示真实类型和不同动作名称。",
            "F5-T04不提前实现F5-T05任务书或F6沙盒/模型交互。",
        ],
        [
            "linkedResourceIds投影保留资源类型并映射到各自专用路由。",
            "右侧详情使用‘打开实训任务书’、‘进入代码沙盒’、‘打开交互模型’等明确标签。",
        ],
        [
            "类型映射测试覆盖三类资源的独立深链。",
            "E2E检查导图页面没有内嵌伪运行或伪实验结果。",
        ],
    ),
    "G21-R13": item(
        "九类资源全部生成并归档，但智能组卷只由总路径中的今日必做任务完成情况解锁；导图生成完成、打开或浏览都不等同于必做任务完成。",
        [
            "F5-T04不修改required/optional标记、今日任务完成规则或exam gate。",
            "页面不能因为资源内容可见就显示任务已完成。",
            "未来若导图为必做任务，必须通过明确的解释节点或关联小测完成事件，而不是浏览事件。",
        ],
        [
            "导图页只展示来自任务上下文的完成条件说明，不自行写完成状态。",
            "保留F4路径与组卷门禁作为唯一授权来源。",
        ],
        [
            "E2E在未完成必做任务时打开并操作导图，确认智能组卷仍锁定且缺失项不变。",
            "资源包和exam gate回归确认生成完成与学习完成继续分离。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F5-T04_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F5-T04 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F5-T04")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T04",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError(f"F5-T04 atomic understanding gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F5-T04 atomic understandings: {ledger_path}")


if __name__ == "__main__":
    main()
