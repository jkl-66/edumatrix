# EduMatrix M5 WORKLOG2

## WL2-M5-20260728-012 - 旧测评、代码与复习入口统一证据双写

- 状态：`PARTIAL`（M5-010/011）。
- 兼容范围：旧 `/api/quiz/evaluate`、`/api/code/run`、`/api/flashcard/review` 和错题反思入口保留原请求/响应与既有数据库行为，同时写入 `m5.assessment-evidence.v1` 和正式 learning event。
- 身份：兼容桥只使用认证层解析后的 student username，再服务端映射至 canonical user public ID；不信任请求体 owner。
- 强证据边界：即时测验无论答对与否均为 `quiz_answered`；错题反思和 SM-2 复习为 `wrong_question_reviewed`；普通代码运行即使无 stderr 也只有 public scope 的 `code_run`。只有显式 hidden/required 全通过或 24 小时延迟复测才可能成为强证据。
- 幂等：测验按 quiz+attempt、代码按 execution、复习按 plan+review count、反思按 note+quiz 绑定稳定幂等键；重复载荷可重放，冲突拒绝。
- 验证：M5 学习/测评/上下文、M8 恢复和安全聚焦回归 `31 passed`；涉及模块 Python 编译通过。
- 当前问题：旧 quiz 仍直接修改 legacy profile mastery，这是既有算法通道，不等于 canonical 路径掌握证据；后续应将画像消费器与路径强证据分离并统一解释。
- 当前问题：统一题目/尝试版本、错因候选确认、SM-2 与不确定性合并队列、延迟复测调度仍未完成。
- 时间：2026-07-28（Asia/Shanghai）。

本日志只追加 M5 的真实实现、测试结果、问题和下一步，不覆盖历史记录。所有外部依赖、未完成门禁和已知问题统一记录在这里。

## WL2-M5-20260727-001 - M5 范围进入与阶段 4 首批能力契约

- 状态：`IN_PROGRESS`（M5-001、M5-005）
- 范围：M5 是完全体阶段 1-9 剩余核心学习平台，不是只实现阶段 4，也不重新实现 M1-M3 已有统一对象和比赛闭环。
- 首批实现：新增严格 `m5.capability.v1`，覆盖权威计划 14 类能力、fast/standard/verified 质量模式、上下文对象引用、输出约束、计划版本和幂等键。
- 能力锁定：未显式要求产物时默认 `answer`；显式 capability 与旧 `/explain`、`/map`、`/code`、`/quiz`、`/video` 命令冲突时拒绝，不允许静默改判。
- 专用门禁：verified 模式要求课程、领域包、画像快照、目标知识点和难度区间；实操指南要求环境与安全边界；交互实验要求显式运行模式。
- 路由：实现 R0 确定性动作、R1 受限自然动作、R2 快速回答、R3 计划/决策确认、R4 单产物、R5 复合任务的预检决策；删除、发布和重大计划/决策在无确认令牌时不执行。
- 能力状态：新增认证 API `/api/v1/m5/capabilities` 和 `/api/v1/m5/route`。当前没有后端真实模型配置、真实 FAISS 和动画目录时返回 unavailable/blockers，不展示假可用状态；API 不接收或返回模型密钥。
- 当前问题：既有 `Settings.vue` 仍把 API Key 保存在浏览器并通过请求头发送，`swarm_factory.py` 仍按请求头动态创建模型；这与 S4-002“密钥只存后端安全配置”和 S4-037 企业模型策略冲突。首批 M5 API 已禁止这种模式，但旧接口尚未迁移，不能宣称所有 AI 请求已通过统一网关。
- 当前问题：现有 `llm_client.py` 有限流、重试和熔断基础，但没有统一能力注册、Prompt 版本、调用级 trace/usage/cost 持久化和结构修复终态；列入 M5-005 后续批次。
- 当前问题：当前本地 `data/faiss_indexes` 没有可验证 `.faiss` 文件，`data/animations` 不存在，后端模型为 deterministic 且 endpoint/key 为空；真实回答、视觉、视频和检索能力必须如实显示不可用。
- 测试：首批能力契约与 API 聚焦测试为 `5 passed, 5 warnings in 1.20s`，警告为既有 FastAPI/Starlette 弃用提示。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M5-20260728-010 - 正式当前资源教师上下文首批

