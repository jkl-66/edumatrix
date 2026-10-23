# EduMatrix M8 WORKLOG2

## WL2-M8-20260803-008 - 重启后持久目标完成复验

- 状态：`PASS / GOAL_COMPLETION_VERIFIED`。
- 复验原因：夜间关机后的自动目标续跑要求从唯一主状态重新审计，确认工作树与证据没有因重启或上下文切换漂移；未重新打开 M2-M8，也未重跑 M2-M4 高成本真实评测。
- 中断记录：第一次全量 pytest 在工具权限上下文切换时被中止，未形成测试结论；第二次在只读沙箱内因无可写临时目录于 pytest 捕获初始化前退出，同样未进入收集或业务断言。确认无遗留 pytest 进程、权限恢复后再完整执行。
- 新鲜全量回归：项目虚拟环境执行 `python -m pytest -q` 为 `546 passed, 6 warnings in 111.09s`，无失败和收集错误。
- 新鲜生产构建：`frontend` 执行 `npm run build` 成功，`3114 modules transformed`；仅保留既有 `StudentAnalysis` 大 chunk 非阻断警告。
- 完成审计：`git diff --check` 退出码 0；M8 runtime-security manifest 6/6 成员字节数和 SHA-256 匹配；M5、M6、M7 的比赛退出审计和 evidence 目录均存在且非空；工作区相关 Python、Node、Chromium 进程为 0。
- 目标裁决：比赛版本、M5-M7 退出证据和最终交付审计均已满足持久目标定义；全量产品延期项仍完整保留。现有压缩包仍需在后续白天明确授权的交付任务中重建，不属于本夜间目标可执行范围。
- 时间：2026-08-03（Asia/Shanghai）。

## WL2-M8-20260803-007 - 运行安全、部署真实性与最终退出收口

- 状态：`PASS（本机比赛范围门禁）/ FULL_SCOPE_DEFERRED（独立与外部验收）`。
- 部署预检纠正：`app/m8_preflight.py` 不再依赖已经淘汰的 `domain_packs` 计数，而是核验正式发布课程、文档和 canonical source reference；canonical hash 检索可作为可用的比赛演示检索后端，FAISS 明确保持可选能力。隔离运行证据显示 2 门已发布课程、21 份文档、21 条来源引用、`retrieval_backend=canonical_hash`、无 blocker。
- 演示账户边界：默认 `teacher/admin123` 只在显式 `EDUMATRIX_DEMO_MODE=1` 时创建；源码默认运行不再静默生成已知凭据。作品运行模板显式启用演示模式，使评委演示路径与源码安全默认值可区分、可解释。
- 模型与密钥边界：`.env.example` 默认使用确定性模式且端点、Key 均为空；浏览器不接受模型 Key，不再指导用户把 Key 写入 localStorage 或请求头；后端启动日志只报告端点是否配置，不打印端点值。`packaging/.env.runtime.template` 与运行说明统一声明模型凭据只能在后端环境配置。
- 对外声明纠正：根 README 删除并非本赛题要求、也无独立证据支持的“幻觉率 <5%、适配率 >=85%、覆盖率 >=90%”表述；Docker 改为可选路径，Windows 一键运行包为评委默认路线；确定性模式只证明流程可运行，不宣称真实模型质量；题库规模改为按运行时可核验计数描述。
- 凭据泄漏排查：在未跟踪文件中发现 `scripts/claude_proxy.py` 含硬编码长令牌，`scripts/proxy.log` 含令牌形态值和请求日志；两者均属于直接泄漏风险并已从工作区移除。随后对 `app`、`frontend/src`、`scripts`、`packaging` 重新扫描，结果 `suspicious_files=0`。日志不记录、不恢复、不复述被移除的值。
- 运行安全证据：`scripts/e2e_m8_runtime_security.py` 串行启动隔离后端，完成 47/47 授权矩阵、trusted-local 正常代码执行、`os` 导入阻断、确定性演示部署预检和 SQLite `integrity_check=ok`。报告、数据库、后端日志和 SHA-256 manifest 位于 `evidence/runtime-security-20260803/`。
- 聚焦验证：`tests/test_m8_hardening.py`、`tests/test_security_contracts.py`、`tests/test_runtime_launcher.py`、`tests/test_competition_package_runtime.py` 合计 `28 passed`。本轮未调用外部模型、未外发数据、未读取或输出 `.env` 值。
- 历史证据完整性：M2、M3、M5、M6、M7、M8 共核验 9 份 manifest、67 个文件；M4 共核验 15 份 manifest、15 个文件；缺失与 hash 不一致均为 0。冻结的 M2-M4 高成本评测未重跑。
- 试错记录 1：M7 首轮 outbox 故障状态已持久化，但数据库会话关闭后再序列化 ORM 对象触发 `DetachedInstanceError` 和 HTTP 500；改为在数据库操作内部序列化，并加入回归测试后通过。
- 试错记录 2：M8 授权矩阵首轮为 46/47；显式演示模式下，未认证跨 owner 画像访问返回 403，而旧断言只接受 401。两者均为 fail-closed，矩阵按 HTTP 认证实现允许 `{401, 403}` 后重跑为 47/47。
- 试错记录 3：全量 pytest 曾两次被工具的 1 秒调用超时在收集阶段终止，未形成产品测试结果；后续使用正常超时完成的运行结果才可作为基线。
- 真实性边界：本轮不宣称独立真人标注、独立干净 Windows 机器、真实 LRS/SSO/HR/LMS、第二真实领域、性能容量指标、生产 Docker 或负责人/官方签字。这些属于完整产品范围或外部独立验收延期项，不重新打开 M2-M7。
- 交付约束：夜间指令禁止重建压缩包，因此现有作品包与源码包未包含本轮最新源代码和文档变更，提交前必须按白天交付流程重新生成并复核；本轮不提交、不推送。
- 最终门禁：项目虚拟环境全量 pytest 为 `546 passed, 6 warnings in 106.75s`，无失败或收集错误；Vue 生产构建成功，`3114 modules transformed`，仅有既有的 `StudentAnalysis` 大 chunk 非阻断警告；`git diff --check` 退出码 0；M8 runtime-security manifest 6/6 成员字节数和 SHA-256 匹配；PowerShell 原生扫描 229 个交付源码/脚本文件，`suspicious_files=0`。
- 最终裁决：M8 本机比赛范围门禁关闭为 `COMPETITION_READY / FULL_SCOPE_DEFERRED`。完整产品延期项和压缩包重建要求继续保留，但不重新打开 M2-M7。
- 时间：2026-08-03（Asia/Shanghai）。

