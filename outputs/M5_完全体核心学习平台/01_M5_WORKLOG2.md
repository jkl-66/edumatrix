# EduMatrix M5 WORKLOG2

## WL2-M5-20260803-050 - 全量顺序回归修复、显式视觉证据与比赛范围退出

- 状态：`PASS（M5-012）`；M5 总体更新为 `COMPETITION_READY / FULL_SCOPE_DEFERRED`。本批完成比赛退出审计，不把企业完全体延期项伪装为已完成。
- 顺序回归：首次全量套件为 `532 passed, 2 failed, 6 warnings`。图谱单例在课程播种前初始化后未刷新，导致完整套件顺序下 canonical course facts 为 0；VisRAG 在显式空 seed 时注入内置图片，违反空证据真实性契约。
- 图谱修复：课程发布签名变化时刷新 canonical 图谱事实，保持 builtin 和 canonical 来源门禁；新增缓存图谱晚播种回归，避免测试顺序或启动顺序改变 verified facts。
- 视觉证据修复：移除 VisRAG 构造器隐式 fallback。新增 `data/evidences.json` 显式声明 7 张真实课程图像，记录来源、锚点、许可证和 SHA-256；加载时复核实际文件哈希。`.gitignore` 只放行这 7 张图片和证据清单，不放行任意上传图片目录。
- 自动验证：最新补丁聚焦 `18 passed, 5 warnings in 2.91s`；完整项目回归 `536 passed, 6 warnings in 98.89s`，收集与失败均为 0。Vue 生产构建转换 3106 modules 并成功，仅保留既有 `StudentAnalysis` 大 chunk 提示。`git diff --check` 无补丁错误，仅有 Windows LF/CRLF 提示。
- 退出证据：复核学习工作台、错因复测、上下文教师、来源回跳和图谱治理五组浏览器证据，共 22 张截图；各 manifest 无 hash 错误，SQLite integrity 均为 `ok`。退出报告位于 `02_M5比赛范围退出审计.md`。
- 分类结论：M5-004 至 M5-011 均达到 `COMPETITION_PASS / FULL_SCOPE_DEFERRED`；M5-012 为 `COMPETITION_PASS`。长期记忆、全量 Gateway、通用 worker、全题型考试、完整媒体上下文和企业外部集成继续保留在全量计划，不阻塞比赛主线。
- 真实性边界：纯中文对英文正文语义仍为 `DEFERRED_COMPETITION`，不得宣称达标；自动测试与同机浏览器证据不等于真人独立验收。本批没有外部模型调用、数据外发或密钥读取。
- 下一步：M5 不再常规重做，主线转入 M6 教师治理与企业培训比赛子集，优先闭合教师任务/干预和岗位差距/培训批次/技能证据签核的评委可操作旅程。
- 时间：2026-08-03（Asia/Shanghai）。

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

## WL2-M5-20260803-049 - 纯中文对英文正文诊断与比赛范围延期决策

- 状态：`DEFERRED_COMPETITION（M5-003 跨语言正文语义）`；M5-003 进入 `COMPETITION_PASS / FULL_SCOPE_DEFERRED`。本批没有因中文文件名、中文课程包装或 hash 碰撞出现召回就宣称“多语种语义检索已完成”。
- 赛题价值判断：赛题 P0 要求至少一个垂直领域知识库、三画像、多 Agent 分析—生成—校验—决策、三类资源、反馈闭环、体验和可运行交付；没有强制跨语言检索。当前 M0 中文原创 RAG 课程和精选机器学习课程已能在中文界面完成课程隔离、检索、可信引用回跳和图谱来源治理。继续连续试验大型 embedding 对 30 分完整性、25 分创新、15 分体验和 30 分实用价值的边际收益低于闭合学生/教师可操作旅程，因此按用户最新“比赛可展示价值优先”目标延期，不删除全量计划。
- 正文-only 冻结集：新增 `cross_language_body_evaluation.json`，8 条纯中文问题均不含英文术语，覆盖 Python 字典、数组变形、表格选择、相关性、数据准备、学习范式、决策树和主成分分析。诊断只读取每章“精选教材内容”后的英文正文，明确排除中文标题、本章目标、课程名、知识点标签和来源元数据。
- 可重复工具：新增 `scripts/evaluate_cross_language_body_retrieval.py`，支持 hash 和本地 SentenceTransformer，E5 可启用官方 `query:`/`passage:` 前缀；逐例报告返回目标章节 rank、分数和最高章节。未知文档、缺正文标记、非法窗口或未知后端 fail-closed。脚本只离线读取本地模型与冻结课程，不调用外部服务。
- 真实结果：当前 hash 为 Recall@3 `5/8`，`paraphrase-multilingual-MiniLM-L12-v2` 为 `5/8`，`multilingual-e5-small` 为 `6/8`，三者均未达到冻结门槛 `8/8`。报告位于 `evidence/cross-language-body-evaluation-20260803/`。hash 结果存在低维碰撞虚高，不可理解为跨语言语义能力；两个专用模型也存在章节吸附和错排，因此均未接入生产。
- 候选资产：本机缓存 BGE 中文模型约 92 MiB，诊断 rank 约 3—12；首个 MiniLM 下载因未限制 allowlist 连同多套 ONNX/OpenVINO 变体落盘，目录目前为本地试验资产且明显过大；E5 allowlist 下载约 491.58 MiB。二者都不是当前生产依赖、不得进入比赛能力声明或默认提交包。未经用户要求，本批不删除已下载文件；后续打包需显式排除 `data/models/` 或只在模型真正达标后制作许可和精简清单。
- 试错记录：首次诊断脚本直接把 NumPy 数组传给项目 `cosine_similarity`，因数组真值歧义导致两份模型报告未生成；显式转 tuple 后重跑成功。该问题只在新诊断工具，生产检索未受影响。模型仓库第一次下载超过 5 分钟无日志后按规则终止，检查发现标准权重已完整、额外变体仍在下载；未删除任何资产。
- 自动验证：跨语言诊断与课程评测聚焦 `9 passed in 8.09s`；全部 `test_m5_*.py` 加 M0 课程、M1 来源和结构化 JSON 扩大回归 `209 passed, 5 warnings in 28.36s`。新增测试固定元数据排除、hash 报告可重放、不达标不宣称 PASS 和未知相关文档拒绝。
- 对外边界：可以声明“中文界面可检索并定位英文预置教材，当前冻结混合问题集通过”；不能声明“纯中文对英文正文的独立跨语言语义检索已达标”。比赛版状态为 `COMPETITION_PASS / FULL_SCOPE_DEFERRED`，赛后恢复入口是替换为经冻结正文-only数据集验证通过的多语种 embedding，并重建索引、回归隔离/低置信/引用和打包许可证。
- 外部数据：联网只下载公开 Hugging Face 模型文件，没有上传课程、用户数据、密钥或 `.env`；模型评测完全离线。
- 下一步：按比赛可展示价值优先进入 M5 比赛范围退出审计，优先核对评委能否从知识库/画像进入上下文教师、看到多 Agent/个性化资源、完成反馈与动态决策并刷新恢复；将无真实企业环境或低展示价值的 M5 全量项分别标记 `FULL_SCOPE_DEFERRED`，不阻塞比赛版本。
- 时间：2026-08-03（Asia/Shanghai）。

## WL2-M5-20260803-048 - M0 完整课程冻结检索集与严格多文档召回

- 状态：`PASS（M5-003 / M0 全量检索子集）`，M5-003 总体仍为 `IN_PROGRESS`。本批把此前只有 1 条 M0 检索断言扩展为覆盖整门冻结课程的可复查问题集；不把 16 条离线案例宣传为真人问答质量评测或外部模型回答准确率。
- 冻结数据集：新增 `outputs/M0_阶段0基线与架构契约/datasets/course_retrieval_evaluation.json`，绑定 `course-rag-engineering-m0-0.1.0`。12 条可回答题覆盖 9/9 文档，其中 9 条逐文档题覆盖课程范围、许可、解析、分块隔离、混合检索、引用拒答、画像资源、指标和恢复，3 条跨章节题覆盖可信闭环、评测闭环和个性化技能验收；4 条域外题覆盖医疗处方、股票预测、基础模型训练及未提供的 Kubernetes 部署细节。
- 评测器泛化：`course_retrieval_evaluation.py` 根据受支持 manifest 结构选择 M0 或 curated 加载器，保持原精选课程默认参数和行为。未知 manifest fail-closed，不用路径或文件名猜测课程类型。
- 严格召回：旧评测对多文档 case 只要命中任意相关文档就算召回；现改为必须召回声明集合中的全部文档，并在逐例报告输出 `recalled_documents` 和 `missing_documents`。精选课程原有单文档题兼容不变；M0 三条跨章节题在 top-8 下缺失文档总数为 0。
- 评测结果：M0 可回答 `12/12`、Recall@8 `1.0`、域外拒答 `4/4`、拒答率 `1.0`，全部命中 canonical source_ref 定位字段。逐例来源、分数、允许词命中和缺失文档报告位于 `evidence/m0-course-retrieval-evaluation-20260803/report.json`，SHA-256 为 `778C9923D2B15303F8AF7160B3FFBA8B5D0B25DC1C342F0D558990344CB0AA80`。
- 自动验证：评测专项 `6 passed in 12.35s`；M0/M1 来源、精选课程、版本、引用与图谱直接因果 `43 passed, 5 warnings in 23.44s`；全部 `test_m5_*.py` 加 M0 课程、M1 来源和结构化 JSON 扩大回归 `206 passed, 5 warnings in 33.26s`。警告仍为既有 FastAPI/Starlette 生命周期弃用。
- 真实性边界：该报告验证冻结材料在当前本地混合检索实现中的课程内召回、定位和低置信拒答，不验证生成模型如何使用证据，也不等于随机真实用户分布。案例由项目团队构造，没有真人独立标注；top-8 是冻结口径，不可与其他 k 值直接混称。
- 外部数据：本批完全离线，未调用外部模型、未发送课程正文、用户数据、密钥或 `.env`。
- 下一步：继续 M5-003 唯一剩余检索边界，建立纯中文查询对英文精选课程正文的独立冻结集；先区分中文文件名/知识点元数据命中与正文语义命中，再决定当前本地 hash embedding 是否只能记为受限能力，或需要引入可离线交付的多语种 embedding。
- 时间：2026-08-03（Asia/Shanghai）。

## WL2-M5-20260803-047 - 类型化知识图谱事实来源门禁

- 状态：`PASS（M5-003 图谱事实来源治理子集）`，M5-003 总体仍为 `IN_PROGRESS`。本批关闭“标签共现、规则抽取或模型自由三元组可能被当成已验证课程前置事实”的风险；不把派生浏览关系、候选关系或内置种子事实宣传为逐条外部专家审核结论。
- 类型化事实：新增 `GraphFactProvenance` 与 `GraphFact`，图谱输入分为 verified、candidate、rejected。verified 只接受 `builtin_seed`、`canonical_course` 和兼容低层显式调用的 `legacy_manual`；规则/模型抽取及 `CO_OCCUR` 只进入 candidate，不写 verified edge。
- canonical 来源门禁：课程事实必须同时绑定 `course_id`、`source_ref_id`、`evidence_id`、`content_hash` 和 `manifest_hash`。导入时从 canonical 数据库与冻结 manifest 播种课程 prerequisite；来源不完整、实体无法双侧对齐、关系类型不受支持或 hash 缺失时 fail-closed。最终形成 44 条 builtin seed 与 57 条 canonical course facts，共 101 条 verified facts；2 个课程外部 prerequisite 因目标不在当前 canonical 课程知识点集合而明确跳过，0 条不完整事实写入。
- 检索边界：`GraphRAG` 加载动态边时只接受 `PREREQUISITE_OF`，不再把 `CO_OCCUR` 当成课程前置关系参与扩展。上传文档抽取仍可保留候选供后续审核，但返回 `graph_candidate_relations`，且本次真实上传产生 1 条 candidate、`graph_edges_written=0`，verified 数量前后均为 101。
- API 与前端语义：图谱统计新增 `governance` 和 `canonical_seed`；知识库页展示“已验证事实 / 候选”数量。原标签共现区域改名为“知识关联视图”，说明“文档标签与共现仅用于浏览，不计入已验证课程前置事实”；ECharts 标题固定为“文档与标签派生关联 / 浏览关系 · 不代表已验证课程事实”，避免使用 Neo4j 名称暗示事实可信度。
- 自动验证：图谱治理与旧图谱专项 `69 passed`；全部 `test_m5_*.py` 加 M0 课程、M1 来源与结构化 JSON 扩大回归 `205 passed, 5 warnings`。Vue 生产构建转换 3106 modules 成功，仅保留既有 `StudentAnalysis` 大 chunk 提示；`git diff --check` 无补丁错误，仅有既有 LF/CRLF 提示。
- 浏览器证据：`evidence/graph-fact-governance-e2e-20260803/` 使用隔离 SQLite、deterministic provider 和本机无头 Chromium，验证候选上传不改变 verified 事实、57 条 canonical 事实保持、派生关系 Canvas 非空、桌面语义和 390×844 移动状态；SQLite `integrity_check=ok`，报告为 PASS。移动首轮目视发现治理状态在窄屏被省略，改为可换行状态组后重建并复跑，最终完整显示“101 条已验证事实 / 1 条候选”。
- 试错记录：首轮产品数据和截图均正确，但 E2E 使用 DOM 文本定位 ECharts Canvas 内标题而超时；改为验证可访问说明文案、Canvas 可见尺寸及采样颜色数，不修改产品逻辑迁就错误测试。最终 Canvas 为 894×500，采样至少 8 种非透明颜色。
- 真实性边界：builtin seed 是项目内置基础图谱，不具备本课程 source_ref/evidence；canonical 事实证明来源、版本和关系结构可追溯，不等同真人专家逐条确认其教学适切性。candidate 数量是待审核关系，不计入 verified；当前仍未证明 M0 全量检索问题集和纯中文对英文正文的跨语言语义质量。
- 外部数据：本批完全离线，未调用外部模型、未发送课程正文、用户数据、密钥或 `.env`。
- 下一步：继续 M5-003，先盘点并冻结 M0 完整课程的全量可回答/无证据问题集，补课程隔离、引用可定位和拒答评测；随后独立评估纯中文查询对英文精选课程的跨语言语义边界。两项均有可复查报告后再判断 M5-003 是否达到退出要求。
- 时间：2026-08-03（Asia/Shanghai）。

## WL2-M5-20260802-046 - 应用内可信 source_ref/evidence 精确回跳