- 状态：`PARTIAL`（M5-009）。
- 正式对象：新增 `tutor_context_sessions`，以用户、课程、主对象、上下文模式、教学风格、讲解深度、引导模式、持久化快照和乐观锁保存可恢复上下文；迁移 `20260727_010` 建表、索引和状态触发器。
- 来源边界：章节、本人产物、正式 source_ref 和本人路径节点可作为主对象；选区引用从数据库解析页码、字符范围、图像区域、quote、内容哈希和 parser 版本，客户端不能用自填文本冒充教材证据。
- 上下文模式：支持仅当前资源、当前课程、个人资源和允许外部知识四档，快照显式返回检索范围；多资源对照只能引用本人仍处于 active 的上下文。
- 运行门禁：预检封装问题、意图、来源和教学设置，但明确 `generation_started=false`；同时返回文本模型和检索真实可用性及 blockers，不在本地模型/FAISS 不可用时伪造回答。
- 认证 API：新增上下文创建/列表/读取/归档和问题预检，均按本人所有权隔离；重复创建幂等，变更载荷冲突，归档使用乐观锁。
- 迁移修复：聚焦治理测试发现旧库直接升级时 `009` 只校验 `learning_event_consumptions` 而未创建；已改为迁移自身幂等建表，`010` 同样不依赖 `create_all` 预建。旧库迁移治理测试通过，空库迁移链到 `20260727_010`。
- 验证：上下文与学习闭环 `10 passed`；全部 M5 聚焦回归 `25 passed`；语法检查和 OpenAPI 关键路由检查通过。
- 当前问题：旧 `/api/stream/chat` 不接受 `context_session_id`，仍从请求头动态创建模型；旧选区解释也未走统一网关。直接复用会丢弃正式上下文，因此本批没有把旧聊天包装为已完成的上下文教师。
- 当前问题：旧流式形成性检查在接触后固定增加掌握度，这与 M5 证据原则冲突；迁移前必须移除该错误更新，并让正式学习事件/画像证据消费者负责掌握变化。
- 当前问题：精读阅读器、阅读位置、文本/公式/区域选择 UI、代码与视频上下文、引用回跳、正式对话消息和跨页面共享侧栏尚未实现。
- 时间：2026-07-28（Asia/Shanghai）。

## WL2-M5-20260728-011 - 测评、代码、错题与复测统一证据适配

- 状态：`PARTIAL`（M5-010）。
- 契约：新增严格 `m5.assessment-evidence.v1`，统一 quiz attempt、code execution、wrong-question review 和 delayed retest 的来源对象、目标对象、发生时间、幂等键及必要指标。
- 强弱证据：答题正确仍记录为 `quiz_answered`；错题复习只记录 `wrong_question_reviewed`；代码只有隐藏或规定测试全部通过才转换为 `code_tests_passed`，公开样例全过或隐藏测试部分通过仍只是 `code_run`；延迟复测必须正确且间隔至少 24 小时才转换为 `delayed_retest_passed`。
- 持久化：统一适配复用 M5 正式学习事件和版本化消费记录，自动驱动路径节点但仍明确 `mastery_changed=false`，不以单次答题、运行或复习伪造掌握。
- API：新增认证 `/api/v1/m5/assessment-evidence`，支持幂等提交和路径消费；OpenAPI 路由确认已注册。
- 验证：新增 4 项契约/持久化测试；学习、上下文和测评聚焦 `14 passed`，M5 全部聚焦回归 `29 passed`，语法检查通过。
- 当前问题：旧 `/api/quiz`、`/api/code`、错题和复习端点尚未双写此契约；在完成兼容适配前，旧操作不会自动进入新事件链。
- 当前问题：统一题目/尝试版本、正式测验答题策略、隐藏答案权限、错因候选及用户/教师确认、SM-2 与不确定性合并排序、延迟复测调度仍未完成。
- 时间：2026-07-28（Asia/Shanghai）。

## WL2-M5-20260727-002 - 统一模型调用记录与结构化输出终态

