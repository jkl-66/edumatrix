# EduMatrix M2 WORKLOG2

## WL2-M2-20260801-013 - M2-012 真实服务浏览器闭环与阶段正式关闭

- 状态：`PASS`（M2-012；M2 阶段正式关闭）。
- 隔离策略：数据库新增显式 `EDUMATRIX_DB_PATH` 覆盖能力；验收脚本使用 `outputs/M2_单画像黄金闭环/evidence/browser-e2e/m2_e2e.db`，不读取或修改开发者的 `edumatrix.db`。脚本仅在隔离库中为随机密码初始化的固定基准用户设置临时测试密码，生产种子仍不包含公开默认密码。
- 真实运行路径：`scripts/e2e_m2_golden_loop.py` 启动真实 FastAPI、Vite 和无头 Chromium，经 `/api/auth/login` 登录固定基准学习者，加载 `/golden-loop`，创建并启动持久任务，生成 lesson/lab_guide/tiered_quiz，执行 schema/source/cross-artifact 三类共 9 项质量检查，提交学习反馈并形成 proposed decision。
- 恢复与权限：同一浏览器刷新后恢复完成态；停止并重新启动后端后仍从隔离 SQLite 读取完整闭环；新注册普通用户访问固定基准与 owner bundle 均返回 `403`。重启后 API 复核得到 `completed`、3 个资源、9 条质量记录、1 条反馈事件和 1 条候选决策。
- 真实运行发现与修复：首次运行发现 Vue 将空字符串 `action` 直接绑定 `disabled` 后仍渲染禁用属性，改为 `Boolean(action)`；第二次运行发现默认确定性后端不满足 M2 原始 JSON 契约，补充严格的三类离线结构化工件适配与引用范围回归。两项都通过真实 API/浏览器路径再次验证。
- 进程治理：Windows 下按受控 PID 回收完整 npm/Vite 进程树；最终运行后 `8000/5173` 均无监听残留。
- 浏览器证据：`evidence/browser-e2e/report.json` 结果为 `passed`；截图覆盖登录、基准加载、三资源与 9/9 质量门禁、反馈完成、后端重启恢复。关键截图已目视确认内容非空、布局完整、状态与报告一致。
- 自动验证：全部 M2 为 `32 passed, 5 warnings`；全量后端为 `332 passed, 6 warnings`，无失败、错误或收集异常；`python -m compileall -q app scripts/e2e_m2_golden_loop.py` 通过；前端生产构建成功，`3102 modules transformed`。
- 声明边界：本次使用 deterministic 模式证明无外部 Key 时的工作流、结构契约、状态机、持久化和权限边界，不作为真实结构化模型质量、真实 FAISS 检索效果或比赛量化指标证据。上述门禁继续由 M3/M4 承担。
- 修改文件：`app/database.py`、`frontend/src/views/GoldenLoop.vue`、`llm_client.py`、`scripts/e2e_m2_golden_loop.py`、`tests/test_m2_artifacts.py`、M2 索引、本日志及验收证据。
- 下一步：按既定顺序进入 M3，先准备许可证可核验教材与真实 FAISS，再接入真实结构化模型，最后执行三画像、四角色、辩论审核和交互工件浏览器闭环。
- 时间：2026-08-01（Asia/Shanghai）。

本日志按实际完成顺序记录 M2 每组代码、测试、限制和下一步。历史记录只追加，不覆盖。

## WL2-M2-20260726-011 - M2-012 未关闭并按用户指示转入 M3

- 状态：`PENDING`
- API 聚焦验证：新增失败步骤重试、owner 越权拒绝、非法 sequence 拒绝和 attempt 2 恢复测试；`python -m pytest -q tests\test_m2_api.py` 为 `2 passed, 5 warnings in 1.86s`。
- 全量后端：详细模式收集 `238` 项，首项实际失败为 `tests/test_animation_integration.py::TestAnimationResources::test_animation_for_specific_knowledge`，常见知识点未发现本地视频；未把该结果描述为 M2 通过。
- 前端构建：沙箱内被 Windows 原生依赖加载和 `spawn EPERM` 阻断；并行沙箱外运行未保留可核对结果，需后续单独重跑。
- 浏览器：当前会话未暴露浏览器技能要求的专用控制工具，因此未执行桌面/移动 E2E，不生成虚构截图或通过结论。
- 阶段变化：用户随后明确要求继续 M3。M2 索引中的 M2-012 和总状态保持 `PENDING/IN_PROGRESS`，仅按用户授权开始 M3，不视为跨过 M2 退出门禁。
- 修改文件：`tests/test_m2_api.py`、本日志。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M2-20260723-001 - M2 范围冻结与现有链路差距审计