- 状态：`PASS（M5-003 / S2-027）`，M5-003 总体仍为 `IN_PROGRESS`。本批关闭课程检索引用只能解析 canonical source_ref、不能在应用内定位可信片段的问题；不把整门课程图谱事实治理或跨语言检索误记为完成。
- 单一引用底座：继续复用现有 `source_documents`、`chapters`、`source_refs` 和 `course_documents`，未新增平行引用表或浏览器自定义引用记录。新增 `app/m5_source_locator.py` 从冻结课程正文与确定性 `chunk_document` 结果重建 evidence 位置；父子检索返回父块时，同一父块的子 evidence 绑定同一可信父块范围。
- 精确字符映射：定位只允许折叠空白，不允许改写正文字符；规范化文本同时保留到原正文的字符偏移映射。按文档顺序定位，无法重建时直接 `evidence_fragment_drift`，不再从文首宽松回搜。内置 2 门课程、21 份文档、582 个检索块全部可映射到非空原文范围，并逐项核对片段 SHA-256。
- 检索元数据：课程 ingestion 为每个 evidence 写入服务端计算的 `evidence_char_start`、`evidence_char_end` 和 `evidence_fragment_hash`，继续携带 canonical `source_document_id/chapter_id/source_ref_id/parser/content_hash`。客户端不能提交这些字段作为权威定位。
- 只读解析 API：新增 `GET /api/v1/source-refs/{source_ref_id}/evidence/{evidence_id}`，响应固定为 `m5.source-evidence-location.v1`。服务端重新验证课程访问、canonical source、课程文档、章节归属、整章范围、全文三方 hash、deterministic evidence ID 和片段 hash，再返回知识库文档 ID、课程/章节、字符范围与 quote。source_ref/evidence 错配或未知 evidence 返回 404，正文/hash/章节漂移返回 409，私有课程未授权访问返回 403。
- 前端深链：`/knowledge` 支持 `course_id`、`document_id`、`source_ref_id`、`evidence_id`。`Knowledge.vue` 先调用可信解析 API，再核对链接课程和文档，自动打开课程文档、滚动到片段并用纯文本 `<mark>` 高亮；刷新可恢复。范围拆分为 before/highlight/after 三个文本节点，不使用 `v-html`，避免把课程 Markdown 当作可执行 HTML。缺参、错配和非法 evidence 显示明确失败状态且不打开伪定位。
- 自动验证：课程引用、精选课程、课程检索评测、版本治理、M1 来源和 M0 课程直接因果组合 `37 passed, 5 warnings in 21.58s`；全部 `test_m5_*.py` 加 M0 课程、M1 来源与结构化 JSON 扩大回归 `200 passed, 5 warnings in 34.66s`。Vue 生产构建转换 3106 modules 成功，仅保留既有 `StudentAnalysis` 大 chunk 提示；`git diff --check` 无补丁错误，仅有既有 LF/CRLF 提示。
- 浏览器证据：`evidence/source-evidence-jump-e2e-20260802/` 使用隔离 SQLite、deterministic provider 和本机无头 Chromium，真实验证桌面范围 `0-1167` 高亮、刷新恢复、非法 evidence fail-closed、390×844 移动端高亮和 SQLite `integrity_check=ok`。4 张截图、后端日志、自包含数据库、结构化 PASS 报告和 SHA-256 manifest 已生成。首轮因测试登录态漏写 `edumatrix_student_id` 导致知识库正确返回 403；补齐与真实登录流程一致的身份键后通过，未放宽产品权限。
- 真实性边界：字符范围证明“该检索 evidence 可回到当前冻结正文中的确定片段”，不证明模型回答中的每个自然语言原子主张都已逐句支持，也不证明纯中文查询对英文正文的多语种语义质量。当前展示的是父块上下文，不宣称为最小句级引用。
- 外部数据：本批完全离线，未调用外部模型、未联网发送课程正文、用户数据、密钥或 `.env`。
- 下一步：继续 M5-003，补类型化知识图谱事实来源门禁。图谱节点/边必须区分 canonical 课程事实、解析候选、标签共现和模型候选；只有绑定可信 source_ref/evidence、通过结构校验和来源 hash 的事实才能进入可验证图谱，不能把现有 UI 标签共现或模型自由三元组写成课程事实。
- 时间：2026-08-03（Asia/Shanghai）。

## WL2-M5-20260802-045 - 冻结课程检索评测、课程隔离与可定位引用

- 状态：`PASS（M5-003 / S2-022、S2-023、S2-026、S2-029 精选课程子集）`，M5-003 总体仍为 `IN_PROGRESS`。本批只证明《机器学习基础与实践》冻结课程的离线检索闭环，不把 M0 全量问题集、跨语言语义检索、应用内回跳或图谱事实门禁误记为完成。
- 冻结数据集：新增 `retrieval_evaluation.json`，Schema 为 `edumatrix.course-retrieval-evaluation.v1`，绑定课程 ID、`course-ml-foundations-1.0.0` 和 top-8。12 条可回答问题逐章覆盖全部 12 个精选文档，每条声明相关文档与允许答案词；4 条无证据问题覆盖量子退火、联邦学习、扩散模型和图神经网络，期望原因固定为 `material_not_covered`。
- 课程作用域：`HybridRAGPipeline.retrieve` 新增向后兼容的 `course_id` 与 `allow_cross_course`。传入当前课程时，在评分前只保留该课程和当前 owner 的私有资料，其他公开课程不能挤占 top-k；只有显式 `allow_cross_course=True` 才扩大到其他已授权课程。另一用户私有资料始终排除。
- 检索与门控：课程作用域不再注入仅覆盖旧演示课程的默认 GraphRAG 池化路径；课程预过滤使用词法查询覆盖、Jaccard 和本地向量的组合评分，先取 `5×top_k` 子块，父块去重后严格截回 top-k。课程冻结集校准门槛为最高分 `>=0.20` 且查询词覆盖率 `>=8%`；全局旧检索继续使用原 `0.30` 门槛和原评分，未为新评测放宽旧产品门禁。
- 引用身份：课程 ingestion 为每个 RAG chunk 写入与数据库同源派生的 `source_document_id`、`chapter_id`、`source_ref_id`、parser、全文字符范围和内容 hash；专项测试逐条用 `DBSourceRef` 解析并核对 source/chapter/hash，不再依靠文件名伪造引用。精确字符选区仍属于 S2-027 后续批次。
- 评测器：新增 `course_retrieval_evaluation.py` 和 `scripts/evaluate_course_retrieval.py`。命令完全离线，输出结构化逐例来源、分数、允许答案词命中、引用可定位性、低置信度与总指标；证据写入 `evidence/course-retrieval-evaluation-20260802/report.json`。最终结果为可回答 `12/12`、Recall@8 `1.0`、无证据拒绝 `4/4`、拒绝率 `1.0`。
- 旧视觉恢复：兼容回归发现当前工作树缺少且 Git 未跟踪 `data/knowledge_base.json` / `data/evidences.json`，导致真实 `data/patches/pooling_2x2.png` 存在但 VisRAG 索引为空。现仅在种子无任何图片时注册该受控文件的 `IMG_PATCH_POOL_01` fallback，并继续经过路径位于 `data/patches` 且文件真实存在的 fail-closed 校验；旧图片召回、D-RAG 清洗和 retrieval evaluation 恢复。
- 域外拒答兼容：降低随机向量影响后，“李白”正确进入低置信度拒答。为保留旧用户提示，中文自然语言域外问题的“专业讲义”拒答附加学科大纲未覆盖说明；垃圾串 `xyz123` 仍返回原精确拒答文案，不会绕过幻觉硬拦截。
- 自动验证：课程评测专项 `5 passed in 8.88s`；课程直接因果 `34 passed, 5 warnings in 16.42s`；全部 `test_m5_*.py` 加 M0 课程、M1 来源和结构化 JSON 扩大回归 `194 passed, 5 warnings in 29.79s`；旧 VisRAG/文档过滤 `6 passed`；旧幻觉 `2 passed`；Swarm、推荐、多模态分别 `2 passed`、`5 passed`、`8 passed`。补丁检查无错误，仅有既有 LF/CRLF 提示。
- 测试编排问题：将 `unittest` 风格 Swarm/幻觉文件与多组 FastAPI 生命周期测试放进同一 pytest 进程会在 Windows 上不退出并遗留父/子 pytest；两次组合均在 124 秒终止且未记结果，残留进程已按命令行精确清理。各文件单跑与 M5 主扩大集合均正常退出；后续重型回归继续串行分组，不以强制延长超时掩盖资源清理问题。
- 语言边界：精选教材 manifest 明确 `language=en`。冻结问题以中文、英文和中英混合覆盖，但纯中文对英文正文的跨语言语义召回尚无独立证明；本地 hash embedding 不能代表真实多语种模型能力，不对外宣称已完成多语种检索。
- 外部数据：本批未联网、未调用外部模型，未发送课程正文、用户数据、密钥或 `.env`。
- 下一步：实现应用内 source_ref 回跳。先为检索 chunk 建立可信的片段级字符定位，再提供只读解析 API 和前端路由状态，使点击引用能打开对应课程文档并定位章节/选区；完成浏览器 E2E 后再进入类型化知识图谱事实来源门禁。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-044 - 课程版本差异预检与显式批准门禁

- 状态：`PASS（M5-003 / S2-007）`，M5-003 总体仍为 `IN_PROGRESS`。本批只关闭课程版本更新治理，不把检索评测、应用内引用回跳或图谱事实来源误记为完成。
- 只读预检：`preflight_course_bundle_update` 以 canonical JSON 计算当前与待导入 manifest 哈希，区分 `new_course`、`unchanged`、`same_version_conflict` 和 `update_available`。差异报告覆盖新增/删除文件、正文 hash、来源与许可证元数据、章节顺序、知识点映射和课程元数据，预检本身不提交数据库、不写 RAG。
- 写前拒绝：同一版本号但 manifest 内容变化时抛出 `CourseManifestConflict`，任何课程、文档、canonical 来源或 RAG 写入前即失败；不同版本默认抛出 `CourseUpdateApprovalRequired`，不能由应用启动自动升级。
- 显式批准：新增 `apply_course_bundle_update` 和 `scripts/preflight_course_update.py`。命令默认只读；`--apply` 必须同时给出预期当前版本与待导入版本，以 compare-and-set 防止审批后版本漂移。版本不匹配明确拒绝，不接受仅传布尔值的宽松批准。
- 启动边界：`seed_default_courses` 发现跨版本更新时保留数据库旧课程且跳过该课程 RAG ingestion；启动日志明确打印课程 ID、旧/新版本及“database and RAG left unchanged”，不再只显示汇总数量而隐藏待审批状态。
- CLI 证据：本机数据库尚无精选课程时，只读命令返回 `status=new_course`、`requires_approval=false`、`incoming_version=course-ml-foundations-1.0.0`、`applied=false`；未产生数据库写入。帮助命令和项目根路径引导均可直接运行。
- 自动验证：版本治理与精选课程聚焦测试 `12 passed, 5 warnings in 3.71s`；M0 课程、M1 来源、课程来源审计、精选导入和版本治理直接因果回归 `29 passed, 5 warnings in 9.07s`；全部 `test_m5_*.py` 加 M0 课程、M1 来源与结构化 JSON 的扩大回归 `189 passed, 5 warnings in 16.77s`。`git diff --check` 无补丁错误，仅有既有 LF/CRLF 提示。
- 外部数据：本批完全离线，未调用外部模型、未发送课程正文或用户数据，未读取或输出 `.env` 与 API Key。
- 真实性边界：`PASS` 证明更新不会静默覆盖且具备可审查差异，不表示已有真人课程管理员批准过一个真实升级，也不表示课程内容质量、检索命中率和引用定位已经验收。
- 下一步：建立 12 章检索问题集，明确每题相关章节、允许答案、必须出现的 source_ref 和无证据样例；用它验证 S2-022/S2-023/S2-026/S2-029，再实现应用内 source_ref 章节/字符选区回跳。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-043 - 课程 canonical 来源详情与固定原文入口

- 状态：`PASS（M5-003 / S2-006 与 S2-026 课程来源子集）`，M5-003 总体仍为 `IN_PROGRESS`。本批将已存在但此前在知识库 API 丢失的 canonical source、source_ref 和 chapter 贯通到课程列表与详情；没有新增平行来源表。
- 读模型：`LegacyReadRepository` 的课程文档查询现联查 `DBSourceDocument`、`DBSourceRef` 和 `DBChapter`。知识库列表与详情均返回 source URL/document/ref/chapter、parser 版本、字符范围和 quote；课程 manifest 额外提供仓库 key、固定 commit、上游文件 SHA-256、SPDX、许可证文件/hash 与保留义务。
- 前端展示：`Knowledge.vue` 的预置课程详情新增可点击固定 GitHub commit 原文、上游文件路径、40 位版本、source_ref、parser、字符范围、转换后文件 hash、上游文件 hash 和许可证文件 hash。M0 等无 HTTP 原文的课程仍显示文字来源，不生成伪链接；外链使用新窗口和 `noopener noreferrer`。
- 交付可达：收尾检查发现根 `.gitignore` 的 `/data/` 规则会连同精选课程一起排除。现只放行 `data/curated/machine_learning_foundations_v1/**`，同时继续忽略 `data/raw/github_repos/`、上传数据和本地数据库；Git 状态已能看到精选目录，原始 1.6GB 候选仓库仍未进入待提交范围。
- HTTP 证据：新增真实 TestClient 链路，以普通认证学习者读取新课程 12 章列表和首章详情，断言固定原文 URL、commit、MIT、许可证文件、source document、chapter、source_ref、字符定位和标题一致。另一用户无需课程私有成员资格即可读公开课程，但仍不能修改或删除课程文档，既有只读边界未放宽。
- 自动验证：新课程与 M0 兼容组合 `14 passed, 5 warnings in 5.43s`；Vue 生产构建 `3106 modules transformed` 并成功，只有既有 `StudentAnalysis` 大 chunk 警告；全部 M5、安全、Swarm、成员 6 与 hardening 扩大回归 `190 passed, 6 warnings in 20.83s`。
- 真实性边界：本批证明 API 可定位 canonical source_ref 且前端可打开固定上游原文，不等于应用内阅读器已经滚动到精确字符选区，也没有浏览器截图证据。因此 S2-006/S2-026 的课程来源子集可记 PASS，S2-027 完整引用回跳仍为 PARTIAL。
- 下一步：继续 M5-003 / S2-007，建立课程 manifest 更新差异预检和“同版本内容变化拒绝”门禁；随后建立 12 章检索问题集与无证据样例，为 S2-022/S2-023/S2-026/S2-029 提供可重复验证，再实现应用内 source_ref 章节/选区回跳。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-042 - 许可精选机器学习课程版本与 canonical 幂等导入

