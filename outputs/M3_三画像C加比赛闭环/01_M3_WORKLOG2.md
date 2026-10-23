# EduMatrix M3 WORKLOG2

本日志按实际完成顺序记录 M3 每组代码、测试、限制和下一步。历史记录只追加，不覆盖。

## WL2-M3-20260726-001 - M3 范围冻结与阶段进入例外

- 状态：`IN_PROGRESS`
- 用户指示：用户明确要求继续 M3，因此开始比赛加速轨的 M3 子集；该指示不构成 M2 自动验收通过证据。
- M2 遗留：M2-012 保持 `PENDING`。全量 pytest 首个实际失败为 `tests/test_animation_integration.py::TestAnimationResources::test_animation_for_specific_knowledge`，原因仍在诊断；浏览器专用控制工具当前未暴露，未执行浏览器 E2E。
- M3 范围：三组差异画像、四角色协同、证据辩论、匹配报告、动态决策和一个“调优混合检索并保持数据隔离”的代表性交互技能工件；不扩张为完整阶段 10 多媒体平台。
- 首组工作：以 M0 `baseline_profiles.json` 为唯一画像金标输入，冻结同一 JOB-05/KP-11~13 目标下的六维领域能力区间和资源适配策略，事实与安全标准保持一致。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-002 - 三组金标画像、能力区间与适配策略

- 状态：`PASS`（M3-001）
- 金标输入：只读取 M0 `datasets/baseline_profiles.json`，严格要求 `baseline-profile-0.1`、`P2-SYNTHETIC` 和 beginner/theory/advanced 三个有序 profile ID；数据集变化 fail-closed。
- 领域画像：冻结理论理解、工具熟练、任务执行、故障排查、规范意识和迁移能力六个区间，每个区间保留金标画像证据引用和置信度，不输出伪精确单点。
- 资源策略：三组分别采用 high/medium/low 脚手架、guided/bounded/open 任务开放度，以及识别应用/应用调试/诊断决策题目重点；每项差异反查背景、证据、偏好或目标字段。
- 不变标准：三组共享 JOB-05 和 KP-11/12/13，事实标准与安全标准均固定 `unchanged`，不因零基础降低正确性、隔离或岗位验收要求。
- 聚焦验证：`python -m pytest -q tests\test_m3_profiles.py` 为 `3 passed in 0.13s`。
- 修改文件：`app/m3_profiles.py`、`tests/test_m3_profiles.py`、M3 索引和本日志。
- 下一步：持久化三个不可变画像快照并装配同目标 verified 上下文。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-003 - 三画像持久快照与同目标 verified 上下文

- 状态：`PASS`（M3-002）
- 持久对象：三个稳定合成学习者、三个课程成员关系和三个不可变画像快照；快照保存 M0 数据哈希、合成标记、六维能力、适配策略、证据和规划约束。
- 同题边界：三个上下文只在 owner/profile snapshot/trace 上不同，课程、active domain version、JOB-05、KP-11~13 和 source_ref 集合完全一致，可用于公平对照。
- 上下文兼容：verified 装配支持快照显式冻结 `focus_knowledge_point_ids`，同时继续兼容 M2 `weak_knowledge_point_ids`；避免把高级画像的共同训练目标错误标成薄弱点。
- 安全与可复现：重复初始化不新增对象；快照内容被修改后拒绝静默覆盖；跨 owner 使用他人快照返回 `profile_snapshot_forbidden`。
- 聚焦验证：`tests/test_m3_baseline.py + tests/test_m2_context.py` 为 `10 passed in 4.39s`；M3 画像契约另有 `3 passed`。
- 修改文件：`app/m3_baseline.py`、`tests/test_m3_baseline.py`、`app/m2_context.py`、M3 索引和本日志。
- 下一步：建立诊断、生成、审核、决策四角色契约和正式 agent_run 轨迹。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-004 - 四角色契约与持久协同轨迹

