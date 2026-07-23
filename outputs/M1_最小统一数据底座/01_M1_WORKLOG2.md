# EduMatrix M1 WORKLOG2

本日志记录 M1 每组实施的实际代码、迁移、测试、限制和下一步。历史记录只追加，不覆盖。

## WL2-M1-20260723-022 - 等价自动证据规则落地与 M1 正式关闭

- 状态：`COMPLETE`
- 团队决策：取消所有已经被精确自动验收覆盖的重复人工操作，并将该规则写入权威总方案；不把取消项伪造为“人工已通过”。
- 总方案规则：自动测试若精确覆盖输入、操作、预期结果、失败条件和持久化结果，并保存可复现报告，则不再重复人工验收；人工只保留视觉主观质量、领域专家判断、法律/责任签署、真实外部环境以及赛事明确要求的人工环节。
- M1 清单：原 24 项空白人工操作已替换为 `04_M1人工业务验收清单.md` 的关闭记录和逐项自动证据映射；状态为 `CLOSED - AUTOMATED EVIDENCE ACCEPTED`。
- 报告生成：`scripts/verify_m1_acceptance.py` 将 M1 的 `manual_acceptance` 记录为 `not_required`，理由是原清单条件均有等价自动证据，而不是声称人工签字完成。
- 最终复验：重新执行真实后端健康、真实模型最小调用和阶段验收测试；`03_M1自动验收报告.json` 为 `automated_status=pass`、`manual_acceptance=not_required`，阶段聚焦测试 `7 passed, 5 warnings`。
- M1 最终证据：S1-001~S1-044 全部 `PASS`，G1~G9 全部 `PASS`，M1 专项 `43 passed`，全量后端 `200 passed, 1 skipped`，前端生产构建通过，真实模型连通性通过。
- 未宣称：没有宣称企业 SSO/HR/LMS 已接入，没有宣称比赛指标达标，没有宣称领域专家或企业责任人已经签字。
- 下一步：进入 M2 单画像黄金闭环，按权威计划实施一组画像、一个薄弱技能、三类资源和一次反馈更新，并验证刷新、重连和失败重试后的可恢复性。
- 时间：2026-07-23。

## WL2-M1-20260723-021 - 真实模型连通性与可复现 M1 验收包

- 状态：`AUTOMATED PASS / MANUAL PENDING`
- 目标：把权威计划阶段 1 的人工场景、真实配置检查和自动化证据整理为可重复执行的验收入口，避免依赖对话记忆或手工拼命令。
- 环境检查：当前前端 `127.0.0.1:5173` 和后端 `127.0.0.1:8000` 正常监听；`/api/health` 返回 `status=ok`，模型配置为 `openai/deepseek-v4-flash`，不是 mock。
- 真实模型：调用项目自带 `/api/llm/test` 完成一次最小真实请求，结果为 `status=ok`、`LLM 连通性测试成功`。未在日志或报告中保存密钥值。
- 自动验收工具：新增 `scripts/verify_m1_acceptance.py`，统一执行后端健康检查、可选真实 LLM 连通性、M1 阶段级聚焦测试，并记录 Python、Git revision、工作树状态和安全字段；报告不会记录 API Key、Token、密码或 endpoint 凭据。
- 本次报告：`outputs/M1_最小统一数据底座/03_M1自动验收报告.json`，`automated_status=pass`、`manual_acceptance=pending`；阶段验收聚焦测试 `7 passed, 5 warnings`。
- 人工清单：新增 `outputs/M1_最小统一数据底座/04_M1人工业务验收清单.md`，覆盖两个企业隔离、岗位标准升级后历史冻结、Trace 重启恢复、正文/密钥不泄露和旧功能抽查；所有勾选项保持空白，必须由实际观察者填写。
- 当前判定：M1 自动实施与自动门禁完成，真实模型连通性已验证；仍不能把自动结果写成人工验收。M1 总状态继续保持 `IN_PROGRESS`，直到团队在准备提交的环境中完成清单并确认结论。
- 下一步：团队只需按 `04_M1人工业务验收清单.md` 逐项观察、记录异常并签字；发现阻断缺陷后再回到代码修复。
- 时间：2026-07-23。

## WL2-M1-20260723-019 - 正式 ProfileEvidence 对象、兼容投影与 Trace 接入

