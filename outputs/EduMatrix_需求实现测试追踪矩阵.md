# EduMatrix 需求—实现—测试—证据追踪矩阵

> **代码执行验收口径**：核心需求按无 Docker、默认禁用代码执行路径追踪；可选研究演示按 `trusted_local` smoke 追踪。后者是受限子进程验证，不等价于 Docker 容器安全隔离。

验证基线：Git `74f8f2715641da20b560571120a66477d300f5de`；结论以 2026-07-20 验证时的最终代码与证据为准。  
状态定义：已证实 / 部分实现 / 待验证 / 不满足或存在风险

## 1. 需求追踪总表

| ID | 需求/评分点 | 功能实现 | 代码证据 | 测试/运行证据 | 当前状态 | 最终材料 |
|---|---|---|---|---|---|---|
| C-01 | 至少 3 个明确 Agent | 9 个 AgentSpec 和对应类 | `agent_swarm.py:34-44` | 静态结构确认 | 已证实（结构） | 主文档 Agent 章节、截图 |
| C-02 | 分析—生成—校验—决策闭环 | 画像、规划、RAG、资源工厂、对齐、反馈 | `agent_swarm.py`、`stream_api.py` | 正式 pytest 145 passed、1 skipped；无 Docker E2E 覆盖核心注册/对话/路径闭环 | 部分实现（核心路径已证实） | 流程图、事件日志 |
| C-03 | 3 种以上个性化资源 | 讲义、导图、代码、练习、视频脚本 | `agent_swarm.py:929-938` | 需固定画像输出 | 已证实（任务） | 资源包截图 |
| C-04 | 学习者先验画像 | 专业、风格、动机、掌握度和历史 | `models.py`、`DBStudentProfile` | 种子/注册代码存在 | 已证实（结构） | 数据字典 |
| C-05 | 2 组差异化初始数据 | 种子学生、Peer 先验、注册冷启动 | `scripts/seed_students.py`、`app/crud.py` | 固定合成画像与注册冷启动证据已生成 | 已证实（演示数据） | 测试数据包 |
| C-06 | 3 组不同背景画像 | 可由画像模型表达 | `models.py`、`frontend`、`outputs/innovation_evidence/profile_cases.json` | 三组合成画像和同题结构性对比已运行 | 已证实（结构性演示；无真实用户实验） | 三组输入输出样例 |
| C-07 | 1 个垂直知识库切片 | 机器学习概念、题库、RAG | `scripts/data/quiz_bank/`、`rag_engine.py`、`outputs/innovation_evidence/fixed_knowledge_set.json` | 固定本地知识集检索返回证据，创新证据已生成 | 已证实（固定演示集） | 知识库切片 |
| C-08 | 个性化学习路径 | ZPD、图谱、掌握度、负荷 | `profile_api.py`、`agent_swarm.py` | 无 Docker E2E 学习路径通过；三画像结构性对比已生成 | 已证实（核心路径） | 路径图 |
| C-09 | 动态反馈更新 | 答题、错题、行为、事件总线 | `quiz_api.py`、`learning_event_bus.py` | 专项结构测试部分覆盖 | 部分实现 | 反馈日志 |
| C-10 | 学情可视化 | Dashboard、画像分析、流形、路径 | `frontend/src/views`、`components` | 前端构建通过 | 已证实（前端） | 截图 |
| C-11 | 多 Agent 协同可视化 | AgentTimeline、SSE 事件 | `AgentTimeline.vue`、`stream.js` | 无 Docker 浏览器 E2E 和截图证据已通过；完整外部 LLM 链仍需复核 | 已证实（默认路径） | 视频时间线 |
| C-12 | 证据溯源 | evidence/citations/graph context | `rag_engine.py`、`AgentOutput` | 固定本地知识集实际返回 6 条证据并保留 ID/来源；人工事实评测未完成 | 部分实现 | 引用表 |
| C-13 | 交叉验证/辩论 | `DebateAugmentedRAG` | `drag_debate.py`、`agent_swarm.py` | LLM 已注入并有异步路径测试；默认 deterministic 仍不是真实模型效果 | 部分实现（真实 provider 需单独验收） | 代码修复证据 |
| C-14 | 可选研究性评测：事实支持率/幻觉分析 | 门限、清洗、引用设计 | `rag_engine.py`、`drag_debate.py` | 无合格人工标注数据；非当前官方 A3 硬性阈值 | 可选评测 | 评测脚本和报告 |
| C-15 | 可选研究性评测：画像—资源适配 | 风格资源排序、画像注入 | `agent_swarm.py`、`learning_strategy.py` | 无人工标注集；非当前官方 A3 硬性阈值 | 可选评测 | 标注表 |
| C-16 | 可选研究性评测：知识点覆盖 | 概念图、题库、路径 | `rag_engine.py`、题库 | 无固定覆盖率计算；非当前官方 A3 硬性阈值 | 可选评测 | 覆盖率脚本 |
| C-17 | 代码实操 | AST、trusted_local 子进程、Docker 池、输出捕获 | `code_exec_api.py`、`scripts/trusted_local_smoke.py` | 默认 disabled 明确拒绝；trusted_local smoke 已验证输出与 os 导入拦截；真实容器执行未验证 | 部分实现（可选能力） | 安全测试、smoke 报告 |
| C-18 | 部署运行 | Dockerfile、compose、启动脚本 | `Dockerfile`、`docker-compose.yml`、`outputs/e2e_no_docker/report.json` | 无 Docker 后端/前端核心路径和浏览器 E2E 已通过；Docker 镜像目标机未验收 | 已证实（默认路径；Docker 可选） | 部署日志 |
| C-19 | 测试说明和单测 | `tests`、`scripts/test_member6_all_tasks.py`、`scripts/trusted_local_smoke.py` | 测试文件及运行报告 | 正式 pytest 145 passed、1 skipped，成员专项 62/62，运行时矩阵 47/47，trusted_local smoke 通过 | 已证实（选定范围） | 测试报告 |
| C-20 | 数据合规 | 脱敏和 owner 设计痕迹 | `DB*`、配置 | 选定跨用户矩阵 47/47，主要路由已认证；全部 API 和正式合规审查仍需复核 | 部分实现/存在剩余风险 | 整改报告 |

