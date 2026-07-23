# EduMatrix M2-M8 Codex 无缝接手交接文档

> 版本：2026-07-24  
> 工作区：`D:\project-edumatrix\edumatrix-main`  
> 用途：交给队友的 Codex 作为接手前必读上下文。  
> 当前原则：先以工作区代码、测试输出和本文件引用的状态文档为准，不以聊天记忆或文件名推断完成状态。

## 1. 给接手 Codex 的首条指令

请直接复制下面这段作为新任务的第一条指令：

```text
你正在接手 EduMatrix 项目，请先完整阅读：

1. outputs/EduMatrix_M2-M8_Codex无缝接手交接文档.md
2. outputs/竞品深度分析/05_EduMatrix完全体最终路线与全量实施计划.md
3. outputs/M1_最小统一数据底座/00_M1执行索引与状态.md
4. outputs/M1_最小统一数据底座/01_M1_WORKLOG2.md
5. outputs/M1_最小统一数据底座/02_M1阶段门禁审计.md
6. outputs/M2_单画像黄金闭环/00_M2执行索引与状态.md
7. outputs/M2_单画像黄金闭环/01_M2_WORKLOG2.md

当前从 M2 继续，不要重新实现已完成的 M1，不要回滚或清理工作区中其他成员的修改。先检查 app/m2_contracts.py 和 tests/test_m2_contracts.py 的语法与测试状态，再按 M2 索引顺序推进。每完成一组任务必须：

- 更新 outputs/M2_单画像黄金闭环/01_M2_WORKLOG2.md；
- 更新 outputs/M2_单画像黄金闭环/00_M2执行索引与状态.md；
- 运行本组聚焦测试；
- 通过后继续下一组，不要每个小任务询问；
- 遇到破坏性变更、真实业务决策、外部信息或无法从代码/测试确定的事实才暂停。

不允许虚构人工验收、专家签字、企业接入、模型指标或比赛指标。自动测试精确覆盖的验收条件不重复安排人工操作；按总方案的“等价证据不重复”规则记录为“自动验收通过/人工不重复”。
```

## 2. 当前真实状态

### 2.1 M1：已完成

M1“最小统一底座”已经正式关闭，当前证据如下：

- S1-001 至 S1-044：全部 `PASS`。
- G1 至 G9：全部 `PASS`。
- M1 专项：最终 `43 passed, 5 warnings`。
- 全量后端：`200 passed, 1 skipped, 6 warnings`。
- 前端生产构建：通过，Vite 转换 3093 个模块。
- 真实模型最小连通性：`openai/deepseek-v4-flash` 成功。
- 统一对象网关：47 类对象。
- `ProfileEvidence` 已正式建表、迁移、兼容投影、权限接入和 Trace 接入。
- M1 人工验收中与自动测试完全重复的内容已经取消，不能重新要求团队逐项执行。

权威状态文件：

- `outputs/M1_最小统一数据底座/00_M1执行索引与状态.md`
- `outputs/M1_最小统一数据底座/01_M1_WORKLOG2.md`
- `outputs/M1_最小统一数据底座/02_M1阶段门禁审计.md`
- `outputs/M1_最小统一数据底座/03_M1自动验收报告.json`
- `outputs/M1_最小统一数据底座/04_M1人工业务验收清单.md`

### 2.2 M2：已开始，但尚未完成

M2“单画像黄金闭环”刚开始，当前只完成：

- 冻结 M2 范围和 12 项首批任务。
- 记录现有链路差距。
- 新增 `app/m2_contracts.py`：三类资源能力契约初稿。
- 新增 `tests/test_m2_contracts.py`：三类契约测试初稿。

**重要：`tests/test_m2_contracts.py` 尚未运行，M2 契约不应标记为通过。** 接手后的第一个动作必须是语法检查和聚焦测试。

M2 当前文件：

- `outputs/M2_单画像黄金闭环/00_M2执行索引与状态.md`
- `outputs/M2_单画像黄金闭环/01_M2_WORKLOG2.md`
- `app/m2_contracts.py`
- `tests/test_m2_contracts.py`