- 状态：`PASS`
- 目标：补齐 M1 阶段级验收中要求的正式 `ProfileEvidence` Schema，避免画像证据只存在于 `student_profiles.profile_evidence` JSON 中而缺少稳定 ID、所有者、来源和版本边界。
- 代码变更：`app/database.py`、`app/migrations.py`、`app/m1_profile_evidence.py`、`app/crud.py`、`app/m1_object_service.py`、`app/m1_evidence.py`、`tests/test_m1_profile_evidence.py`，以及相关状态/审计文档。
- 数据对象：新增 `profile_evidence_items`，保存稳定 ID、`owner_public_id`、旧学生标识、稳定兼容键、来源类型/来源对象 ID、特征、权重、置信度、证据摘要、观察时间、状态、证据版本和 `trace_id`；权重/置信度范围、状态枚举和兼容键唯一性由数据库约束保护。
- 兼容策略：旧 JSON 字段保留且不改写；画像保存时通过稳定兼容键幂等投影到正式表。能解析到用户的记录归属用户，历史记录无法映射用户时标记为 `legacy_unresolved`，不虚构所有者；提供兼容读取视图，正式表缺失时直接读取旧 JSON。
- 安全边界：对象网关注册 `profile_evidence`，使用统一所有者授权；详情只返回元数据和来源 ID，不返回 `evidence_summary`；Trace 汇总增加证据数量和安全来源字段，不返回证据正文。
- 迁移：新增 `20260723_004`，对新旧 SQLite 数据库均可幂等创建表和索引；旧迁移历史保持只追加，checksum 校验继续有效。
- 测试：新增与联合聚焦回归 `16 passed, 5 warnings`；覆盖迁移表、旧 JSON 不丢失、同步幂等、现有画像保存路径、无法解析所有者的兼容状态、对象越权、正文不泄露和 Trace 聚合。
- 未宣称：没有把旧 JSON 中所有历史证据都宣称已自动补齐为可访问的正式对象；无用户映射的历史记录仍需后续账号关联治理。没有宣称比赛指标达标。
- 下一步：运行全部 `test_m1_*.py`、全量后端测试和前端构建；根据回归结果继续处理 M1 阶段剩余的真实业务验收证据。
- 时间：2026-07-23。

## WL2-M1-20260723-020 - M1 最终自动回归与交付前审计

- 状态：`PASS WITH MANUAL ACCEPTANCE PENDING`
- 目标：在新增画像证据对象后，重新执行 M1 专项、全量后端和前端生产构建，并核对阶段索引、门禁和迁移账本的一致性。
- M1 专项：全部 `tests/test_m1_*.py` 结果为 `43 passed, 5 warnings`。
- 全量后端：`200 passed, 1 skipped, 6 warnings`；跳过项保持原测试声明，未计入通过数。警告为既有 Starlette/httpx、FastAPI `on_event` 弃用和张量转换提示。
- 前端：`npm.cmd --prefix frontend run build` 通过，Vite 转换 `3093` 个模块；仅有既有大于 500 kB chunk 性能提示。
- 迁移与注册表：`20260723_004` 可在既有测试数据库上幂等补建 `profile_evidence_items`；统一对象网关当前注册 47 类对象；旧迁移 checksum 未改写。
- 当前判定：S1-001~S1-044 均为 `PASS`，G1~G9 均为 `PASS`，代码和自动化回归满足 M1 实施门槛。M1 总索引仍为 `IN_PROGRESS`，原因是权威计划要求真实模型/API 配置下的业务人员验收、提交环境复核和展示证据，自动测试不能替代这些事项。
- 未宣称：没有宣称真实企业 SSO/LMS 已接入，也没有宣称幻觉率、适配率、覆盖率或其他比赛指标达标；没有把自动化浏览器检查写成人工现场验收。
- 下一步：由团队按交付环境配置 API 并执行一次人工业务验收；若人工验收通过，再将 M1 总索引从 `IN_PROGRESS` 改为完成状态，并进入后续阶段。
- 时间：2026-07-23。

## WL2-M1-20260723-018 - M1 全量回归、离线测试隔离与浏览器验收

- 状态：`PASS WITH FINAL REVIEW`
- 目标：完成 M1 仓储收敛后的全量后端回归、前端生产构建和关键权限/课程页面的自动化浏览器验收。
- 额外修复：`rag_engine.py` 在 `CONFIG.llm_provider == "mock"` 时自动禁用外部 arXiv/视频回退。该模式是测试显式设置的离线契约，避免 DNS/公共 API 延迟；真实模型配置仍保留外部检索能力。
- 后端回归：全量 pytest 收集 `196` 项，实际结果为 `196 passed, 1 skipped, 6 warnings in 43.78s`；多模态专项 `8 passed, 5 warnings in 6.92s`。此前 244 秒超时已定位为闲聊请求触发在线视频 DNS 回退，修复后消失。
- 前端构建：`npm.cmd --prefix frontend run build` 通过，Vite 转换 `3093` 个模块；仅有大于 500 kB chunk 的性能提示。
- 浏览器验收：使用本地无头 Chromium 检查学生仪表盘、学生知识库、学生越权访问内部对象、教师内部对象检查四个场景；页面均无 JavaScript 异常。知识库展示正式课程“RAG 应用开发与幻觉评测实训课”及 9 个文档；学生越权重定向到 `/?access=forbidden`；教师对象检查页正常展示对象类型/状态/关键词筛选和空结果状态。
- 截图证据：`outputs/m1_browser_check/student_dashboard.png`、`student_knowledge.png`、`student_forbidden_internal.png`、`teacher_internal.png`。
- 警告边界：6 个后端警告来自 Starlette/httpx、FastAPI `on_event` 弃用和既有张量转换提示；1 个 skipped 保持原测试声明，未将其计入通过数。浏览器检查为自动化验收，不虚构人工现场验收或比赛指标达标。
- 当前状态：S1-001~S1-044 均已具备当前任务定义下的 PASS 证据；G1~G9 均为 PASS；M1 总索引仍保留 `IN_PROGRESS`，后续应由团队完成真实 API 配置下的人工业务验收和发布包检查。
- 时间：2026-07-23。

## WL2-M1-20260723-017 - S1-024 与阶段门禁 G1 闭环