- 状态：`IN_PROGRESS`
- 权威范围：一组画像、一个薄弱技能、讲义/实操指南/分阶测试三类正式资源、一次反馈更新；刷新、断线、重启和局部失败后仍可恢复。
- 现有可复用能力：M1 的画像快照、任务/步骤/事件、正式产物和版本、质量/事实/决策对象、Trace、权限和迁移；现有 Swarm 的画像探针、规划、五角色生成、对齐检查和指定 Agent 局部重生成。
- 关键缺口：主聊天生成结果主要停留在内存 `ResourcePackage` 和旧会话记录；资源类型是中文自由字符串；“代码实操案例”不能等同于包含环境、步骤、预期、验收、故障、回滚和风险的正式实操指南；练习题没有强制三阶 Schema；局部返工尚未统一写入正式任务步骤、质量检查和产物版本。
- 实施顺序：先冻结三类能力契约，再建立持久任务执行器，随后完成三类生成与检查、反馈决策和恢复 E2E。不会为了快速演示另建静态 JSON 或绕开 M1 统一对象。
- 时间：2026-07-23。

## WL2-M2-20260726-002 - 三类资源契约验证与 Windows 基线可复现修复

- 状态：`PASS`
- 完成内容：验证 `GenerationContext`、`LessonArtifact`、`LabGuideArtifact`、`TieredQuizArtifact`、能力与产物类型映射，以及分阶测试学习者视图的答案/解析隔离。
- 聚焦验证：`python -m py_compile app\m2_contracts.py tests\test_m2_contracts.py` 无错误；`python -m pytest -q tests\test_m2_contracts.py` 为 `5 passed in 0.12s`。
- M1 回归：`python -m pytest -q $m1Tests` 在允许 pytest 正常使用临时目录的执行环境中为 `44 passed, 5 warnings in 15.66s`。
- 环境差异：新克隆不包含交接文档中的 `.venv`，本轮使用 `D:\code\anaconda\python.exe`（Python 3.12.7、Pydantic 2.13.4、pytest 7.4.4）。沙箱内 pytest 临时目录 ACL 会导致 `PermissionError`，完整回归在沙箱外执行；这不是产品断言失败。
- 可复现修复：新增 `.gitattributes` 固定冻结课程 Markdown 为 LF；`course_catalog.py` 在校验冻结 manifest 前规范化文本换行，避免系统级 `core.autocrlf=true` 改变检出字节；新增 Windows CRLF 回归测试并忽略本地 `.tmp/`。
- 修改文件：`.gitattributes`、`.gitignore`、`course_catalog.py`、`tests/test_m1_course_sources.py`、`outputs/M2_单画像黄金闭环/00_M2执行索引与状态.md`、本日志。
- 下一步：执行 `M2-001`，冻结一个可重复初始化的基准学习者、正式课程、领域版本、画像快照和薄弱知识点；随后进入 `M2-003` verified 上下文装配。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M2-20260726-010 - 刷新、重连、重启、重复提交与局部失败恢复

- 状态：`PASS`
- 恢复环境：新增文件型 SQLite 集成测试，在多个 checkpoint 之间关闭 Session、dispose Engine 并从同一数据库重新创建 Engine，区别于仅在同进程换 Session 的弱验证。
- 故障注入：lesson backend 首次返回 Markdown 围栏，结构化解析以 `invalid_generator_json` 失败；失败事件和 step 状态提交后重启，只为 lesson 创建 attempt 2，随后正常生成并继续 lab/quiz/quality/feedback。
- 刷新与重连：任意时点可从持久 task/最新 step 恢复；按 `after_event_sequence` 续取时首条序号严格为 cursor+1，完整事件序列从 1 连续到最后一条，无丢失和重复。
- 响应丢失与重放：模拟产物已提交但客户端重放同请求，复用原 artifact/version；完成后重复黄金任务创建和反馈提交分别返回原 task/feedback，不新增对象或 manifest 版本。
- 最终核对：同一 trace 只有 1 个 generation task、1 个 learning event、3 个正式子资源加 1 个 manifest；lesson 失败发生在落库前，因此最终只有 1 个 lesson artifact/version；manifest 在反馈前后保留 2 个版本；task event 行数等于最后事件序号。
- 假成功防护：生成失败时无 artifact；质量或反馈缺失时任务不能 completed；最终 completed 发生在三类版本、质量检查和正式反馈均存在之后。
- 聚焦验证：`python -m pytest -q tests\test_m2_recovery.py` 为 `1 passed in 1.63s`；全部 M2 为 `29 passed in 8.97s`。
- 修改文件：`tests/test_m2_recovery.py`、M2 索引和本日志。
- 下一步：执行 `M2-012`，增加规范 API 和学习者可见闭环界面，运行后端全量、M1 回归、前端构建与浏览器 E2E，生成 M2 自动验收和已知限制报告。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M2-20260726-009 - 学习反馈、画像证据、候选决策与完成门禁

