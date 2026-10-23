#!/usr/bin/env python3
"""Generate synchronized status, constitution, route matrix, and recovery index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_status(
    product: dict[str, Any],
    implementation: dict[str, Any],
    audit: dict[str, Any],
    crosscheck: dict[str, Any],
    current_routes: list[dict[str, Any]],
    scope: dict[str, Any],
) -> str:
    counts = crosscheck["counts"]
    return f"""# EduMatrix 原系统融合重构唯一执行状态

> 当前目标：`FUSION-REBUILD-F0-F10`  
> 当前状态：`F0-PASS / F1-AUTOMATED-PASS / F1-VISUAL-CONFIRMATION-PENDING / F2-BLOCKED-BY-GATE`  
> 唯一原则：7.20 原版是产品主体；当前复杂版只是候选能力池。  
> 最近更新：2026-08-11

## 1. 每次恢复的强制读取顺序

上下文压缩、重启、交接或记忆丢失后，必须依次完整读取：

1. 本文件；
2. `06_用户意图与产品宪法.md`；
3. `outputs/改进想法.docx` 原文；
4. `13_改进想法逐句逐图实质落实审计.md`；
5. `09_EduMatrix最终产品方案.md`；
6. `10_原版融合重构详细实施方案.md`；
7. `07_双版本代码地图与功能清单.md`；
8. `08_用户需求追踪与路由迁移矩阵.md`；
9. `evidence/` 下的目标路由、当前路由、保护页、后端端点和数据模型归宿证据；
10. 唯一赛题 PDF；
11. `11_上下文恢复与实施索引.md` 和 `02_融合重构_WORKLOG.md` 最后一条。

必须逐张查看 29 张原图。图片必须与对应文字一起理解：前一非空段、图片承载段、后一非空段、人工语义锚点、跨主题边界和图文综合解释缺一不可。不得只看 contact sheet 或机械拼接相邻段落。

## 2. 当前精确断点

- Word 原文：{audit['paragraph_count']} 个段位，其中 {audit['nonempty_paragraph_count']} 个非空文字段。
- 原始图片：{audit['image_count']} 张，已形成同数目的图文语义单元。
- 需求拆解：{audit['group_count']} 个需求组、{audit['atomic_requirement_count']} 条原子要求；每条均有完整语义、页面合同、唯一主责产品章节、唯一主责任务和影响数组。
- 产品规格：{product['product_section_count']} 个主章节、{product['target_route_count']} 条目标路由；路由数由正确产品结构生成，不使用固定数字门禁。
- 实施规格：F0-F10 共 {implementation['phase_count']} 个阶段、{implementation['task_count']} 个任务；每项包含完整实施字段，并在任务自身携带 {len(implementation['f1_design_contract']['rules'])} 条 F1 设计继承规则。
- 当前代码事实：{len(current_routes)} 条前端路由、{len(scope['routes'])} 个已分类注册端点、{len(scope['models'])} 个已分类 ORM 模型；数量不等于产品页面数量。
- 原版保护：{counts['protected_pages']} 页，分别是学习画像、学习路径、笔记本和错题本。
- 机器交叉校验：`{crosscheck['status']}`；共 {len(crosscheck['checks'])} 项，除 Word 图文、路由和旅程外，还逐条校验 {audit['atomic_requirement_count']} 条完整语义进入 09/10、29 张图三类视觉合同、28 组布局合同，以及全部 {implementation['task_count']} 个任务逐项继承 F1 设计规则。
- F0：`PASS`。唯一赛题边界、29 张图文语义、50 条目标路由、四页保护基线和回滚证据均已冻结。
- F1：运行代码已实施；当前有效视觉合同为雾白页面、白色内容面与墨蓝灰浅色极简主题，正文使用思源黑体，少量大型焦点标题使用思源宋体。
- F1 浏览器证据：2 种桌面尺寸、26 张截图、学生/教师/管理员三角色、4 个保护页；0 横向溢出、0 控件碰撞、0 内容裁切、0 小于 14px 的可见文字、0 控制台错误、0 页面异常、0 失败请求。
- 当前有效视觉基线：应用壳、字体、字号、雾白/白色内容面/墨蓝灰色彩、导航、展示页、登录页、设置页、Dashboard 渐进展开和角色入口；保护页内部信息架构按责任阶段渐进减负。
- F2：尚未授权进入。用户确认 F1 前，禁止开始 `F2-T01` 或任何后续页面开发。