### 2.3 当前工作树

工作树非常脏，包含此前用户、队友和自动生成材料的修改。必须遵守：

- 不执行 `git reset --hard`。
- 不执行 `git checkout --` 回滚文件。
- 不删除或移动不属于本次任务的文件。
- 不把整个工作树格式化或批量改名。
- 编辑使用 `apply_patch`。
- 修改前先读取目标文件当前内容。
- `git status` 中大量未提交文件是已知现状，不要把它们误判成需要清理的垃圾。

## 3. 权威路线和阶段关系

唯一权威总方案：

`outputs/竞品深度分析/05_EduMatrix完全体最终路线与全量实施计划.md`

比赛加速轨顺序：

```text
M0 赛题与评测契约冻结
  -> M1 领域包、统一对象与三组画像的底座子集（已完成）
  -> M2 单画像黄金闭环（当前）
  -> M3 三画像 C+ 比赛闭环与一个代表性交互技能工件
  -> M4 50+ 案例量化评测与可靠性交付
  -> 比赛可交付门禁
  -> M5-M8 完全体主序列
```

M2-M8 的定位：

| 里程碑 | 目标 | 主要对应完全体阶段 | 退出条件 |
|---|---|---|---|
| M2 | 一名基准学习者、一个薄弱技能、三类资源、一次反馈更新 | 阶段 4、5、6、7、9 的比赛子集 | 刷新、重连、重启、幂等和局部失败后仍可完成并复现 |
| M3 | 三组差异画像、四角色协同、辩论审核、匹配报告、动态决策、一个交互工件 | 阶段 10 子集及阶段 3/5/7/9 交叉部分 | 三画像差异可解释，交互任务产生真实技能证据 |
| M4 | 50+ 有效案例、官方指标、安全隐私、干净环境和交付包 | 阶段 13、14 子集 | 指标如实报告，安装和黄金旅程可复现 |
| M5 | 完全体核心学习平台，补齐阶段 1-9 剩余任务 | 阶段 1-9 | 统一对象覆盖核心功能，旧功能回归通过 |
| M6 | 教师治理、企业内训、岗位标准、转岗、认证、媒体和运营 | 阶段 10、11 | 学生、教师、企业管理者共享同一证据链 |
| M7 | 第二领域、SSO/HR/LMS、xAPI/cmi5、分享、插件和空间工作区 | 阶段 12 | 第二领域不复制核心代码，集成契约稳定 |
| M8 | 可靠性、安全、性能、部署、全量评测、文档和最终交付 | 阶段 13、14 | 所有能力域有实现、测试、证据、文档或正式不采用决定 |

不要为了完成 M2 而提前实现 M5-M8 的大范围功能，也不要用静态 JSON、硬编码 Agent 结果或旧聊天记录冒充正式统一产物。

## 4. M2 的首批任务顺序

完整清单在 `outputs/M2_单画像黄金闭环/00_M2执行索引与状态.md`。推荐按以下顺序推进：

1. 验证并完成 `app/m2_contracts.py` 和对应测试。
2. 冻结一个基准学习者、正式课程、领域版本、画像快照和一个薄弱知识点。
3. 建立 `verified` 模式的最小上下文装配：画像快照、目标知识点、领域版本和 `source_ref` 必须明确绑定。
4. 复用 M1 `generation_task/task_step/task_event`，建立 M2 黄金任务执行服务，不能另建内存任务状态。
5. 将现有生成器输出适配为正式 `lesson` 产物并保存 artifact/version/source relation。
6. 实现正式 `lab_guide` 产物。代码案例不自动视为实操指南，至少需要环境、目标、步骤、预期结果、验收、故障分支、回滚和风险。
7. 实现正式 `tiered_quiz` 产物，强制 foundation/application/advanced 三层，答案和解析不能返回学习者视图。
8. 对三类产物执行类型检查、来源检查和一致性检查；失败只局部返工，合格产物版本不得被覆盖。
9. 建立闭环资源包/manifest，列出任务、画像、领域、产物、版本、来源、检查和决策 ID。
10. 将一次学习反馈写入 learning event、画像证据和候选 decision record，区分“反馈已记录”和“能力已掌握”。
11. 注入断线、刷新、重启、重复提交、局部生成失败和重试，验证不重复产物、不丢事件、不产生假成功。
12. 运行后端、前端和浏览器 E2E，保存 M2 自动验收报告，再更新 M2 状态。