- 状态：`PASS`（M3-003）
- 角色边界：诊断、领域生成、证据审核和决策调度分别具有 registry ID、版本、职责、必需输入、正式输出类型、允许工具和禁止动作；现有多个实现 Agent 可归入四类业务责任但不能混淆审计责任。
- 持久任务：新增 M3 四角色 collaboration capability，复用 generation task、四个 task step、连续 task event 和 agent_run；三组合成画像各有独立任务与 trace。
- 执行规则：必须按诊断→生成→审核→决策依赖顺序运行；owner 越权拒绝；同角色启动重放复用原 run；四角色未完成不能结束任务。
- 输入最小化：步骤和 agent_run 只保存对象 ID、契约版本与 `content_included=False`，不保存画像正文、证据正文、Prompt 或密钥。
- 聚焦验证：`tests/test_m3_agents.py + tests/test_m3_baseline.py` 为 `6 passed in 3.80s`。
- 修改文件：`app/m3_agents.py`、`tests/test_m3_agents.py`、M3 索引和本日志。
- 下一步：让领域生成角色输出三画像差异化的正式三类资源及资源集 manifest。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-005 - 三画像差异化正式资源

- 状态：`PASS`（M3-004）
- 专用契约：M3 lesson/lab_guide/tiered_quiz 在 M2 严格内容 Schema 上增加 profile-bound personalization evidence，包含难度带、脚手架、术语密度、步骤粒度、提示策略、开放度、题目重点和金标理由引用。
- 生成边界：领域生成器只接受原始 JSON Bundle，只能引用 verified KP/source；画像策略来自不可变快照，不接受调用方自由声明；高脚手架强制至少四个短实操步骤，开放进阶资源必须含 evaluate/create 任务。
- 正式输出：每个画像保存三类 artifact/version 和一个 `m3_personalized_resource_set` manifest，contains 关系保留子资源身份；相同内容重放复用原版本，部分集合或不同内容重放 fail-closed。
- 差异证据：自动测试实际得到三套不同讲义正文、`4/3/2` 实操步骤和 `L0-L1/L1-L2/L2-L4` 难度带；差异来自冻结 profile strategy，不是随机字符串比较。
- 不变与脱敏：三套资源均保存 `fact_standard=unchanged`、`safety_standard=unchanged`；tiered_quiz 正式服务端版本含答案，M1 学习者投影继续移除 answer_key/explanation。
- 聚焦验证：`tests/test_m3_resources.py + tests/test_m3_agents.py` 为 `5 passed in 3.67s`。测试使用 profile-aware 结构化替身，只证明契约、差异规则和持久化，不宣称真实模型内容质量。
- 修改文件：`app/m3_resources.py`、`tests/test_m3_resources.py`、M3 索引和本日志。
- 下一步：实现原子事实 Prover/Challenger/Judge 辩论、保守裁决和停止规则，并与正式版本/审核角色绑定。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-006 - 原子事实 Prover/Challenger/Judge 辩论审核

- 状态：`PASS`（M3-005）
- 原子输入：每项 claim 绑定正式 artifact version、产物位置和允许 source_ref；产物或来源越出当前 M3 任务范围时在审核前 fail-closed。
- 职责分离：Prover 保存支持状态、证据与适用条件；Challenger 独立保存不支持、版本冲突、遗漏条件、危险步骤、难度不符或内部矛盾；Judge 输出 keep/revise/reject/uncertain、理由、证据和置信度。
- 停止规则：keep/reject 视为本轮解决，uncertain 以 `evidence_insufficient` 保守停止，revise 可进入下一轮并受 1~4 轮上限约束；不会无限循环或把不确定内容自动放行。
- 持久证据：最终结论写 DBClaimCheck，每轮三方输出分开写 DBDebateRound，汇总写 `m3_debate_report` artifact/version；审核角色输出绑定报告，原生成版本不被覆盖。
- 指标边界：报告固定 `semantic_quality_metric_assessed=False`。测试使用确定性审核替身证明流程、范围和状态，不宣称真实模型语义准确率、幻觉率或专家事实签字。
- 聚焦验证：`tests/test_m3_debate.py + tests/test_m3_resources.py` 为 `4 passed in 3.32s`。
- 修改文件：`app/m3_debate.py`、`tests/test_m3_debate.py`、M3 索引和本日志。
- 下一步：建立六维资源难度、推荐区间、盲区、正式路径版本和实际表现的数据不足表达，生成个人匹配报告。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-007 - 个人学情与资源匹配报告