- 状态：`PASS（M5-003 文件精选/Notebook 转换/课程版本导入批次）`，M5-003 总体仍为 `IN_PROGRESS`。本批在 S2-001~S2-003 许可审计基础上完成一门真实公开课程的文件级精选与导入，不把 7 个许可清晰仓库或整个 `data/raw/github_repos/` 暴露给前端和 RAG。
- 文件级精选：新增 `scripts/build_curated_ml_course.py`，机器检查 7 个 MIT/Clear-BSD 候选并记录本版选择或不选原因。主教材固定为 MIT 许可的 `nyandwi-machine-learning-complete@8aabb071866027dd5c83de6de0c82a17f2ebe79e`；从固定 Git commit 精选 12 个文件，覆盖 Python、NumPy、Pandas、EDA、数据准备、机器学习范式、scikit-learn、线性分类、决策树、集成学习、K-Means 和 PCA。
- 转换与隐私：11 个 Notebook 只通过结构化 JSON 解析，不执行代码；保留 Markdown 和代码单元，剥离 624 个执行输出及单元元数据。另有 1 个原生 Markdown 章节。清洗后 12 章合计 224,791 字节，敏感模式扫描未发现 API Key、Bearer token、本机用户路径、内嵌 Base64 图片或 Notebook `outputs` 结构。
- 课程版本清单：生成 `data/curated/machine_learning_foundations_v1/course_manifest.json`、12 个稳定 Markdown 章节和 `LICENSE.upstream.txt`。每个文件记录仓库 URL、40 位 commit、上游路径/类型/字节/SHA-256、转换后路径/字节/SHA-256、parser 版本、MIT 许可证及义务、13 个版本化知识点映射和选择理由；清单固定 Schema 为 `edumatrix.course-version-manifest.v1`。
- 许可证换行口径：首次生成因审计报告对 Windows CRLF 工作树计算哈希、Git blob 使用 LF 而按门禁停止。现同时要求工作树原始哈希匹配来源审计，并要求规范化换行后的审计文件与固定 commit blob 内容完全一致；manifest 保留可分发 Git blob 哈希和来源审计哈希，没有降低许可证校验。
- 幂等导入：`course_catalog.py` 新增严格版本 manifest 加载器，只读取清单列出的 bundle 内文件，拒绝路径穿越、哈希不符、许可证篡改、未知知识点、非 permissive 许可和非 40 位 revision。现有 `course_documents`、canonical `source_documents/chapters/knowledge_points/chapter_knowledge_points/source_refs` 与 RAG ingestion 直接复用，没有第二套课程表。
- 启动与前端：应用启动改为分别播种冻结 M0 基准课和新 `course-machine-learning-foundations-v1`，共 2 门公开课程、21 份文档、582 个检索块。现有知识库 API 和 `Knowledge.vue` 已按 `course_id/course_title` 分组并展示课程版本、来源、许可证和章节文档，因此无需新增平铺旁路或静态前端数据。
- 自动验证：新课程专项 `5 passed in 1.29s`；M0 兼容、M1 来源、来源审计与新课程组合 `22 passed, 5 warnings in 7.63s`。旧测试中 2 条“系统永远只有一门公开课程”的写死断言改为验证 M0 的 9 份身份仍完整且允许其他正式课程共存，生产逻辑未隐藏新课程。全部 M5、安全、Swarm、成员 6 与 hardening 扩大回归 `189 passed, 6 warnings in 20.42s`。
- 真实性边界：本批未执行 Notebook、未运行上游实验、未联网、未调用外部模型，也没有真人课程维护者签字。S2-004、S2-012、S2-017 和 S2-043 仅完成本课程版本所需子集；人工发布确认、上游版本 diff、多格式全覆盖、精确引用回跳、检索评测集、类型化知识图谱事实来源与完整领域包仍待续。
- 下一步：继续 M5-003，优先补 S2-006/S2-007/S2-026/S2-027：让知识库详情直接返回并展示 canonical source URL、commit、许可证文件和 source_ref，引入课程版本差异预检且禁止静默覆盖；随后为 12 章课程建立可定位问题集，验证当前课程过滤、低相关拒答和引用回跳，再进入图谱事实来源门禁。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-041 - GitHub 课程素材与许可证机器审计白名单

- 状态：`PASS（M5-003 / S2-001~S2-003）`，M5-003 总体仍为 `IN_PROGRESS`。现有 9 文档原创 RAG 基准课程、canonical 来源/章节/source_ref 和前端课程展示保持不变；本批没有把原始仓库直接导入知识库。
- 审计工具：新增 `scripts/audit_course_sources.py`，读取 `data/manifest/source_manifest.jsonl`，对 Git 来源验证本地目录与 40 位 commit SHA，扫描课程候选扩展名、统计字节数，并对仓库根 LICENSE/COPYING 计算 SHA-256 和识别许可证类型。
- 保守白名单：只有本地许可证明确识别为 MIT 或 Clear-BSD 的仓库进入 `approved_default_course_candidate`；GPL-3.0 与 CC-BY-NC-SA-4.0 标记 `manual_obligation_review_required`，不自动接受 copyleft、署名、非商业和相同方式共享义务；无根许可证文件的仓库直接阻断；未打包直链仅 `external_reference_only`。
- 结构化结果：生成 `data/manifest/course_source_audit.json`，覆盖 15 个 manifest 来源，其中 13 个本地 Git 仓库；状态为 7 个默认候选、4 个义务复核、2 个无许可证阻断、2 个仅外部引用。默认候选为 `data-science-from-scratch`、`dtreeviz`、`edge-impulse-courseware`、`mlbook-dafriedman`、`nyandwi-machine-learning-complete`、`rasbt-ml-book-code` 和 `ruban-iris-classification`。
- 可复现性：报告保存 source manifest SHA-256、每仓库 commit、许可证文件路径/hash/SPDX 识别、材料类型计数、材料字节数、资格状态、阻断原因和义务；重跑脚本会从当前工作树重新生成，不依赖人工复制表格。
- 自动验证：来源审计、M0 课程目录和 M1 canonical 来源专项 `17 passed, 5 warnings in 5.71s`；全部 M5、安全、Swarm、成员 6 与 hardening 扩大回归 `184 passed, 6 warnings in 19.20s`。测试阻止无许可证、互惠许可证或直链来源静默进入默认白名单。
- 声明边界：白名单表示“可进入文件级精选候选”，不表示整个仓库所有文件均已完成内容、商标、第三方素材和文件级例外审查；GPL/CC 来源并非非法，只是当前默认课程不自动承担其额外义务。
- 外部数据：本批只读取已下载仓库和本地 Git 元数据，没有联网、模型调用、用户数据或密钥外发。
- 下一步：从 7 个许可清晰候选中按课程目标建立文件级精选清单，优先 Markdown/Notebook/代码与可验证实验；记录每个文件的来源 commit、许可证、哈希、章节和知识点，转换 Notebook 输出后通过新课程版本幂等导入 canonical 来源。导入前不得把未选中的仓库全文暴露给前端或 RAG。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-040 - M5 身份权限审计与统一对象增量闭环

- 状态：`PASS（M5-002）`，M5 总体仍为 `IN_PROGRESS`。本结论复用 M1 已冻结的 S1-001 至 S1-044 与 G1-G9 证据，只验证 M5 新增能力没有破坏身份、对象、组织和审计契约；没有重新打开或重新验收 M1。
- 路由认证：运行时检查 `app.m5_api.router` 的 38 条路由，全部直接依赖 `get_current_user`；新增契约测试固定路由数量与认证依赖，后续新增匿名 M5 路由会失败。各路由继续从 token 用户派生 owner，不接受请求体伪造权威身份。
- 统一对象缺口：M1 对象网关冻结后，M5 新增正式表未同步注册，导致测评、复测、上下文和模型调用无法通过统一检查页还原所有权。现新增 12 类对象注册：学习事件消费、上下文会话、模型调用/额度、评测注释/报告、集成交付、题目/版本、作答、错因和复测。
- 派生作用域：题目版本从题目解析 owner/course，事件消费从学习事件解析 owner/course，集成交付使用 organization 边界；作答、错因、复测、上下文和模型调用使用正式 owner/course。模型额度、评测注释和报告保持 internal-only，不向普通学习者开放。
- 越权证据：新增代表性测试覆盖题目版本、作答、错因、复测、事件消费、上下文和模型调用。本人可获得不含敏感正文的统一对象元数据，另一普通用户对每类对象均收到 403；原 M1 课程、资源、组织和内部检查网关测试继续通过。
- 审计补齐：计划/路径、资源归档、上下文等既有 M5 写操作已有审计；本批为正式题目创建和学习者错因决定补 `assessment.question.create` 与 `assessment.misconception.decide`。摘要只保存题型、来源、版本、决定和布尔标志，不保存题干、答案、解析、错因正文、决定备注或证据。
- 自动验证：统一对象、M1 对象网关、内部检查和安全聚焦组合 `30 passed, 5 warnings in 6.01s`；测评审计、评测核心与 M1 网关组合 `27 passed, 5 warnings in 5.30s`；全部 M5、安全、Swarm、成员 6 与 hardening 扩大回归 `181 passed, 6 warnings in 16.93s`。
- 声明边界：M5-002 PASS 表示当前 M5 正式对象和路由没有已知身份/统一对象回退，不表示真实企业 SSO、HR/LMS 或生产多租户部署已经接入；这些仍属于 M7/M8 外部集成与部署验收。
- 外部数据：本批仅使用内存数据库和本地自动测试，没有网络或外部模型调用，没有用户数据或密钥外发。
- 下一步：进入 M5-003 课程知识底座剩余缺口审计。优先区分已完成的来源/导读/视觉调用治理与尚未完成的真实教材导入、许可证、解析版本、层次切块、跨模态引用回跳、检索评测集和图谱事实来源门禁，再选择最能形成真实闭环的一批实现。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-039 - PDF 页面视觉外发治理与旧 AI P2 清单收敛

- 状态：`PASS（M5-003/M5-005/M5-011 PDF 视觉调用迁移批次）`，M5 总体仍为 `IN_PROGRESS`。PDF 文本解析、页面渲染、视觉证据、VisRAG 写入和本地 PIL 降级保持兼容。
- 可达链路：认证知识库上传和 Web 直链下载在 PDF 分支调用 `parse_pdf_visually`，每页可通过 OpenAI-compatible 多模态端点发送 Base64 PNG。旧实现直接 `requests.post`，没有 owner、trace、Token、输出 hash 或失败终态，确认是用户可达外发。
- 认证与追踪：两个端点现传入 `current_user.public_id` 和各自 `m5-pdf-upload-*` / `m5-pdf-download-*` parent trace；逐页调用使用 `legacy_pdf_visual_description:1.0`，记录明确的 `multimodal-openai-compatible` provider、模型、Token 估算、输出 hash 和成功/结构失败/供应商失败终态。无 owner 时不访问视觉端点，只生成本地图片元数据。
- 数据最小化：视觉提示不再包含文件名；审计摘要只保存页码、估算图片字节数、`image_payload_included=false` 和 `filename_payload_included=false`，不保存 Base64、文件名、页面内容、Prompt、API Key 或输出正文。
- 输出与降级：空视觉描述记录 `pdf_visual_description_output_invalid`；HTTP/JSON/供应商异常记录 `pdf_visual_description_provider_failed`。两类失败均继续使用 PIL 元数据，不阻断文档上传；异常日志不打印端点响应或密钥相关文本。
- provider 修正：共享 `model_identity` 优先读取后端显式 `provider`，使多模态兼容端点不会被误记为普通文本 provider；既有后端无显式 provider 时行为不变。
- dormant 补充：`app/agents/coder.py` 直接构建 `openai.AsyncClient`，但产品代码没有任何导入或调用，仅旧测试通过 patch 引用，标记 `legacy dormant`；不把它计为已治理运行调用。
- 自动验证：PDF 视觉、文档导读、Web 调用和安全专项 `28 passed in 1.22s`；全部 M5、安全、Swarm、成员 6 与 hardening 扩大回归 `171 passed, 6 warnings in 17.94s`。新增 4 项测试覆盖逐页成功、空输出、供应商失败和无 owner 零外发。
- 试错记录：首次 PDF 专项使用 `monkeypatch.setattr` 修改冻结配置 dataclass，4 项均在夹具阶段失败且未发网络请求；改为测试隔离配置对象后通过，生产只读配置不变。
- 外部数据：本批所有 HTTP 与模型行为均由虚拟响应替代，没有真实网络或外部模型调用，没有 PDF 页面、Base64、文件名、用户数据或密钥外发。
- 下一步：旧 AI P2 差异已无未分类的用户可达调用；转入 M5-002，按身份边界、对象授权、审计事件、租户/课程作用域和统一对象残余旁路逐项审计，发现真实缺口后分批修复。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-038 - 困难复习降维适配调用治理

- 状态：`PASS（M5-005/M5-010/M5-011 复习适配迁移批次）`，M5 总体仍为 `IN_PROGRESS`。SM-2 更新、canonical 学习证据、卡片字段和分块响应保持兼容。
- 可达链路：认证 `POST /api/flashcards/review` 在 `quality=2` 时调用 `build_review_adaptation_payload`，旧实现通过 `asyncio.to_thread(DEFAULT_LLM.generate)` 外发概念和掌握度。该函数引用形态不会被普通 `.generate(` 扫描完整识别，现已补入清单。
- 认证与终态：端点传入 `current_user.public_id`；只有认证 owner 存在时才执行同步模型调用，并使用 `legacy_review_adaptation:1.0` 记录 provider/model、trace、Token、输出 hash和成功/结构失败/供应商失败终态。无 owner 直接使用内置概念适配内容，零模型调用。
- 输出门禁：空值、过短文本和旧占位响应记录 `review_adaptation_output_invalid` 后回退；普通短文与既有 JSON `{explanation, mermaid}` 兼容。模型失败不影响复习排程和卡片返回。
- 真实性修复：`llm_backend` 默认明确为 `deterministic-fallback`，只有模型输出通过门禁后才显示真实后端类名；Agent trace 改为“生成或回退”，不再在异常时宣称模型已生成。
- 隐私摘要：只保存评分、粗粒度掌握区间和 `concept_payload_included=false`，不保存概念名、精确掌握度、卡片正文、Prompt 或输出正文。
- 自动验证：复习适配、安全、成员 6 与 hardening 聚焦组合 `39 passed, 6 warnings in 11.07s`；全部 M5、安全、Swarm、成员 6 与 hardening 扩大回归 `167 passed, 6 warnings in 17.79s`。新增 4 项测试覆盖成功、结构失败、供应商失败和无 owner 零模型调用。
- 试错记录：首次聚焦命令引用不存在的 `tests/test_m5_legacy_adapters.py`，pytest 在收集前停止，未执行测试；随后内存 SQLite 夹具在线程池中触发 `check_same_thread`，改为测试专用 `StaticPool` 共享连接后通过。生产文件数据库与每线程会话逻辑未放宽。
- 外部数据：本批使用虚拟同步后端和内存数据库，没有真实外部模型调用，没有概念、掌握度、卡片、用户数据或密钥外发。
- 下一步：完成直接 OpenAI 客户端、线程池函数引用和 provider 工厂的补充差异扫描；P2 清单收敛后进入 M5-002 身份、权限、审计与统一对象缺口审计。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-037 - Matrix 跨线程指代消解治理与 dormant 入口收敛