## 5. 当前三类 M2 契约草稿

`app/m2_contracts.py` 当前定义：

- `GenerationContext`
  - `owner_public_id`
  - `course_id`
  - `domain_version_id`
  - `profile_snapshot_id`
  - `target_knowledge_point_ids`
  - `source_ref_ids`
  - `quality_mode="verified"`
- `LessonArtifact`
  - 目标、前置知识、章节、知识点、来源引用和检索回顾题。
- `LabGuideArtifact`
  - 环境、安全边界、连续步骤、动作/命令、预期结果、回滚、风险、验收标准和故障分支。
- `TieredQuizArtifact`
  - foundation/application/advanced 三层题目、知识点、Bloom 层级、难度依据、评分规则、答案和解析。
- `validate_m2_artifact()`
  - 能力类型和产物类型必须匹配。
- `learner_payload()`
  - 分阶测试学习者视图排除答案和解析。

接手时需要重点审查：

- Pydantic 版本是否支持当前 `TypeAdapter`、判别联合和 `model_validator`。
- Schema 是否需要和数据库的 artifact metadata/专用表进一步对齐，而不是只停留在内存校验。
- 所有 `source_ref_ids` 是否真的存在、属于当前课程且对当前用户可读。
- 生成内容是否真的符合 Schema，不能只让测试构造一个合法样例。
- `answer_key` 只能进入受权限控制的正式版本或服务端检查，不能进入学习者接口、SSE 完成事件或截图。

## 6. 现有生成链的真实边界

旧的 `agent_swarm.py` 已有：

- 画像探针、路径规划、理论教授、逻辑画师、极客助教、考官智能体和视频推荐官。
- 五类内存资源输出。
- `regenerate_only` 局部重生成机制。
- 对齐检查、失败 Agent 定位和部分资源缓存复用。

但不能直接当作 M2 正式闭环，因为：

- `ResourcePackage` 主要是内存 dataclass。
- 资源类型大量使用中文自由字符串。
- 主聊天 SSE 会保存会话和旧画像，但不等于正式 M2 artifact/version 资源链。
- 现有“代码实操案例”缺少 M2 实操指南的强制字段。
- 现有“练习题”不等于三阶题目 Schema。
- 局部重生成需要接入 M1 task step、quality check、artifact version 和 trace，而不是只替换内存 tuple。

优先新增适配层和领域服务，保留旧聊天链兼容行为；不要直接重写整个 `agent_swarm.py` 或 `stream_api.py`。

## 7. M1 可复用的核心接口和对象

重要模块：

- `app/database.py`：SQLAlchemy 模型、`init_db()`、`run_db_op()`。
- `app/migrations.py`：只追加版本化迁移，当前含 `20260723_001` 至 `20260723_004`。
- `app/m1_repository.py`：课程、任务、产物、版本和事件仓储。
- `app/m1_object_service.py`：47 类对象统一读取、权限和安全详情。
- `app/m1_api.py`：M1 规范 HTTP API。
- `app/m1_evidence.py`：领域包、评测案例、Trace 聚合及安全 Trace 摘要。
- `app/m1_lifecycle.py`：计划、审核、发布、归档和并发控制。
- `app/m1_enterprise.py`：组织、岗位、能力标准、培训批次、技能证据和认证统一写服务。
- `app/m1_profile_evidence.py`：旧画像 JSON 到正式画像证据的兼容投影。
- `app/authorization.py`：课程和对象授权原语。

M2 新对象必须：

- 有稳定 ID、owner/course/organization 边界、状态和版本。
- 尽量复用 `DBArtifact`、`DBArtifactVersion`、`DBGenerationTask`、`DBTaskStep`、`DBTaskEvent`，不要创建平行演示表。
- 通过 `OBJECT_SPECS` 注册对象，并写权限测试。
- 使用 `trace_id` 关联画像、任务、产物、检查、反馈和决策。
- 对正文、答案、Prompt、密钥和隐私字段提供最小返回策略。