- 状态：`PASS WITH FINAL REGRESSION PENDING`
- 目标：对 M1 与 M0 兼容 API 的数据访问边界做最终静态审计，并复测全部 M1 专项用例。
- 静态审计：扫描根目录和 `app/` 下名称包含 api/main 的 12 个 Python 文件，搜索 `session.query|db.query|db_session.query`，结果为 `NO_DIRECT_ORM_HITS`。
- 仓储边界：M1 规范对象由 `m1_repository.py`、`m1_object_service.py` 和企业领域服务承载；M0 兼容读取与相关写操作由 `legacy_repositories.py` 承载；路由保留认证、参数、业务编排和响应职责。
- 测试：运行全部 `tests/test_m1_*.py`，结果 `38 passed, 5 warnings in 23.18s`。警告为 Starlette/httpx 和 FastAPI `on_event` 现有弃用提示，不是本组失败。
- 状态判定：S1-024 更新为 `PASS`；阶段门禁 G1 更新为 `PASS`，因此 G1~G9 当前均有实现与自动测试证据。
- 边界：尚未运行全量后端测试、前端生产构建和浏览器人工验证，因此 M1 总状态仍为 `IN_PROGRESS`，不提前宣称阶段最终完成。
- 下一步：运行全量 pytest；单独定位此前 `test_multimodal_chat.py` 超时；执行前端生产构建和浏览器人工验收。
- 时间：2026-07-23。

## WL2-M1-20260723-016 - 测验、错题、签到与 MCMC 兼容 API 仓储迁移

- 状态：`PASS WITH FOLLOW-UP`
- 目标：在不改变现有出题、评分、MIRT、错题、相似题、签到和校准行为的前提下，移除 `quiz_api.py` 路由及后台任务中的直接 ORM 查询。
- 代码变更：`app/legacy_repositories.py`、`quiz_api.py`。
- 实现：仓储统一负责题库可用题筛选、测验记录读取、题库 beta 更新、错题幂等创建与管理、复习优先级和相似题关联、签到范围/历史/日期查询，以及 MCMC 训练数据读取和校准参数回写；路由继续负责身份边界、业务算法、响应序列化和原有异常语义。
- 兼容性：选择题与主观题评分顺序不变；画像、Q-learning 和 MIRT 更新顺序不变；错题列表字段、概念统计、删除/置顶/笔记响应结构不变；签到按 UTC 入库并按 UTC+8 计算连续天数的逻辑不变；MCMC 仍要求至少两个带有效三维 theta 的学生。
- 静态证据：`quiz_api.py` 搜索 `session.query|db.query` 无匹配；`app/legacy_repositories.py` 和 `quiz_api.py` 均通过 `py_compile`。
- 测试：自动选择当前仓库中名称匹配 quiz/MIRT/BKT/wrong/checkin/member6/security_contracts 的测试；实际命中 `test_member6_refactoring.py` 和 `test_security_contracts.py`，结果 `21 passed, 6 warnings`。覆盖评分沙箱、MIRT 向量和安全契约，但当前仓库没有独立以 wrong/checkin 命名的测试文件，因此不把这些接口宣称为专项全覆盖。
- 当前限制：本条只证明 `quiz_api.py` 完成仓储收敛；尚需扫描其余 API 文件并运行 M1 与全量回归，才能判定 S1-024 和阶段门禁 G1 是否最终通过。
- 下一步：执行全项目 API 直接 ORM 扫描；若无剩余兼容路由缺口，更新 S1-024/G1 后运行全部 M1、全量后端与前端构建。
- 时间：2026-07-23。

## WL2-M1-20260723-015 - 知识库与画像兼容 API 仓储迁移

- 状态：`PASS WITH FOLLOW-UP`
- 目标：收敛知识库课程/个人文档和画像历史查询，保留 M0 前端依赖的完整返回契约和删除权限。
- 代码变更：`app/legacy_repositories.py`、`knowledge_api.py`、`profile_api.py`。
- 知识库：仓储统一查询个人/public/system 文档和 published public 课程文档；详情保持个人/公共/课程三种上下文；导读写入和删除操作进入仓储，课程与公共文档继续只读；路由不再直接查询或删除 ORM 对象。
- 画像：显示名、最近认知对齐、历史测验、个人知识文档、历史对话画像快照和复习计划删除进入仓储；卡尔曼历史重构、学习目标推荐、时空回溯和画像缓存同步逻辑保持不变。
- 静态证据：`knowledge_api.py` 和 `profile_api.py` 搜索 `session.query|db.query|db_session.query` 均无匹配，模块编译通过。
- 测试：M0 基线/课程、M1 课程来源和安全契约 `29 passed, 5 warnings`；画像、目标推荐、推荐引擎、安全和成员 6 重构测试 `27 passed, 6 warnings`。
- 未完成证据：包含 `test_multimodal_chat.py` 的首轮组合测试在 180 秒超时，未返回失败栈；该套件涉及长流式矩阵流程，不把超时记为通过，留到全量回归单独定位。
- 当前限制：`stream_api.py` 和 `quiz_api.py` 仍存在路由层 ORM；S1-024 继续为 `PARTIAL`。
- 下一步：迁移流式对话和测验 API，先逐文件提取查询到仓储，再运行流式/测验聚焦回归。
- 时间：2026-07-23。

## WL2-M1-20260723-014 - 第一批 M0 兼容 API 仓储迁移