- 状态：`PASS（M5-005/M5-008/M5-011 指代消解迁移批次）`，M5 总体仍为 `IN_PROGRESS`。Planner 的显式概念匹配、BKT/ZPD 计算、检索和无模型回退保持兼容。
- 可达链路：`EduMatrixSwarm.async_process -> ZPDPlannerAgent.plan_async -> asyncio.to_thread(plan)` 会在模糊代词、已有历史且无显式概念命中时，通过主事件循环调用 `DEFAULT_ASYNC_LLM`。旧实现会发送活跃概念、最近 5 条对话和当前问题，但没有 owner、course、trace 或调用终态，确认不是 dormant。
- 认证与追踪：Matrix 主链现把认证 owner、course 和 `m5-matrix-*` parent trace 传入 Planner；只有存在 owner 时才允许指代模型调用。无 owner 时直接沿用 `_infer_target` 等确定性逻辑，不构建模型请求。
- 严格结果：模型输出只能是当前活跃概念集合中的精确名称或 `None`；其他文本统一记录 `coreference_resolution_output_invalid` 并回退，不把自由文本当作概念。供应商失败记录 `coreference_resolution_provider_failed`，异常响应内容不写控制台。
- 生命周期增强：异步旧调用包装器新增可选 course 和结构验证器；验证发生在 completed 之前，结构失败保存输出 Token/hash 并记录 failed，再由调用者执行原有回退。
- 隐私摘要：只保存活跃概念数量、历史轮数以及 query/history/concept payload 均未进入摘要；不保存概念名、对话正文、学生问题、Prompt 或模型输出正文。
- dormant 证据：产品代码调用搜索显示同步 `InstructRAGGenerator.generate` 仅定义并被导入，没有实例化调用；`AsyncInstructRAGGenerator.generate_stream` 只有定义，Matrix 使用已治理的异步 `generate`；`DebateAugmentedRAG.clean` 仅见旧单元测试，产品 Swarm 使用已治理的 `aclean`。三者标记 `legacy dormant`，保留兼容实现但不伪装为已迁移的运行调用。
- 自动验证：指代消解、画像、Matrix、Planner 与 hardening 聚焦组合 `23 passed in 4.33s`；全部 M5、安全、Swarm、成员 6 与 hardening 扩大回归 `163 passed, 6 warnings in 17.98s`。新增 4 项测试覆盖成功、结构失败、供应商失败和无 owner 零模型调用。
- 外部数据：本批使用虚拟异步后端和内存数据库，没有真实外部模型调用，没有对话、概念、问题、用户数据或密钥外发。
- 下一步：重新生成旧 AI 调用差异结果，确认剩余直接调用只属于底层 provider、已治理包装器、M2-M4 关闭实现或有证据的 dormant 入口；若 P2 清单收敛，则转向 M5-002 至 M5-012 的功能缺口审计，优先核对身份/权限/审计与统一对象剩余能力。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-036 - 委员会事实共识严格输出与同步审计治理

- 状态：`PASS（M5-005/M5-006/M5-011 委员会事实共识迁移批次）`，M5 总体仍为 `IN_PROGRESS`。旧 `ManifoldAlignmentVerifier.verify` 返回结构、流形校验和确定性降级保持兼容。
- 可达链路：`EduMatrixSwarm.async_process` 每轮资源生成后调用 `ManifoldAlignmentVerifier.verify -> CouncilDecisionEngine.synthesize`。旧实现会在每次合成时现场 `build_llm()`，并同步发送目标知识点及最多每项 800 字资源正文；它不是 dormant 调用。
- 认证与追踪：Matrix 主链现透传认证 owner、course 和 `m5-matrix-*` parent trace。无 owner 时不构建模型、不发送正文，直接执行既有确定性事实检查；有 owner 时使用 `legacy_council_fact_review:1.0` 同步审计记录 provider/model、Token 估算、输出 hash 和终态。
- 严格输出：新增 `CouncilConflict`、`CouncilVerdict` 和 `CouncilDecision` 严格 Schema，禁止额外字段、空关键字段和越界分数；verdict Agent 必须与本轮资源 Agent 集合完全一致，禁止缺失、重复或未知 Agent，冲突引用也只能指向本轮 Agent。
- 失败语义：供应商异常记录 `council_fact_review_provider_failed`；结构异常记录 `council_fact_review_output_invalid`，并保留已收到输出的 Token/hash，再抛给委员会确定性 fallback。结构失败不会先写 completed，也不会伪装模型判决成功。
- 隐私摘要：只保存资源数量、资源类型集合和 `resource_payload_included=false`，不保存资源正文、目标知识点、Agent 名称、Prompt 或模型输出正文。
- 自动验证：委员会、Planner、辩论与 hardening 聚焦组合 `22 passed in 2.57s`；全部 M5、安全、Swarm、成员 6 与 hardening 扩大回归 `159 passed, 6 warnings in 17.66s`。新增 4 项委员会测试覆盖严格成功、未知 Agent 结构失败、供应商失败和无 owner 零模型调用。
- 外部数据：本批使用虚拟同步后端和内存数据库，没有真实外部模型调用，没有资源正文、目标知识点、Agent 输出、用户数据或密钥外发。
- 下一步：审计 `instruct_rag.py` 的同步生成器和 `generate_stream` 是否存在产品调用者，形成可达性证据；随后治理 Swarm 跨线程指代消解，并核对 `drag_debate.clean` 是否仅由旧测试或内部兼容链调用。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-035 - Swarm 异步证据辩论严格判决与审计治理

- 状态：`PASS（M5-005/M5-006/M5-011 证据辩论迁移批次）`，M5 总体仍为 `IN_PROGRESS`。1 条或 12 条以上证据、无 owner、无模型和模型失败时继续使用既有确定性评分，主生成链可用性保持。
- 可达链路：`EduMatrixSwarm.async_process` 在检索后调用 `DebateAugmentedRAG.aclean`。现将同一 Matrix 请求的认证 owner、course 和 `m5-matrix-*` parent trace 传入；证据辩论保留独立 call ID 和终态。
- 严格判决：新增 `DebateJudgment`，每项只允许 evidence_id、三项 0-1 分数和非空 reason；只接受完整 JSON 数组或完整 JSON fence，拒绝额外字段、越界分数、重复 ID 和本次证据集之外的 ID。缺失的合法证据继续按原确定性评分，不伪造模型判断。
- 行为缺陷修复：旧 `_llm_debate_clean_async` await 得到判决后，`_build_llm_debate_result` 又无条件调用同步 judge 覆盖结果；异步后端因此常退化为空判决和确定性评分。删除重复调用后，严格验证的异步 verdict 现在真正决定证据保留/剔除。
- 生命周期：使用 `legacy_evidence_debate:1.0` 和 evaluate 能力；供应商失败记录 `evidence_debate_provider_failed`，结构失败记录 `evidence_debate_output_invalid`，取消记录 `client_disconnected` 并传播。供应商/结构失败后主链使用确定性评分，失败调用不伪装 completed。
- 隐私摘要：只保存证据数量、模态集合和 `evidence_payload_included=false`，不保存查询、目标、学习路径、证据标题/正文/来源/标签/锚点或 verdict 正文。
- 匿名阻断：没有认证 owner 的 `aclean` 不调用模型，直接使用确定性辩论；旧 hardening 测试更新为注入真实内存用户和数据库执行器，不放宽 owner 外键。
- 自动验证：严格辩论与 hardening 专项 `15 passed in 2.33s`；全部 M5、安全、Swarm、成员 6 与 hardening 扩大回归 `155 passed, 6 warnings in 28.78s`。该组合比常规 M5 回归额外包含 10 条 hardening 测试。
- 外部数据：使用虚拟裁判和内存数据库，无真实模型调用，无查询、路径、证据正文、判决或密钥外发。
- 下一步：审计 `manifold_alignment.py` 委员会事实共识调用的真实注入条件。当前 `ManifoldAlignmentVerifier` 默认创建无 LLM 的 `CouncilDecisionEngine`；若产品链无动态注入则标记该 `.generate` dormant，并转向 `instruct_rag.py` 剩余同步/流式入口及 Swarm 指代消解调用。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-034 - 学习路径 Planner 同步调用治理与首批 dormant 判定

- 状态：`PASS（M5-005/M5-008/M5-011 路径 Planner 迁移批次）`，M5 总体仍为 `IN_PROGRESS`。旧 `planner_review`、个性化 guidance、确定性 fallback 和路径计算响应保持兼容。
- 可达链路：`GET /api/profile/{student_id}/learning-path` 在认证和 student scope 校验后，通过 `asyncio.to_thread(PATH_PLANNER.plan)` 同步构建路线；旧 `_review_candidate_route_with_planner` 每次可能调用同步 `DEFAULT_LLM`，此前无 owner、trace 或终态。
- owner 传递：认证端点将 `current_user.public_id` 沿 `PathPlanner.plan -> build_adaptive_astar_route -> _review_candidate_route_with_planner` 传入；使用 `legacy_learning_path_review:1.0` 记录 provider/model、Token、输出 hash、认证 owner 和成功/供应商失败终态。
- 匿名阻断：内部或测试调用未提供 owner 时不再执行模型，明确返回既有确定性 guidance 和 `deterministic-fallback-unowned`。这既消除匿名画像/路线外发，也保持算法调用者不依赖数据库用户外键。
- 隐私摘要：只保存候选路径数量、路线节点数量和 `profile_payload_included=false`，不保存概念名、掌握度、认知负荷、挫败度、学习目标或 Prompt 正文。
- 同步边界：新增同步审计函数，生产默认使用 `SessionLocal`，测试可注入 session factory；失败记录终态后继续抛给旧 fallback，未放宽 `model_calls.owner_public_id` 外键。
- dormant 证据：`NoteGenerator.summarize_conversation` 当前只有定义，无产品调用者；`app.main` 只使用无 LLM 的 `LearningProgressAnalyzer`。图谱构建器注入 `DEFAULT_ASYNC_LLM`，同步三元组入口检测 coroutine 后明确规则降级，因此当前上传链不会执行同步 `.generate`。两处先标记 `legacy dormant/currently non-executing`，不因文本命中重写。
- 自动验证：Planner 同步调用与既有路径专项 `7 passed in 0.40s`；全部 M5、安全、Swarm 与成员 6 回归 `140 passed, 6 warnings in 32.36s`。
- 外部数据：使用同步虚拟后端和内存数据库，无真实模型调用，无路线、画像、概念、掌握度或密钥外发。
- 下一步：治理当前 Swarm 主生成链可达的 `DebateAugmentedRAG.aclean` 异步证据辩论，将已有 `model_call_context` 的 owner/course/trace 传入，使用严格 verdict Schema 和失败/取消终态；之后审计同步委员会事实共识调用的真实执行条件。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-033 - 文本与视觉连接测试的认证和流式终态

- 状态：`PASS（M5-005/M5-011 模型连接测试迁移批次）`，M5 总体仍为 `IN_PROGRESS`。文本/视觉未配置 warning、成功预览和原状态字段保持兼容；视觉失败文案去除供应商异常详情。
- 认证门禁：`GET /api/llm/test` 与 `GET /api/llm/test-vision` 现显式依赖认证用户，实际模型调用绑定 `current_user.public_id`。确定性文本后端或未配置视觉后端继续直接返回 warning，不创建伪模型调用记录。
- 文本测试：固定探针通过共享旧文本审计边界，使用 `legacy_text_connection_test:1.0`，摘要只声明固定探针且不含用户数据；记录 provider/model、Token/成本和成功/供应商失败/取消终态。
- 视觉测试：固定 1×1 图片流式调用使用 `legacy_vision_connection_test:1.0`；摘要只记录固定图片数量、编码字符数、`image_payload_included=false` 和无用户数据，不保存 Base64。成功记录完整累计输出的 Token/hash；部分输出后供应商失败或取消也记录已产生输出的 Token/hash 和明确终态。
- 错误脱敏：视觉供应商异常不再通过 `str(e)` 返回前端；失败响应固定为“视觉模型调用失败”，审计只保存稳定错误码。
- 依赖边界：专项测试首次意外命中当前配置包装器，定位到端点内部重复局部导入绕过模块级构造器；删除局部导入并统一使用模块级 `build_swarm_from_headers`，提升测试隔离且不改变生产构造逻辑。此次未完成真实外部调用。
- 自动验证：连接测试与 Web 调用专项 `8 passed, 4 warnings in 1.23s`；全部 M5、安全、Swarm 与成员 6 回归 `137 passed, 6 warnings in 24.51s`。
- 外部数据：使用虚拟文本/视觉后端和固定测试图片，无真实外部模型调用，无用户图片、Base64、密钥或供应商错误外发。
- 下一步：对 P2 与内部同步调用做可达性审计：`note_engine.py` 对话摘要、`learning_strategy.py` guidance、`knowledge_api.py` 极客助教，以及 `agent_swarm.py` 指代消解、`instruct_rag.py` 同步/流式生成、`drag_debate.py`、`manifold_alignment.py` 和图谱生成；有当前用户入口的继续治理，无可达证据的标记 legacy dormant 并建立防重新接入门禁。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-032 - Web 搜索、URL 与来源脱水调用统一治理

- 状态：`PASS（M5-003/M5-005/M5-011 Web 文本调用迁移批次）`，M5 总体仍为 `IN_PROGRESS`。搜索、URL 加载、知识库 Web 来源导入、历史记录、RAG 入库和原 fallback 响应保持兼容。
- 共享边界：新增 `app/m5_legacy_calls.py`，统一旧文本调用的 provider/model、Prompt 版本、Token/成本估算、认证 owner、成功/供应商失败/取消终态；业务 Prompt、响应和 fallback 仍留在各自模块，没有把三个入口耦合成新旁路。
- 搜索摘要：`web_search_summary` 记录查询字符数、结果数量和 `result_text_included=false`，不保存查询、标题、snippet、URL 或完整搜索结果；无结果时继续走确定性提示，不伪造模型调用。
- URL 摘要：`url_content_summary` 记录正文截断字符数、来源 host 和 `web_content_included=false`，不保存 URL path/query、网页标题或正文；供应商失败继续返回原“已加载并索引”fallback。
- Web 来源脱水：`web_source_dehydration` 绑定认证 owner，只记录查询/标题/snippet 字符数、来源 host 和正文未写入审计；失败继续使用原始标题、URL、查询和 snippet 构造 Markdown 入库，不把 fallback 标成模型成功。
- 认证证据：端点级 `web_search` 测试证明调用 owner 来自 `current_user.public_id`，而业务数据仍按既有 `enforce_student_access` 的 username 作用域保存，未混淆两种标识。
- 自动验证：Web 包装器与端点专项 `4 passed in 0.76s`；与文档导读组合 `8 passed in 1.04s`；全部 M5、安全、Swarm 与成员 6 回归 `133 passed, 6 warnings in 26.43s`。
- 外部数据：使用虚拟搜索结果、虚拟模型和内存数据库；无真实网络搜索、网页抓取、外部模型调用或密钥外发。
- 下一步：治理 `app/main.py` 的文本模型连接测试与视觉模型连接测试，记录认证 owner、provider/model、成功/失败/取消终态；视觉流式调用需保留部分输出失败证据且不得在摘要中保存 Base64。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-031 - 文档导读后台任务的归属与严格输出治理