关键图文边界：

- 图 13：图片段第 30 段，人工语义锚点第 31 段，跨主题边界第 29 段，产品含义是知识库书架。
- 图 25：图片段第 47 段，人工语义锚点第 49 段，跨主题边界第 46 段，产品含义是费曼第一轮，不是智能组卷。

## 3. 当前已经完成

- 已重写 `09_EduMatrix最终产品方案.md`：逐路由写明职责、桌面布局、输入、输出、动作、状态、联动、保留、候选、隐藏和验收；245 条原子要求各自只在唯一主责章节出现一次；29 张图在对应章节中与文字联合展示。
- 已重写 `10_原版融合重构详细实施方案.md`：F0-F10、{implementation['task_count']} 个任务，每项包含来源、路由、原版保护、候选取舍、模块、协议、UI、全状态、测试、验收、回滚和用户可见结果；{audit['atomic_requirement_count']} 条原子要求各自只在唯一主责任务中作为必做合同出现一次；每个任务还独立携带 {len(implementation['f1_design_contract']['rules'])} 条 F1 设计继承门禁。
- 已重建 `13`：{audit['atomic_requirement_count']} 条原子要求逐条记录完整语义、页面合同、唯一主责和影响范围，不再使用固定 175 条或 G01-G28 关键词门禁。
- 已重写 `12` 及生成器：按实际结构进行 {len(crosscheck['checks'])} 项严格检查，不再把 ID、章节、任务存在或顶部视觉总则当作实质覆盖。
- 已同步本状态、产品宪法、路由迁移矩阵、恢复索引和工作日志。
- 已完成 F0 三项任务：需求/图文/路由追踪冻结、唯一赛题闭环边界冻结、四个原版核心页面保护基线与回滚证据冻结。
- 已完成 F1 四项任务的代码实施，并在 F4 用户反馈修复中将有效视觉令牌更新为雾白页面、白色内容面与墨蓝灰浅色极简系统。
- 已把 F1 设计系统下沉为逐任务合同：后续每个 F0-F10 小任务都必须在自身正文和 JSON 中携带完整规则，纯非 UI 任务只能逐条说明 N/A，触及界面即必须执行双尺寸视觉门禁。
- 已将 Dashboard 首屏精简为课程上下文、今日任务、学习焦点、趋势和四项指标；原有详细能力保留在按需展开区，不在 F1 删除业务功能。
- 已完成生产构建、11 项契约测试、双尺寸浏览器 E2E 和 Codex 逐图复核；最终报告为 `passed`，证据位于 `evidence/f0_f1_browser_e2e/`。
- 已复核四个保护页当前源码 SHA-256 与 F0 快照一致；F1 未改写这些页面源码。
- 已清理本轮 E2E 服务；端口 8891 当前未监听，没有遗留的 F0/F1 Playwright、Python 或 Node 测试进程。

## 4. 尚未完成

- F1 用户视觉确认；自动测试和 Codex 人工看图不能替代该确认。
- F2-F10 的运行代码实施。
- 数据库 schema 和部署包的目标产品改造。
- Git 提交、推送、远程仓库和比赛交付包更新。
- 移动端、企业治理、专家认证、组织集成和视频生成。

## 5. 不可违背约束

- 学生一级入口固定为：首页、个人中心、学习画像、学习空间、智能对话、知识库、学习市场、设置。
- 测评中心只包含入学诊断和智能组卷；学习中练习归入 `/workspace/resources/quizzes/:resourceId` 测验题资源。
- 首次画像以自然语言多轮交流为主；团队预置知识库直接提供课程输入，不要求学生上传课程材料。
- 实训任务书、代码沙盒、可交互模型三者职责分开。
- 总路径由学生点击今日知识点生成九类完整资源包；今日必做任务全部有证据完成后才解锁智能组卷。
- 普通浏览、点击、搜索、展开、下载和查看来源不改变掌握度。
- 私有思维链、系统提示词、API Key 和原始 Agent 日志不得展示。
- 当前周期只做桌面端；移动端是明确延期项。
- F1 设计规则是每个后续小任务自身的完成门禁；不能只引用全局总则，也不能在任务中省略配色、字体、字号、布局、渐进展开、状态和双尺寸验收。