- 状态：`PASS`
- 完成内容：新增 `record_m2_feedback()`，一次提交分别写入正式 `DBLearningEvent`、`DBProfileEvidence` 和 `DBDecisionRecord`，并把对象 ID 汇入闭环 manifest 新版本。
- 幂等：learning event/profile evidence/decision 使用 owner + idempotency key 派生的稳定服务端 ID；完全相同重放复用原对象与 manifest 版本，不同内容复用同 key 返回 `idempotency_conflict`。
- 证据边界：事件保存行为类型、完成状态、正确率、求助、主观难度和耗时，但不保存自由文本 note 正文；事件与证据均写 `mastery_state=unchanged_pending_evidence`/等价说明，单次反馈不建立掌握结论。
- 候选决策：按 `m2.feedback.v1` 产生收集更多证据、维持巩固、变式练习、降表达负荷、先修微测或延迟复测等候选；decision 保持 `proposed`、`user_confirmed=False`、`mastery_update=none`，重大进阶仍需确认。
- 完成门禁：四个资源/质量步骤全部完成但没有正式反馈时，黄金任务返回 `task_feedback_missing` 并保持 running；反馈对象落库后才允许 completed，最终 manifest 状态为 completed 并包含 event/evidence/decision ID。
- 验证性质：测试提交的是可复现自动化反馈事件，不宣称真实人类已掌握、人工已验收或决策效果已经回流。
- 聚焦验证：反馈/任务/质量/manifest 组合为 `10 passed in 4.40s`；全部 M2 为 `28 passed in 9.31s`。测试后 Conda hook 有 `_ctypes`/证书插件噪声，pytest exit code 为 0。
- 修改文件：`app/m2_feedback.py`、`tests/test_m2_feedback.py`、`app/m2_tasks.py`、相关测试、M2 索引和本日志。
- 下一步：执行 `M2-011`，注入刷新/事件游标重连、服务 Session 重启、重复任务与反馈提交、局部生成/质量失败及重试，验证不重复产物、不丢事件和不产生假成功。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M2-20260726-008 - 正式闭环资源包 manifest 与血缘

- 状态：`PASS`
- 完成内容：新增 `M2BundleManifest` 与 `build_m2_manifest()`，以正式 `m2_bundle_manifest` artifact/version 保存闭环资源包，不使用临时字典或静态 JSON 文件冒充统一产物。
- 血缘范围：manifest 汇聚 task/trace/owner/course/domain/profile/KP/source_ref、三类 artifact/version/hash/status/step attempt、quality/claim/task event，以及后续 learning event/profile evidence/decision ID。
- 内容最小化：manifest 只保存对象 ID、版本哈希、状态和检查引用，不复制三类正文、Prompt、quiz 答案或解析；metadata 声明 contains artifact IDs 和来源。
- 门禁：只有三类当前版本均绑定 completed step，且各自通过 schema/source/cross-binding 三类检查后才可创建；未检查版本返回 `quality_checks_incomplete`。
- 版本与关系：内容未变化时重建复用当前 manifest version；反馈、决策或任务状态变化时追加新版本；manifest 通过三条 `contains` 关系连接正式资源，重复构建不重复关系。
- 聚焦验证：`python -m pytest -q tests\test_m2_quality.py tests\test_m2_manifest.py` 为 `4 passed in 2.27s`。测试后 Conda shell hook 额外输出 `_ctypes`/`pip_system_certs` 环境错误，但 pytest 已以 exit code 0 完成。
- 修改文件：`app/m2_manifest.py`、`tests/test_m2_manifest.py`、`app/m2_quality.py`、M2 索引和本日志。
- 下一步：执行 `M2-010`，将一次幂等学习反馈分别写入 learning event、画像证据和 candidate decision record，明确“反馈已记录”不等于“能力已掌握”，并更新 manifest 新版本。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M2-20260726-007 - 版本化质量检查、三资源绑定与局部返工