- 状态：`PASS WITH FOLLOW-UP`
- 目标：在不改变 M0 业务行为的前提下，移除代码沙箱历史、网页检索历史、闪卡和主应用路由中的直接 ORM。
- 代码变更：`app/legacy_repositories.py`、`code_exec_api.py`、`web_search_api.py`、`flashcard_api.py`、`app/main.py`。
- 实现：`LegacyReadRepository` 集中用户、学生画像 ID、测验记录、复习计划、到期卡片、代码执行历史和网页检索历史查询；原路由保留身份解析、业务算法、事务提交和响应序列化，不再构造 ORM filter/order/limit。
- 静态证据：上述四个 API 文件和 `app/main.py` 搜索 `session.query|db.query` 均无匹配；五个模块 `py_compile` 通过。
- 测试：自动选择 flashcard、web_search、code_exec、security_contracts、runtime_launcher 和 M1 identity 相关测试，结果 `21 passed, 5 warnings`。
- 兼容性：闪卡 SM-2 调度、教师种子、匿名注册迁移、教师看板、代码/网页历史返回结构和条数限制均保持原行为。
- 当前限制：`knowledge_api.py`、`profile_api.py`、`stream_api.py` 和 `quiz_api.py` 仍存在路由层 ORM，S1-024 继续保持 `PARTIAL`。
- 下一步：迁移知识库 API 的课程/个人文档读取、详情、删除和统计查询，并运行知识库及 M0 课程回归。
- 时间：2026-07-23。

## WL2-M1-20260723-013 - 企业对象统一写服务、版本快照与全链审计

- 状态：`PASS`
- 目标：关闭 G8 中企业对象只能手工拼 ORM 的缺口，使组织、岗位、标准、培训、证据和认证的创建都经过同一权限、版本和审计边界。
- 代码变更：`app/m1_enterprise.py`、`tests/test_m1_enterprise.py`、`tests/test_m1_object_gateway.py`。
- 实现：新增组织创建与成员加入、岗位族、岗位等级、能力标准、培训方案、培训批次、培训分配、技能证据和认证签发服务；系统管理员创建组织时自动成为组织管理员；后续操作依据 learner/mentor/manager/admin 角色分别限制 read/review/assign/manage/approve。
- 版本：岗位等级和能力标准使用明确版本；培训方案有版本；批次自动冻结岗位等级版本、能力标准版本、技能标准引用、课程/资源/考核版本；认证重新生成并保存岗位与能力标准快照。标准更新后历史批次和证书保持原版本。
- 一致性：方案目标岗位、证据能力标准和认证岗位必须属于同一组织；培训只能分配给 active 组织成员；认证证据必须完整且属于同一组织和目标学员。
- 审计：组织、成员、岗位族、岗位等级、能力标准、方案、批次、分配、技能证据、认证、免修、外部身份绑定/撤销均写 `audit_logs`；不写外部 subject 或证据正文。
- 测试：企业治理、数据库治理和对象网关联合回归 `16 passed, 5 warnings`。完整服务工作流创建组织到认证，随后更新能力标准版本，验证批次和认证快照不变，并核对十类对象均存在审计记录。
- 测试夹具修复：外部身份网关夹具原先把成员与映射放在同一次 flush，SQLite 可能先执行映射触发器；改为先 flush 成员再绑定，符合真实写服务顺序，约束与回归均通过。
- 门禁更新：G8 更新为 `PASS`。当前门禁仅 G1 因 M0 兼容 API 残留直接 ORM 保持 `PARTIAL`。
- 下一步：迁移 M0 兼容 API 路由层直接 ORM 到领域仓储，再执行全部 M1 和全项目回归。
- 时间：2026-07-23。

## WL2-M1-20260723-012 - 数据库不可变、企业边界、迁移失败与完整 trace

- 状态：`PASS`
- 目标：把关键门禁从服务约定提升为数据库和自动失败测试，避免绕过 API 后污染评测金标或跨组织引用。
- 代码变更：`app/database.py`、`app/migrations.py`、`app/m1_enterprise.py`、`app/m1_evidence.py`、`tests/test_m1_governance_data.py`、`tests/test_m1_enterprise.py`、`tests/test_m1_evidence_chain.py`。
- 迁移：新增 `20260723_003`；冻结 `evaluation_cases` 的 UPDATE/DELETE；校验组织成员角色/状态；拒绝 training_program→job_level、cohort→program、assignment→cohort、exemption→assignment 的跨组织拼接；外部身份映射要求目标用户是组织 active 成员。
- 版本与审计：能力标准新增独立 `version` 字段并兼容旧 SQLite 增量迁移；免修申请/审批写入审计；新增管理员授权的外部身份绑定/撤销服务，审计元数据只记录组织和 provider，不记录 external subject。
- trace：`trace_bundle` 新增同 trace_id 的 `learning_events`，测试用 `feedback.submitted` 证明反馈事件与画像、任务、Agent、产物、质量和决策可共同恢复。
- 迁移演练：临时空库通过 `Base.metadata.create_all` 后依次应用 001/002/003；手动篡改 001 checksum 后再次运行明确抛出 `Migration history changed`，证明迁移失败不会被静默吞掉。
- 测试：治理、企业和证据链聚焦回归 `13 passed in 5.68s`。覆盖评测案例更新/删除拒绝、空库迁移、checksum 篡改、非法角色、跨组织培训引用、外部身份管理员绑定与审计、免修审计和完整 trace。
- 门禁更新：G4、G5、G7、G9 更新为 `PASS`；G8 仍需企业对象统一写服务和更完整审计后才能通过。
- 下一步：建立企业组织、岗位标准、培训批次、技能证据和认证的统一写服务，确保版本快照、组织边界和审计不依赖调用者手工组装 ORM。
- 时间：2026-07-23。