## WL2-M8-20260801-006 - 工程基线并发、依赖、测试隔离与运行数据库治理

- 状态：`PASS`（本组工程基线；M8-004/008/009 仍按各自完整范围保持阶段索引中的原状态）。
- 迁移并发：SQLite 注册迁移改为在读取历史前执行 `BEGIN IMMEDIATE`，把迁移发现、执行和历史写入置于同一跨进程写事务，避免并发启动同时插入同一 `schema_migrations.version`；新增双并发启动回归测试。
- 依赖完整性：FAISS 摄入脚本直接导入的 `nbformat` 与 `faiss-cpu` 已加入 `requirements.txt`；验证过程中先后暴露并补齐两层未声明依赖，避免新环境在 M3 冷启动测试收集阶段中断。
- 测试隔离：M5 能力 API 的“无模型”测试显式注入空 `RuntimeAvailability`，不再依赖开发机 `.env` 是否配置真实模型；生产能力探测逻辑保持不变。
- 数据库治理：恢复 `*.db` 对 `edumatrix.db` 的忽略规则，并从 Git 索引停止跟踪运行数据库；本地数据库文件保留，不覆盖、不删除用户数据。安全备份文件继续按既有交付策略处理。
- 聚焦验证：迁移历史幂等、双并发启动、M5 空运行态注入和 M3 冷启动共 `9 passed, 5 warnings`；本地 `edumatrix.db` 文件存在且命中 `.gitignore`，Git 索引仅记录停止跟踪。
- 全量验证：项目 `.venv` 执行 `python -m pytest -q` 为 `331 passed, 6 warnings in 69.02s`，无失败、无收集错误；`npm.cmd --prefix frontend run build` 成功，3102 modules transformed，仅保留既有 `StudentAnalysis` 大 chunk 性能警告。
- 基线结论：截至 2026-08-01，本条形成后续 M2-M8 开发唯一可复现自动化基线；后续阶段不得用更窄测试覆盖或替代该全量结果。
- 时间：2026-08-01（Asia/Shanghai）。

## WL2-M8-20260728-004 - 后端唯一密钥边界与最终验证

- 状态：`PARTIAL`（M8-002/008/009）。
- 二次扫描发现 `Settings.vue` 与 `api/common.js` 仍可将文本/视觉 API Key、端点和模型保存到 localStorage 并写入 `X-EduMatrix-*` 头；`swarm_factory.py` 仍消费这些头。这是首轮头像/健康修复之外的同类安全缺陷。
- 修复：设置页改为只读后端能力状态和学习偏好；进入页面清除旧 `edumatrix_llm_config`。公共客户端只发送认证 JWT 和非秘密教学风格。Swarm factory 忽略所有外部 provider/key/endpoint/model 头，只从后端配置构建模型；开发环境仅保留明确 deterministic 测试模式。
- 验证：安全与多模态聚焦回归 `23 passed`；前端生产构建在沙箱外成功，`3066 modules transformed`。仅有既有 `StudentAnalysis` 564.22 kB 大 chunk 警告。
- 当前预检：数据库可用、迁移 `20260728_011` 当前、5 用户/1 领域包、frontend dist 可用；文本模型、视觉模型、检索、沙箱、媒体均不可用，整体 `not_ready`，`generation_allowed=false`。
- 时间：2026-07-28（Asia/Shanghai）。