## 6. 下一步

当前有效视觉合同为雾白页面、白色内容面与墨蓝灰浅色极简系统；后续任务必须继承该合同并在自身阶段验收中验证。

若用户明确回复“确认 F1 视觉方向”，则先把 F1 状态记为 `PASS`，再按 `10` 中的 `F2-T01` 进入统一课程上下文与闭环对象底座；若用户指出不满意页面，则保持在 F1，只修正被指出的视觉问题并重跑同一组门禁。不得跳回旧 M/W/FC/Next 任务，也不得越过 F2 直接开发后续页面。
"""


def render_constitution() -> str:
    return """# EduMatrix 用户意图与产品宪法

> 状态：`APPROVED / AUTHORITATIVE`  
> 生效日期：2026-08-11  
> 作用：约束所有后续产品设计、代码实施、测试和验收。代码现状、旧阶段任务和实现便利性不得推翻本文件。

## 1. 唯一产品目标

EduMatrix 是面向人工智能与机器学习工程技能学习的“领域知识个性化生成与多智能体协同决策系统”。系统先基于团队预置课程知识库，通过自然语言交流和入学诊断理解学习者；再由职责明确的 Agent 完成分析、生成、校验和决策；随后提供可真正阅读、练习、运行、实验和复述的个性化资源；最后依据真实学习证据更新画像、路径、错题、复习和下一日安排。

产品成功的优先级固定为：完整学习闭环 > 用户知道下一步且操作轻松 > 7.20 原版连续性和实质能力 > 比赛技术呈现 > 已有代码数量。

## 2. 权威输入与冲突裁决

冲突时按以下顺序裁决：

1. 用户已经批准的产品决策；
2. `改进想法.docx` 的图文语义单元；
3. 唯一赛题 PDF；
4. 本宪法与 `09` 最终产品方案；
5. `10` 详细实施方案；
6. 7.20 原版事实与保护证据；
7. 当前复杂版候选能力；
8. 旧 M/W/FC/Next 任务只能作为历史证据。

任何图片都必须与对应文字联合理解。必须保存并使用前一非空段、图片承载段、后一非空段、人工语义锚点、跨主题边界和综合产品解释；不能只看图、只看 contact sheet 或机械采用最近段落。

## 3. 产品主体与候选能力

- 7.20 原版是产品、导航、体验和丰富功能的主体。
- 当前复杂版是候选能力池，不是第二套产品。
- 候选能力只有在有明确用户任务、自然入口、统一数据对象、可恢复状态和闭环价值时才可进入正式产品。
- 已经存在的企业、认证、集成、评委旅程和内部工作台代码可以保留，但不进入普通导航，不得因为代码多而扩张产品。

## 4. 用户与信息架构

学生是核心用户。学生一级入口固定为：

1. 首页；
2. 个人中心；
3. 学习画像；
4. 学习空间；
5. 智能对话；
6. 知识库；
7. 学习市场；
8. 设置。

学习空间承载测评中心、总/科目路径、资源中心、讲义、思维导图、测验题、实训任务书、代码沙盒、视频推荐、PPT/网页课件、可交互模型、费曼复述、复习、笔记和错题。它们可以有独立深链，但不能成为全局并列工作台。

教师只承担教学总览、课程与资源、学生学情、测评与干预。管理员只承担账号权限、模型配置、内容审核、系统状态。教师和管理员不扩展企业 HR、专家认证、组织市场或集成治理。

## 5. 当前周期视觉与桌面范围

