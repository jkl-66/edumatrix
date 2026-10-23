# EduMatrix M4 WORKLOG2

本日志只追加 M4 的真实实现、测试结果、限制和下一步，不覆盖历史记录。

## WL2-M4-20260727-001 - M4 范围进入与冻结指标内核

- 状态：`PASS`（M4-001、M4-003~005；M4-006 `PARTIAL`）
- 范围确认：M4 是比赛加速轨的 50+ 案例量化评测与可靠性交付，对应完全体阶段 13/14 子集，不是完全体阶段 4 模型网关。
- 复用输入：M0 已冻结 60 条非重复案例、三组匿名画像、32 个核心知识点和 `metrics-m0-0.1` 公式；M1 已有 evaluation_case/run/result 正式表。
- 本组实现：新增冻结 benchmark loader、文件哈希、案例分布和知识点引用校验；盲运行 payload 排除 gold/failure_branch；新增原子事实、五维画像适配、核心覆盖、案例结果 Schema 和三项指标/辅助指标计算。
- 声明边界：报告固定 `publication_authorized=false`；真实批量运行、双人标注和独立评测批准未完成，不声明 `<5%`、`>=85%` 或 `>=90%`。
- 聚焦测试：`.venv\Scripts\python.exe -m pytest -q tests\test_m4_evaluation.py` 为 `3 passed in 0.18s`。
- 下一步：通过聚焦验证后，接入 DBEvaluationRun/DBEvaluationResult 正式生命周期和批量盲运行服务。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M4-20260727-002 - 正式盲运行生命周期

- 状态：`PASS`（M4-002）
- 数据同步：将 M0 文件同步为正式 `evaluation-case-m0-0.1` 数据版本，已有同版本内容不一致时 fail-closed，不覆盖历史 M1 版本。
- 运行生命周期：按 `trace_id + code/data/model version` 幂等创建 `DBEvaluationRun`；配置冲突拒绝复用。
- 盲法边界：运行端只读取 `input_data`，不返回 gold、difficulty、failure_branch；输出使用受限 `BlindCaseOutput` Schema。
- 结果边界：每个 run/case 只允许一个不可变原始输出；重复相同输出幂等，不同输出冲突；写入时 `passed=false`，不在未标注时预判成功。
- 封存门禁：只有 60/60 结果存在时才能从 `running` 进入 `awaiting_annotation`，不能直接进入 passed/completed。
- 聚焦测试：`tests/test_m4_runs.py` 为 `2 passed in 0.59s`。
- 下一步：验证生命周期后接入批量执行适配器与标注持久化。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M4-20260727-003 - 不可变标注、draft 报告与管理员 API

- 状态：`PARTIAL`（M4-007、M4-011）
- 数据对象：新增不可变、可版本化的 `evaluation_annotations` 和 `evaluation_reports`；迁移 `20260727_005` 校验表存在并安装禁止更新/删除触发器。
- 双人规则：同一标注键至少两名独立 final 标注实质一致才进入计算；冲突、单人或 draft 进入 unresolved；adjudicated 可作为裁决结果。
- 报告版本：内容不变幂等复用，内容变化自动生成下一 report version；只能保存 draft，独立审批未实现前拒绝 approved 声明。
- 管理员 API：新增 `/api/v1/m4` benchmark、run、blind cases、result、seal、annotation 和 draft report 接口；仅 admin/teacher 可访问，benchmark 响应不含 gold。
- 聚焦验证：M4 评测、运行、标注和 API 共 `7 passed, 5 warnings in 2.69s`；双人解析补充测试 `3 passed`。
- 外部缺口：尚无真实模型端点和双人标注者，故不执行正式指标发布。
- 下一步：实现可恢复批量 executor、评测证据 manifest 与失败案例导出。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M4-20260727-004 - 可恢复批量盲运行执行器

- 状态：`PARTIAL`（M4-008；执行能力完成，真实运行待外部配置）
- 执行语义：逐例调用受限 executor，每条输出先持久化再进入下一条；重启后跳过已有结果。
- 失败语义：超时、异常、Schema 错误和 case_id 错配都形成正式 timeout/failed 结果，不从分母删除。
- 封存语义：只有 60 条全部持久化后自动进入 `awaiting_annotation`；测试 limit 仅用于开发验证，不代表正式运行。
- 聚焦测试：`tests/test_m4_batch.py` 为 `1 passed`；当前 M4 聚焦回归合计 `10 passed, 5 warnings in 1.69s`。
- 真实边界：当前未配置 JSON 模型和真实 FAISS，不运行 60 条假案例，不生成官方指标。
- 下一步：验证 executor 后实现结果 manifest、哈希和失败案例导出。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M4-20260727-005 - 证据 manifest、失败清单与隐私脱敏