- 状态：`PASS`（M3-006）
- 能力与推荐：由六维能力区间的中点和平均区间宽度计算推荐难度区间，保留算法版本、能力中点和不确定性，不输出模型临时编造的单点能力分。
- 资源难度：对 lesson/lab_guide/tiered_quiz 分别保存先修深度、概念复杂度、操作步骤、工具复杂度、认知负荷和开放度；聚合值只用于与区间定位，六维原值继续可审计。
- 盲区表达：KP-11~13 分别标记未接触、证据不足、疑似薄弱或当前未提示；M0 合成先验不会被升级为“确认薄弱”或“已掌握”。
- 路径边界：为每个金标画像创建正式、不可变的 benchmark plan version，但 plan 保持 draft，报告固定 `plan_execution_authorized=False`，不冒充用户确认路径。
- 表现曲线：只读取当前 trace 的 learning event；无事件时 points 为空并显示 `no_valid_events`，有操作观察时追加报告版本并显示 `observed_not_mastery`，不覆盖旧版本。
- 聚焦验证：`tests/test_m3_matching.py + tests/test_m3_debate.py` 为 `4 passed in 3.75s`。三报告的能力中点按 beginner/theory/advanced 递增，三类资源均落在适配或可接受挑战范围。
- 修改文件：`app/m3_matching.py`、`tests/test_m3_matching.py`、M3 索引和本日志。
- 下一步：根据版本化规则和正式事件生成补证据、降维、补先修、维持、进阶候选，保存 proposed decision，不自动确认重大变化。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-008 - 规则优先的动态决策候选

- 状态：`PASS`（M3-007）
- 规则输入：只读取正式 matching report version、debate report 和当前 trace learning event；规则版本固定 `m3.dynamic_decision.rules.v1`，accuracy、求助、连续失败、主观难度、隐藏验收和延迟复测分别保留。
- 证据状态：明确区分 `insufficient/conflicting/observed/delayed_confirmed`；无事件或高正确率同时高求助/高难度时优先补证据，不强行进阶。
- 候选比较：每次同时返回补证据、降维解释、补先修、维持巩固和进阶挑战，分别列理由、证据 ID、负担范围、路径变化、资源成本、风险和确认要求。
- 选择规则：测试覆盖 beginner 低表现→补先修、theory 低表现→降维、advanced 隐藏+延迟强证据→进阶，以及不足/冲突→补证据。
- 执行边界：DBDecisionRecord 固定 `status=proposed`、`user_confirmed=False`、`mastery_update=none`、`after_version_id=None`；重大路径候选只记录 pending_confirmation，不执行用户未确认的变化。
- 聚焦验证：`tests/test_m3_decisions.py + tests/test_m3_matching.py` 为 `4 passed in 4.14s`。
- 修改文件：`app/m3_decisions.py`、`tests/test_m3_decisions.py`、M3 索引和本日志。
- 下一步：实现 JOB-05 代表性交互工件的受限 manifest、确定性状态机、隐藏验收和证据回流。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-009 - 代表性交互技能工件、隐藏验收与证据回流

- 状态：`PASS`（M3-008、M3-009、M3-010）
- 工件契约：正式 `interactive_skill_artifact` manifest 绑定 JOB-05、课程/领域/KP/source、四个受控参数、10 个公开 query 场景、状态/动作/故障、owner-only 权限和隐藏检查器版本。
- 安全边界：运行模式明确为 `safe_deterministic_simulation`，安全等级为 `no_external_code_or_network`；只允许参数、指标、检索日志、证据、故障、提示和验收七类组件，Strict Schema 拒绝 remote_script 等任意脚本字段，并提供静态降级说明。
- 状态运行时：session 本身是正式 artifact，每次动作追加不可变 version 和 learning event；configure/run/evaluate/diagnose/rerun/submit/reset 转换受规则约束，动作使用稳定 idempotency key，重放不重复版本或事件。
- 参数与故障：keyword/vector 权重必须合计 1，top_k/阈值受边界约束并真实改变公开 recall/ranking/latency；版本错配等故障必须选择正确恢复动作后才能 rerun，过滤开关不暴露为可修改参数。
- 隐藏验收：只返回 passed_count/total/failure_categories/checker_version，不暴露隐藏期望值；结果绑定 checker hash 和工件版本。
- 证据等级：隐藏通过且无提示为 SE-4，使用提示最高 SE-2；写 learning event 和 profile evidence，说明只支持该任务版本的技能证据，不代表长期掌握或岗位胜任。
- 闭环回流：提交事件触发 matching report 新版本和新的 proposed decision；所有记录保持 `mastery_update=none`、`user_confirmed=False`。
- 聚焦验证：`python -m pytest -q tests\test_m3_interactive.py` 为 `5 passed in 4.27s`，覆盖白名单、快乐路径、幂等、重置、错误恢复、隐藏验收、SE-4/SE-2 和回流。
- 冷启动补充：用户确认 `edumatrix.db` 为本地生成且不入 Git；真实 FAISS 需要依次运行 `scripts/collect_ml_multimodal_data.py --download` 与 `scripts/ingest_to_faiss.py`。当前安全模拟不冒充真实 FAISS，M3-012 将此列为真实检索复现前置条件。
- 修改文件：`app/m3_interactive.py`、`tests/test_m3_interactive.py`、M3 索引和本日志。
- 下一步：增加认证 API 和三画像/四角色/辩论/匹配/交互前端，并执行专项与构建验证。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-010 - 认证 API、三画像竞赛工作台与浏览器验收