- 当前周期只设计、实施和验收桌面端。1440x900 为主基准，1366x768 为最低桌面基准。
- 移动端、390x844、移动抽屉和平板专项统一延期，不得写入当前完成门禁。
- 页面背景为雾白 #F5F7F7，内容面为白色，主文字 #06141B，主动作 #11212D，次级层级使用 #4A5C6A、#60727C 与 #CCD0CF；#9BA8AB 不用于白底正文。禁止绿色、棕色或蓝紫成为主题色，当前不设计深色模式。
- 禁止蓝紫渐变、发光背景、装饰光球、过量毛玻璃、卡片嵌套、卡片墙、负字距和炫技式 AI 视觉。
- 正文、导航、表单、普通页标题和数据说明统一使用思源黑体/Noto Sans CJK SC、Source Han Sans SC，Windows 回退微软雅黑；只有 Landing 产品名和大型学习焦点标题少量使用思源宋体/Noto Serif CJK SC、Source Han Serif SC。正文 15-16px 为主，辅助文字不低于 14px。
- 页面第一屏必须回答“我在哪里、现在做什么、完成条件是什么、下一步点哪里”。同一状态最多一个视觉主按钮。
- 详情、技术依据和低频动作按需展开；不删除必要学习信息，只删除重复说明、内部术语和首屏噪音。
- 以上视觉规则必须由 `10` 中每个小任务独立继承。纯协议、数据或文档任务可以在验收证据中逐条标记 N/A 并说明原因；一旦修改页面、组件、样式、图表、弹窗或截图，全部规则和 1440x900、1366x768 双尺寸验收立即生效。

## 6. 首次画像与课程输入

- 初始课程知识库由团队提前构建、解析和索引。学生开始使用时不需要上传课程课件、教材或大纲。
- 首次画像由系统主动进行自然语言多轮交流，依次询问背景、目标、基础、困难和偏好；右侧画像随确认结果逐轮更新。
- 成绩单、课表或个人经历文件只能作为可选个人资料，附件失败不能阻塞流程。
- 学生确认画像后进入入学诊断；诊断根据预置课程、知识点、画像和来源动态生成。

## 7. 测评与练习归属

- 测评中心只包含“入学诊断”和“智能组卷”。
- 学习中练习、生成测试题和即时判分统一属于“测验题资源”，正式路由为 `/workspace/resources/quizzes/:resourceId`。
- 入学诊断建立初始掌握证据和路径草稿；智能组卷验证今日学习结果并更新后续决策。
- 所有题目必须根据当前课程、知识点、画像、掌握证据和最近学习事件动态生成；示例问题不能写成固定产品行为。

## 8. 总路径、九类资源包与组卷门禁

- 总路径统筹多科目，科目路径展示单课顺序。学生在总路径查看今日/未来知识点、必做/可选任务、预计时长、完成条件和状态。
- 学生主动点击今日知识点生成完整资源包。资源包固定包含：个性化讲义、思维导图、测验题资源、实训任务书、代码沙盒任务、视频推荐、PPT/网页课件、可交互模型、费曼复述任务。
- 九类产物分别归档到对应资源空间，保存来源、版本、历史和生成状态；完整产物不得堆在智能对话中。
- 今日必做任务必须显示知识点、资源类型、预计时长、完成条件、状态和进入动作。
- 智能组卷只由“今日必做任务全部形成有效完成证据”解锁。可选资源不阻塞；未解锁时必须列出缺失任务。

## 9. 三类技能资源的职责边界

- **实训任务书**：说明工程任务目标、前置条件、环境、数据、步骤、检查点、提交物和评分标准。
- **代码沙盒**：实际编辑、运行、停止、调试代码，查看真实输出、错误和图表，并接受基于运行证据的 AI 点评。
- **可交互模型**：通过参数、滑块、图表、实验步骤和观察记录理解模型规律。

三者可以互相深链，但不能合并成含糊的“实操指南”页面。

## 10. 高质量资源硬约束