- 状态：`PASS`（M4-010）；`PARTIAL`（M4-006、M4-009、M4-011）
- 证据包：新增 `app/m4_evidence.py`，将 run/trace、代码版本、数据版本、模型版本、冻结案例与知识点哈希、逐例结果、失败清单和可选 draft 报告关联为 `m4.evidence-manifest.v1`。
- 运维入口：新增 `scripts/export_m4_evidence.py export --run-id ... --output ...` 与 `verify --input ...`；导出目录已存在时拒绝覆盖。
- 完整性门禁：校验每个文件的 SHA-256 与字节数，并核对 run 对象关联、结果/失败行数和 report ID；manifest、引用文件缺失、文件篡改、路径越界或对象关联不一致均 fail-closed。
- 隐私边界：证据结果递归遮蔽身份/凭据类字段、邮箱、手机号和 Bearer 凭据；失败清单只保留 case/result/status/error/failure 定位字段，不复制原始回答。
- 失败分类：批处理异常、超时、Schema 错误和 case ID 错配会持久化为正式 failed/timeout 结果；导出时进入失败清单，不从评测分母中删除。
- 聚焦验证：`tests/test_m4_batch.py` 与 `tests/test_m4_evidence.py` 为 `2 passed in 0.61s`；M4 全部聚焦测试为 `10 passed, 5 warnings in 1.69s`，警告均为既有 FastAPI/Starlette 弃用提示。
- 真实边界：没有执行虚构 60 例运行，也没有生成官方指标；M4-008、真实双人标注、系统级故障注入和干净第三方环境复现仍未完成。
- 时间：2026-07-27（Asia/Shanghai）。

## WL2-M4-20260802-006 - 真实模型 60 例盲测与证据封存

- 状态：`PASS`（M4-008）；`PARTIAL`（M4-006、M4-007、M4-009、M4-011）。
- 用户授权边界：仅允许发送 M4 冻结的 60 条合成盲测输入、匿名三画像策略、冻结课程来源摘录和输出 Schema；禁止发送 gold、failure_branch、API Key 和真实用户数据。
- 出站门禁：`app/m4_executor.py` 新增全量预检与逐请求复检，递归阻断禁发键、当前环境中的密钥值、邮箱、中国大陆手机号和 Bearer 凭据；任一 60 条上下文不合规时，在首个网络请求前 fail-closed。
- 真实运行配置：run ID `er-cb01ebf69fef418fb1b866204715746c`，trace `trace-m4-real-deepseek-v4-flash-v1`，模型 `deepseek-v4-flash`，thinking `disabled`，最大输出 `16384`，数据版本 `evaluation-case-m0-0.1`。
- 断点与结果：复用此前 2 条已持久化结果，先完成 1 条真实冒烟，再断点续跑 57 条；最终累计 `60/60`，执行状态均为 `completed`，`failed=0`、`timeout=0`，run 自动封存为 `awaiting_annotation`。该状态只表示盲测生成完成，不表示案例有效性或三项指标达标。
- 盲法证据：运行摘要固定 `gold_visible_to_executor=false`；执行器只构造 blind case、匿名策略、课程来源和严格响应 Schema，gold/failure_branch 保留在数据库评测侧且不进入模型请求。
- 证据交付：隔离数据库位于 `evidence/real-run/m4_real.db`；导出目录为 `evidence/real-model-20260802/`，包含 `run.json`、`results.jsonl`、空 `failures.jsonl` 和 `manifest.json`。导出与 verify 均返回 `result_count=60`、`failure_count=0`。
- 工具改进：`scripts/export_m4_evidence.py export` 新增 `--db`，可明确选择隔离评测数据库，避免误从默认开发库导出；数据库模块在参数处理后加载。
- 自动验证：出站审计、严格 Schema、断点批处理、运行生命周期、标注、证据和 API 共 `18 passed, 5 warnings in 2.04s`；警告均为既有 FastAPI/Starlette 弃用提示。新增门禁聚焦批次为 `11 passed in 0.78s`。
- 指标边界：本次没有向模型发送 gold，也没有执行解盲评分或伪造人工标注；不得据此声称幻觉率、画像适配率或核心覆盖率达到任何阈值。
- 下一步：由两名独立标注者基于冻结 gold 完成原子事实、五维画像适配和覆盖标注，解决不一致项并生成仅供审查的 draft 指标报告；之后执行系统级故障注入与独立干净环境复现。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M4-20260802-007 - 隔离 AI 双遍标注、裁决与对象正确的指标分母

