#!/usr/bin/env python3
"""Record F8-T05's independent per-atom product understanding."""

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
    "G22-R06": item(
        "测验、代码、可交互模型、费曼、智能组卷和复习产生可信完成证据后，系统必须把同一不可变事件投影到首页、学习画像、学习路径、错题本、复习中心和学习历史，并给出一致版本、下一日安排、逐项进度和失败恢复动作。",
        [
            "跨页反馈只消费当前登录学生的统一学习事件；不能由页面彼此直接改写，也不能让普通浏览、筛选或展开触发画像和计划更新。",
            "部分失败必须保留已完成投影和旧的可读快照，只重放失败步骤；完整同步前不得显示虚假全绿或不同页面各自生成的版本。",
            "保留7.20原版结果页和历史记录；新增反馈是紧凑、可展开的状态与去向，不复制原有长报告。",
        ],
        [
            "扩展app/learning_aggregation.py的统一聚合结果，声明affectedViews、expectedSnapshots、实际快照版本、下一日安排和完成后确定性consistencyToken。",
            "在app/m5_api.py提供所有者隔离的最近反馈查询与既有事件重放；在frontend/src/api/m5.js提供同一协议的读取和恢复调用。",
            "新增AggregationStatus.vue，并接入首页、画像、路径、错题、复习、历史和正式组卷结果页，使这些页面读取同一事件与一致性令牌。",
        ],
        [
            "隔离SQLite覆盖六类事件、六页面快照版本、下一日安排、部分失败、服务恢复、跨日和同幂等键重试。",
            "前端合同、生产构建、Impeccable检测与1440x900/1366x768 E2E验证进度、失败恢复、进入动作和无布局溢出。",
        ],
    ),
    "G22-R01": item(
        "新课程仍须先通过入学诊断建立可用起点；F8-T05的反馈同步不得把尚未诊断的课程伪装成已形成可靠画像或路径。",
        [
            "不修改入学诊断生成、作答、报告或课程初始化门禁；跨页反馈不能代替诊断。",
            "没有可信完成事件时反馈组件保持诚实空态，不创建基线学习成绩或默认完成记录。",
        ],
        [
            "只在F8-T05查询和展示层保护诊断前状态；复用现有诊断与路径前置合同，不增加新初始化流程。",
            "回归入学诊断完成前后首页、画像、路径与最近反馈的状态边界。",
        ],
        [
            "运行诊断与路径门禁回归，断言查询反馈不会新增诊断、画像证据或学习事件。",
            "E2E确认新课程未诊断时原入口和说明仍存在，完成诊断后才出现真实后续状态。",
        ],
    ),
    "G22-R02": item(
        "知识点推荐和学习路径继续由画像、课程结构和正式计划决定；完成反馈只把可信事件结果同步回现有路径，并显示下一步。",
        [
            "不得由反馈组件在前端重新计算或覆盖推荐知识点、路径顺序和前置依赖。",
            "不同课程的事件、画像和路径必须隔离；无匹配路径时仍可完成其他投影并明确路径项未变化。",
        ],
        [
            "复用learning_aggregation的path_task投影和现有LearningPathGraph；只补充统一版本与恢复提示。",
            "最近反馈接口按当前用户和可选课程筛选，路径进入动作指向正式/workspace/path。",
        ],
        [
            "测试有路径、无路径、前置阻塞和跨课程事件，确认推荐及节点顺序不被反馈查询改写。",
            "E2E从反馈状态进入路径，核对同一事件、节点状态与下一步一致。",
        ],
    ),
    "G22-R03": item(
        "资源包继续依据当前画像、知识点、来源和最近学习事件生成；F8-T05只消费完成证据并反馈其跨页影响，不重新生成资源。",
        [
            "不得在反馈查询、展开详情或进入页面时生成讲义、测验、代码、模型或其他资源。",
            "生成失败和聚合失败是两种状态；反馈组件只能恢复事件聚合，不能假装恢复资源生成。",
        ],
        [
            "保持F5资源生成与归档接口不变；聚合元数据只引用来源事件、知识点和已有对象。",
            "通过相关回归保护资源历史、版本和自定义生成入口。",
        ],
        [
            "断言读取/重试反馈不会增加DBArtifact、DBArtifactVersion或DBGenerationTask。",
            "E2E确认已有资源入口可继续使用，反馈区不堆叠完整生成产物。",
        ],
    ),
    "G22-R04": item(
        "资源满足自己的完成规则后仍通过统一事件自动勾选对应路径任务；跨页反馈要显示该投影是否完成并可进入路径核对。",
        [
            "不能把打开资源、运行未通过或手工浏览当成完成；前置任务未满足时必须保留阻塞状态。",
            "重复处理同一完成事件不得重复增加时长、完成次数或再次改变节点。",
        ],
        [
            "保留path_task聚合步骤和taskId/objectId匹配规则，在expectedSnapshots中把路径页面绑定该步骤。",
            "AggregationStatus的路径项显示完成、处理中或失败，并使用同一事件的重放动作。",
        ],
        [
            "测试资源完成、前置阻塞、无匹配节点和重复重放，断言路径节点和actual_minutes幂等。",
            "E2E从完成结果进入路径，确认任务勾选与反馈项状态相同。",
        ],
    ),
    "G22-R05": item(
        "只有今日必做任务全部完成时智能组卷才解锁；反馈同步不得绕过门禁，并应保留缺失项和直达动作。",
        [
            "一致性令牌、画像更新或其他可选资源完成都不能单独解锁智能组卷。",
            "反馈恢复只处理已存在事件的投影，不补写未完成的今日任务。",
        ],
        [
            "保持exam_gate和FormalExamWorkspace的解锁合同；结果页只在合法组卷提交后显示聚合反馈。",
            "将正式组卷事件纳入六类来源，同时保留锁定态未完成项与原有作答/报告流程。",
        ],
        [
            "运行智能组卷门禁回归，断言未完成项、禁用状态和直达链接不受反馈接口影响。",
            "E2E分别验证锁定和解锁后的组卷入口，并在提交后查看同一聚合版本。",
        ],
    ),
    "G22-R07": item(
        "组卷或其他可信学习完成后，错题本、复习中心、笔记与资源空间仍承担深度学习；反馈状态要把学生带到真正发生变化的错题、复习、历史或下一步页面。",
        [
            "不为正确答案伪造错题，不为无掌握证据事件伪造复习计划；笔记和资源内容不由本任务自动新增。",
            "进入错题、复习或历史的读取动作不得产生新掌握证据。",
        ],
        [
            "把wrong_review和activity步骤分别映射到错题/复习和历史视图，并提供正式内部路由。",
            "在WrongQuestionBook、Review和History中读取同一最近反馈，同时保留各页原有详细能力。",
        ],
        [
            "测试错误作答、正确作答、复习完成和无概念事件的错题/复习投影。",
            "E2E从结果反馈进入错题、复习和历史，核对对象存在且浏览零写入。",
        ],
    ),
    "G22-R08": item(
        "动态问题仍在智能对话中先获得回答，再由明确动作生成相关资源；F8-T05不改变对话主流程。",
        [
            "不得把最近反馈组件变成第二个聊天入口，也不得在读取反馈时自动生成对话资源。",
            "对话中的普通提问本身不能无依据提高掌握度；只有后续可信学习行为进入聚合。",
        ],
        [
            "不修改Chat.vue或对话接口；相关回归确认统一聚合只接受声明的可信完成事件。",
            "历史投影可展示真实对话事件，但本任务的六类反馈只聚焦可形成学习闭环的完成事件。",
        ],
        [
            "检查六类事件白名单不包含普通chat浏览/提问，查询反馈前后事件数不变。",
            "导航回归确认智能对话入口、回答和资源生成动作仍由原页面负责。",
        ],
    ),
    "G22-R09": item(
        "完整生成产物继续归档到学习空间的对应资源模块；跨页反馈只显示摘要、同步项和进入动作，不在首页、历史或结果页复制产物正文。",
        [
            "不得在AggregationStatus内渲染讲义、代码、测验、课件或模型的完整内容。",
            "反馈数据只包含受控内部路由和同步摘要，不返回任意外部URL或私有生成内容。",
        ],
        [
            "组件采用紧凑摘要和按需展开的六项列表，完整资源仍由现有资源路由打开。",
            "后端反馈协议只投影事件、步骤状态、版本、下一日安排与固定页面动作。",
        ],
        [
            "前端合同扫描组件无完整资源正文或第二套资源列表。",
            "E2E确认反馈首屏信息克制，进入动作跳到正式页面。",
        ],
    ),
    "G22-R10": item(
        "每种学习资源的历史和自定义知识点生成仍保留；反馈同步不能覆盖、删除或替代这些历史。",
        [
            "事件重放只恢复聚合步骤，不能重新生成资源版本或清空既有历史。",
            "最近反馈是学习闭环状态，不是资源历史的唯一来源。",
        ],
        [
            "不修改各资源模块的历史与自定义生成协议；F8-T05仅引用来源对象和受控入口。",
            "回归资源历史抽屉和版本记录，确认聚合重试没有资源写入副作用。",
        ],
        [
            "隔离数据库比较重试前后资源及版本数量和哈希不变。",
            "E2E确认资源历史和自定义生成入口仍可找到。",
        ],
    ),
    "G22-R11": item(
        "智能对话继续展示可审计的职责、来源、候选、分歧、校验和决策摘要；跨页反馈只展示可核验投影步骤，绝不暴露私有思维链或原始Agent日志。",
        [
            "不能把consistencyToken、处理器内部异常栈、trace、worker或数据库步骤名直接作为用户说明。",
            "技术版本可在按需详情中以短令牌呈现，但主文案必须是学生能理解的业务语言。",
        ],
        [
            "AggregationStatus将内部五步映射为画像、路径、错题、复习、历史和首页六个业务项。",
            "保留现有对话审计边界，不修改其Agent过程展示。",
        ],
        [
            "静态扫描可见文案不含trace、worker、lease、processor或私有思维链。",
            "E2E检查完成与失败状态只说明同步对象、原因和恢复动作。",
        ],
    ),
    "G22-R12": item(
        "旧聊天测验、代码和联网搜索继续分别归入学习空间测验题、代码沙盒和知识库；F8-T05只让其中可信完成事件进入统一反馈。",
        [
            "不得恢复旧聊天内测验、聊天内代码执行或独立联网搜索入口。",
            "联网搜索阅读不属于本任务六类可信完成事件，不能提高掌握度。",
        ],
        [
            "复用测验与代码现有事件类型，组件动作指向正式学习空间、复习和历史路由。",
            "通过导航与事件白名单回归保护迁移后的能力归属。",
        ],
        [
            "路由合同检查旧入口仍重定向到正式归属，六类事件含测验和代码而不含联网浏览。",
            "E2E确认测验与代码完成后可同步，知识库浏览不触发反馈更新。",
        ],
    ),
    "G22-R13": item(
        "完整闭环仍从自然语言多轮画像构建和团队预置课程知识库开始，学生无需先上传课程材料；F8-T05不能改变首次旅程。",
        [
            "不得新增上传课件、教材或大纲作为反馈、画像或路径同步的前置条件。",
            "没有个人上传文件不能被解释为聚合失败或阻止查看已有学习状态。",
        ],
        [
            "不修改Onboarding和知识库初始化；反馈查询只依赖统一事件、用户身份和可选课程。",
            "回归首次画像与课程选择，确认新增组件在无事件时安静退场。",
        ],
        [
            "首次旅程合同检查无强制课程材料上传；新账号读取反馈返回诚实空结果。",
            "E2E确认完成自然语言画像和入学诊断后才进入学习闭环。",
        ],
    ),
    "G22-R14": item(
        "学生仍在总路径点击今日知识点一次生成并分发完整资源包；跨页反馈只显示资源学习完成后的统一影响，不把资源逐个塞进聊天或反馈区。",
        [
            "不得由F8-T05增加第二套一键生成入口、重复资源分发或前端临时资源包。",
            "反馈完成不等于资源包中所有可选资源都必须完成，组卷门禁仍只看今日必做任务。",
        ],
        [
            "保护LearningPathGraph和ResourceBundleWorkspace的生成/归档合同；反馈路径项只读取完成事件。",
            "在回归中区分资源包生成状态与事件聚合状态。",
        ],
        [
            "测试反馈重试不新增资源包或资源版本，且不改变必做/可选标记。",
            "E2E确认路径的一键生成入口仍唯一，反馈区仅给同步状态与去向。",
        ],
    ),
    "G22-R15": item(
        "智能组卷未解锁时必须明确列出未完成的今日必做任务并提供直达入口；跨页反馈不能遮蔽、替代或错误解除这一提示。",
        [
            "反馈同步成功不代表组卷门禁成功；不能用六项全同步状态替代今日必做任务核验。",
            "直达链接必须是受控内部路由并保留课程与任务上下文。",
        ],
        [
            "保留FormalExamWorkspace现有锁定视图；AggregationStatus在结果存在时显示，不覆盖组卷前门禁。",
            "回归exam_gate的missingRequiredTasks和targetRoute字段。",
        ],
        [
            "自动测试在不同聚合状态下断言锁定缺失项不变，并验证受控内部链接。",
            "E2E逐个点击未完成项直达任务，全部完成后再进入组卷。",
        ],
    ),
    "G22-R16": item(
        "生成、保存、判分或事件聚合任一步失败时必须保留已经完成的业务对象和聚合步骤，并允许使用同一事件从最近检查点继续。",
        [
            "不得整批回滚已经提交的测验、代码、模型、费曼、组卷或复习结果，也不得重复执行成功步骤。",
            "失败状态不得伪装成0变化或全同步；错误消息必须转成业务说明并保留可继续使用的旧页面数据。",
        ],
        [
            "延续DBLearningEventConsumption逐步checkpoint，补充expected/actual快照状态；恢复接口重用同一event_id。",
            "AggregationStatus在partial/failed时显示已完成数量、失败业务项和重试按钮，重试后刷新同一consistencyToken。",
        ],
        [
            "故障注入使中间步骤失败，验证已完成步骤持久化、attempt递增、成功步骤不重跑且最终完成。",
            "E2E模拟失败和服务重启，确认旧内容可读、恢复动作明确、完成后六页版本一致。",
        ],
    ),
    "G24-R01": item(
        "测验、代码、可交互模型、费曼、智能组卷和复习的有意义完成行为都必须形成统一不可变学习事件，成为跨页反馈的唯一输入。",
        [
            "事件必须归属于当前用户、课程和真实学习对象；页面读取、筛选、展开和反馈重试本身不新建学习事件。",
            "六类事件之外的行为不能被F8-T05临时包装成强证据。",
        ],
        [
            "确认五类现有来源已经调用统一聚合器，并在interactive_lab.py补齐可交互模型提交后的聚合调用。",
            "最近反馈查询只读取DBLearningEvent与DBLearningEventConsumption，不建立第二套活动表。",
        ],
        [
            "六类来源各创建一个事件，断言事件身份、课程、对象、来源和消费记录完整。",
            "读取六个页面和点击展开前后DBLearningEvent数量完全不变。",
        ],
    ),
    "G24-R02": item(
        "同一学习事件可按规则影响画像、知识掌握、路径、错题/复习、历史和首页摘要；反馈协议必须把这些实际影响作为同一版本公开。",
        [
            "不要求每个事件都改变每个业务值；无匹配概念、路径或错题时应显示已检查但无变化，而非伪造更新。",
            "所有投影必须使用同一事件所有者和课程范围，不能混入其他学生或其他课程。",
        ],
        [
            "为五个聚合步骤定义六个受影响页面与实际快照版本，画像/路径/错题复习/历史/首页都由同一消费结果派生。",
            "最近反馈接口返回统一事件摘要、同步项、下一日安排和一致性令牌。",
        ],
        [
            "断言六页面项的sourceEventId和consistencyToken相同，实际业务值与各投影步骤一致。",
            "跨用户、跨课程测试确认最近反馈和投影严格隔离。",
        ],
    ),
    "G24-R03": item(
        "不同学习事件继续按事件类型、证据状态和evidence_strength加权更新掌握度；跨页一致性不能把所有完成行为等价计分。",
        [
            "普通完成勾选和无结果浏览只影响完成状态或历史，不能产生掌握观察值。",
            "可交互模型提交可形成确定性观察，但使用提示时保留较低证据强度，不能前端硬编码掌握增量。",
        ],
        [
            "复用_project_profile按evidence_strength计算的现有规则，只补充interactive_model_observation_submitted的可识别观察。",
            "反馈组件展示是否同步，不展示伪精确的算法增分承诺。",
        ],
        [
            "对六类事件使用不同强度和分数，手工重算并断言画像结果；提示前后模型证据影响不同。",
            "回归普通user_marked_complete只完成路径而不提高掌握度。",
        ],
    ),
    "G24-R04": item(
        "首页、画像、路径、错题、复习和历史的浏览、展开、筛选以及查看同步详情必须完全只读，不能无依据提高掌握度。",
        [
            "组件挂载、轮询、查看版本、页面跳转和点击展开不能记录mastery_eligible事件。",
            "重试按钮只能重新消费已经存在的不可变事件，不能创建新的评分或完成证据。",
        ],
        [
            "前端组件只调用GET最近反馈/事件聚合和POST既有事件process；后端process按event_id重用原消费。",
            "六个消费页面不增加任何完成或掌握写入监听器。",
        ],
        [
            "在浏览、展开、切页和重试前后比较学习事件数、画像掌握、路径节点和证据表。",
            "E2E键盘与鼠标操作均验证零业务写入。",
        ],
    ),
    "G24-R05": item(
        "画像、路径、错题/复习、历史和首页结论必须能够由不可变学习事件确定性重放；服务重启后从持久化步骤继续并得到同一一致性版本。",
        [
            "不能依赖页面内存、本地缓存或随机时间生成业务结果；重放不重新选择不同知识点或改写原事件。",
            "只有全部预期快照完成时生成consistencyToken，部分状态不能沿用旧完成令牌冒充一致。",
        ],
        [
            "consistencyToken由事件ID、处理器版本和六页实际快照版本确定性哈希；逐步结果继续保存在DBLearningEventConsumption.result。",
            "恢复接口根据completed_steps跳过成功步骤，并在服务重启后读取同一消费记录。",
        ],
        [
            "同一数据库重启会话后重放六类事件，断言快照版本、业务结果和consistencyToken保持一致。",
            "故障恢复测试确认partial状态无完成令牌，恢复完成后令牌稳定。",
        ],
    ),
    "G24-R06": item(
        "资源或任务完成状态与知识掌握证据必须分离：完成可勾选路径，只有accepted且mastery_eligible并可解释评分的事件才改变掌握度。",
        [
            "AggregationStatus不能把‘已同步’表述成‘已掌握’，也不能把路径完成数量等同于掌握率。",
            "无观察值的完成事件仍可更新路径和历史，但画像、错题和复习应诚实显示无证据变化。",
        ],
        [
            "保留completion_effect与_observation/_mastery_events两条独立路径；同步项按实际步骤结果说明是否有变化。",
            "用户文案使用‘反馈已同步/未产生新的掌握判断’，避免混淆完成与掌握。",
        ],
        [
            "成对测试user_marked_complete和有评分的quiz/code/model事件，断言路径完成相同而掌握变化不同。",
            "E2E检查组件与结果页不使用‘完成即掌握’文案。",
        ],
    ),
    "G24-R07": item(
        "学习事件写入和五步聚合继续使用稳定幂等身份；同一事件失败重放不得重复计分、重复错题、重复复习计划或重复路径完成。",
        [
            "相同幂等键绑定不同请求必须继续报冲突；恢复不能复制事件或创建第二条消费记录。",
            "并发或快速重复点击恢复时只能得到同一事件、同一聚合消费和确定性结果。",
        ],
        [
            "沿用DBLearningEvent.idempotency_key与DBLearningEventConsumption唯一消费身份；模型提交的existing_event路径也检查并恢复同一聚合。",
            "前端重试期间禁用按钮，完成后重新读取同一event_id而非提交新学习行为。",
        ],
        [
            "重复和并发重放断言事件数、消费数、画像增量、错题数、复习计划数和路径状态不重复。",
            "E2E快速双击恢复仅发出一个进行中动作，最终令牌与单次恢复一致。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F8-T05_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F8-T05 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    if len(actual_ids) != len(set(actual_ids)):
        raise RuntimeError("F8-T05 ledger contains duplicate atomic requirement IDs")

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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F8-T05")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F8-T05",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F8-T05 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