- 状态：`PASS`
- 检查对象：新增 `run_m2_quality_checks()`，对每个当前正式版本分别写入 `schema`、`source_binding`、`cross_artifact_binding` 三类 `DBQualityCheck`，检查器版本固定为 `m2.schema.v1`、`m2.source_binding.v1`、`m2.cross_binding.v1`。
- 指标口径：结构、来源解析和跨资源绑定分别保存 0/1 结果与错误明细，不合成无依据总分；`DBClaimCheck` 只声明 source_ref 已解析、ready 且属于课程，rationale 明确“不代表语义事实支持”。
- 一致性：三类版本必须共享 verified profile snapshot、domain version、目标 KP、source_ref 和 trace，且至少存在共同正式来源；当前只证明结构与血缘一致性，`semantic_conflict_assessed=False`，不虚构模型语义审核结论。
- 局部返工：质量失败不会修改 completed step 或旧 artifact version，而是只为被定位的产物创建下一 `rework_scheduled` attempt；修订内容追加为同 artifact 的新 version，其他合格产物和版本保持不变。质量步骤本轮失败后以新 attempt 重跑。
- 幂等：同一不可变版本和检查器版本重复执行复用原 quality/claim 记录；已通过质量步骤重复检查不新增事件或检查记录。
- 聚焦验证：任务、产物、质量组合为 `9 passed in 3.26s`；全部 M2 为 `24 passed in 6.38s`。测试实际证明单个 lesson metadata 失败只返工 lesson，修复后 lesson 保留 2 个版本，lab/quiz 不重生成。
- 修改文件：`app/m2_quality.py`、`tests/test_m2_quality.py`、`app/m2_tasks.py`、`app/m2_artifacts.py`、M2 索引和本日志。
- 下一步：执行 `M2-009`，建立持久、可重开的闭环 manifest，汇聚任务/画像/领域/产物版本/source/check/decision ID 与状态，并验证 owner 权限和重建一致性。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M2-20260726-006 - 三类结构化生成与正式 artifact/version 持久化

- 状态：`PASS`（M2-005、M2-006、M2-007）
- 生成适配：新增 `M2StructuredArtifactGenerator`，复用现有异步 LLM backend，以能力专属 JSON Schema、verified context、画像摘要和正式来源正文生成原始 JSON；不解析自由 Markdown，不接受代码围栏或附加解释。
- 讲义：强制目标、章节正文、目标 KP、source_ref、检索回顾题和总结；生成内容通过契约与上下文范围校验后保存 `lesson` JSON 版本。
- 实操指南：强制环境、安全边界、连续步骤、动作/命令、预期结果、回滚、风险、验收标准和故障恢复分支；旧“代码案例”不会自动升级为 lab_guide。
- 分阶测试：强制 foundation/application/advanced 三阶、唯一题号、Bloom 层级、难度依据、评分、答案和解析；完整答案仅保存在服务端正式版本，`M1Repository.artifact_payload()` 对 tiered_quiz 始终返回学习者脱敏 JSON，异常旧内容 fail-closed。
- 正式血缘：每个版本 metadata 保存 schema、quality mode、profile snapshot、domain version、目标 KP、source_ref、trace 和敏感字段声明；前三个任务步骤必须绑定对应 `artifact_version_id`。
- 幂等与失败：不合法 JSON、Schema 失败、越界来源/KP 在落库前失败；相同任务/类型/内容重放复用原版本，不重复产物；不同内容重放冲突，不静默覆盖。
- 聚焦验证：`python -m pytest -q tests\test_m2_artifacts.py` 为 `3 passed in 1.51s`；全部 M2 为 `22 passed in 5.64s`。
- M1 回归：`python -m pytest -q $m1Tests` 为 `44 passed, 5 warnings in 16.39s`。
- 修改文件：`app/m2_artifacts.py`、`tests/test_m2_artifacts.py`、`app/m1_repository.py`、M2 索引和本日志。
- 下一步：执行 `M2-008`，为类型、来源和三资源一致性检查写入正式 quality/claim 对象，并把失败结果连接到单步骤返工 attempt，保证合格版本不被覆盖。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M2-20260726-005 - 持久黄金任务、步骤、事件与重启恢复