- 个性化讲义必须包含标题、摘要、目录、关键概念、图表/公式、例子、反例、代码、小测、来源脚注、AI 伙伴、进度、编辑版本和导出。
- 代码沙盒采用任务/历史、编辑器/标准输入、输出/错误/图表/点评三栏布局；点评必须引用真实运行证据，建议应用后可重跑。
- 费曼复述依次为第一轮、第一轮评价、真实追问与回答、第二轮、证据化对比和应用；不得跳过追问或伪造提升。
- 视频当前只做有来源的推荐与播放，视频生成延期。

## 11. 知识库与智能对话

- 知识库首页按我的书架、智能推荐、联网发现组织；联网候选未经许可/审核不得直接进入权威课程库。
- 文档阅读器必须以原文为主体，支持页码/章节定位、文本划选提问、图片区域框选提问、来源、导出、笔记和当前文件生成资源。
- 智能对话支持附件解析、流式回答、停止/继续、来源和资源深链；完整产物仍归档到学习空间。
- 只展示 Agent 职责、输入来源、候选、分歧、校验、修订和最终决策摘要；私有思维链、提示词和原始日志永不展示。

## 12. 证据、事件与动态更新

- 普通点击、浏览、搜索、展开、下载、查看来源和调整视图不能改变掌握度。
- 只有提交答案、成功代码运行、提交交互观察、提交费曼轮次、交卷、完成复习等有证据行为才可进入掌握聚合。
- 完成状态与掌握证据分开；同一事件必须幂等，重复请求不能重复计分。
- 智能组卷完成后，同一事件链更新画像、路径、下一日安排、错题本和复习计划；部分失败必须可恢复。

## 13. 原版四页保护

学习画像、学习路径、笔记本和错题本必须保留 7.20 的丰富能力，只允许：

- 调整排版与信息顺序；
- 删除重复说明、内部字段和首屏低频动作；
- 增加来源、证据、深链和闭环联动；
- 使用折叠、抽屉和详情降低视觉负担。

禁止把四页改成空洞摘要，禁止删除编辑、筛选、历史、来源、复习或核心交互，禁止用新技术工作台替代。

## 14. 状态与恢复

每个重要页面必须定义加载、空、处理中/生成中、部分成功、失败、重试、恢复和完成。失败必须保留输入与已成功结果；重试只重放失败步骤；恢复显示最近检查点；完成显示证据、归档位置和下一步。内部状态码只能进入授权诊断详情。

## 15. 禁止事项