- 状态：`IN_PROGRESS`（M5-005）
- 数据对象：新增正式 `model_calls`，记录 trace、所属任务/用户、锁定能力、Prompt 版本、提供商/模型、状态、最小化输入摘要、输入/输出 Token、Token 来源、重试数、估算成本、耗时、输出哈希和错误码；不保存 API Key 或原始用户 Prompt。
- 数据迁移：新增 `20260727_006`，验证 `model_calls` 表存在并安装状态/非负计量数据库触发器；内存 SQLite 实测迁移顺序为 `20260723_001` 至 `20260727_006` 共 6 项。
- 模型注册：新增提供商、模型、强弱档、支持能力、JSON/视觉/流式能力、上下文长度、价格和数据区域的严格注册 Schema；调用前拒绝不支持锁定能力或不支持 JSON 的模型。
- Prompt 与输出：每次调用绑定 `prompt_key:version`；结构化请求严格解析 JSON 并用 Pydantic Schema 校验，错误持久化为 `structured_output_invalid`，不把非法文本伪装成成功产物；提供商异常持久化为 `provider_call_failed`，即使提供商抛出 `ValueError` 也不会误分类为结构错误。
- 数据最小化：调用记录只保存上下文对象 ID、引用数量、质量模式、Prompt 标识和输入字符数，不保存原始 Prompt；成功结果保存 SHA-256，不在调用表复制完整输出。
- Token 边界：当前通用后端协议不返回提供商 usage，因此首批统一网关明确记录 `token_source=estimated`，成本也是注册价格上的估算值，不能作为供应商账单或官方实际成本。
- 聚焦验证：M5 能力、API 和网关共 `8 passed, 5 warnings in 1.30s`；成功 trace、无原文摘要、Prompt 版本、输出哈希、结构错误和提供商错误 failed 终态均有断言。
- 测试环境问题：`tests/test_m1_governance_data.py` 中不依赖 `tmp_path` 的 4 项通过；2 项依赖 pytest 临时目录的测试因 Windows ACL 报 `WinError 5`，即使把 `--basetemp` 指向工作区也会在遍历/清理时报错。内存迁移验证已通过，但不能把这 2 项记录为 pytest 通过。
- 清理问题：pytest 创建的 `outputs/.pytest_m5_governance_20260727` 被异常 ACL 锁定，普通及提升权限 `Remove-Item` 均卡住并已主动终止；该目录不是产品证据，当前会话未能安全清除。
- 剩余问题：旧 `/api/process`、流式问答和 M2/M3 生成仍直接消费 `build_swarm_from_headers`/旧 LLM 接口，尚未全部迁移到 `M5ModelGateway`；因此阶段 4“所有 AI 请求统一入口”门禁仍未满足。
- 下一步：实现后端模型注册/策略选择与任务级配额，再按风险逐个迁移旧 AI 入口；迁移前保留旧接口兼容，禁止一次性替换造成回归。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M5-20260727-003 - 后端模型策略、同质量主备与日额度

- 状态：`IN_PROGRESS`（M5-005）
- 策略对象：新增不含密钥的后端 `GatewayPolicy`，约束允许的 provider/model、能力、数据区域，以及用户/课程/模型 UTC 日额度；普通请求不能通过请求体扩大策略。
- 分档选择：fast 优先 fast，standard 只在 standard/strong/review 中选择，verified 只允许 strong/review；主模型和备用模型都必须满足锁定能力、允许区域和质量模式，不把 fast 模型作为 verified 的静默降级。
- 课程作用域：`model_calls` 新增正式 `course_id`，迁移 `20260727_007` 为旧库补列并建索引；网关只接受能力契约中的 `course_id`，不允许 GatewayRequest 另传课程覆盖额度归属。
- 额度：调用前累计当前 UTC 日的调用数、估算输入/输出 Token 和估算成本，并按用户、课程、模型 fail-closed；成本门禁包含本次预计输入成本。
- 迁移验证：内存 SQLite 实测 7 项注册迁移从 `20260723_001` 顺序应用到 `20260727_007`。
- 当前问题：额度当前是“查询后写入 model_call”的预检，不是独立原子 reservation；多进程高并发下仍可能同时越过剩余额度，不能宣称强一致配额。后续需使用数据库额度桶/预留记录或外部原子计数器。
- 当前问题：同质量备用模型目前只形成可审计选择结果，尚未绑定真实后端实例自动执行重试；外部 provider/key 也尚未迁入后端注册存储。
- 聚焦验证：加入策略与额度测试后，M5 聚焦测试为 `10 passed, 5 warnings in 1.37s`。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M5-20260727-004 - 统一资源中心首批后端