- 状态：`PASS`
- 完成内容：新增基于 M1 `DBGenerationTask/DBTaskStep/DBTaskEvent` 的 M2 黄金任务状态机；一个任务固定包含讲义、实操指南、分阶测试和质量汇总四个逻辑步骤，不创建平行内存任务状态。
- 幂等语义：同 owner/idempotency key 且 context/course/model 完全相同时返回原任务，不重复步骤或 context 事件；相同 key 绑定其他能力或请求时返回 `idempotency_conflict`。
- 状态与恢复：queued→running→completed/failed 显式转换；步骤按 sequence/attempt 持久化；可重试失败仅为该 sequence 创建下一 attempt，并通过 `parent_step_id` 保留历史；新数据库 Session 可按事件游标恢复最新步骤和未读事件。
- 假成功防护：所有逻辑步骤的最新 attempt 未全部完成时，任务不能 completed；重复完成相同状态不新增事件，完成步骤若尝试绑定不同产物版本则冲突。
- 聚焦验证：`python -m pytest -q tests\test_m2_tasks.py` 为 `4 passed in 1.72s`；显式收集全部 4 个 M2 测试文件后为 `19 passed in 4.69s`。
- 已知后续：当前步骤允许无产物版本完成是为质量步骤保留的底层能力；M2-005~007 的生成服务将强制前三步绑定正式 `artifact_version`，M2-008 再强制质量步骤检查全部版本。
- 修改文件：`app/m2_tasks.py`、`tests/test_m2_tasks.py`、M2 索引和本日志。
- 下一步：按 `M2-005`~`M2-007` 将现有生成链输出适配为正式 lesson/lab_guide/tiered_quiz Schema，并保存 artifact/version/source metadata，答案只保留在受控服务端版本。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M2-20260726-004 - verified 最小上下文服务端装配

- 状态：`PASS`
- 完成内容：新增 `assemble_verified_context()`，调用方只能提交对象 ID，`quality_mode` 由服务端固定为 `verified`；只有全部正式对象解析、授权和关系校验通过后才返回 `GenerationContext`。
- 权限与实体校验：要求 owner 存在且启用、课程已发布且可读、领域版本存在且为课程当前 active 版本、画像属于 owner 且内容哈希有效、目标 KP 属于该领域版本、来源处于 ready 且属于课程。
- 一致性校验：每个目标 KP 必须至少被一个所选课程来源教授，每个来源必须与目标 KP 相关；画像快照必须冻结同一课程、领域版本、薄弱 KP 和来源集合。
- 失败语义：缺失 owner/领域/KP/source、跨所有者画像、快照篡改、跨课程或无关来源均以稳定 `M2ContextAssemblyError.code` 失败；只转换授权层 `HTTPException`，数据库与程序错误不会被伪装成 403。
- 聚焦验证：`python -m pytest -q tests\test_m2_contracts.py tests\test_m2_baseline.py tests\test_m2_context.py` 为 `15 passed in 3.92s`；异常边界收紧后 `python -m pytest -q tests\test_m2_context.py` 为 `7 passed in 2.68s`。
- 修改文件：`app/m2_context.py`、`tests/test_m2_context.py`、M2 索引和本日志。
- 下一步：执行 `M2-004`，复用 M1 `generation_task/task_step/task_event` 建立持久黄金任务执行服务，先实现幂等创建、状态转换、事件续接和重启恢复边界。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M2-20260726-003 - 基准学习者、正式上下文与薄弱知识点冻结

- 状态：`PASS`
- 完成内容：新增 `seed_m2_baseline()`，复用 M0 正式课程和 M1 RAG 领域包，冻结服务端基准学习者、有效课程成员关系、`KP-16 原子事实与来源引用`、不可变画像快照、对应正式章节/来源，以及讲义/实操指南/分阶测试三类待生成资源。
- 可复现性：新空库中的 RAG 领域包、领域版本、知识点、来源文档、章节和来源引用使用基于业务键与版本的确定性 opaque ID；同库重复初始化不重复对象，两个独立空库产生完全相同的 `GenerationContext`。
- 规划边界：画像探针只进入不可变快照，不直接修改正式画像；允许章节来自冻结课程目录；先修代码、已有/待生成资源和 `45~75` 分钟范围写入快照，不使用伪精确时长。
- 安全边界：基准用户密码由初始化时随机不可知值哈希，不引入默认明文凭据；发现相同 username/public ID 被其他主体占用或画像快照被篡改时立即失败，不覆盖历史快照。
- 聚焦验证：`python -m pytest -q tests\test_m2_contracts.py tests\test_m2_baseline.py` 为 `8 passed in 1.87s`。
- M1 回归：`python -m pytest -q $m1Tests` 为 `44 passed, 5 warnings in 16.09s`。
- 修改文件：`course_catalog.py`、`app/m1_evidence.py`、`app/m2_baseline.py`、`tests/test_m2_baseline.py`、M2 索引和本日志。
- 下一步：执行 `M2-003`，建立只能由服务端装配的 verified 上下文，对画像所有权、课程权限、领域版本、知识点和来源引用做实体级绑定校验。
- 时间：2026-07-26（Asia/Shanghai）。