- 禁止恢复旧 M/W/FC/Next 阶段作为当前主线。
- 禁止新增普通用户一级入口和并列工作台。
- 禁止把代码存在或测试通过写成用户闭环完成。
- 禁止用虚假统计、固定示例或冻结演示结果冒充真实成绩。
- 禁止未经授权修改运行代码、数据库、Git、远程仓库和交付包。
- 禁止在当前周期加入移动端、企业治理、专家认证、组织集成和视频生成门禁。
"""


def render_route_matrix(
    product: dict[str, Any],
    implementation: dict[str, Any],
    current_routes: list[dict[str, Any]],
    scope: dict[str, Any],
) -> str:
    lines = [
        "# EduMatrix 用户需求追踪与路由迁移矩阵",
        "",
        "> 状态：`AUTHORITATIVE / SYNCHRONIZED`  ",
        "> 说明：需求、目标路由和实施任务均从 09/10/13 JSON 导出；路由数量由产品结构决定。",
        "",
        "## 1. 固定产品归属",
        "",
        "- 测评中心只包含入学诊断和智能组卷。",
        "- 测验题资源正式路由：`/workspace/resources/quizzes/:resourceId`；不存在目标路由 `/workspace/practice/:resourceId`。",
        "- 首次画像：`/onboarding` 自然语言多轮交流；预置课程直接提供知识库输入。",
        "- 实训任务书：`/workspace/resources/training-tasks/:resourceId`；代码沙盒：`/workspace/code/:resourceId`；交互模型：`/workspace/resources/models/:resourceId`。",
        "- 当前周期只做桌面端；移动端延期。",
        "",
        "## 2. 需求组到产品与任务",
        "",
        "| 需求组 | 产品章节/子章节 | 实施任务 |",
        "|---|---|---|",
    ]
    group_products = product["group_product_section_map"]
    group_tasks = implementation["group_implementation_task_map"]
    for group_id in sorted(set(group_products) | set(group_tasks)):
        lines.append(
            f"| `{group_id}` | {', '.join(f'`{value}`' for value in group_products.get(group_id, []))} | "
            f"{', '.join(f'`{value}`' for value in group_tasks.get(group_id, []))} |"
        )

    lines.extend(
        [
            "",
            f"## 3. {len(product['routes'])} 条目标产品路由",
            "",
            "| 路由 | 页面 | 角色 | 产品规格 | 阶段 | 主动作 | 7.20保留 | 当前候选取舍 | 验收 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for route in product["routes"]:
        lines.append(
            f"| `{clean(route['path'])}` | {clean(route['label'])} | {clean(route['role'])} | `{route['subsection_id']}` | "
            f"{clean(route['phase'])} | {clean(route['primary_action'])} | {clean(route['baseline_code'])} | "
            f"复用：{clean(route['candidate_code'])}；改造：{clean(route['refactor_code'])}；隐藏：{clean(route['hidden_or_removed'])} | {clean(route['acceptance'])} |"
        )

    lines.extend(
        [
            "",
            f"## 4. {len(current_routes)} 条当前前端路由的唯一归宿",
            "",
            "| 当前路由 | 视图 | 角色 | 用户价值 | 决定 | 目标归宿 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for route in current_routes:
        lines.append(
            f"| `{clean(route.get('path'))}` | `{clean(route.get('view'))}` | {clean(route.get('role'))} | "
            f"{clean(route.get('value'))} | {clean(route.get('disposition'))} | `{clean(route.get('target_destination'))}` |"
        )

    route_dispositions: dict[str, int] = {}
    for item in scope["routes"]:
        key = str(item.get("disposition"))
        route_dispositions[key] = route_dispositions.get(key, 0) + 1
    model_dispositions: dict[str, int] = {}
    for item in scope["models"]:
        key = str(item.get("disposition"))
        model_dispositions[key] = model_dispositions.get(key, 0) + 1
    lines.extend(
        [
            "",
            "## 5. 后端端点与数据模型归宿摘要",
            "",
            f"- 已分类注册端点：{len(scope['routes'])} 个；分布：{route_dispositions}。",
            f"- 已分类 ORM 模型：{len(scope['models'])} 个；分布：{model_dispositions}。",
            "- 全量逐项证据：`evidence/fusion_scope_matrix/current_backend_scope.csv`、`current_data_model_scope.csv`、`backend_model_destination_map.md`。",
            "- 端点/模型数量只用于证明能力事实和迁移边界，不作为新增页面、工作台或数据表的理由。",
            "",
            "## 6. 迁移门禁",
            "",
            "1. 旧深链必须重定向到明确目标页或显示可理解失效页，不能静默 404。",
            "2. 画像、路径、笔记、错题四个保护页发现能力减少时立即回滚。",
            "3. 兼容迁移只新增字段/映射，不删除旧对象；恢复失败保留旧只读入口。",
            "4. 企业、认证、集成、评委和内部工作台保持隐藏/延期，不进入学生或教师普通导航。",
            "5. 任何路由迁移都必须有加载、空、失败、恢复、完成和回滚证据。",
            "6. 每个迁移任务必须执行自身携带的F1设计继承门禁；不得以本文件或10号顶部已写全局规则为由省略逐任务视觉验收。",
            "",
        ]
    )
    return "\n".join(lines)


def render_recovery_index(
    product: dict[str, Any],
    implementation: dict[str, Any],
    audit: dict[str, Any],
    crosscheck: dict[str, Any],
) -> str:
    lines = [
        "# EduMatrix 上下文恢复与实施索引",
        "",
        "> 状态：`AUTHORITATIVE / F0-PASS / F1-AUTOMATED-PASS / F1-VISUAL-CONFIRMATION-PENDING`  ",
        "> 更新：2026-08-11  ",
        "> 用途：任何模型、队友或新任务在记忆不完整时，依本文件恢复唯一主线。",
        "",
        "## 1. 一句话主线",
        "",
        "以 7.20 原系统为主体，把竞品中真正有价值的自然语言画像、九类高质量资源、代码/实验/费曼、知识库选区、多 Agent 校验和动态反馈自然融入原闭环；最终做成简洁、可操作、可追溯的 AI/ML 技能学习系统，而不是继续堆工作台。",
        "",
        "## 2. 强制读取顺序",
        "",
        "1. `00_唯一执行状态.md`；",
        "2. `06_用户意图与产品宪法.md`；",
        "3. `outputs/改进想法.docx` 原文；",
        "4. `13_改进想法逐句逐图实质落实审计.md`；",
        "5. `09_EduMatrix最终产品方案.md`；",
        "6. `10_原版融合重构详细实施方案.md`；",
        "7. `07_双版本代码地图与功能清单.md`；",
        "8. `08_用户需求追踪与路由迁移矩阵.md`；",
        "9. `evidence/target_product_spec/`、`route_product_spec/`、`protection_baseline/`、`fusion_scope_matrix/`；",
        "10. 唯一赛题 PDF；",
        "11. 本文件和 `02_融合重构_WORKLOG.md` 最后一条。",
        "",
        "29 张原图必须逐张打开，并和对应 Word 文字一起看。图 13 和图 25 是禁止机械相邻归类的强制回归样例。",
        "",
        "## 3. 当前机器事实",
        "",
        f"- Word：{audit['paragraph_count']} 个段位；图片：{audit['image_count']} 张；需求组：{audit['group_count']}；原子要求：{audit['atomic_requirement_count']}。",
        f"- 产品：{product['product_section_count']} 个主章节、{product['target_route_count']} 条目标路由。",
        f"- 实施：{implementation['phase_count']} 个阶段、{implementation['task_count']} 个任务；每个任务独立携带{len(implementation['f1_design_contract']['rules'])}条F1设计规则。",
        f"- 交叉校验：`{crosscheck['status']}`；不能把规格 PASS 写成运行代码已完成。",
        "- 当前实现：F0 已通过；F1 运行代码、生产构建、11 项契约测试和 26 张截图浏览器 E2E 已通过。",
        "- 当前断点：F1 只等待用户视觉确认；确认前 F2 禁止开始。",
        "",
        "## 4. 已批准且无需再问的决定",
        "",
        "- 桌面端优先，移动端延期；雾白页面、白色内容面与墨蓝灰浅色极简系统，安静、清晰、克制、专业。正文使用思源黑体，只有 Landing 和大型学习焦点标题少量使用思源宋体。",
        "- 学生八个一级入口固定；教师和管理员只保留最小任务闭环。",
        "- 测评中心只有入学诊断和智能组卷；练习归入测验题资源。",
        "- 预置知识库先行；自然语言多轮画像；个人资料附件可选。",
        "- 总路径点击今日知识点生成九类资源包；今日必做完成后解锁智能组卷。",
        "- 讲义必须是高质量产物；实训任务书、代码沙盒、交互模型三者分开。",
        "- 知识库支持大窗口、划选、图片框选、来源、笔记和文件级生成。",
        "- 普通浏览不改变掌握度；私有思维链与原始日志不展示。",
        "- 画像、路径、笔记、错题保留 7.20 丰富功能，只做减负和联动。",
        "",
        "## 5. 唯一实施顺序",
        "",
        "| 阶段 | 名称 | 任务数 | 进入条件 |",
        "|---|---|---:|---|",
    ]
    for phase in implementation["phases"]:
        lines.append(
            f"| `{phase['id']}` | {clean(phase['title'])} | {len(phase['tasks'])} | {clean('；'.join(phase['dependencies']))} |"
        )
    lines.extend(
        [
            "",
            "F0 已通过，F1 已实施并通过自动验收。只有用户明确确认 F1 视觉方向后，才从 `F2-T01` 继续。不得重新执行 F0、不得越过 F2 直接改后续核心页面，也不得恢复旧 M/W/FC/Next 主线。",
            "",
            "## 6. 每个任务开始前",
            "",
            "1. 在 `10` 找到当前任务，先读取‘唯一主责原子要求’、原图硬约束和该任务自己的‘F1设计继承门禁’，再读取其余实施字段；相关需求上下文只用于防止破坏，不能扩大当前任务范围。",
            "2. 打开任务列出的 Word 段落和原图，按 `13` 的语义锚点重新确认，不只读摘要。",
            "3. 在 `09` 打开对应产品章节/路由，确认用户看到什么、点击什么、失败后怎么办。",
            "4. 在 `07/08/evidence` 查 7.20 保留代码、当前候选代码、API、端点和数据模型归宿。",
            "5. 修改前记录保护能力、特性开关和回滚路径；修改后逐条执行任务内F1设计规则、自动测试与仅剩必要的桌面人工验收。纯非UI任务必须逐条记录N/A理由。",
            "6. 每完成一个任务立即更新 `02` 和 `00`，记录真实实现证据，不把计划写成完成。",
            "",
            "## 7. 当前禁止操作",
            "",
            "- 用户确认 F1 视觉方向前不得进入 F2，也不得把 F1 自动验收写成用户已经确认。",
            "- F1 期间不得改写四个保护页源码来消除局部重复；相关页面应在后续责任阶段按保护能力清单减负。",
            "- 未经用户授权不得提交 Git、推送远程、修改数据库 schema 或更新比赛交付包。",
            "- 不先做量化评测、PPT、视频生成、打包和企业化功能；先把产品主线实现完整。",
            "- 不因 452 个端点或 193 个模型已经存在而新增普通用户工作台。",
            "- 不用固定路由数、固定原子数或关键词出现作为完成证明。",
            "",
            "## 8. 当前门禁与继续条件",
            "",
            "- 12 号交叉校验必须 PASS。",
            "- 245 条原子要求各有唯一主责产品章节和唯一主责任务；完整要求与页面合同在 09/10 正文中各出现于主责位置，不能只检查 ID。",
            "- 29 组图片都有人工语义锚点和跨主题边界；图片的结构、必须吸收和禁止照搬在 09/10/13 中使用同一完整解释。",
            f"- 全部 {implementation['task_count']} 个任务各自携带 {len(implementation['f1_design_contract']['rules'])} 条 F1 设计规则；12号必须逐任务核对JSON合同、Markdown独立小节和规则次数，顶部总则不能替代。",
            "- 学生完整旅程每一步都有路由、主动作、状态、失败恢复和下一步。",
            "- F0 的保护基线和当前页面快照可复核；F1 不得降低四个保护页的业务能力。",
            "- F1 必须同时通过生产构建、契约测试、两种桌面尺寸浏览器 E2E、Codex 逐图复核和用户视觉确认；当前只缺最后一项。",
            "- 用户确认后先更新 `00`、`02` 和 F0-F1 验收报告，再进入 `F2-T01`。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path("."))
    args = parser.parse_args()
    root = args.workspace.resolve()
    base = root / "outputs" / "原系统融合重构执行"
    product = load_json(base / "09_EduMatrix最终产品方案.json")
    implementation = load_json(base / "10_原版融合重构详细实施方案.json")
    audit = load_json(base / "13_改进想法逐句逐图实质落实审计.json")
    crosscheck = load_json(base / "12_方案交叉校验报告.json")
    current_routes = load_json(
        base / "evidence" / "route_product_spec" / "route_product_spec.json"
    )
    scope = load_json(
        base / "evidence" / "fusion_scope_matrix" / "fusion_scope_matrix.json"
    )
    if crosscheck.get("status") != "PASS":
        raise ValueError("Crosscheck must PASS before synchronizing context documents")

    outputs = {
        "00_唯一执行状态.md": render_status(
            product, implementation, audit, crosscheck, current_routes, scope
        ),
        "06_用户意图与产品宪法.md": render_constitution(),
        "08_用户需求追踪与路由迁移矩阵.md": render_route_matrix(
            product, implementation, current_routes, scope
        ),
        "11_上下文恢复与实施索引.md": render_recovery_index(
            product, implementation, audit, crosscheck
        ),
    }
    for filename, content in outputs.items():
        (base / filename).write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