- 状态：`PARTIAL`（M5-007）
- 复用边界：直接复用正式 `artifacts`、`artifact_versions`、`artifact_relations` 和既有 learner-safe 内容转换，没有新建资源旁路表。
- 搜索与重开：新增 `/api/v1/m5/resources` owner 范围搜索与过滤，以及资源详情；列表不返回全文，支持标题、类型、课程、状态、归档和游标条件。
- 版本对比：同一 artifact 的两个正式版本可生成统一 diff，并返回两侧内容哈希；不存在的版本明确失败，diff 超过 200000 字符时标注截断。
- 可校验导出：导出前重新计算持久化内容 SHA-256，不一致时 fail-closed；导出包包含 artifact/version 身份、格式、元数据、持久化哈希和实际导出内容哈希。
- 防泄题：`tiered_quiz` 导出复用 learner-safe 转换，移除 `answer_key` 和 explanation；由于脱敏后内容变化，持久化哈希与导出哈希分别标注，不混用。
- 生命周期：归档/恢复使用 `expected_lock_version` 乐观锁并写正式 audit log，重复同状态请求幂等返回。
- 聚焦验证：M5 能力、网关、策略、API 和资源中心共 `13 passed, 5 warnings in 1.46s`；包含检索、diff、哈希导出、归档审计、并发冲突和测验答案不外泄断言。
- 当前问题：资源中心首批只覆盖 canonical artifact；旧聊天附件、旧笔记和错题导出尚未迁移为 artifact 或兼容视图。
- 当前问题：当前只提供可校验 JSON 响应，尚无 PDF/DOCX/ZIP 文件导出，也没有 M5 资源中心前端页面。
- 当前问题：当前 owner 范围已验证，课程教师/助教共享、企业保密策略和公开 publication 浏览仍需结合阶段 6 全量权限规则实现。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M5-20260727-005 - 原子额度预留与同质量主备执行

- 状态：`IN_PROGRESS`（M5-005）
- 原子额度：新增正式 `model_quota_buckets`，按 `scope_type + scope_key + utc_day` 唯一保存用户、课程和模型日额度；迁移 `20260727_008` 校验表、索引、范围和值约束。
- 事务语义：一次调用的用户/课程/模型三个额度桶使用 SQLite `ON CONFLICT DO UPDATE ... WHERE` 条件原子增加，并处于同一事务；任一作用域超额会回滚全部桶，不再采用先查后写的并发弱预检。
- 预留口径：调用前按输入 Prompt 估算 Token，并结合输出 `max_length` 或默认上限预留输出 Token 与成本；失败的提供商尝试同样占用调用和预计资源额度，避免重试绕过配额。
- 主备执行：新增策略驱动执行链；只按后端批准注册和同质量档位尝试主备，provider failure 可切换备用，结构错误、策略拒绝和额度错误不自动换模型掩盖。
- 追踪：每次真实尝试保留独立 `model_call`；返回 `attempted_models` 和 `fallback_used`，能够区分主模型失败与备用成功。
- 聚焦验证：策略/网关 7 项测试通过，覆盖额度回滚、verified strong→review 备用、失败与成功两条调用记录；干净内存库 8 项迁移顺序应用至 `20260727_008`。
- 当前问题：实现使用 SQLite 原子 upsert，符合当前正式数据库；未来切换 PostgreSQL 时需提供对应 dialect 实现，不能直接复用 SQLite insert。
- 当前问题：额度预留按估算上限扣减，尚无 provider usage 回写和未使用输出额度结算，因此偏保守且不等同供应商账单。
- 当前问题：真实 provider/key 注册尚未落入后端安全配置，当前策略执行仅通过注入后端完成确定性验证。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M5-20260727-006 - 资源中心前端与构建验证

