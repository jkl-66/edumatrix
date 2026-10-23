# EduMatrix M7 WORKLOG2

## WL2-M7-20260803-002 - xAPI 集成沙箱闭环与 M7 比赛范围退出

- 状态：`PASS（M7-005 比赛子集；M7-010）`。M7 总状态更新为 `COMPETITION_READY / FULL_SCOPE_DEFERRED`；真实 LRS/cmi5/SSO/HR/LMS、公共市场和空间画布不写成完成。
- 正式事件链：新增认证 M7 API 和 `/integration-sandbox` 管理员工作台，复用 M6 教师干预生成的正式 `teacher_confirmed` 学习事件。入队前验证事件所有者是目标组织的有效成员，跨组织事件返回 409，普通学员访问返回 403。
- xAPI 与 outbox：事件映射为最小 xAPI 语句，组织、目标、事件和映射版本形成幂等交付；重复入队返回原记录。外部失败只更新 `integration_deliveries` 的状态、尝试次数、错误码和下次重试时间，不修改本地学习事件。
- 模拟边界：首批发送器明确是 `local_simulation`。工作台显示 `network_sent=false` 和“真实 LRS 兼容性未声明”；没有读取外部凭证或发送网络请求。
- 自动验证：原 xAPI/outbox 3 项、受限插件 2 项和新增 API 4 项合计 `9 passed, 5 warnings`；项目全量 `545 passed, 6 warnings in 101.43s`；Vue 生产构建 `3114 modules transformed` 成功，仅保留既有大 chunk 警告。
- 浏览器证据：`evidence/integration-sandbox-e2e-20260803/` 使用隔离 SQLite 和本机无头 Chromium，完成正式教师事件、xAPI 入队、幂等重放、模拟 LRS 失败、本地证据保持、恢复送达和 390×844 移动端。最终状态 `delivered`、尝试 2 次、SQLite integrity `ok`；manifest 中 8 个文件 SHA-256 全部复核通过。
- 视觉检查：桌面失败态清楚显示错误码、幂等键、本地事件未改变和恢复命令；移动端采用纵向信息带与堆叠事件行，无重叠，已送达状态可见。
- 试错记录：首次 E2E 的失败状态已写入数据库，但路由在 `run_db_op` 关闭会话后读取 ORM 交付对象，触发 `DetachedInstanceError` 并返回 500。改为在数据库操作闭包内序列化响应，并新增模拟会话剥离的回归测试；没有修改 outbox 权限或状态规则。全量回归第一次调用因工具超时设为 1 秒而在收集早期终止，使用 240 秒上限重新运行后 545 项全部通过。
- 插件结论：受限数据插件 manifest、hash、路径和能力边界继续作为已测试契约；尚无注册/导入/参考领域的评委闭环，因此不提升为完整插件框架声明。
- 下一步：M7 不因全量延期项常规重开。主线进入 M8，先用最新 M3-M7 关闭证据修订旧 M8 索引和最终退出审计，再完成可自主执行的安全、部署、浏览器与交付门禁。
- 时间：2026-08-03（Asia/Shanghai）。

## WL2-M7-20260803-001 - M7 进入与既有集成/插件基线审计

- 状态：`IN_PROGRESS`；M6 已按比赛范围退出，M7 成为唯一开发主阶段。
- 复用基线：`app/m7_integrations.py` 已把正式 `DBLearningEvent` 映射为 xAPI 语句，并以组织、目标和事件版本组成幂等键写入正式 `DBIntegrationDelivery`；外部失败只改变 outbox，不改变本地学习事件。
- 失败语义：既有实现支持 pending、failed、delivered 和 dead_letter，失败采用有上限的指数退避，delivered 为终态；目前没有实际网络发送器、API、工作台或浏览器证据。
- 插件基线：`app/m7_plugins.py` 是受限数据契约而非 Python 扩展加载器。它拒绝绝对/穿越路径、资产 hash 篡改、网络、密钥、可执行代码和未声明动作；目前没有注册服务、领域导入、参考插件包或 UI。
- 已有自动证据：`tests/test_m7_integrations.py` 3 项与 `tests/test_m7_plugins.py` 2 项已包含在最新全量 `541 passed` 中；这些测试只能证明服务契约，不能写成企业 LRS/插件市场已完成。
- 比赛优先选择：先闭合 `M6 正式学习事件 -> xAPI outbox -> 模拟 LRS 失败 -> 本地权威事件保持 -> 重试成功 -> 审计展示`。真实 SSO/HR/LMS/LRS、公共市场和空间画布保留全量计划，不作为首批阻塞项。
- 外部数据：本批只读审计，没有网络发送、真实员工数据或密钥读取。
- 时间：2026-08-03（Asia/Shanghai）。