- 状态：`PASS（内部 AI 评测）`（M4-006、M4-007、M4-011）；独立真人验证仍为对外发布阻断项。
- 评审口径：固定为 `two_isolated_ai_passes_with_ai_adjudication`，A/B 是隔离执行的两遍 AI 评审，不是两名真人；`human_annotators=0`、`publication_authorized=false`。
- 对象纠正：没有把 60 条案例回答错误充当资源适配和知识点覆盖分母。正式任务拆成 60 个案例有效性任务、275 个原子事实任务、9 个 M3 真实资源适配任务和 32 个核心知识点覆盖任务，共 376 项。
- 双遍结果：A/B 各完成 `376/376`；预裁决只有 `case:M0-G04` 与 `claim:M0-G08:c1` 两项真实语义分歧，按严格冻结 gold 裁决为 `valid` 与 `supported`。
- 工件门禁：8 个 M0 原创课程章节和 9 个 M3 真实资源，共 17 项，由 A/B 隔离审批验证语义质量、来源可追溯性和版本完整性；`17/17` 一致通过，覆盖任务据此重建为 v2 后重新完成 A/B 标注。
- 内部指标：有效案例 `60/60`；幻觉率 `0/275`；适配准确率 `9/9`；核心覆盖率 `32/32`；引用可定位 `304/304`。报告包含按类别、画像和资源类型分层统计。
- 解释限制：生成与评审使用同一配置模型家族；隔离双遍不提供跨模型或真人独立性；结构化引用任务可能比开放生产流量更容易；适配仅覆盖一个共享 RAG 任务的 9 个资源；覆盖基于紧凑 M0 原创课程而非学期级外部课程。
- 并发事故：一次桌面等待终止未结束沙箱外子进程，导致首版 A 文件出现并发重复写入。损坏文件保留为 `annotations-a.concurrent-corrupt.jsonl`，首版错误裁决和旧签名报告也仅作内部事故证据；工作流已增加单实例 `.lock` 门禁，相关测试通过。这些文件不进入评委证据包。
- 中间证据：任务与标注工作区位于 `evidence/annotation-workflow-20260802/`；最终解析指标位于 `evidence/annotation-evidence-final-v2-20260802/`。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M4-20260802-008 - 最终证据白名单、防篡改和声明边界收口

- 状态：`PASS`（M4-010 加固；M4 内部指标证据收口）。
- 正式证据包：`evidence/M4-final-evidence-v3-20260802/`，仅白名单收录原始 60 例运行、v2 任务、A/B v2 标注、v2 一致性与裁决、17 项工件审批，以及 final-v2 指标/一致性/解析标注。
- 排除项：并发损坏 A 文件、被复核否决的 v1 裁决、旧签名一致性与分歧文件均不进入正式证据包；加固前目录保留为 `M4-final-evidence-v3-pre-line-verification-internal`，只用于内部历史追踪。
- 完整性门禁：`scripts/finalize_m4_evidence.py` 按白名单组装且拒绝覆盖；verify 严格核对文件集合、SHA-256、字节数和文本行数，并固定评审方法、`human_annotators=0`、`publication_authorized=false` 与 `independent_human_validation_missing`。
- 证据计数：原始结果 60；指标任务/A/B/解析标注各 376；裁决 2；工件任务/A/B 各 17。assemble 与 verify 均成功。
- 聚焦测试：证据加固与离线评测共 `18 passed in 1.66s`；明确列出全部 M4 测试文件后的 M4 回归为 `36 passed, 5 warnings in 3.42s`。警告均为既有 FastAPI/Starlette 生命周期弃用提示。
- 可复现命令：Windows PowerShell 不稳定展开 pytest 路径通配符，因此基线使用明确测试文件清单，不使用 `tests\\test_m4*.py`。
- 剩余门禁：M4-009 系统级故障注入、M4-012 干净 Windows 安装与黄金旅程复现。完成前 M4 总状态保持 `IN_PROGRESS`。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M4-20260802-009 - 系统级进程崩溃、跨进程恢复与 SQLite 证据