## WL2-M8-20260728-005 - 全量回归与 M2-M8 退出结论

- 全量 pytest：`304 passed, 13 failed, 11 errors, 6 warnings`。
- 13 failed 分类：动画/视频真实资产缺失 6 项；FAISS 持久化或真实 patch 资产缺失 4 项；当前 Windows 子进程/命名管道限制导致 trusted-local、spawn、视觉输出 3 项。
- 11 errors：全部在测试 setup 阶段因 `C:\Users\Administrator\AppData\Local\Temp\pytest-of-Administrator` ACL `WinError 5`，未进入业务断言。
- 本批新增模块没有出现在失败清单；聚焦证据包括 M5/M8 `31 passed`、M7/企业 `12 passed`、安全/多模态 `23 passed`、恢复 `4 passed`。
- 结论：本地代码硬化与可验证功能已继续推进，但 M2-M8 权威阶段门禁没有全部完成。不能把外部资源缺失、真实运行、独立标注、浏览器/干净机验收或性能指标伪造成 PASS。详细阻塞见 `02_M2-M8最终退出审计.md`。
- 时间：2026-07-28（Asia/Shanghai）。

## WL2-M8-20260728-001 - 健康接口与浏览器端密钥泄露修复

- 状态：`PARTIAL`（M8-002/007/008）。
- 发现：旧 `/api/health` 回显模型端点及客户端传入 Key 的存在状态；旧 `/api/llm/test` 使用请求头构建模型、提示浏览器配置 Key，并回显端点或原始异常。
- 修复：健康接口只返回数据库和能力布尔状态；不接受客户端模型 Key、不返回端点。LLM 测试只读后端环境配置，缺模型时明确警告，不回显原始异常和端点。
- 发现：`AvatarSpeech.vue` 从 localStorage 读取第三方 AppId/API Key/API Secret，在浏览器执行 HMAC 并直连第三方 WebSocket。
- 修复：删除前端密钥、HMAC 和直连路径，改为无密钥的浏览器 `speechSynthesis`，保留播放、暂停、恢复、停止、静音、自动播报和压力情境降速；不宣称后端 TTS 已接入。
- Docker：移除预填第三方地址/模型，Key 仅从部署环境注入。
- 验证：安全契约 `13 passed`，Python 编译通过。
- 时间：2026-07-28（Asia/Shanghai）。

## WL2-M8-20260728-002 - 原子恢复与完整性验证

- 状态：`PASS`（M8-005）。
- 加固：备份使用 SQLite online backup；恢复先在同父目录 staging 完整校验 manifest、成员唯一性、路径边界、SHA-256、字节数和 `PRAGMA integrity_check`，全部成功后才移动至空目标。
- 行为：拒绝非空目标、重复/缺失成员、路径穿越、校验和或大小变化、缺失数据库及损坏 SQLite；失败不留下对外可见的半恢复目录。
- 验证：数据库与中文文件往返、恢复库可查询、内容篡改拒绝、非空目标拒绝、恶意路径拒绝，共 `4 passed`。
- 环境问题：系统/Python `tempfile` 创建目录后出现 Windows ACL 拒绝访问；改用仓库预建受控目录继承 ACL 才完成业务验证。此前失败属于环境 ACL，不是业务断言失败。
- 时间：2026-07-28（Asia/Shanghai）。

## WL2-M8-20260728-003 - 认证部署预检与当前构建阻塞

- 状态：`PARTIAL`（M8-007/008）。
- 新增教师/管理员认证接口 `/api/v1/m8/deployment-preflight`，报告数据库、最新迁移、初始化数据、前端 dist、文本/视觉模型、检索、沙箱和媒体能力。
- 预检输出 `ready/not_ready`、`generation_allowed` 和可操作 blocker；不含 Key、端点或异常正文，Key 仅以“后端是否配置”布尔值表示。
- 当前前端构建失败：`@tailwindcss/oxide-win32-x64-msvc` 原生 `.node` 无法加载（stream did not contain valid UTF-8），同时 Vite 配置加载出现 `spawn EPERM`。这不是本次 Vue 源码的业务测试失败，尚不能声明构建通过。
- 当前 Windows 还阻止 multiprocessing 命名管道创建（WinError 5）；相关启动测试不能在本环境宣称通过。
- 时间：2026-07-28（Asia/Shanghai）。