- 状态：`PARTIAL`（M5-007）
- 前端入口：新增 `/resources` 路由、学生/教师侧边栏入口、`frontend/src/api/m5.js` 和 `ResourceCenter.vue`，复用正式 M5 资源 API；M5 客户端只发送 JWT，不沿用浏览器 API Key 请求头。
- 页面功能：支持标题搜索、类型/状态筛选、显示归档、资源详情、稳定版本选择、版本 diff、校验包 JSON 下载、乐观锁归档和恢复；归档前需要用户确认。
- 布局：桌面为资源列表与详情双栏，移动端切为单栏；列表、详情、版本工具和内容区使用稳定高度/网格约束，图标采用现有 Lucide 库。
- 后端聚焦验证：M5 能力、API、网关、策略和资源中心为 `15 passed, 5 warnings in 1.53s`；警告为既有 FastAPI/Starlette 弃用提示。
- 前端构建：沙箱内 Vite 因 `spawn EPERM` 和 Tailwind Windows 原生二进制加载失败未进入源码编译；按相同 `npm run build` 在沙箱外执行后成功，3066 modules transformed，并生成独立 `ResourceCenter` CSS/JS chunk。
- 构建警告：现有 `StudentAnalysis` 等 chunk 超过 500 kB；资源中心自身 JS gzip 约 3.14 kB，不是大 chunk 来源。本轮未做无关拆包重构。
- 运行验证：项目 `.venv` 启动 FastAPI 成功，`/api/health` 返回 deterministic、endpoint/key 为空、FAISS 关闭；检查后已停止服务。
- 浏览器限制：按浏览器技能尝试访问 `http://127.0.0.1:8000/resources` 时，内置浏览器安全策略明确拒绝该本地地址并禁止换浏览器或其他自动化方式绕过；因此本轮没有桌面/移动截图和实际视觉验收，不能把生产构建通过等同于浏览器验收。
- 当前问题：资源中心尚未实现课程教师/助教共享、企业策略、publication 浏览、PDF/DOCX/ZIP 导出和旧笔记/聊天/错题兼容迁移。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M5-20260727-007 - 通用后台任务编译与恢复骨架

- 状态：`PARTIAL`（M5-006）
- 复用底座：直接使用正式 `generation_tasks`、`task_steps`、`task_events`，没有为 M5 新建内存任务或静态进度对象。
- 路由边界：只有已通过可用性和确认门禁的 R3 规划、R4 单产物、R5 复合任务能创建后台任务；R0/R1 确定性动作和 R2 快速回答明确拒绝进入重型队列。
- 编译规则：R3 编译为上下文、规划、策略校验、确认提交；R4 编译为上下文、能力生成、类型校验、产物提交；R5 按锁定的复合能力逐项生成/校验，再聚合和提交资源包。
- 隐私：`m5.contract.locked` 只保存严格能力契约、路由决策和能力列表，明确 `message_included=false`；步骤摘要只记录对象数量和能力/质量，不保存自然语言正文。
- 生命周期：支持幂等创建与内容冲突拒绝、启动、前置步骤完成门禁、步骤完成/失败、retryable 局部重试、非 retryable 任务失败、全步骤完成门禁和按事件序列断线续取。
- 局部返工：失败步骤生成相同 sequence 的下一 attempt，并绑定 `parent_step_id`；已完成步骤不重建，最新 attempt 决定恢复状态和任务进度。
- API：新增认证 `/api/v1/m5/tasks` 创建、`/start`、GET 续取和 `/steps/{sequence}/retry`；HTTP 只提交/读取状态，不在请求连接内同步执行完整 R5。
- 聚焦验证：通用任务 3 项测试通过；M5 能力、网关、策略、资源和任务合计 `18 passed, 5 warnings in 1.70s`。
- 当前问题：尚无消费通用步骤的后台 worker，未把每个步骤绑定正式 `AgentRun`、M5 Gateway 调用、产物草稿和质量检查；当前只证明任务编译与恢复，不证明内容生成完成。
- 当前问题：R5 目前采用顺序步骤，尚未实现无依赖子资源并行、取消传播、看门狗、超时回收和服务重启自动认领。
- 当前问题：通用类型验收工具名已锁定到步骤，但实际 checker、证据辩论、高风险人工审核和局部 rework 执行仍待下一批接入。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M5-20260727-008 - 类型化质量门禁与通用局部返工