- 状态：`PASS（M5-003/M5-005/M5-011 文档导读迁移批次）`，M5 总体仍为 `IN_PROGRESS`。上传、Web 来源导入和 URL 文件下载的旧响应仍返回 `doc_guide_status=pending`，导读继续异步写入原 metadata 字段。
- 后台归属：三个导读调度点现在传递认证 `owner_public_id`；后台模型调用前按 `doc_id + student_id` 重新确认文档仍存在且归属一致。文档不存在、已删除或 owner 不匹配时不调用模型，也不创建调用记录。
- 严格结构：新增 `DocumentGuide` 与 `DocumentGuideFAQ`，限制摘要、1-10 条非空看点、1-10 条完整问答并禁止额外字段；只接受一个 JSON 对象或完整 JSON fence。缺字段、错误类型、空字符串和额外字段不再补造“无摘要/无看点”，记录 `failed/document_guide_output_invalid` 且不写导读。
- 生命周期：使用 `legacy_document_guide:1.0`、独立 `m5-doc-guide-*` trace、认证 owner、provider/model、Token/成本估算和成功/供应商失败/结构失败/取消终态；文档在生成期间消失则记录 `document_unavailable_after_generation`。
- 隐私摘要：只保存 operation、文档 ID、截断后字符数和 `document_body_included=false`，不保存文档正文、标题、文件名或生成内容。输出正文只保留 SHA-256 与 Token 估算，不复制到审计表。
- 参数护栏：专项测试首次把相邻字符串参数传反，暴露正文可被误作 owner 的风险；将 `owner_public_id` 与 `text_content` 改为仅关键字参数，生产调度原本已使用关键字，旧 HTTP 接口无变化。
- 自动验证：文档导读专项 `5 passed in 0.87s`；全部 M5、安全、Swarm 与成员 6 回归 `129 passed, 6 warnings in 34.42s`。
- 外部数据：使用虚拟后端，无外部模型调用，无文档正文、标题、文件名、导读或密钥外发。
- 下一步：治理 `web_search_api.py` 搜索结果摘要和 URL 内容摘要，以及 `knowledge_api.py` Web 来源脱水总结；绑定认证 owner、最小网页摘要、失败/取消终态并保持原 fallback 与入库响应。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-030 - 三 Agent 画像报告的共享追踪与独立终态

- 状态：`PASS（M5-004/M5-005/M5-011 画像报告迁移批次）`，M5 总体仍为 `IN_PROGRESS`。旧成长信笺、仪表盘诊断、缓存字段和 fallback 文案保持兼容。
- 调用治理：`NarrativeReportGenerator` 的教师评估、叙事生成和仪表盘诊断统一经过可审计调用包装器；一次报告请求共享 `m5-profile-analysis-*` parent trace，三次真实模型调用各自保留 call ID、provider/model、Prompt 版本、Token/成本估算和终态。
- 认证与隐私：`/{student_id}/narrative` 已有本人访问门禁，现将认证 `current_user.public_id` 绑定到三次调用。审计摘要只保存 operation 和 `profile_payload_included=false`，不保存 student_id、课程名、知识点、掌握度、成因、教师建议或画像正文。
- 独立失败：教师评估失败只使用既有教师建议 fallback；叙事与仪表盘继续并发，但使用独立异常结果，任一供应商失败不再导致另一项成功输出被一起丢弃。失败调用记录 `profile_{operation}_provider_failed`，fallback 不泄露供应商异常。
- 取消语义：每个 Agent 取消均记录 `failed/client_disconnected` 并继续传播，不缓存或返回伪成功报告。
- 自动验证：画像报告治理与既有画像探针专项 `7 passed in 2.75s`；全部 M5、安全、Swarm 与成员 6 回归 `124 passed, 6 warnings in 27.53s`。新增 3 条测试覆盖共享 trace、认证 owner、最小摘要、并发单项失败和取消终态。
- 外部数据：使用虚拟后端，无外部模型调用，无画像、课程、掌握度、成因、建议或密钥外发。
- 下一步：推进 P1 的 `knowledge_api.py` 文档导读和 Web 来源总结，以及 `web_search_api.py` 搜索/URL 摘要；先核对端点认证、文档归属、后台任务生命周期和现有响应，再分批治理。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-029 - 笔记润色入口的隐私与调用生命周期治理

- 状态：`PASS（M5-005/M5-007/M5-011 笔记润色迁移批次）`，M5 总体仍为 `IN_PROGRESS`。旧 `/api/notes/ai-polish` 响应、Mermaid 生成、代码块保护与恢复、标签和概念解析均保持兼容。
- 认证归属：端点显式接收认证用户，将 `owner_public_id` 写入每次真实模型调用记录；旧笔记没有 canonical note/artifact 或可靠课程绑定，因此不伪造 course_id。
- 生命周期：笔记整理调用使用 `legacy_note_polish:1.0`，记录 provider/model、独立 `m5-*` trace、Prompt 字符数、Token/成本估算和 completed/failed 终态；客户端取消记录 `client_disconnected` 后继续抛出，不被通用 fallback 吞掉。
- 隐私摘要：审计摘要只保存操作类型、原文字符数、受保护代码块数量和是否含 Mermaid，不保存原始笔记、代码、占位后的正文、标签或概念。完整笔记只进入当前请求选择的模型上下文，不复制到审计表。
- 兼容降级：供应商异常记录 `failed/note_polish_provider_failed`，旧响应继续返回原始笔记并保留代码块恢复；面向用户的 fallback 不再包含供应商异常文本，避免内部错误信息泄露。失败记录与 fallback 内容明确区分，不伪装模型成功。
- 测试夹具修复：新 TestClient 测试最初因 `app.main` 先于数据库对象导入触发兼容重载，使内存库建表元数据与模型实例不一致，并暴露 SQLite 跨线程限制。仅调整测试导入顺序并使用 `StaticPool + check_same_thread=False`，未放宽生产外键、Schema 或权限。
- 自动验证：笔记润色与苏格拉底专项 `9 passed, 5 warnings in 1.60s`；全部 M5、安全、Swarm 与成员 6 回归 `121 passed, 6 warnings in 26.67s`。相对上一批新增 3 条笔记治理测试，覆盖成功、供应商失败、owner、终态、代码块恢复、解析和隐私摘要。
- 外部数据：使用虚拟后端，无外部模型调用，无笔记、代码、标签、概念或密钥外发。
- 下一步：治理 `profile_api.py` 的教师评估、画像叙事和仪表盘诊断。一次画像分析请求共享 parent trace，三次模型调用保留独立 call ID 和终态；绑定认证 owner，审计摘要不得保存画像正文，并覆盖并发单项失败与取消。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-028 - 局部再生成归属与苏格拉底双 Agent 治理

- 状态：`PASS（M5-005/M5-009/M5-011 再生成与苏格拉底迁移批次）`，M5 总体仍为 `IN_PROGRESS`。旧 `/regenerate` JSON 响应、笔记持久化、`/explain` SSE/JSON 双轨和 fallback 文案保持兼容。
- 局部再生成：`/api/stream/regenerate` 继续复用受治理的 `AsyncInstructRAGGenerator`，新增 `m5-regenerate-*` trace 和认证 owner 透传；旧请求没有可靠 course/tutor context 绑定，因此课程保持空值。端点级 TestClient 证明不是只在辅助函数中存在参数。
- 数据库依赖：移除 `regenerate_component` 内部重复导入 `run_db_op`，统一使用模块级执行器。首轮端点测试因此暴露局部导入绕过 monkeypatch 并误写隔离全局库的外键失败；未放宽外键，修正依赖入口后通过。
- Consultant：新增严格 `SocraticPlan`，教学动作只允许 DEFINE、COUNTER_EXAMPLE、SOCRATIC_QUESTION、HINT_LADDER，focus_concept 必须非空；替换正则截取任意 JSON。结构失败记录 failed/socratic_consultant_output_invalid，供应商失败记录对应 provider error，端点继续使用原默认苏格拉底动作。
- Teacher：同步与流式调用均使用 `legacy_socratic_teacher:1.0`；Consultant 与 Teacher 共享一次 `m5-socratic-*` trace、各自保留 call ID。同步异常、流式部分输出异常、取消分别形成明确终态；部分流式输出计入输出 Token 后再 fallback，不伪装 completed。
- 隐私和归属：两 Agent 调用绑定认证 owner，摘要只记录 operation 和 streaming，不保存选中文本、上下文、历史或追问；旧 explain 请求无 canonical course，不伪造 course_id。
- 自动验证：苏格拉底、Matrix、stream context 与 regenerate 端点专项 `21 passed, 5 warnings in 2.41s`；全部 M5、安全、Swarm 与成员 6 回归 `118 passed, 6 warnings in 28.40s`。
- 外部数据：使用虚拟后端，无外部模型调用，无选中文本、历史、画像或密钥外发。
- 下一步：生成旧 AI 入口差异清单，排除 M2-M4 已关闭阶段与底层 provider 包装器，按用户入口风险继续迁移 app/main、profile、knowledge、web search、note 等剩余直接调用。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-027 - Quiz 四类模型调用统一治理

- 状态：`PASS（M5-005/M5-010/M5-011 Quiz 迁移批次）`，M5 总体仍为 `IN_PROGRESS`。确定性题库快轨、选择题秒判、IRT/MIRT、沙箱、自适应跟进、错题双写和旧响应均保留。
- 共享边界：`quiz_api.py` 四处直接 `llm.generate` 已收敛为 `_call_quiz_model`；统一记录 provider/model、`legacy_quiz_{operation}:1.0`、认证 owner、请求 trace、尝试序号、Token 估算和 completed/failed 终态，不保存题目、答案、画像或学生正文到摘要。
- 独立 Schema：基础/自适应出题使用 `QuizGenerationOutput`；主观判卷使用 `QuizGradingOutput` 和四维严格分数；相似题使用 `SimilarQuizOutput` 并保留 python_validator。三类契约均拒绝额外字段、缺字段、越界分数和非法难度，不用宽松字段回填伪装成功。
- 重试审计：相似题最多三次模型生成共享一次 `m5-quiz-*` trace，每次保留独立 call ID 和 attempt；结构失败为 failed/quiz_output_invalid，供应商失败为 failed/quiz_provider_failed，取消为 failed/client_disconnected，后续重试成功不会覆盖前一失败。
- 课程边界：旧 `quiz_records` 没有可靠 course_id，调用记录只绑定认证 owner，不从请求体概念或学生字段伪造课程归属。后续 canonical assessment 全量迁移时再从冻结题目版本派生课程。
- 兼容降级：各端点继续使用原有 fallback quiz、判卷 fallback 和相似题最终兜底；失败记录与回退结果区分，不把 fallback 写成模型成功。
- 自动验证：共享边界、量化评估和真实旧代码题 API 专项 `12 passed, 6 warnings in 8.23s`；全部 M5、安全、Swarm 与成员 6 回归 `112 passed, 6 warnings in 28.13s`。
- 外部数据：使用虚拟/确定性后端，无外部模型调用，无题目、答案、画像或密钥外发。
- 下一步：先给 `/api/stream/regenerate` 透传认证 owner、可验证 course 和独立 trace，复用现有资源生成生命周期；再将 `/api/stream/explain` 的 Consultant 严格 JSON 与 Teacher 流式/同步调用统一治理。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-026 - 量化评估严格输出与 Matrix 归属追踪

- 状态：`PASS（M5-005/M5-011 量化评估迁移批次）`，M5 总体仍为 `IN_PROGRESS`。本批保留 `LearningSignal`、原确定性回退公式和资源包响应，不把模型自评描述为真实学习成绩或人工质量验收。
- 严格结构：新增 `QuantitativeEvaluation`，强制 accuracy、completeness、depth_match 均在 0~1 且 needs_replan 为布尔值；替换手工 `json.loads` 和静默默认字段，越界、缺字段、额外字段或非 JSON 输出均不能进入成功结果。
- 调用治理：实际评估调用使用 `legacy_quantitative_evaluation:1.0` 和 evaluate 能力，成功为 completed；供应商异常为 failed/evaluation_provider_failed；结构异常为 failed/evaluation_output_invalid；任务取消为 failed/client_disconnected 且继续抛出取消，不被通用回退吞掉。
- 归属与 trace：两处 Matrix 评估调用均透传认证 owner、course 和本次 `m5-matrix-*` parent trace；资源 Agent 和评估调用可按一次请求聚合，同时各自保留独立 call ID、Token 估算和终态。
- 隐私：调用摘要只保留资源数量、资源类型和是否有画像，不保存画像概念、掌握度、资源正文或原始 Prompt；完整输入仍只发给当前请求选择的模型后端，不复制进审计表。
- 兼容降级：供应商或结构失败后使用既有确定性资源覆盖/认知负荷公式；失败调用仍留下真实审计记录，不把回退结果伪装为模型评估成功。
- 自动验证：评估、Matrix、Swarm 和画像专项 `12 passed in 7.63s`；全部 `test_m5*.py`、安全契约与 Swarm 回归 `95 passed, 5 warnings in 32.20s`。尝试加入整个 `test_multimodal_chat.py` 的更大组合在 180 秒工具上限终止，未形成结果且未记录为通过；该历史长套件与本批评估路径无直接修改面。
- 外部数据：使用虚拟后端，无外部模型调用，无课程、画像、资源正文或密钥外发。
- 下一步：统一 `quiz_api.py` 四处考官生成调用，先抽取共享严格题目输出与审计服务，再保持各端点旧响应和现有评分/脱敏行为；随后处理局部再生成与苏格拉底双 Agent。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-025 - 唯一工程基线与超长任务状态防回退

- 状态：`PASS（工程基线批次）`，M5 总体仍为 `IN_PROGRESS`。M2、M3、M4 的既有关闭结论保持不变，本批不重新验收或重新开发这些阶段。
- 迁移并发：SQLite 注册迁移在读取历史前使用 `BEGIN IMMEDIATE`，4 个并发调用者专项验证迁移集合精确、版本唯一且 `PRAGMA integrity_check=ok`。
- 依赖与运行库：`requirements.txt` 已声明 `nbformat>=5.10.0`，项目 `.venv` 安装版本为 `5.10.4`；`.gitignore` 忽略根目录 `edumatrix.db`，运行数据库已从当前 Git 索引移除，不删除现有用户数据库文件。
- 测试隔离：新增进程级 `tests/conftest.py`，在应用模块收集前设置唯一 OS 临时目录和 `EDUMATRIX_DB_PATH`，随后执行完整 `init_db()`。这修复了全局 `SessionLocal` 运行时测试落入项目库或在临时库中因 `model_calls` 缺表而静默降级的问题；进程退出只清理本轮临时目录。
- 解释器统一：第一次系统 Python 全量结果为 `427 passed, 2 failed`，其中 Windows worker 测试正确识别出解释器不是项目 `.venv`；另一项意图测试因隔离库未初始化而被兼容分支放行。改用项目 `.venv` 并初始化测试 Schema 后，两项聚焦复测为 `2 passed`。
- 唯一全量基线：执行 `.\\.venv\\Scripts\\python.exe -m pytest -q`，结果为 `429 passed, 6 warnings in 87.60s`，0 收集错误。warning 仅为 FastAPI/Starlette 生命周期弃用、TestClient 兼容提示及既有 PyTorch 张量转换提示。
- 防回退状态：新增 `outputs/00_MASTER_EXECUTION_STATE.md`，固定用户最新指令、主状态文件、阶段索引、WORKLOG2、总方案和旧目标的冲突优先级；明确 M2-M4 为 CLOSED，当前唯一主阶段为 M5，并写入精确下一批和更新协议。上下文压缩或模型切换后必须先读该文件，旧目标不得重新打开已关闭阶段。
- 外部数据：本批未调用外部模型，未发送课程、画像、用户输入或密钥。
- 下一步：严格从 M5-005/M5-011 的旧 AI 入口统一断点继续，优先量化评估、quiz 生成、局部再生成和苏格拉底式回答；每批聚焦回归并即时更新本日志和主状态文件。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-024 - PK 对抗挑战严格输出与调用追踪

