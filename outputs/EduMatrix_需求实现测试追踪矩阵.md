# EduMatrix 需求—实现—测试—证据追踪矩阵

基线：`2952dc1b17d793e5d76f54e1764348ebe50e4d5e`  
状态定义：已证实 / 部分实现 / 待验证 / 不满足或存在风险

## 1. 需求追踪总表

| ID | 需求/评分点 | 功能实现 | 代码证据 | 测试/运行证据 | 当前状态 | 最终材料 |
|---|---|---|---|---|---|---|
| C-01 | 至少 3 个明确 Agent | 9 个 AgentSpec 和对应类 | `agent_swarm.py:34-44` | 静态结构确认 | 已证实（结构） | 主文档 Agent 章节、截图 |
| C-02 | 分析—生成—校验—决策闭环 | 画像、规划、RAG、资源工厂、对齐、反馈 | `agent_swarm.py:1363-1640` | 需完整依赖 E2E | 部分实现 | 流程图、事件日志 |
| C-03 | 3 种以上个性化资源 | 讲义、导图、代码、练习、视频脚本 | `agent_swarm.py:929-938` | 需固定画像输出 | 已证实（任务） | 资源包截图 |
| C-04 | 学习者先验画像 | 专业、风格、动机、掌握度和历史 | `models.py`、`DBStudentProfile` | 种子/注册代码存在 | 已证实（结构） | 数据字典 |
| C-05 | 2 组差异化初始数据 | 种子学生、Peer 先验、注册冷启动 | `scripts/seed_students.py`、`app/crud.py` | 需导出固定样例 | 部分实现 | 测试数据包 |
| C-06 | 3 组不同背景画像 | 可由画像模型表达 | `models.py`、`frontend` | 尚无完整评测报告 | 待验证 | 三组输入输出样例 |
| C-07 | 1 个垂直知识库切片 | 机器学习概念、题库、RAG | `scripts/data/quiz_bank/`、`rag_engine.py` | 需固定证据包 | 部分实现 | 知识库切片 |
| C-08 | 个性化学习路径 | ZPD、图谱、掌握度、负荷 | `profile_api.py`、`agent_swarm.py` | 需对比三画像 | 部分实现 | 路径图 |
| C-09 | 动态反馈更新 | 答题、错题、行为、事件总线 | `quiz_api.py`、`learning_event_bus.py` | 专项结构测试部分覆盖 | 部分实现 | 反馈日志 |
| C-10 | 学情可视化 | Dashboard、画像分析、流形、路径 | `frontend/src/views`、`components` | 前端构建通过 | 已证实（前端） | 截图 |
| C-11 | 多 Agent 协同可视化 | AgentTimeline、SSE 事件 | `AgentTimeline.vue`、`stream.js` | 后端 E2E 待验证 | 部分实现 | 视频时间线 |
| C-12 | 证据溯源 | evidence/citations/graph context | `rag_engine.py`、`AgentOutput` | 需样本级人工核验 | 部分实现 | 引用表 |
| C-13 | 交叉验证/辩论 | `DebateAugmentedRAG` | `drag_debate.py` | 默认 LLM 未注入 | 部分实现，存在缺口 | 代码修复证据 |
| C-14 | 幻觉率 <5% | 门限、清洗、引用设计 | `rag_engine.py`、`drag_debate.py` | 无合格评测数据 | 待验证 | 评测脚本和报告 |
| C-15 | 适配准确率 ≥85% | 风格资源排序、画像注入 | `agent_swarm.py`、`learning_strategy.py` | 无人工标注集 | 待验证 | 标注表 |
| C-16 | 覆盖率 ≥90% | 概念图、题库、路径 | `rag_engine.py`、题库 | 无固定覆盖率计算 | 待验证 | 覆盖率脚本 |
| C-17 | 代码实操 | AST、Docker 池、输出捕获 | `code_exec_api.py` | 当前依赖缺失；Docker 未验证 | 部分实现，高风险 | 安全测试 |
| C-18 | 部署运行 | Dockerfile、compose、启动脚本 | `Dockerfile`、`docker-compose.yml` | 前端成功，后端未启动 | 部分实现 | 部署日志 |
| C-19 | 测试说明和单测 | `tests`、`scripts/test_member6_all_tasks.py` | 测试文件 | 62 个中 51 通过、11 错误 | 部分实现 | 测试报告 |
| C-20 | 数据合规 | 脱敏和 owner 设计痕迹 | `DB*`、配置 | 多个 API 未认证 | 不满足/高风险 | 整改报告 |

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

## 4. 交付前必须补齐的证据

1. 三组画像 JSON；
2. 同一问题三组资源输出；
3. Agent 事件时间线；
4. RAG 证据和引用；
5. A 用户文档不能被 B 检索的测试；
6. 无 Token 401 的测试；
7. Docker 代码执行和 Docker 离线拒绝测试；
8. 幻觉/适配/覆盖率人工标注表；
9. 干净环境安装和后端启动日志；
10. PDF 导出和 Playwright 浏览器安装证据。