## WL2-M1-20260723-011 - M1 HTTP 边界仓储收敛

- 状态：`PASS WITH FOLLOW-UP`
- 目标：落实 S1-024“API 不直接拼 ORM”，先将全部新增 M1 HTTP 路由收敛到领域仓储和对象服务，同时保持既有响应契约不变。
- 代码变更：`app/m1_repository.py`、`app/m1_object_service.py`、`app/m1_api.py`。
- 实现：`M1Repository` 集中课程详情/大纲、来源上下文、任务详情/时间线/列表、产物详情/版本/血缘/列表查询；内部检查库存与血缘查询迁移到 `m1_object_service`；`m1_api.py` 只保留 Pydantic Schema、权限编排、事务提交和 HTTP 状态映射。
- 静态证据：`Select-String app/m1_api.py -Pattern 'session.query'` 无匹配；`py_compile` 对三个模块通过。
- 测试：课程来源、任务产物、内部检查和统一对象网关联合回归 `16 passed, 5 warnings`，接口响应、权限、分页、血缘和归档语义保持不变。
- 状态判定：新增 M1 HTTP 边界已满足仓储要求，但全项目扫描仍发现 M0 兼容 API 中存在直接 ORM，因此 S1-024 暂保持 `PARTIAL`，不以缩小范围宣称全项目完成。
- 下一步：先完成阶段门禁矩阵中的数据库完整性、企业跨组织一致性、评测案例不可变和迁移演练，再按风险迁移 M0 兼容 API 的直接 ORM。
- 时间：2026-07-23。

## WL2-M1-20260723-010 - 统一 M1 对象网关与全对象读取授权

- 状态：`PASS`
- 目标：关闭“新建对象仍需逐项接入授权”的缺口，使所有 M1 正式对象共享一个可审计、可扩展且不暴露敏感正文的 API 契约。
- 代码变更：`app/m1_object_service.py`、`app/m1_api.py`、`tests/test_m1_object_gateway.py`。
- 实现：集中注册课程、来源、产物、任务、计划、学习事件、记忆、审核发布、审计、领域包、画像、Agent、质量/声明/辩论/决策、评测、组织、岗位、培训、免修、技能证据、认证和外部身份等 46 类对象；统一解析直接 owner/course/organization 字段及 artifact_version→artifact、task_step→task、plan_version→plan、job_level→job_family→organization 等间接边界；提供 `GET /api/v1/objects/{object_type}/{object_id}` 标准详情 Schema 和 `GET /api/v1/objects/{object_type}` 稳定列表 Schema。
- 标准回答：每个详情统一返回对象类型、ID、标题、状态、版本、所有者、创建者、课程、组织、来源外键、创建/更新时间和访问策略，可回答“谁创建、属于谁、来自哪里、当前版本、谁可访问”；不返回产物正文、记忆正文、评测输入/输出、外部 SSO subject、密码或密钥。
- 权限：所有者可读私有对象；课程对象使用持久化课程成员状态和可见性；企业对象使用组织成员关系；公开领域标准和冻结评测案例作为认证后公共参考；evaluation_run/result 仅教师或管理员可读；未知对象类型返回 400、不存在返回 404、越权返回 403。
- 列表：统一网关对 46 类对象提供状态和关键词服务端过滤、ID 稳定游标、每页 1~100 条限制，并在服务端剔除当前用户不可见对象。
- 测试：聚焦执行对象网关、任务产物和企业治理测试，结果 `12 passed, 5 warnings`。覆盖 OpenAPI Schema、注册表完整性、公开课程、私有产物与版本血缘、跨用户拒绝、组织成员/外部人员隔离、外部身份脱敏、内部评测限制、权限过滤列表和游标不重复。
- 状态判定：S1-003 从 `PARTIAL` 更新为 `PASS`；前端辅助任务中的“所有列表稳定分页和服务端过滤”更新为 `PASS`。
- 下一步：收敛 `app/m1_api.py` 残留直接 ORM 到领域仓储/对象服务，完成 S1-024 的 API 不直接拼 ORM 要求。
- 时间：2026-07-23。

## WL2-M1-20260723-009 - 任务/产物列表契约与归档状态语义