- 状态：`PASS`（M3-011）
- 认证边界：新增 `/api/v1/m3` 路由，创建任务只接受金标 `profile_id` 和幂等键；服务端将不可变画像绑定到当前 JWT owner，后续从正式 `m3.context.verified` 事件恢复上下文，跨 owner 返回 403。
- 流程接口：覆盖任务创建/恢复、四角色运行、三类资源、原子事实辩论、匹配报告、proposed decision、交互 manifest/session/action/evidence 和脱敏 bundle；学习者输出移除 quiz 答案/解释、Prompt、密钥和画像理由。
- 多用户修复：基准 plan/version ID 增加 owner 稳定作用域，消除不同用户选择同一画像时的 `benchmark_plan_conflict`，同一 owner 仍幂等复用。
- 前端：新增 `/competition-loop` 工作台与导航，包含三画像差异、四角色轨、lesson/lab/quiz、辩论裁决、推荐区间/盲区、proposed decision、参数实验、故障诊断、隐藏验收、提示和技能证据状态。
- 浏览器：1440x900 桌面和 390x844 移动均渲染；移动页面宽度 `390/390`、页头 `286/286`、内部溢出列表为空；键盘 Enter 刷新后焦点仍在刷新按钮，进阶画像和诊断完成状态可从服务端恢复；控制台无 error/warning。
- 浏览器边界：当前 deterministic provider 在真实生成端点返回非 JSON；浏览器任务停在诊断完成、领域生成待执行，并显示 `M3 generator did not return raw JSON`。这证明失败可见和恢复，不证明真实模型内容质量或完整业务 E2E。
- 聚焦验证：全部 M3 为 `25 passed, 5 warnings in 15.19s`；M2 回归 `31 passed`；M1 回归 `44 passed`；前端生产构建通过。API 测试的生成/审核使用结构化替身。
- 修改文件：`app/m3_api.py`、`app/m3_matching.py`、`app/main.py`、`tests/test_m3_api.py`、`frontend/src/api/m3.js`、`frontend/src/api/index.js`、`frontend/src/router/index.js`、`frontend/src/App.vue`、`frontend/src/views/M3CompetitionLoop.vue`、M3 索引和本日志。
- 下一步：配置严格 JSON 模型并准备真实 FAISS/媒体资源，完成三画像真实浏览器全链路与全量门禁。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-011 - M3 自动验收审计与已知限制

- 状态：`PENDING`（M3-012）
- 产物：生成 `02_M3自动验收报告.json` 与 `03_M3已知限制.md`，逐项记录通过、替身边界、浏览器证据、外部前置条件和退出授权。
- 全量结果：`254 passed, 9 failed, 6 warnings in 57.41s`。失败分布为 6 项动画目录/视频、1 项 VisRAG patch 图片、1 项 M0 manifest 字节不匹配、1 项项目 `.venv` 解释器不匹配。
- 真实检索：未运行教材下载与 FAISS ingestion；交互工件继续明确为安全确定性模拟，不把模拟指标写成真实检索性能。
- 退出审计：三画像、四角色、个性化资源契约、辩论、匹配/决策、交互工件、认证前端与响应式浏览器证据已具备；配置模型真实闭环、真实 FAISS 和全量回归未满足，故 `stage_exit_authorized=false`。
- 下一步：M3-012 保持 `PENDING`，不自动进入 M4。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-012 - 冷启动实跑与 FAISS 假阳性防护