- 状态：`PASS（M5-005/M5-010/M5-011 PK 迁移批次）`，总体仍未全量完成。本批不改变 PK 的 SSE、挑战展示、历史记录或静态高难度兜底。
- 独立服务：内联长 Prompt、模型调用、Markdown fence 清理和手工 `json.loads` 被提取为 `_generate_peer_challenge`。输出由 `PeerChallenge` 严格约束，只允许 wrong_code、wrong_reason、correction_instructions 三个非空限长字符串，额外字段被拒绝。
- 调用治理：使用 `legacy_peer_challenge:1.0`、code 能力和 owner/course 归属；调用前 running，供应商异常 failed/provider_call_failed，JSON/Schema 异常 failed/structured_output_invalid，取消 failed/client_disconnected，成功 completed。摘要只记录是否有历史上下文，不保存概念、对话正文、代码或纠错答案。
- 兼容降级：动态调用失败后继续进入原有按池化/注意力/反向传播分类的高难度静态挑战，不中断演示；确定性后端若不支持该严格结构会留下真实结构失败记录，而不会伪装动态生成成功。
- 自动验证：成功、供应商失败和结构失败三种隔离 SQLite 路径均有独立断言，原始概念与历史不落摘要；PK/上下文专项 `13 passed`。全部 M5、安全契约加真实 Matrix 命令为 `90 passed, 4 warnings in 10.17s`。
- 外部数据：本批使用虚拟后端，无外部模型调用，无对话、课程、画像或密钥外发。
- 仍未完成：PK 目前没有专门的题目版本/作答评测 canonical 对象；量化评估、指代消解、quiz、再生成、教学规划和苏格拉底调用仍未完全迁移；完整 policy/fallback/quota 仍未覆盖兼容 lifecycle。
- 下一步：从 `EffectEvaluatorAgent._async_llm_evaluate` 开始迁移严格量化评估；随后统一 quiz 四处考官生成，最后处理再生成/苏格拉底流并产出旧 AI 调用扫描差异报告。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-023 - Matrix 资源 Agent parent-child 调用追踪

- 状态：`PASS（M5-005/M5-006/M5-011 Matrix 子调用迁移批次）`，总体仍未全量完成。一次 Matrix 请求下的资源 Agent 现在可按同一 trace 聚合，同时保留每个实际供应商调用的独立终态与成本信息。
- Trace 设计：`StreamingModelCallLifecycle` 支持调用方提供 trace ID；`EduMatrixSwarm.async_process` 每次创建 `m5-matrix-*` parent trace，并沿 `factory.generate_all` 透传至 `AsyncInstructRAGGenerator.generate`。未新增冗余数据库表，仍使用 `DBModelCall.trace_id` 聚合。
- 子调用记录：每个资源 Agent 在真实 `llm.generate` 前创建独立 call ID，摘要含 agent_role、resource_type 和 evidence_count；成功写 completed，供应商异常写 failed/agent_provider_failed，取消写 failed/client_disconnected。owner/course 与 parent trace 同步透传。
- 非调用分支：对齐重试时复用 previous_resources 的缓存分支不建记录；已有代码 refinement 本地分支不建记录；只有真正执行模型的资源 Agent 计入调用与 token，避免成本虚增。
- 异常语义：资源工厂使用 `asyncio.gather(return_exceptions=True)` 后可能生成降级资源，但子生成器会在异常被外层接管前先写 failed，因此不会遗留 running，也不会把降级产物误记为供应商成功。
- 自动验证：新增生成器级测试证明两个 Agent 共享 trace、call ID 独立、角色可区分、原始 query 不落摘要；失败 Agent 终态正确。Matrix 专项 `2 passed`；全部 M5、安全契约加真实 `/matrix` 命令为 `87 passed, 4 warnings in 9.46s`。
- 外部数据：使用确定性/虚拟后端，无外部模型调用，无课程、画像、用户输入或密钥外发。
- 试错记录：首版补丁因同步和异步生成器存在同名 `generate`，把新参数加到了同步签名，异步函数引用未定义变量；专项在任何 DB 写入或模型调用前以 TypeError 停止。将参数移到正确异步签名后 `2 passed`，完整回归通过。
- 仍未完成：parent trace 当前是关联标识，不是独立 `agent_runs` 父记录；量化评估、指代消解、PK、再生成、苏格拉底和 quiz 仍有直接模型调用；精确 provider usage 与 policy/quota 尚未统一到所有子调用。
- 下一步：迁移 PK 挑战严格 JSON 生成，替换手工 fence 清理与 `json.loads`；之后处理量化评估和 quiz，再生成/苏格拉底流最后迁移。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-022 - Chat/Swarm 共享意图分类服务与归属透传

- 状态：`PASS（M5-005/M5-011 共享分类迁移批次）`，总体仍为 `IN_PROGRESS`。本批消除 chat 与 Swarm 两套分类实现，不宣称资源 Agent 子调用已统一。
- 模块边界：新增 `app/m5_intent.py`，集中严格 `IntentClassification`、治理 Prompt、Gateway 调用、模型兼容注册和故障放行。`stream_api` 保留原 `_classify_academic_intent` 名称作为兼容包装；`EduMatrixSwarm._check_academic_intent` 调用同一服务，避免从 Swarm 反向导入 API 模块造成循环依赖。
- 归属传播：`EduMatrixSwarm.async_process` 新增可选 `owner_public_id/course_id`，旧调用签名继续兼容；流式 Matrix 入口传入认证用户和 canonical tutor course。Swarm 内部分类与画像探针均接收同一归属，后续模型记录可按用户/课程审计。
- 测试隔离：共享服务的 session factory 在运行时解析，避免 Python 默认参数提前捕获 `SessionLocal` 导致 monkeypatch 后仍连接工作库。新增轻量测试证明 Swarm 包装器复用共享服务并完整透传 llm/message/owner/course。
- 自动验证：共享分类与画像专项 `13 passed`；全部 `test_m5*.py` 加安全契约为 `84 passed, 4 warnings in 8.69s`。没有循环导入或接口回归。
- 外部数据：本批无外部模型调用，没有发送用户消息、课程数据、画像或密钥。
- 仍未完成：`app/main.py` 和同步 `process()` 等无认证上下文调用仍不会有 owner/course；Matrix 资源 Agent 主要经 `AsyncInstructRAGGenerator` 间接调用，尚无 parent trace/per-agent records；PK、再生成、苏格拉底和 quiz 仍有直接调用。
- 下一步：为 Matrix 创建 parent trace 上下文并在 `AsyncInstructRAGGenerator` 每次真实模型调用外层建立 child lifecycle；先核对缓存命中、代码 refinement 和确定性分支，确保未调用模型的路径不产生记录。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-021 - 建议追问调用追踪与剩余调用面扫描

- 状态：`PASS（M5-005/M5-011 建议追问迁移批次）`，总体仍为 `IN_PROGRESS`。本批同时完成旧 AI 入口静态扫描，但扫描不是全量迁移完成证明。
- 建议追问：`_generate_suggested_questions` 接收可选 owner/course，实际模型调用使用 `legacy_suggested_questions:1.0` 生命周期；成功记录 completed，供应商异常记录 failed/provider_call_failed，取消记录 failed/client_disconnected。输入摘要只记录是否存在画像上下文，不保存概念、画像文本或生成问题。
- 产品语义：模型返回不足三题但供应商正常完成时，调用仍记 completed，产品层改用三条确定性兜底；这一区分了“供应商执行失败”和“内容质量不足”。concept 为空时直接返回静态默认问题，零模型调用且不产生虚假账单。
- 自动验证：隔离 SQLite 覆盖成功/失败终态、Prompt 版本、原概念不落摘要和静态路径零调用；专项 `10 passed`。全部 `test_m5*.py` 加安全契约为 `83 passed, 4 warnings in 9.04s`。
- 剩余调用面：静态扫描确认 `agent_swarm.py` 仍有指代消解、量化评估、资源生成与 Swarm 内部意图分类；`stream_api.py` 仍有 PK 挑战、再生成、教学规划和苏格拉底流；`quiz_api.py` 有 4 处考官生成。Matrix 资源生成主要经 `AsyncInstructRAGGenerator` 间接调用，不能只包 `async_process` 表层就宣称各 Agent 已追踪。
- 外部数据：本批仅用虚拟后端，无外部模型调用，无用户画像、课程内容或密钥外发。
- 仍未完成：Swarm 内部意图分类与聊天分类重复；parent trace/child calls 尚未建立；调用注册仍为兼容标识，未统一 policy/fallback/quota；非流式建议问题仍使用估算 token。
- 下一步：将共享意图分类下沉到独立 M5 服务模块，供 chat 与 Swarm 复用，消除重复未治理实现；随后为 `AsyncInstructRAGGenerator` 注入 parent trace 与 per-agent lifecycle，再迁移 PK 和 quiz 生成。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-020 - 画像探针模型调用与知识点白名单治理

- 状态：`PASS（M5-004/M5-005/M5-011 画像探针迁移批次）`，三项总体仍未全量完成。治理放在复用的 `ProfileProbeAgent` 内部，使聊天、测验和 Matrix 调用共享同一边界；聊天入口额外传递 owner 与 canonical course。
- 调用边界：精确知识点快轨和 TTL 缓存命中不创建 `model_calls`，因为没有实际模型调用；只有 `_async_extract_with_llm` 真正请求模型时创建 `legacy_profile_extraction:1.0` 生命周期记录，成功/失败/取消均有终态。
- 输出治理：新增 `ProfileExtraction` 严格字段模型，限制 course/major 长度、目标/弱点/偏好数量、掌握度数值类型；JSON 只允许一个完整对象。Schema 通过后再次按当前课程动态 active concepts 过滤 weak_points 与 mastery_updates，模型不能向画像注入课程外知识点。
- 降级语义：无效 JSON、字段类型错误或供应商异常写 `failed/profile_output_invalid`，返回空模型增量；模型调用前的确定性基础画像更新仍保留，因此模型失败不撤销可信本地信号。取消写 `failed/client_disconnected` 并继续传播。
- 可测试性：`ProfileProbeAgent` 新增可选 `database_runner` 注入，生产默认仍使用全局短会话，隔离测试可使用内存 SQLite，不触碰工作库。测试覆盖快轨零调用、合法输出 completed、未知概念过滤、非法输出 failed 且非法字段不污染画像。
- 自动验证：画像与上下文专项 `10 passed`；全部 `test_m5*.py` 加安全契约为 `80 passed, 4 warnings in 7.61s`。警告仅为既有 FastAPI/Starlette 生命周期弃用。
- 外部数据：本批使用虚拟后端，没有调用外部模型，没有发送画像、消息、课程数据或密钥。
- 试错记录：首轮失败测试错误假设“模型输出失败时画像应完全不变”；实际设计先运行确定性基础更新，测试消息中的“分类”被合法识别。修正门禁为非法模型字段不得进入画像，保留可信本地更新，随后专项通过。
- 仍未完成：测验与 Matrix 旧调用没有传 owner/course，当前其模型调用可追踪但归属为空；画像 Schema 仍兼容 list/dict 两种 learning_state_causes，后续应统一 canonical 三画像事件；长期记忆查看、撤回、过期和用户控制尚未实现。
- 下一步：为 Matrix/Swarm 建立 parent trace 与各 Agent 子调用记录，并让所有调用方传 owner/course；随后迁移建议问题、PK 等剩余直接 LLM 调用，生成旧 AI 入口扫描报告。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-019 - 外部视觉 OCR 调用追踪

- 状态：`PASS（M5-005/M5-011 OCR 迁移批次）`，总体仍为 `IN_PROGRESS`。本地确定性启发式 OCR 不伪装为模型调用；实际进入外部视觉后端的链路才创建调用记录。
- 实际路由：OCR 优先使用 LLM 暴露的 `external_vision_backend`，避免主文本模型内部再路由备用视觉节点而导致审计 provider/model 与实际供应商不一致；无独立视觉后端时保持原调用对象和降级行为。
- 生命周期：视觉调用使用 `legacy_multimodal_ocr:1.0`，调用前写 running，完成写 completed，供应商异常写 failed/vision_provider_failed，取消写 failed/client_disconnected。记录 owner、canonical course、实际视觉 model、token/耗时/输出哈希。
- 图片隐私：`input_summary` 只保存 operation、image_count 和 image_encoded_chars，不保存 data URI、Base64、图片内容、用户问题或 OCR 结果；模型输出同样只留哈希和长度估算。供应商失败继续返回原保守占位描述，聊天链路不因 OCR 不可用整体中断。
- 自动验证：隔离 SQLite 覆盖视觉成功和失败终态、Prompt 版本、图片数量/长度以及 Base64/问题正文不落摘要；真实确定性多模态聊天专项通过。全部 `test_m5*.py` 加安全契约为 `77 passed, 4 warnings in 5.01s`。
- 外部数据：本批只使用测试内虚拟 data URI 与虚拟后端，未调用外部模型，未发送真实图片、课程来源、用户数据或密钥。
- 仍未完成：视觉调用当前使用兼容注册信息而非完整 policy/quota；供应商 usage 尚未回填精确 token；画像探针、建议问题、PK 生成、Matrix/Swarm 子调用仍存在直接模型调用。
- 下一步：审计 profile probe 的内部模型调用与持久化边界；随后为 Matrix/Swarm 设计 parent trace 和子调用记录，避免只记录最终聚合答案而遗漏各 Agent 成本与失败。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-018 - 结构化意图分类统一 Gateway 迁移

- 状态：`PASS（M5-005/M5-011 意图分类迁移批次）`，总体仍为 `IN_PROGRESS`。本批只迁移聊天入口的学术/闲聊分类，不宣称 OCR、画像探针或 Matrix/Swarm 已迁移。
- 严格结构：意图输出改为 `_IntentClassification`，强制 `is_academic:boolean`、非空且限长 reason、限长 reply；学术意图必须返回空 reply，非学术意图必须以治理标题 `## 智能答疑 / 系统说明` 开头。类型或业务语义不合法均按 `structured_output_invalid` 记录失败。
- Gateway 调用：分类请求使用 `legacy_intent_classification:1.0` Prompt 版本、answer/fast 能力契约和后端 provider/model 标识，经 `M5ModelGateway.execute` 统一创建 `model_calls`。记录 owner、canonical course、token/耗时/哈希和非正文摘要，不保存用户消息或返回正文。
- 兼容与降级：合法分类继续维持原闲聊引导和学术问答分支；供应商异常、JSON 错误或 Schema 错误保持原产品策略“放行到学习回答”，但现在失败有可审计终态，不再静默吞掉所有诊断。确定性演示后端新增同 Schema 的本地意图分类，不依赖外部模型。
- 自动验证：隔离 SQLite 断言合法 JSON 产生 completed、非法 Schema 产生 failed/structured_output_invalid、原始消息不进入 input_summary；真实闲聊 TestClient 分支保持通过。全部 `test_m5*.py` 加安全契约为 `75 passed, 4 warnings in 5.14s`，警告仅为既有生命周期弃用。
- 外部数据：本批没有调用外部模型，没有发送文本、图片、课程来源、用户数据或密钥。
- 试错记录：首版误将旧业务容器 `AgentOutput` 当作 Pydantic 输出基类；`py_compile` 不会发现该运行时类型问题。静态核对后在运行测试前改为项目 `StrictModel`，随后专项与完整回归均通过。
- 仍未完成：当前分类 Gateway 使用后端当前模型构造兼容注册，尚未接入租户 policy/fallback/quota；异常放行是可用性优先策略，不等于分类可靠性通过独立评测。OCR、profile probe、建议问题及 Matrix/Swarm 子调用仍绕过统一追踪。
- 下一步：迁移 OCR/多模态描述调用，要求图片原文不落审计摘要、记录视觉模型实际 provider/model 和失败终态；随后处理画像探针和 Matrix/Swarm parent-child trace。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-017 - 流式模型调用生命周期与主回答追踪