## 8. 必须执行的验证命令

在当前虚拟环境中：

```powershell
# M2 第一断点：先验证契约
& .\.venv\Scripts\python.exe -m py_compile app\m2_contracts.py tests\test_m2_contracts.py
& .\.venv\Scripts\python.exe -m pytest -q tests\test_m2_contracts.py

# 保证 M1 没有回归
$m1 = @(Get-ChildItem -LiteralPath tests -Filter 'test_m1_*.py' | ForEach-Object { $_.FullName })
& .\.venv\Scripts\python.exe -m pytest -q $m1

# 阶段结束时
& .\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run build
```

如果 `rg` 在 Windows 会话中出现 `Access is denied`，使用 PowerShell `Select-String` 替代，不要把检索失败误判为代码问题。

## 9. Worklog 和状态更新规则

每完成一组任务：

1. 先运行聚焦测试。
2. 记录真实命令、通过数、警告、修改文件、未完成项和下一步。
3. 更新 M2 索引对应任务状态。
4. 若新增数据库表或迁移，记录空库、旧库、重复迁移和失败迁移证据。
5. 若新增 API，记录 Schema、认证、403/404/409/410、越权和正文脱敏测试。
6. 若新增前端交互，记录构建、浏览器检查、控制台错误和必要截图。
7. 不使用“应该”“预计”“设计上支持”代替实际测试结果。

推荐日志编号：`WL2-M2-YYYYMMDD-NNN`，只追加，不覆盖历史。

## 10. 关键禁止事项

- 不得宣称幻觉率、适配率、覆盖率达标，除非使用冻结数据集、明确分母和可复现脚本实际测量。
- 不得把 `200 passed` 当作 M2 已完成；M2 还要求正式三类资源、反馈、恢复和 E2E 证据。
- 不得把内存 `ResourcePackage`、旧笔记、旧 JSON 或前端静态对象冒充正式 artifact。
- 不得让模型自由决定能力类型、资源版本、组织边界或重大路径变化。
- 不得把阅读/点击/勾选步骤直接当作掌握或岗位胜任。
- 不得把无 Docker 的本地代码执行描述为强隔离；必须显示当前安全等级和限制。
- 不得因测试失败而删除测试或缩小 M2 范围；先定位契约、兼容或环境原因。
- 不得修改用户或队友未授权的 `.env` 密钥内容，也不得把密钥写入日志、截图或报告。

## 11. 接手后的推荐首轮工作

```text
读取本交接文档和 M2 状态文件
  -> py_compile m2_contracts + 运行 test_m2_contracts
  -> 修复契约测试或兼容问题
  -> 运行 M1 专项回归
  -> 在 WORKLOG2 追加“契约验证”记录
  -> 冻结基准用户/课程/薄弱 KP fixture
  -> 实现 verified 上下文装配
  -> 再进入持久黄金任务执行器
```

第一轮不应直接接真实模型批量生成，也不应先改前端。必须先让三类契约测试和 M1 回归稳定，再把契约接到任务和生成链。

## 12. 交接完成标准

队友 Codex 只有在以下条件满足后，才可宣布 M2 完成并进入 M3：

- 三类资源均为正式 artifact/version，具备严格 Schema、来源、版本和权限。
- 一名基准学习者和一个薄弱技能可从空库或指定初始化脚本重复运行。
- 一次反馈同时留下 learning event、画像证据、任务/资源关联和决策记录。
- 刷新、SSE 重连、服务重启、重复提交和局部失败不会产生重复或假成功。
- 答案、密钥、Prompt 和隐私字段不泄露。
- M2 专项、M1 回归、全量后端、前端构建和浏览器 E2E 有实际结果。
- M2 WORKLOG2、阶段索引、自动验收报告和已知限制报告均已更新。
- 只对真实通过的内容标记 `PASS`；没有证据的内容保持 `PENDING` 或 `PARTIAL`。