- 状态：`PARTIAL`（M5-006）
- 持久检查：新增 M5 integrity、type_schema、source_binding 三类版本化 checker，结果幂等写入正式 `quality_checks`，关联 artifact version 和 trace。
- 完整性：所有类型先重算版本正文 SHA-256 并与 `content_hash` 比较；不一致直接 failed，不能继续审核。
- 类型 Schema：`lesson`、`lab_guide`、`tiered_quiz` 和 `interactive_skill_artifact` 分别使用既有正式 Pydantic Schema；未知类型返回 `manual_required`，不会用“非空文本”自动通过。
- 来源：读取 artifact version 的 `source_ref_ids` 并验证正式引用存在；verified 无来源引用或引用缺失直接 failed；fast/standard 无声明来源时不伪造引用。
- 审核门禁：只有三类检查均 passed 才返回 `ready_for_review=true`；manual_required 和 failed 都不能自动进入批准状态。本批没有自动发布 artifact。
- 局部返工：通用任务新增 `schedule_capability_rework`，只对已完成逻辑步骤创建下一 attempt，保留旧输出和 parent_step_id，并按最新 attempt 重算进度。
- 聚焦验证：已知类型三项检查通过且重放不重复写；未知类型进入人工待审；verified 无来源失败。M5 全部聚焦测试为 `20 passed, 5 warnings in 1.74s`。
- 当前问题：当前 checker 只覆盖四种已有正式 Schema；code、mindmap、slides、video、report、match_report 和 decision 仍需各自类型检查器，当前会诚实进入 manual_required。
- 当前问题：质量检查尚未自动消费生成步骤输出，也未自动触发 rework；需要后台 worker 将生成→检查→返工状态连接起来。
- 当前问题：来源检查只证明引用对象存在，不等于原子事实语义得到支持；语义事实核验、Challenger/Judge 和高风险专家签名仍未接入通用 M5 门禁。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M5-20260727-009 - 版本化计划、正式路径与可重放学习事件

- 状态：`PARTIAL`（M5-008）。
- 数据与迁移：扩展正式 `plan_drafts`、`learning_paths`、`path_nodes` 和 `learning_events`，新增 `learning_event_consumptions`；迁移 `20260727_009` 为旧库补列、索引和计划/路径状态触发器。全新内存 SQLite 已顺序执行 9 项注册迁移至 `20260727_009`。
- 计划生效门禁：草稿保存不会创建正式路径；计划节点必须引用本课程正式章节或本人 canonical artifact，扩展内容必须单独标记并填写原因。用户确认后才创建 active 路径；重规划产生不可变新版本及 added/removed/moved/changed 差异，再次确认后仅归档同一计划谱系的旧路径并建立 supersedes 关系，不会误归档同课程的其他计划。
- 路径与日程：路径支持带乐观锁的暂停、恢复和归档；普通状态切换不能直接完成路径，只有所有节点获得强证据后才汇总为 completed。今日任务只读取 active 路径，排除已完成节点和前置条件未满足节点，并返回预计时长范围和资源状态。
- 事件闭环：实现严格 `m5.learning-event.v1`、用户级幂等键、来源、对象、发生时间和版本化消费记录；重复事件和重复消费可安全重放，冲突载荷拒绝。访问、阅读、视频、讲解、笔记、答题和代码运行只形成接触/进行中状态，`user_marked_complete` 不覆盖算法；仅测试全过、延迟复测通过或教师确认可完成节点，且不能越过未完成前置节点。消费结果明确记录 `mastery_changed=false`，未伪造掌握度变化。
- 认证 API：新增计划创建/读取/修订/差异/确认、路径读取/状态转换、事件记录/重放和今日任务接口；OpenAPI 路由表已确认关键端点全部注册。首批授权严格限制为对象本人所有权。
- 聚焦验证：M5 学习闭环新增 6 项测试，覆盖草稿不执行、幂等冲突、正式目标/扩展、版本差异和谱系替换、状态锁、强弱证据、前置阻塞、消费重放及今日任务；M5 聚焦回归为 `21 passed in 1.49s`，语法检查通过。
- 当前问题：尚无计划草稿和路径的前端编辑/差异确认 UI；今日工作台尚未聚合到期复习与教师任务，也没有负荷冲突、不可用时间和提醒渠道。
- 当前问题：旧前端、代码沙箱和媒体播放器尚未统一发布此事件 Schema；事件当前只驱动路径节点，不更新 BKT/IRT/MIRT 掌握度、画像、复习日期或仪表盘订阅，因此 M5-008 不能记为完成。
- 当前问题：动态降维、补先修、巩固、进阶候选及用户确认/撤销尚未实现；企业岗位标准、免修、高风险必修、批次排程和主管审批仍属于后续缺口。
- 当前问题：计划和路径 API 首版为 owner-only；课程教师/助教共享、组织策略和企业审批权限尚未接入完整授权模型。
- 时间：2026-07-27（Asia/Shanghai）。