- 状态：`PASS（M5-005/M5-011 主回答流迁移批次）`，两项总体仍为 `IN_PROGRESS`。本批迁移聊天模式的主回答 provider stream，不宣称意图分类、OCR、画像探针或 Matrix/Swarm 子调用已统一。
- 可复用生命周期：`app/m5_gateway.py` 新增 `StreamingModelCallLifecycle`。供应商调用前创建 `model_calls.status=running`；成功后写 `completed`，供应商流异常写 `failed/provider_stream_failed`，客户端断连或任务取消写 `failed/client_disconnected`。DB 现有状态约束只有 running/completed/failed，因此取消使用 failed 加明确错误码表达，未篡改既有数据库约束。
- 可观测性：记录 trace/call ID、owner、canonical course、能力、Prompt key/version、provider/model、输入/输出 token 估算、耗时、估算成本和输出 SHA-256。输入摘要只含字符数、模式、是否含图、上下文 ID 和来源数量，不保存 system/user prompt、引用正文、模型输出或 API Key。
- 异步与数据库边界：生命周期每次状态变更通过短会话 `run_db_op` 执行，不把 SQLAlchemy session 跨异步流长期持有；终态具有本地幂等锁，后续重复 complete/fail 不会覆盖首个终态。断连路径以 `asyncio.shield` 尽力先写终态再传播取消。
- 兼容迁移：`/api/stream/chat` 的聊天模式主回答继续使用原 `generate_stream` 和原 SSE `progress/chat_chunk/complete` 协议，只在外层增加审计生命周期；deterministic 测试模型与后端配置模型均记录真实 provider/model 标识。没有改写 1000 余行旧编排，也没有改变 RAG、安全审查、画像更新或建议追问逻辑。
- 自动验证：生命周期与 tutor context 聚焦 `10 passed`；聊天主回答真实 TestClient 分支 `1 passed`；全部 `test_m5*.py` 加 `test_security_contracts.py` 为 `73 passed, 4 warnings in 5.22s`。警告仅为 FastAPI/Starlette 生命周期弃用。测试覆盖 running、completed、provider failure、client disconnect、首终态不被覆盖、输出哈希及原始输入/输出不落摘要。
- 外部数据：本批未调用外部模型，未发送课程内容、三画像、用户数据或密钥，也未消耗外部 token。
- 试错记录：首次完整回归命令把 `tests/test_m5*.py` 直接交给 Windows pytest，PowerShell 未展开通配符，结果为 no tests ran；随后先由 PowerShell 枚举绝对测试路径再执行，73 项全部通过。该命令问题未修改代码或数据库。
- 仍未完成：意图分类、OCR、profile probe、建议问题和 Matrix/Swarm 多智能体调用仍绕过统一生命周期；流式调用当前使用估算 token，尚未消费供应商 usage；主回答虽然已追踪，但尚未改成基于模型注册和策略选择的完整 `execute_with_policy` 流式版本。
- 下一步：先把结构化意图分类接入统一 Gateway 的严格 Schema 和策略路由，再迁移 OCR/多模态调用；之后为 Matrix/Swarm 建立 parent trace 与每个子调用记录，最后核对所有旧 AI 入口是否仍存在直接 provider 调用。
- 时间：2026-08-02（Asia/Shanghai）。

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

## WL2-M5-20260802-010 - M5 首轮审计与计划工作台可演示闭环

- 状态：`PASS（M5-001 首轮审计）`；`PARTIAL（M5-008，可演示闭环 PASS）`。本批没有把阶段 7 全量门禁误标为完成。
- 审计结论：M5 后端已有能力契约、网关、任务、质量、资源、学习、测评和上下文教师等 10 个聚焦测试文件，进入本批前真实基线为 `34 passed, 5 warnings`。统一模型入口仍有大量旧调用，计划/路径和上下文工作台前端明显落后于后端；因此先闭合已经具备正式数据对象的计划执行链，而非重复铺设模型网关骨架。
- 后端列表与恢复：新增认证 `GET /api/v1/m5/planning-targets`、`GET /api/v1/m5/plans` 和 `GET /api/v1/m5/paths`。目标目录只返回公开课程、本人拥有课程或有 active membership 的课程章节，以及本人未归档 artifact；计划和路径列表严格按 `owner_public_id` 隔离，支持课程和归档过滤，页面刷新后不依赖 localStorage 旁路恢复。
- 前端工作台：新增 `/workspace`、学生导航“计划工作台”、M5 API 客户端和 `LearningWorkspace.vue`。支持从真实章节/本人资源选择正式节点，扩展节点必须单独勾选并填写理由；支持节点排序、时长范围、草稿创建、不可变新版本、确认后正式路径、暂停/恢复、今日任务，以及弱访问证据与延迟复测强证据提交。
- 确认门禁：浏览器 E2E 创建 1 个计划草稿后直接查询正式 API，确认 `plans=1`、`paths_before_confirmation=0`；点击确认后才创建 active 路径。访问事件只将节点推进到 `in_progress`，不会假装掌握；`delayed_retest_passed` 才完成节点，单节点路径随之完成，今日任务自动排除已完成内容。
- 恢复与视觉：刷新后路径和节点保持 `completed`；1440×1000 桌面与 390×844 移动端均完成真实浏览器截图和目视检查，未发现文字溢出、重叠或异常空白。生产构建转换 3104 modules，新页面独立 JS gzip 约 `5.42 kB`；唯一大 chunk 警告仍来自既有 `StudentAnalysis`。
- 正式证据：`evidence/learning-workspace-e2e-20260802/`，包含 5 张截图、后端日志、结构化 `report.json`、SQLite 官方 backup 生成的 `m5_workspace_evidence.db` 和 `manifest.json`。数据库 `integrity_check=ok`；manifest 实际/清单均为 8 文件，集合一致且 SHA-256 零异常，不依赖 WAL/SHM。
- 自动验证：课程/资源可见性和 owner 隔离新增 2 项 API 测试；M5 全明确文件回归为 `36 passed, 5 warnings in 2.87s`，警告仅为 FastAPI/Starlette 生命周期弃用提示。OpenAPI 确认目标、计划、路径和今日任务静态路由均存在且没有被参数路由遮蔽。
- 仍未完成：12 类事件尚未全部从旧前端、播放器、沙箱和后端双写到 canonical Schema；事件仍不更新 BKT/IRT/MIRT、画像、复习日期或仪表盘；今日任务未合并到期复习、教师任务、负荷冲突、不可用时间和提醒；动态降维/补先修/巩固/进阶候选、版本确认/撤销，以及企业免修、高风险必修、批次/导师/环境容量和主管审批均未实现。
- 下一步：优先实现 M5-010 统一题目/尝试版本、隐藏答案权限、错因确认和统一复习队列，并把真实测评证据消费回计划；随后补 M5-009 当前上下文教师页面，再处理 M5-005 旧 AI 入口的分批迁移。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-016 - 旧流式聊天绑定 canonical tutor context

- 状态：`PASS（M5-005/M5-011 第一条旧 AI 入口迁移）`，M5-005 与 M5-011 总体仍为 `IN_PROGRESS`。本批只关闭旧聊天无法携带正式上下文的问题，保持原 SSE 事件、无上下文请求、Matrix 模式、多模态参数和前端消息结构兼容；尚未把实际模型执行接入 M5 Gateway 调用记录。
- 服务端契约：`POST /api/stream/chat` 新增可选 `context_session_id`。在创建 `StreamingResponse` 和任何模型调用前，服务端从 `tutor_context_sessions` 读取对象，验证存在、本人所有权和 active 状态，并复用 `tutor_prompt_envelope` 形成 `generation_started=false` 的冻结请求。未知上下文 404、跨 owner 403、归档上下文 409，均不会进入 SSE 或调用模型。
- 来源边界：从 tutor snapshot 提取 canonical `source_document_id`，查询正式 `DBSourceDocument.filename` 并加入旧 RAG 的 `doc_constraints`；同时把 primary title、retrieval_scope、教学设置、source_ref、page、content hash 与 quote 注入系统提示，明确只允许使用冻结引用且不得伪造页码/来源。初版曾误用接收旧知识文档 ID 的 `LegacyReadRepository.knowledge_filenames`，在测试前审计发现并改为 canonical source 查询。
- 前端兼容：`streamChat` 与 Pinia `sendChatMessage` 在原参数末尾增加可选上下文 ID，默认空值保持所有旧调用行为。上下文教师页在 preflight ready 时提供“使用该上下文进入智能对话”，通过路由携带 ID 和问题；`Chat.vue` 的普通发送、Matrix 发送、建议追问与两类重新生成均持续传递同一上下文，避免首轮受约束而后续静默丢失。
- 密钥审计：`Settings.vue` 已经只测试后端连接，并在 mounted 时清理历史 `edumatrix_llm_config`；`common.js` 不发送模型密钥头，`swarm_factory.py` 明确忽略外部 endpoint/model/secret 请求头。因此本批没有重复修改设置页，浏览器端密钥专管门禁继续由 `test_security_contracts.py` 覆盖。
- 自动验证：新增 `tests/test_m5_stream_context.py`，服务层断言本人上下文解析不启动生成、教学设置、quote/page/hash、canonical filename 约束；越权和归档拒绝；真实 HTTP 端点证明另一用户在 SSE 前收到 403。迁移、安全与 workspace 组合 `22 passed`；合并后 M5 聚焦回归 `47 passed, 4 warnings in 13.06s`；Vue 构建 `3106 modules transformed` 成功，仅既有 `StudentAnalysis` 大 chunk 警告。
- 旧聊天回归：`tests/test_multimodal_chat.py` 首轮整套执行 `26 passed, 1 failed`，失败项为固定学生 `test-multimodal-student` 的多轮记忆内容断言，耗时约 153 秒；该项单独复跑 `1 passed`，确认属于套件共享固定学生历史/顺序污染，不是本批无上下文链路回归。本批没有通过放宽产品逻辑或删除断言掩盖该问题，后续应把旧套件改为每项唯一用户或清理全部会话记录。
- 试错记录：新异步测试最初使用本机未安装的 `pytest-asyncio` 标记，改为标准库 `asyncio.run`；随后测试用户漏填非空 `hashed_password`，补齐夹具后通过。一次构建命令误在仓库根目录寻找 `D:/package.json`，未执行构建，之后在 `frontend/` 正确运行并通过。上述失败均未触及正常数据库或外部模型。
- 仍未完成：旧聊天内部有意图分类、OCR、profile probe、直接回答、Matrix 1+3+5、多处独立 LLM 调用和流式生成；当前只统一了身份、上下文和来源前置边界，模型调用尚未持久化到 `model_calls`，token/cost 仍为旧估算，不能宣称整个聊天已通过 Gateway。上下文教师在运行依赖不 ready 时不会显示跳转按钮，正式模型回答需后端模型可用。
- 下一步：为流式链路设计兼容 Gateway 的 streaming call lifecycle，先统一创建 `model_calls` running 记录、完成/失败/取消终态、prompt 版本、来源摘要和 token 估算，再迁移主回答生成；结构化意图分类与 OCR 分支分批接入，避免一次性改写 1000 行旧编排。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-015 - 来源可追溯的上下文教师工作台

- 状态：`PASS（M5-009 来源精读工作台批次）`，M5-009 总体仍为 `PARTIAL`。本批关闭正式 tutor context 缺少前端、恢复和浏览器证据的问题；尚未把旧聊天迁移到统一 Gateway，也没有把调用前检查伪装成教师回答。
- 正式前端：新增 `TutorWorkspace.vue` 和认证课程作用域路由 `/tutor-workspace`，接入学生侧栏。页面复用 M5 规划目标目录与 M1 canonical 课程大纲/来源 API，可选择课程、章节/来源/本人资源、当前资源/当前课程/个人资源/允许外部检索四种范围，以及教学风格、讲解深度、引导模式、公式和视频时间点。
- 来源精读：课程章节自动解析正式 `source_ref`，用户可选择最多 8 条来源。冻结后的快照展示 quote、页码或文本定位、字符范围、SHA-256 内容哈希和 parser 版本；客户端不能自行填写引用文本冒充教材证据。刷新后从数据库恢复同一快照，并支持多个 active context 切换和乐观锁归档。
- 真实性门禁：问题和 intent 只调用 `/preflight` 构造 `m5.tutor-request.v1`，页面固定显示“尚未调用模型”；结果明确展示 `generation_started=false`、来源数量、意图、真实运行依赖和 blockers。本批没有向外部模型发送课程或用户数据，也不消耗外部模型额度。
- 权限与 HTTP：新增真实 TestClient 契约，验证本人创建、列表恢复、来源 quote/hash、无模型时 `text_model_unavailable`、跨课程来源拒绝、另一用户列表为空以及读取/预检/归档全部 403、本人归档后默认列表隐藏且审计列表可见。与既有服务层测试合计 `9 passed`。
- 浏览器证据：新增 `scripts/e2e_m5_tutor_workspace.py`，使用隔离 SQLite、deterministic provider 和本机无头 Chromium。真实完成 M0 课程选择、来源选择、close_reading/deep/socratic 上下文创建、问题预检、刷新恢复、另一用户三类越权拒绝和 390×844 移动端展示。证据位于 `evidence/tutor-workspace-e2e-20260802/`：5 张截图、结构化 `report.json`、后端日志、自包含数据库及 manifest；SQLite integrity 为 `ok`，manifest 8/8 文件，SHA-256 零异常。
- 视觉检查：桌面证据中侧栏、来源选择、来源快照、问题输入和预检结果在 1440×1000 视口内无重叠；生成状态在首屏和结果区均清晰显示。移动端改为单列，来源快照可见，未发现文本遮挡或横向结构破坏。
- 回归与构建：完整 M5 聚焦组合 `44 passed, 4 warnings in 12.24s`；Vue 生产构建 `3106 modules transformed` 并成功。警告仅为既有 FastAPI/Starlette 生命周期弃用和 `StudentAnalysis` 大 chunk，不影响本批断言。
- 附带修复：回归发现 `trusted_local` 子进程设置 `PYTHONNOUSERSITE=1`，而 Windows 作品环境的 NumPy 位于用户 site-packages，导致安全允许列表中的正常 NumPy 示例无输出。现改为继续清除项目 `PYTHONPATH`、密钥环境变量并使用临时目录，但允许 Python 用户依赖目录；恶意 `os` 与 raw `__import__` 拦截和 NumPy 正常输出专项均通过。安全声明不变：该模式仅适合可信本机研究演示，不具备容器隔离。
- 试错记录：首次 E2E 因系统 Python 缺少 Playwright 客户端而在导入阶段停止；安装 `playwright==1.55.0` 后发现对应 Chromium 缓存缺失，安装官方 Chromium 140 运行时。页面首次启动后，测试标签“课程”同时匹配来源文本，改为精确标签；随后错误等待隐藏的 HTML `option` 可见，改为等待选项数量；一次补丁存在 Python 引号语法错误，在启动任何进程前由 `py_compile` 发现并修复。最终 E2E PASS，且每轮失败后隔离后端和 Chromium 均已清理。
- 仍未完成：旧 `/api/stream/chat` 尚未接收 `context_session_id` 并走统一 Gateway；本批没有正式生成教师回答、持久化对话消息或消费模型调用预算。代码编辑器选区、视频时间轴、精读阅读位置、跨页共享侧栏和引用回跳仍待实现，不能据此宣称 M5-009 全量完成。
- 下一步：进入 M5-005/M5-011，审计旧 AI 入口并按低风险顺序迁移到统一 Gateway；优先解决浏览器 API Key/请求头动态模型和旧流式聊天绕过调用追踪的问题，同时保持旧响应兼容、流式体验和当前 tutor context 的来源边界。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-014 - 到期复测执行与强证据回流计划路径

