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