- 状态：`PENDING`（M3-012）
- 冷启动实跑：执行 `python scripts/collect_ml_multimodal_data.py --download`。GitHub `ls-remote` 可达，但多个仓库的 pack/blob 传输返回 128 或长时间无进展；GitHub 官方 codeload 探测成功下载 `890346` 字节，平均仅约 `26 KB/s`，按候选池体量不适合在本轮继续全量下载。
- 采集器加固：仓库先克隆到隐藏 `.partial` 目录，完成后原子发布；已存在但无有效 `HEAD` 的目录不再静默跳过；失败自动清理 partial，保留 stderr 供事件审计，并增加低速保护。
- 摄取边界：`ingest_to_faiss.py` 改为仓库相对路径，只扫描 `data/raw`，排除 `data/uploads`、既有索引、`.git` 和 `.partial`；本轮真实执行得到 `0 files -> 0 chunks`，退出码 1，未写入空索引，不宣称 FAISS 成功。
- 跨平台修复：M0 manifest 测试改用生产代码相同的规范化字节，Windows CRLF 不再造成伪失败。
- 验证：冷启动/基线聚焦 `16 passed`，M3 全集 `31 passed, 8 warnings in 15.30s`；全量 `261 passed, 8 failed, 6 warnings in 55.11s`。剩余失败为 6 项动画、1 项 VisRAG patch 和 1 项缺少项目 `.venv`，M0 manifest 失败已消除。
- 数据清理：仅删除本轮失败 clone 产生的残缺 Git 元数据/partial 和 codeload 探测 ZIP；`edumatrix.db` 与用户数据未改回、未删除。
- 退出结论：真实教材和 FAISS 索引仍未生成，严格 JSON 模型浏览器闭环仍未完成；`stage_exit_authorized=false`，不进入 M4。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260726-013 - 项目解释器门禁与 VisRAG 伪证据清理

- 状态：`PENDING`（M3-012）
- 项目运行时：按 `start.bat` 和 `runtime_preflight.py` 契约创建本地 `.venv`，使用项目解释器验证 FastAPI、Uvicorn、Matplotlib、Pandas、scikit-learn；preflight 为 `PASS`，spawn worker/启动器测试 `5 passed`。`.venv` 已被 `.gitignore` 排除。
- 资产溯源审计：Git 历史、`origin/main` 和仓库脚本均不包含预期 7 张 patch 的权威文件或生成来源；动画测试要求至少 20 个知识点/60 个真实视频，现有 crawler 依赖外部视频平台、`yt-dlp`、下载体量与版权选择，不能生成占位资源。
- VisRAG fail-closed：删除在无本地图像时自动注册 `教材图像切片 PDF:P45` 等 7 条硬编码证据的回退；现在只接受 image modality、非空 source 且 `raw_image_ref` 确实位于 `data/patches` 的证据。多模态响应不得返回悬空 slide reference。
- 聚焦验证：VisRAG/多模态聊天 `11 passed`；非资产型 FAISS 持久化 `4 passed, 1 deselected`；冷启动 `6 passed`。
- 全量验证：使用 `.venv` 得到 `265 passed, 7 failed, 6 warnings in 55.02s`。运行时失败已消失，剩余只有 6 项动画部署和 1 项 patch 部署断言。
- 模型配置审计：`/api/health` 报告 `llm_provider=deterministic`、`llm_model=deterministic`、endpoint 为空、API key 未配置；进程环境也没有 EduMatrix/OpenAI/Ollama 模型配置。真实 JSON 模型闭环需要外部端点、模型和凭据。
- 退出结论：没有伪造 patch、视频、模型质量或 FAISS 证据；M3-012 保持 `PENDING`，不进入 M4。
- 时间：2026-07-26（Asia/Shanghai）。

## WL2-M3-20260801-014 - 真实 FAISS、结构化模型门禁与 E2E 诊断