## 2. 功能到 API 追踪

| 功能 | 前端入口 | API | 主要服务 | 持久化 |
|---|---|---|---|---|
| 登录 | `Login.vue` | `/api/auth/login` | `app/auth.py` | `users` |
| 冷启动 | `Onboarding.vue` | `/api/auth/register`、profile | `app/crud.py` | `student_profiles` |
| 智能对话 | `Chat.vue` | `/api/stream/chat` | `EduMatrixSwarm` | history/alignment |
| 画像分析 | `ProfileDashboard.vue`、`StudentAnalysis.vue` | `/api/profile/{id}/analysis` | profile API | profiles/quiz |
| 学习路径 | `LearningPathGraph.vue` | `/api/profile/{id}/learning-path` | ZPD/graph | profiles |
| 知识库 | `Knowledge.vue` | `/api/knowledge/*` | parser/RAG | documents/index |
| 测验 | `Chat.vue`/相关组件 | `/api/quiz/*` | quiz/BKT/MIRT | quiz/wrong |
| 错题复习 | `WrongQuestionBook.vue`、`Review.vue` | wrong/checkin/flashcard | Anki/strategy | review/checkin |
| 代码沙箱 | `SandboxConsole.vue`、`SandboxVisualizer.vue` | `/api/code/*` | sandbox runner | code executions |
| 报告 | Notes/Profile | `/api/v1/profile/export` | Playwright | profile data |
| 教师 | `Teacher.vue` | `/api/teacher/*` | teacher handlers | profiles/reviews |

## 3. 证据等级

### A 级：直接运行证据

命令输出、浏览器截图、HTTP 响应、数据库记录和固定输入输出。

### B 级：源码直接证据

函数、类、配置和路由真实存在，但没有证明在当前环境运行。

### C 级：文档或设计证据

README、旧报告、注释和 Mermaid 图中描述，但不能单独证明代码接入。

### D 级：规划或推断

未来建议、目标指标和未完成能力，不能写成已实现。

## 4. 证据状态与仍需补齐事项

| 证据项 | 当前状态 | 直接证据 | 仍需注意 |
|---|---|---|---|
| 三组画像 JSON | 已完成（合成演示数据） | `outputs/innovation_evidence/synthetic_profiles.json`、`profile_cases.json` | 不能称为真实用户调研 |
| 同一问题三组资源输出 | 已完成（结构性对比） | `innovation_benchmark.json` | 不能直接推导学习效果 |
| Agent 事件时间线 | 已完成默认路径截图 | `outputs/e2e_no_docker/04-chat-response.png` | 真实外部 LLM 运行链仍需复核 |
| RAG 证据和引用 | 已完成固定知识集证据 | `fixed_knowledge_set.json`、`innovation_benchmark.json` | 仍需人工事实准确性标注 |
| A 不能读取 B 的数据 | 已完成选定运行时矩阵 | `outputs/runtime_security_matrix.json`，47/47 | 不是全部 API 的穷尽证明 |
| 无 Token 返回 401 | 已完成契约测试和运行时覆盖 | `tests/test_security_contracts.py`、矩阵 | 目标机仍需复现 |
| Docker 代码执行 | 未完成真实容器执行；离线拒绝已完成 | `code/status` E2E、沙箱契约测试 | Docker 是可选增强，不阻断核心验收 |
| 幻觉/适配/覆盖率正式标注 | 未完成 | 当前仅有方法和合成结构证据 | 不能填写比赛量化达标结论 |
| 干净环境安装和后端启动 | 当前机器默认路径已完成 | `outputs/e2e_no_docker/report.json` | 目标评委机器仍需团队复现 |
| PDF 导出 | 未完成独立 smoke test | Dockerfile 已包含浏览器安装命令 | 目标机需单独验证 |