- 状态：`PASS`（M4-009）。
- 验收器：新增 `scripts/m4_fault_injection.py`，使用专用 SQLite 数据库和确定性无网络执行器；不读取或修改正式真实模型评测数据库，也不调用外部模型。
- 故障场景：父进程启动独立工作进程；工作进程逐条提交 13 个结果后以非正常退出码 `73` 硬退出，故意跳过正常会话清理，以模拟运行进程突然终止。
- 崩溃边界：第二个全新进程检查数据库仍为 `running` 且恰有 13 个已提交结果，证明提交边界没有回退或越界。
- 恢复结果：第三个全新进程使用相同 trace/run 恢复，只执行剩余 47 条；最终 `before=13`、`attempted=47`、`after=60`、`remaining=0`、`sealed=true`、状态为 `awaiting_annotation`。
- 数据完整性：最终独立校验确认 SQLite `integrity_check=ok`、WAL checkpoint 无忙锁、60 个结果对应 60 个唯一案例、无重复 run/case 结果、输出 case_id 与数据库案例完全匹配。
- WAL 处理：首轮测试发现硬退出后 SQLite 会保留 `-wal`/`-shm` 旁车文件。验收器据此补充受控 `wal_checkpoint(TRUNCATE)` 并在关闭 SQLAlchemy 连接池后再封装，最终证据为单一自包含数据库，不把旁车文件遗漏在白名单之外。
- 正式证据：`evidence/fault-injection-20260802/`，仅包含 `m4_fault_injection.db`、`report.json`、`manifest.json`；独立 verify 成功，数据库 SHA-256 为 `0abe150ec69e280f9ae1051e193f3dfb8299fb5eb5bb919cf2f1fed068814dbf`。
- 自动测试：新增两项系统测试，覆盖硬退出精确恢复及额外文件/内容篡改拒绝；纳入 M4 明确文件回归后为 `38 passed, 5 warnings in 11.70s`。
- 下一步：执行 M4-012 干净 Windows 安装、真实前后端黄金旅程和提交包复现，完成比赛可交付门禁后再进入 M5。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M4-20260802-010 - 提交包修复、同机干净 Windows 复现与代码执行演示

- 状态：`PASS（M4-012，同机干净复现）`；M4 内部工程与比赛可交付门禁完成，可进入 M5。该结论不等同第三方独立机器验收，也不解除独立真人指标验证的发布阻断。
- 交付问题修复：实际安装发现 PyTorch 深路径触发 `WinError 206`，评委启动器因此默认使用 `%LOCALAPPDATA%\EduMatrix\00015352\.venv` 短路径，并允许 `EDUMATRIX_VENV_PATH` 覆盖；短路径独立 venv 完成锁定依赖安装且 `pip check` 通过。
- 运行资产修复：作品包白名单补入 M0 冻结课程与数据；修复通用 `dist` 排除规则误删 `frontend/dist/assets`；新增 Vue Router history fallback，同时保持 `/api/*`、`/data/*` 和缺失静态扩展文件返回 404。
- 最新作品包：`outputs/00015352作品.zip`，`1,091,526,089` 字节，SHA-256 `5e895eeb7d4b0ec5ccc9807a9d0c0f0bee8ae53c8695e81ffbd5c7fa4e2ea13b`，共 `3,101` 项。ZIP CRC 校验通过；含 9 篇冻结课程文档、6 个冻结数据/清单文件、完整前端产物和最新版运行脚本；不含 `.env`、`.venv`、`node_modules`、WAL/SHM 或密钥。
- 默认黄金旅程：在同一 Windows 主机的全新 `.m4r` 解压目录和独立短路径 Python 3.11 `.m4v` 中运行；通过运行预检、Chromium、后端健康、注册登录、仪表盘、确定性问答、学习路径、知识库 9 文档/9 只读项/来源、画像分析和多模态设置，生成 9 张最新截图。默认 `disabled` 模式明确展示代码执行未启用，不伪装成沙箱可用。
- 代码执行旅程：默认后端停止后，以 `EDUMATRIX_SANDBOX_MODE=trusted_local` 重启；状态为 `execution_enabled=true`、`isolation=trusted_local_child_process`、`security_level=research_only_no_container_isolation`。安全代码 `print(6 * 7)` 输出含 `42` 且无错误；危险代码 `import os; os.system(...)` 无输出且返回错误。
- 防篡改证据：`evidence/clean-windows-reproduction-20260802/` 由 `report.json` 和文件级 SHA-256 manifest 封存，独立 `verify` 返回 `passed`。此前默认旅程 PASS 已归档为 `evidence/clean-windows-reproduction-default-journey-pass/`；失败发现目录只作内部缺陷追踪，不进入评委最终证据。
- 自动回归：M4 明确文件清单连同提交包、SPA fallback 和运行启动器测试共 `47 passed, 5 warnings in 9.17s`。警告仅为 FastAPI/Starlette 生命周期弃用提示。
- 声明边界：`independent_third_party_machine=false`；这是同机全新解压和独立 venv 的可复现证据。`trusted_local` 没有容器隔离，只适合本机研究和现场演示；高风险或不可信代码仍应使用 Docker。M4 指标继续固定 `human_annotators=0`、`publication_authorized=false` 和 `independent_human_validation_missing`。
- 时间：2026-08-02（Asia/Shanghai）。