- 状态：`IN_PROGRESS`（M3-012 未关闭）。
- 真实 FAISS：加载 `licensed_ml_course.faiss`，365 个向量、`IndexFlatIP`、512 维 BGE embedding；决策树查询 Top-3 均命中 MIT 来源，证据写入 `evidence/browser-e2e/report.json`。该索引是合法机器学习课程检索基础设施证据，当前不冒充 M3 RAG 任务的语义来源。
- 真实模型：确认当前 `.env` 的 OpenAI-compatible structured provider 可连通；真实 E2E 使用隔离数据库、三注册用户和 Chromium，不记录端点或密钥。
- 首轮真实失败：模型响应从 JSON 对象开始但追加非 JSON 解释；增加公共严格 JSON 解析器、原生 `response_format=json_object`，围栏外额外内容仍拒绝。
- 第二轮真实失败：JSON 可解析但 `tiered_quiz.pass_rules` 未覆盖 foundation/application/advanced；增加一次 Schema 反馈重生成，不放宽 Pydantic 契约。
- 第三轮真实失败：响应以尾逗号结束；将解析错误纳入一次反馈重生成，禁止自动修补不完整 JSON。
- 工程修复：M2/M3/M5 结构化入口统一使用公共解析器；真实验收环境设置 `EDUMATRIX_DISABLE_LLM_FALLBACK=1`，防止确定性后备掩盖真实模型失败；E2E 请求超时提高到 180 秒，报告错误脱敏。
- 聚焦验证：结构化 JSON、M2/M3/M5 回归 `26 passed, 5 warnings`；M3 资源重试专项 `15 passed`。
- 当前缺口：真实三画像资源、三组辩论、刷新/重启、越权和交互工件尚未在同一次 E2E 中全部通过；外部审批服务本轮返回 502，未绕过重试。
- 下一步：审批服务恢复后重新执行 `scripts/e2e_m3_competition_loop.py`；只有三画像资源差异、四角色辩论、交互隐藏验收和持久化恢复全部有报告证据，才将 M3-012 改为 PASS。
- 时间：2026-08-01（Asia/Shanghai）。

## WL2-M3-20260801-015 - 严格 JSON 重试后的真实模型复验

- 状态：`BLOCKED`（M3-012 未关闭，不进入 M4）。
- 客户端加固：结构化提示请求 OpenAI-compatible `response_format=json_object`；真实验收设置 `EDUMATRIX_DISABLE_LLM_FALLBACK=1`；空 content 进入已有退避重试；Schema/解析错误最多反馈重生成一次，拒绝自动补逗号、填缺失字段或截取正文。
- 真实复验结果：模型仍先后出现缺少三层 `pass_rules`、空响应、截断到非 JSON 字符等情况；即使增加精确字段提示和重生成，三画像资源未完成一次稳定返回。
- 本地验证：全量 `350 passed, 6 warnings`；M3 资源/解析专项 `15 passed`；前端 `vite build` 成功（3102 modules transformed）。
- 结论：代码契约、失败可见性和退避已具备，但当前 `.env` 指向的外部模型/别名无法提供可复现的 M3 结构化产物。该阻塞不是本地代码测试失败，也不能用 deterministic fallback 代替真实证据。
- 解除条件：将 `.env` 的模型换成稳定支持 JSON Object/结构化输出且有足够输出额度的模型，或提供同一端点下可用的正式模型名；随后从 `scripts/e2e_m3_competition_loop.py` 重新执行，不需要重做本地修复。
- 时间：2026-08-01（Asia/Shanghai）。

## WL2-M3-20260802-016 - 真实模型再测、拆分降级与空响应阻塞