- 状态：`PASS WITH FOLLOW-UP`
- 目标：让核心持久任务和产物具备可扩展列表契约，并让归档对象与不存在、无权限、并发冲突明确区分。
- 代码变更：`app/m1_api.py`、`tests/test_m1_artifact_tasks.py`、`tests/test_m1_internal_inspection.py`。
- 实现：新增 `GET /api/v1/generation-tasks` 和 `GET /api/v1/artifacts`；两者默认只查询当前权威用户拥有的对象，按不可预测但稳定的对象 ID 升序游标分页，限制每页 1~100 条；任务支持 status/course_id 过滤，产物支持 status/course_id/include_archived 过滤；列表不返回产物正文；归档产物详情和追加版本返回 410，未归档并发写冲突继续使用 409。
- 测试隔离修复：首次复跑发现内部检查测试使用固定账号，持久化测试库中该账号已在上轮提升为教师，导致学生 403 用例错误返回 200；改为每次生成唯一账号后，测试可重复运行且不依赖历史数据库状态。
- 测试：`.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_m1_artifact_tasks.py tests/test_m1_internal_inspection.py`，结果 `7 passed, 5 warnings`。覆盖所有者隔离、状态过滤、稳定游标、下一页不重复、归档 410、普通用户 403、内部对象 404 和内部血缘查询。
- 当前限制：分页已覆盖 M1 当前公开的任务、产物及内部对象列表；计划、记忆、评测、企业治理等对象尚未形成完整公开/管理 API，需通过阶段门禁审计确认哪些必须在 M1 补齐。
- 下一步：建立 M1 阶段门禁审计矩阵，逐条核对数据库约束、仓储、API Schema、权限、迁移、幂等、trace、企业版本锁定和审计证据，并继续修复真实缺口。
- 时间：2026-07-23。

## WL2-M1-20260723-008 - M1 前端统一上下文与内部对象检查

- 状态：`PASS WITH FOLLOW-UP`
- 目标：让前端身份与课程权限以服务器状态为准，统一处理关键 HTTP 状态，并提供不向普通学生开放的内部对象检查入口。
- 代码变更：`app/m1_api.py`、`frontend/src/api/common.js`、`frontend/src/api/m1.js`、`frontend/src/api/index.js`、`frontend/src/stores/context.js`、`frontend/src/router/index.js`、`frontend/src/App.vue`、`frontend/src/views/InternalObjectInspector.vue`、`tests/test_m1_internal_inspection.py`。
- 实现：新增 Pinia 当前身份/课程上下文；路由进入受保护页面时调用 `/api/auth/me` 获取权威角色；教师/管理员路由不再只信任本地角色；存在当前课程 ID 时调用课程 API，由持久化课程成员状态和课程可见性决定访问；Axios 将 401、403、404、409、410 分为未认证、无权限、不存在、版本冲突和已归档；内部对象检查 API 和页面可查询 course/source_document/generation_task/artifact，返回所有者、当前版本、权限上下文、即时血缘和关联任务；列表按 ID 稳定游标分页，并支持对象类型、状态和标题/能力服务端过滤。
- 数据保护：内部检查不返回产物正文、用户密码、密钥或完整审计正文；普通学生访问内部接口返回 403；对象不存在返回 404。
- 测试：聚焦执行 `tests/test_m1_internal_inspection.py`、`tests/test_m1_course_sources.py`、`tests/test_m1_identity_authorization.py`，结果 `12 passed, 5 warnings`；`npm.cmd --prefix frontend run build` 成功，Vite 转换 3093 个模块并生成检查页独立异步 chunk。
- 当前限制：统一错误分类已建立，但核心归档对象尚需统一返回 410；稳定分页目前覆盖内部检查列表，generation_task、artifact 和其他正式对象列表仍需继续接入；尚未完成浏览器人工验证。
- 下一步：为任务和产物提供所有者隔离的稳定列表 API，补齐归档 410 语义和测试，再继续 M1 核心对象 API/权限门禁审计。
- 时间：2026-07-23。

## WL2-M1-20260723-007 - S1-036~S1-044 企业组织、培训治理与外部身份

- 状态：`PASS`
- 任务：S1-036 至 S1-044。
- 目标：在统一底座上建立面向企业内训、转岗培训和复训场景的组织边界、岗位能力标准、培训批次、免修治理、技能证据、认证和外部身份映射。
- 代码变更：`app/database.py`、`app/m1_enterprise.py`、`tests/test_m1_enterprise.py`。
- 数据对象：新增 `organizations`、`organization_memberships`、`departments`、`job_families`、`job_levels`、`competency_standards`、`training_programs`、`training_cohorts`、`training_assignments`、`exemption_requests`、`skill_evidence`、`certifications` 和 `external_identity_mappings`。
- 实现：组织成员使用显式角色和 active 状态；跨组织访问默认拒绝；岗位族与岗位等级带版本和有效期；能力标准保存要求等级、证据要求、必修性、风险等级、免修策略和验收规则；培训批次锁定岗位标准、课程、资源和考核快照；分配记录保存组织指派、岗位要求、个人申请、转岗或复训等来源及来源引用；免修申请保留证据和规则判断，并区分普通审批、人工审批和高风险禁止免修；技能证据支持实操、代码、隐藏测试、专家签核、成绩、提示依赖和有效期；认证保存岗位、标准快照、证据、签发人、有效期和复训规则；外部 SSO/HR/LMS 标识与内部用户主键分离，并按组织、提供方和外部 subject 强制唯一。
- 权限与治理：企业管理员可审批免修，学习者只能为自己的培训分配申请免修；高风险且策略为 `forbidden` 的能力直接拒绝；组织外用户访问返回 403；岗位标准后续更新不会改写既有培训批次和认证中的快照。
- 测试：`.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_m1_enterprise.py`，结果为 `3 passed in 2.77s`。覆盖跨组织拒绝与批次快照锁定、普通免修审批与证据/认证链、高风险禁止免修和外部身份唯一约束。
- 状态判定：S1-036~S1-044 均为 `PASS`，因为当前任务定义要求的模型、关键约束、权限策略和专项测试证据均已具备。
- 范围边界：本组提供统一数据对象和治理函数，不宣称已经完成完整企业前端工作流、真实 SSO 对接、HR/LMS 生产集成或任何比赛指标达标；这些属于后续 API、前端和集成阶段。
- 下一步：执行全部 M1 专项测试，随后审计并补齐前端当前用户/课程上下文、路由守卫、403/404/409/归档状态提示、内部对象检查入口、分页和服务端过滤，以及 M1 阶段门禁。
- 时间：2026-07-23。