- 状态：`PASS（M5-010 延迟复测闭环批次）`，M5-010 总体仍为 `PARTIAL`。客观题从错误作答、本人确认错因、24 小时排程、到期作答到强证据回流已形成正式闭环；完整题型与正式考试能力仍未全量完成。
- 到期门禁：新增 `RetestAttemptInput`、复测任务读取与提交 API。到期前提交返回冲突；任务 owner 隔离；客户端只能提交答案、置信度和时长，不能提交 score/correct。复测始终绑定原 immutable question version，读取载荷不含答案键、评分规则和解析。
- 服务端评分：复测复用 canonical `record_attempt`。客观题由冻结答案键评分；错误答案生成新的 immutable retest attempt，任务保持 due；简答、代码和开放题保持 `manual_required`，不会误判通过；只有 `grading_status=graded && correct=true` 才完成任务。相同幂等请求可重放，不同请求在任务关闭后拒绝。
- 计划目标门禁：正式计划的 assessment 节点现在可以绑定可用的冻结题目版本；草稿/未批准且非本人题目不能被他人加入正式计划，公开课程可读不等于可把草稿题纳入执行路径。题目课程与计划课程不一致时拒绝。
- 强证据回流：复测答对后，在同一数据库事务内完成任务并发布 `delayed_retest_passed` 学习事件，目标固定为 `question_version_id`；事件消费完成匹配的 assessment 路径节点并重新汇总路径状态。答错、未到期或 manual_required 均不会发布强证据。
- 队列语义：completed/cancelled 的错因复测任务退出统一待复习队列；独立 SM-2 计划继续保留。复习页加入脱敏题目读取、到期按钮、选项/文本答案和提交反馈；通过后显示“强证据已回流学习路径”。错题页 completed 状态显示“稳定掌握证据已形成并回流路径”，不再错误显示“尚未形成”。
- 自动验证：M5 明确测试加真实旧代码题 API 链路为 `52 passed, 6 warnings in 10.02s`；复测服务层 `13 passed`；学习节点与真实 HTTP 回流聚焦 `8 passed`。Vue 生产构建转换 3104 modules 成功，仍只有既有 `StudentAnalysis` 大 chunk 警告。
- 浏览器证据：更新 `evidence/misconception-retest-e2e-20260802/`，真实完成错误选择题、错因修改、排程、正式 assessment 计划确认、隔离测试时钟前移、复习页答对、错因项退出、路径和节点 completed、错题页刷新恢复及 390×844 移动端完成状态。数据库有 2 个 immutable attempts、1 个 misconception、1 个 completed retest task、1 个 `delayed_retest_passed` 事件和 1 条 completed path；SQLite integrity `ok`。manifest 8 个实际文件与清单一致，SHA-256 零异常。
- 试错记录：首轮完成后脚本错误要求整个统一队列为空，但展开错题卡自动生成了合法 SM-2 计划；修正为只要求 `misconception_review` 来源退出并记录剩余来源。随后脚本停留在复习页却查找错题卡，显式返回 `/wrong-questions` 后通过。两次失败的持久数据均证明强证据和路径回流已成功，不以放宽生产门禁解决测试问题。
- 仍未完成：multiple_choice、fill_blank 的规范化评分器，主观题教师/专用评分器审核，正式测验关闭与答案释放、自动保存/CAT、画像与掌握度订阅、PDF/DOCX 报告仍待续；M5-009 当前上下文教师完整前端和 M5-005 旧 AI 入口迁移也尚待完成。
- 下一步：进入 M5-009，基于已有可恢复 tutor context、来源预检和权限边界实现当前资源/课程上下文工作台，再以真实浏览器验证上下文切换、刷新恢复、引用边界和越权拒绝。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-013 - 学习者确认错因与延迟复测正式排程

- 状态：`PASS（M5-010 错因确认与排程批次）`，M5-010 总体仍为 `PARTIAL`。接受错因只创建复测任务，不会直接形成掌握证据。
- 自动候选：旧 `/api/quiz/evaluate` 在完成服务端评分和 canonical attempt 双写后，仅对 `accuracy_score < 0.6` 的错误作答幂等创建 `misconception_reviews` 候选。候选优先使用服务端判卷的误区描述；缺乏证据时标记 `insufficient_evidence`。证据仅保存 quiz ID、分数、后续动作和受信任来源，不保存 API Key、完整提示词或真实敏感数据。
- 学习者控制：`WrongQuestionBook.vue` 从旧错题列表读取 canonical diagnosis，展示“待你确认”，提供接受、修改为七类正式错因或拒绝三种操作。拒绝项不排程；接受/修改后保留本人说明、确认类别和决定状态，刷新后由数据库恢复，不依赖前端本地旁路。
- 正式排程：新增 `assessment_retest_tasks` 和注册迁移 `20260802_013`。任务唯一绑定一个已确认错因、原始 immutable attempt 和冻结 question version；最早到期时间强制为决定后 24 小时，状态限制为 scheduled/due/completed/cancelled。重复排程返回原任务，未确认或已拒绝错因不能排程。
- 统一队列：确认错因后的复习队列使用正式复测任务到期时间并返回任务状态；所有未完成任务固定 `stable_mastery=false`。UTC 数据库时间通过带 `Z` 的 ISO 8601 输出，浏览器正确转换为本地时区，避免少显示 8 小时。
- 自动验证：核心与 HTTP 聚焦组合 `13 passed, 5 warnings`；完整 M5 明确测试加真实旧代码题 API 链路 `50 passed, 6 warnings in 10.23s`；Vue 生产构建转换 3104 modules 并成功，仅保留既有 `StudentAnalysis` 大 chunk 警告。
- 浏览器证据：`evidence/misconception-retest-e2e-20260802/` 使用隔离 SQLite、deterministic provider 和本机无头 Chromium，真实完成 0 分选择题、自动候选、错题页修改为 knowledge_gap、24 小时后复测排程、刷新恢复和 390×844 移动端展示。SQLite `integrity_check=ok`，question attempt/misconception/retest 均为 1；manifest 6 个实际文件与清单一致，SHA-256 零异常。
- 试错记录：首轮使用 deterministic 主观题兜底，评分固定 0.6，正确地未触发 `<0.6` 错题门槛；改用隔离库确定性选择题秒判 0 分。第二轮页面脚本误点概念筛选卡而非错题记录，后端数据正常；将定位限定到错题卡后通过。初版全页截图不能清楚展示控件，最终改为目标滚入视口并等待折叠动画后截图，目视检查桌面与移动端均无重叠或溢出。
- 仍未完成：到期复测提交、服务端评分、答对后任务完成和 `delayed_retest_passed` 强证据回流计划路径尚未实现；当前任务只是已排程，不能宣称掌握。完整题型评分、正式测验关闭与答案释放、自动保存/CAT、画像订阅和报告导出仍待续。
- 下一步：实现到期门禁和复测提交；答错保持待复测，答对才完成任务并以冻结版本 ID 为目标发布强证据，使正式计划中的 assessment 节点可验证完成。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-012 - 旧测验不可变 canonical 双写

- 状态：`PASS（M5-010 双写批次）`，M5-010 总体仍为 `PARTIAL`。本批只关闭旧测验提交到 canonical question/version/attempt 的兼容缺口，不把完整题型、延迟复测和掌握度消费误标为完成。
- 受信任适配器：`app/m5_assessment_core.py` 新增仅供服务端调用的 `record_legacy_quiz_attempt`。它只接收数据库 `DBQuizRecord` 和 `/api/quiz/evaluate` 已在服务端计算的答案、分数、置信度、时长与尝试序号；公开 M5 尝试 API 仍禁止客户端提交 `score/correct`，没有新增可伪造评分的 HTTP 入口。
- 确定性映射：旧 `quiz_id` 经 SHA-256 派生稳定 canonical question ID；题干、选项、冻结答案、IRT 参数、来源和评分规则构造稳定内容哈希。选择题沿用旧评分器首字母大写规范化；无选项且题干含代码/Python/函数等标识时映射为 code，其余映射为 short_answer。旧来源统一标记 `origin=legacy`、`status=approved`。
- 不可变与幂等：同一旧题重复映射只产生 1 个 question 和 1 个 immutable version；`legacy-quiz-attempt:{quiz_id}:{attempt_number}` 固定尝试身份。相同载荷重放返回原 attempt，不同答案、分数、置信度或时长重放明确触发 `attempt_idempotency_conflict`；冻结后题目内容变化触发 `legacy_question_content_conflict`，不会静默篡改历史。
- 旧链路兼容：`/api/quiz/evaluate` 在既有 canonical learning evidence 事务中追加 assessment 双写，保留旧 `accuracy_score`、feedback、IRT/BKT/MIRT、错题入库、事件总线和 `canonical_evidence` 字段，并新增 `canonical_assessment` 返回 question/version/attempt ID、创建状态和内容哈希。canonical 写入失败会回滚该事务，不会伪装成功。
- 测试隔离修复：真实旧代码题 API 测试原先使用固定 quiz ID，重复运行后会与上轮冻结记录的不同临时用户发生所有者冲突。测试改为按本轮随机学生 ID 派生 quiz ID；生产冲突保护保持不变，未通过放宽所有者约束来掩盖问题。
- 自动验证：核心适配器 `10 passed in 1.21s`；真实 `/api/quiz/evaluate` 沙箱与三维 MIRT 专项 `1 passed`；完整 M5 明确测试加该真实旧 API 链路为 `48 passed, 6 warnings in 9.35s`。警告为 FastAPI/Starlette 生命周期弃用、TestClient 兼容提示和既有 BKT 张量转换提示，不影响本批断言。
- 仍未完成：错题页尚未展示并处理错因候选；已确认错因尚未形成可执行延迟复测任务并回流计划路径；多选、填空、简答、代码和开放题的专用评分流、正式测验关闭与答案释放、自动保存/CAT、掌握度和画像订阅、报告导出仍待实现。
- 下一步：接入错题页候选接受/修改/拒绝 UI，并让确认项生成延迟复测任务；通过延迟复测后发布强证据回流正式学习路径。
- 时间：2026-08-02（Asia/Shanghai）。

## WL2-M5-20260802-011 - Canonical 测评、错因确认与统一复习队列首批

- 状态：`PARTIAL（M5-010，canonical 首批 PASS）`。本批建立正式数据与安全契约，不宣称阶段 9 全量测评闭环完成。
- 正式对象：新增 `assessment_questions`、`assessment_question_versions`、`assessment_attempts` 和 `misconception_reviews`。题目身份与不可变版本分离；尝试只绑定冻结 `question_version_id`，不会因题目后续修改篡改历史；错因候选与用户决定分开保存。
- 数据库约束：注册迁移 `20260802_012`，校验 4 张表存在并建立 owner/time、owner/status 索引；题目版本和作答尝试在 SQLite 触发器层禁止 UPDATE/DELETE。干净数据库迁移顺序已扩展至 12 项，幂等及 checksum 机制保持不变。
- 防泄题与评分：学习者题目载荷只返回题干、选项、版本、难度、Bloom 层级和内容哈希，不返回 `answer_key`、评分规则或解析。客户端 Schema 禁止提交 `score/correct`，恶意注入返回 422；客观题由服务端按冻结答案键评分，简答/代码/开放任务进入 `manual_required`；正式测验策略返回中隐藏分数和正确性直至关闭。
- 权限：题目创建仅教师/管理员可调用，课程公开可读不等于可出题；教师必须是课程 owner、admin 或 active teacher/assistant membership。学习者读取和提交尝试前校验课程可见性；尝试 course_id 从题目版本派生，不接受客户端伪造课程归属。
- 错因控制：候选支持知识缺口、概念混淆、策略错误、计算失误、粗心、编程错误和证据不足，并保存理由、证据和模型置信度。候选未确认时不进入复习队列；学习者可以接受、修改或拒绝，拒绝项不会作为永久诊断或复习依据，重复决定被拒绝。
- 统一队列：`GET /api/v1/m5/review-queue` 聚合已确认/修改的错因诊疗项和既有 SM-2 `review_plans`，保留来源、排序理由、到期时间和优先级；所有项目固定 `stable_mastery=false`，复习入队不等于掌握。`Review.vue` 新增独立“统一待复习队列”区带，旧 SM-2 评分、删除和自适应解释操作保持不变。
- HTTP 合约：真实 TestClient 链路验证教师创建、学生脱敏读取、恶意分数注入拒绝、服务端错误答案判 0 分、错因确认前队列为空、用户修改为 knowledge_gap 后入队。owner 隔离、幂等冲突、正式测验隐藏结果和数据库不可变触发器均有独立断言。
- 自动验证：M5 明确测试文件加入 `test_m5_assessment_core.py` 后为 `44 passed, 5 warnings in 4.00s`；assessment/API/干净数据库迁移聚焦组合为 `17 passed`；Vue 生产构建 `3104 modules transformed` 并成功输出。警告仍仅为 FastAPI/Starlette 生命周期弃用提示和既有 `StudentAnalysis` 大 chunk。
- 未完成边界：旧 `quiz_records` 尚未双写 canonical question/version/attempt，不能声称所有历史答题已统一；错题页尚无候选接受/修改/拒绝 UI；多选、填空、简答、代码和开放题需要专用评分器/人工评分流；正式测验关闭与答案释放、自动保存/CAT、延迟复测调度、掌握度与画像消费、PDF/DOCX 报告仍待实现。
- 下一步：为旧测验提交建立确定性 canonical question/version/attempt 双写映射和幂等测试；随后把错因确认控件接入错题页，并让确认后的复习项安排延迟复测、通过后回流计划路径。
- 时间：2026-08-02（Asia/Shanghai）。
