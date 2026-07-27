# EduMatrix M5 WORKLOG2

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
