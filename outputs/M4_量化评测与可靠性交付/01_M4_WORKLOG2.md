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