## WL2-M1-20260723-001 - S1-001~S1-004 统一身份与授权基础

- 状态：`PASS WITH FOLLOW-UP`
- 任务：S1-001、S1-002、S1-003、S1-004。
- 目标：将权限主体从可读 username 分离为服务器生成的稳定 ID，建立标准角色、课程成员关系、对象级授权服务和 ID 规则，同时保持旧 student_id 业务兼容。
- 代码变更：`app/identity.py`、`app/authorization.py`、`app/database.py`、`app/auth.py`、`app/main.py`、`tests/test_m1_identity_authorization.py`。
- 实现：新增不可预测 `public_id`；JWT `sub/uid` 使用 `public_id`；旧令牌兼容读取；注册忽略客户端 role/user_id；五角色枚举；课程成员表；对象访问策略；课程成员权限从数据库读取；`GET /api/auth/me` 返回权威身份。
- 迁移：旧 `users` 表增量添加 `public_id`、随机回填并建立唯一索引；新库直接创建约束；课程成员使用课程和用户稳定 ID 外键。
- 兼容决策：已有 username 与学生画像 `student_id` 暂不整体改名，避免一次迁移破坏当前聊天、画像、测评和知识库；它们成为兼容业务键，不再作为 JWT 权威主体。
- 测试：`tests/test_m1_identity_authorization.py`、`tests/test_security_contracts.py`、`tests/test_m0_course_catalog.py` 合计 `24 passed, 5 warnings`。
- 修复：首次迁移测试暴露 SQLite 在父键唯一索引创建前校验课程成员外键的问题；已将唯一索引创建调整到旧用户回填之前并复测通过。
- 状态判定：S1-001、S1-002、S1-004 为 PASS；S1-003 为 PARTIAL，因为 artifact、task、memory 等后续对象尚未创建，后续每个对象/API 必须继续接入授权服务。
- 未宣称：没有宣称全系统对象级授权已经完成，也没有删除旧身份兼容字段。
- 下一步：实施 S1-005~S1-008，建立课程、来源文档、章节、知识点和统一精确引用。
- 时间：2026-07-23。

## WL2-M1-20260723-006 - S1-026~S1-035 领域包与比赛证据链

- 状态：`PASS`
- 任务：S1-026 至 S1-035。
- 目标：将主领域、画像输入、Agent 运行、质量与事实检查、辩论、决策和评测统一到可复现 trace。
- 代码变更：`app/database.py`、`app/m1_evidence.py`、`tests/test_m1_evidence_chain.py`。
- 实现：domain_pack/domain_version；12 个岗位任务和 3 档技能标准；不可变 profile_snapshot；agent_run；quality_check；claim_check；debate_round；decision_record；evaluation_case/run/result；trace_bundle 汇聚器。
- 数据：从 M0 `core_knowledge_points.json` 构建领域版本，从 `evaluation_cases.jsonl` 幂等导入 60 个不可变案例，保留数据版本与内容哈希。
- 范围修正：初稿只录入 8 个岗位任务，核对冻结文档后补齐正式 `JOB-01~JOB-12`，未以缩小范围通过验收。
- 测试：12 任务、3 技能、60 案例重复导入不重复；构造完整 trace 后十类证据各可汇聚 1 条；聚焦回归 `6 passed`。
- 声明边界：数据结构支持指标复算，但本阶段未运行完整模型评测，仍不宣称幻觉率、适配率或覆盖率达标。
- 下一步：实施 S1-036~S1-044 企业组织、岗位、培训、免修、技能证据、认证与外部身份映射。
- 时间：2026-07-23。

## WL2-M1-20260723-005 - S1-021~S1-025 迁移、兼容、约束与备份

- 状态：`PASS WITH FOLLOW-UP`
- 任务：S1-021、S1-022、S1-023、S1-024、S1-025。
- 目标：让 M1 数据骨架可升级、可兼容旧数据、可拒绝非法状态并可做一致备份恢复。
- 代码变更：`app/database.py`、`app/migrations.py`、`app/legacy_adapter.py`、`app/backup.py`、`tests/test_m1_governance_data.py`。
- 实现：schema_migrations 保存版本/描述/checksum；迁移重复执行幂等、历史被修改即拒绝；旧知识文档、笔记、复习计划、聊天和错题只读投影；关键角色与任务/产物状态使用新库约束和旧库触发器；SQLite 在线 backup API 创建一致快照，文件与数据库写入 SHA-256 manifest，恢复仅允许空目录并防路径穿越。
- Windows 修复：发现 sqlite3 连接上下文不会自动关闭文件句柄，改用 `contextlib.closing`，解决临时快照 WinError 32 占用。
- 测试：适配器不修改旧记录、迁移账本幂等、非法角色触发器拒绝、备份恢复内容与校验值一致；治理组聚焦回归 `11 passed, 5 warnings`。
- 状态判定：S1-021/022/023/025 PASS；S1-024 PARTIAL，原因是 M1 写仓储已集中，但旧 API 和部分 M1 读查询仍需在后续迁移中逐步收敛，不能宣称全项目已消除直接 ORM。
- 下一步：实施 S1-026~S1-035 的领域包、岗位技能、画像快照、Agent/质量/声明/辩论/决策、评测运行和 trace 证据链。
- 时间：2026-07-23。