- 状态：`BLOCKED`（M3-012 未关闭，不进入 M4 正式发布）。
- 今日复验：继续使用 `.env` 配置的 `deepseek-v4-flash`、隔离数据库、真实 365 向量 FAISS、本机 FastAPI/Vite 和无头 Chromium；未启用 deterministic fallback。
- 第一轮结果：完整 Bundle 生成在浏览器 180 秒请求窗口内未返回。该表现不同于此前立即暴露的 JSON 截断，但仍无法形成第一个画像的正式资源产物。
- 可靠性改进：完整 Bundle 最多尝试两次；若仍失败，按 `lesson`、`lab_guide`、`tiered_quiz` 三个较小严格 Schema 分别生成，再由服务端组合并执行原有画像一致性、来源范围、事实、安全和结构总校验。新增回归覆盖完整 Bundle 失败后的小对象降级，禁止自动补字段、修尾逗号或接受额外正文。
- 第二轮优化：解析级截断不再重复请求同一个大 Bundle，而是立即进入小对象降级；可解析但 Schema 不合格时仍保留一次反馈修复。E2E 单请求窗口提高到 420 秒，只用于容纳串行小对象调用，不改变底层模型失败判定。
- 第二轮真实结果：第一个画像的 `/generate` 在约 259 秒后返回 422；明确错误为 `structured model returned an empty content field`，底层退避重试 3 次仍失败。说明当前模型别名不仅对大对象有截断问题，对较小严格 JSON 也存在连续空响应，不能靠继续拆分稳定解决。
- 新鲜验证：资源/结构化解析专项 `15 passed`；M2/M3/M5 聚焦回归在第一轮改动后为 `53 passed, 5 warnings`。真实 FAISS 查询继续通过，但三画像、辩论、交互、刷新/重启和越权未在同一次真实 E2E 中完成。
- 历史核对：本日志早期已明确 API 和资源测试使用 `ProfileAwareFakeLLM` / deterministic reviewer，只证明契约、差异和持久化，不宣称真实模型质量；原浏览器记录也明确 deterministic provider 在生成端点失败。因此“原先测试正常”与本次真实模型失败不矛盾，M3-012 历史上从未由真实模型关闭。
- 安全检查：E2E 报告中的 Authorization 已脱敏；失败请求使用隔离测试账户，未把 `.env` 密钥写入报告。控制台曾显示的临时 JWT 不作为证据保存。
- 解除条件：将模型改为稳定支持 JSON Object、足够输出上限且能持续返回非空 content 的正式模型，再从 `scripts/e2e_m3_competition_loop.py` 重跑。当前模型停止继续试错，避免无效消耗。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M3-20260802-017 - 思考模式根因闭环与真实 M3 E2E 通过

- 状态：`PASS`（M3-012 关闭，允许进入 M4 实施与正式评测准备）。
- 协议探针：同一端点、模型和 API Key 的普通输出及 JSON Output 均返回 200。响应包含 `reasoning_content`，证明模型默认启用思考；显式发送 `thinking={"type":"disabled"}` 后仍返回有效 JSON。
- 根因 A/B：使用真实 `lesson` Schema 时，默认思考耗时 70.17 秒、completion 8105 tokens，其中 reasoning 6664 tokens，逼近项目原 `max_tokens=8192`；关闭思考后耗时 8.06 秒、completion 1014 tokens、JSON 有效。此前空 content 是思考耗尽共享输出预算，不是模型不支持 JSON。
- 正式配置：新增兼容性变量 `EDUMATRIX_LLM_THINKING_MODE`，仅在值为 enabled/disabled 时发送 provider thinking 参数；当前 DeepSeek 配置为 disabled，`EDUMATRIX_LLM_MAX_TOKENS=16384`。其他 OpenAI-compatible provider 留空即可保持原协议。
- 单画像冒烟：禁用 deterministic fallback，实际客户端断言为 `deepseek-v4-flash / 16384 / disabled`；24.19 秒生成 lesson、lab_guide、tiered_quiz，完整严格 Bundle Schema 通过。
- 真实 E2E：隔离数据库、本机 FastAPI/Vite、无头 Chromium、真实模型和 365 向量 MIT FAISS 同时运行，145 秒完成。三画像的难度/脚手架/开放度及三类工件哈希均有差异，来源范围一致，三组生成和辩论全部完成。
- 交互与安全：故障注入和恢复成功，隐藏验收 5/5、SE-4、mastery 不自动更新；浏览器刷新与后端重启后状态恢复；跨 owner 任务与 Bundle 均返回 403；桌面三画像、交互、重启和移动端共 6 张截图落盘。
- 兼容修复：M3 测验学习者投影现在使用 M3 严格 Schema，保留标题、分层题目和可展示画像，同时删除 answer_key、explanation 与内部 rationale_refs；malformed 测验仍 fail-closed。
- 审核加固：辩论 reviewer 接收完整 `DebateRoundOutput` JSON Schema；未知枚举或解析错误最多反馈重生成一次，连续非法则严格失败，不做静默映射。
- 证据：`outputs/M3_三画像C加比赛闭环/evidence/browser-e2e/report.json` 为 `result=passed`，报告不含 Bearer、JWT 或 API Key 值。
- 最终门禁：全量后端 `357 passed, 6 warnings in 75.68s`；前端生产构建通过，`3102 modules transformed`。警告为既有 FastAPI/Starlette 弃用提示、PyTorch tensor 转换提示和前端大 chunk 提示，不影响本次 M3 退出判定。
- 时间：2026-08-02（Asia/Shanghai）。