## WL2-M1-20260723-004 - S1-014~S1-020 学习状态与治理生命周期

- 状态：`PASS`
- 任务：S1-014、S1-015、S1-016、S1-017、S1-018、S1-019、S1-020。
- 目标：使计划、学习事件、记忆、审核发布和关键操作成为可恢复、可审计、可并发控制的正式对象。
- 代码变更：`app/database.py`、`app/m1_lifecycle.py`、`learning_event_bus.py`、`tests/test_m1_lifecycle.py`。
- 实现：plan_draft/plan_version/learning_path/path_node 分离；旧事件总线发布时同步持久化标准事件信封；memory_item 保存来源、置信度、敏感级和有效期；review_decision 与 publication 分离；audit_log 过滤 password/token/api_key/secret/content；产物归档可恢复；lock_version 防陈旧写入。
- 兼容策略：`LearningEventBus.publish()` 的订阅、事件类型和并发处理保持不变，持久化失败记录警告但不阻断旧订阅器。
- 测试：计划版本、正式路径、审计脱敏、学习事件持久化、记忆生命周期、审核发布分离、乐观并发冲突均通过；本组及前三组聚焦回归 `17 passed, 5 warnings`。
- 下一步：实施 S1-021~S1-025 的版本化迁移、旧数据适配、完整性约束、仓储收敛和一致备份恢复。
- 时间：2026-07-23。

## WL2-M1-20260723-003 - S1-009~S1-013 统一产物与持久任务

- 状态：`PASS`
- 任务：S1-009、S1-010、S1-011、S1-012、S1-013。
- 目标：让生成结果脱离聊天消息拥有稳定身份、版本和血缘，让生成任务在页面断开后仍可恢复和重放。
- 代码变更：`app/database.py`、`app/m1_repository.py`、`app/m1_api.py`、`tests/test_m1_artifact_tasks.py`。
- 实现：artifact 主表、不可变 artifact_version、artifact_relation；generation_task 保存所有者、课程、trace、能力、模型、状态、进度、幂等键、成本和失败；task_step 保存 Agent/工具步骤与 attempt；task_event 保存单调序号和版本化事件载荷。
- API：认证创建/查询任务，认证创建/查询产物和追加版本；返回完整任务时间线、产物版本与血缘；跨用户访问返回 403。
- 权限决策：学生读取公开课程后可创建属于自己的任务与产物，不获得课程修改权；任务/产物始终由 owner_public_id 隔离。
- 测试：验证任务幂等、事件序号、步骤重试、产物不覆盖、血缘唯一约束、API 断线恢复语义和跨用户拒绝；联合回归 `25 passed, 5 warnings`。
- 首轮问题：重复血缘关系在仓储 `flush()` 即被唯一约束拒绝，修正测试捕获位置；公开课程个人任务最初误用课程 create 权限导致 403，改为课程 read + 新对象 owner 权限后通过。
- 下一步：实施 S1-014~S1-020 的计划路径、统一学习事件、记忆、审核发布、审计、归档和并发控制。
- 时间：2026-07-23。

## WL2-M1-20260723-002 - S1-005~S1-008 课程来源与精确引用

- 状态：`PASS`
- 任务：S1-005、S1-006、S1-007、S1-008。
- 目标：把 M0 预置课程从兼容展示表投影为正式课程、来源文档、章节、知识点和可精确回跳的来源引用。
- 代码变更：`app/database.py`、`course_catalog.py`、`app/m1_api.py`、`app/main.py`、`tests/test_m1_course_sources.py`。
- 实现：课程补学科和所有者；来源文档保存格式、哈希、许可、来源、上传者、解析版本和处理状态；章节树与知识点图分离；32 个冻结 KP 使用不可预测主键并保留 `KP-xx` 业务编码；9 个课程章节通过多对多关系映射 KP；source_ref 保存解析版本、字符区间、页码/图片区域扩展位、引用文本与内容哈希。
- 兼容策略：原 `courses/course_documents/knowledge_documents` 继续服务现有知识库 UI；幂等种子流程同步规范对象，不删除旧用户文档；旧 `upsert_course_bundle()` 返回结构保持不变。
- API：新增认证只读 `/api/v1/courses/{id}`、课程 outline 和 `/api/v1/source-refs/{id}`，通过课程公开性或持久化成员关系授权。
- 首轮回归问题：向旧导入函数返回值增加规范对象计数，破坏了 M0 精确字典契约；已恢复旧返回结构，规范对象改由数据库/API 测试验证。
- 测试：第一轮发现 1 个契约失败并修复；新增 API 后与第一组联合回归为 `29 passed, 5 warnings`。
- 下一步：复测新增只读 API 后实施 S1-009~S1-013 的统一产物、版本、关系、生成任务、步骤和事件。
- 时间：2026-07-23。
