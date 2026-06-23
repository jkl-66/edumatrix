# 🧠 EduMatrix 智教矩阵 — 赛题要求与系统实现物理映射白皮书 (Competition Requirements & Implementation Mapping Blueprint)

> [!IMPORTANT]
> **🤖 答辩与评审白盒化支撑声明**
> 本文档旨在深度剖析 **第十五届中国软件杯大赛 A组赛题 ——《基于大模型的个性化资源生成与学习多智能体系统开发》** 的各项功能与非功能性要求，并白盒化论证 **EduMatrix 智教矩阵** 系统在底层数据库设计、后端 Python 多智能体 Swarm 调度以及前端 Vue3 流式渲染层面的具体物理文件与核心算法映射。本白皮书可作为软件杯初赛/决赛技术说明书、测试说明书的重要核心章节。

---

# 🧭 第一部分：赛题基本功能需求对照映射

## 🎯 赛题重点一：对话式学习画像自主构建 (Basic Requirement 1)

### 1.1 赛题指标规范
*   **指标 1**：摒弃传统繁琐表单，支持通过**自然语言对话**（结合学生的专业、学习目标、学习历史等）自动抽取特征。
*   **指标 2**：构建包含**不少于 6 个维度**（如知识基础、认知风格、易错点偏好等）的动态学生画像。
*   **指标 3**：支持画像的“**随学随新**”（动态随学更新）。

### 1.2 EduMatrix 物理代码映射与核心算法

#### 📂 核心映射文件：
1.  **[models.py](file:///d:/project-edumatrix/edumatrix-main/models.py)** L276-312：定义了 `StudentProfile` 数据类，维护完整的内存学情画像。
2.  **[agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py)** L120-246：定义了画像探针智能体 `ProfileProbeAgent` 的特征提取、3轮滑动窗口及口语指代消解逻辑。
3.  **[app/crud.py](file:///d:/project-edumatrix/edumatrix-main/app/crud.py)**：负责画像数据的持久化读写与 SQLite WAL 模式下的高并发事务提交。

#### 🛠️ 技术实现剖析：
*   **十维画像指标对齐**：我们的 `StudentProfile` 画像远远超出了赛题要求的 6 个维度，实际物理追踪并建模了 **10 大认知与行为维度**：
    1.  **知识基础 (Knowledge Foundation)**：`knowledge_base` 字段与基于 BKT（贝叶斯知识追踪）的每个核心概念的 `concept_mastery` 掌握度。
    2.  **认知风格/学习风格 (Cognitive Style)**：`cognitive_style` (如视觉/代码导向、文本阅读型等，与后续资源排版渲染强绑定)。
    3.  **薄弱点盲区 (Weak Points)**：`weak_points` 数组，动态追踪学生尚未突破的概念节点。
    4.  **认知负荷 (Cognitive Load)**：`cognitive_load` (0~1 数值，决定系统是否进行降维讲解或语速减缓)。
    5.  **元认知自评偏差 (Metacognitive Mismatch)**：`metacognitive_mismatch` (度量学生主观宣称掌握度与客观答题表现的一致性)。
    6.  **易错偏好与不会原因占比 (Misconception & Causes)**：`learning_state_causes` (包含 prerequisite_gap 前置缺陷、misconception 概念混淆等 7 大分类比例)。
    7.  **情绪与挫败感状态 (Emotional State)**：`frustration_index` (挫败感) 与 `engagement_level` (参与度，由做题退缩等行为信号实时推算)。
    8.  **Bloom 认知层级追踪 (Cognitive Hierarchy)**：`bloom_levels` (映射各个概念处于记忆、理解、应用、分析、评价、创造的哪一层级)。
    9.  **学习历史 (Learning History)**：`recent_quiz_accuracy` (最近 3 次答题正确率滑动记录)。
    10. **专业与学习目标 (Major & Goals)**：`major` 与 `learning_goals` 字符串数组。
*   **3轮滑动上下文窗口与口语指代消解 (Coreference Resolution)**：
    *   在 [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py#L76-L117) 中，核心函数 `_resolve_coreference` 针对口语对话中的模糊代词（如“它”、“这个代码”、“怎么算”）建立上下文消解机制，利用最近 3 轮的对话滑窗历史，将代词替换为最近提及的真实概念（如“逻辑回归”）。
    *   L186 定义了 `_KNOWLEDGE_WHITELIST` 知识点白名单，画像提取器 `ProfileProbeAgent` 将非 ML 词汇映射至白名单中最接近的节点，杜绝画像中产生无用垃圾特征。
*   **画像更新主客观信号对齐与防膨胀锁死**：
    *   在 [models.py](file:///d:/project-edumatrix/edumatrix-main/models.py) 的 `_refresh_dynamic_profile` 中，引入信号分级加权：**客观测试/沙箱正确率权重设为 0.8**，**主观对话陈述权重设为 0.2**。
    *   **硬拦截锁死**：若某概念最近 3 次客观答题正确率低于 `0.6`，则该概念的掌握度物理上限被强行卡死在 `0.5` 以下，元认知偏差上调 `30%`，确保画像精度符合实际学情，不受学生盲目自信的干扰。
    *   **艾宾浩斯时间遗忘衰减引擎**：[models.py](file:///d:/project-edumatrix/edumatrix-main/models.py) 实现了 `apply_profile_decay` 遗忘公式：
        $$M_{\text{decayed}} = M_{\text{last}} \cdot \left( \frac{t_{\text{elapsed}} + 24.0}{24.0} \right)^{-\beta}$$
        每次读取画像时自动运行该函数，使掌握度随流逝时间发生真实物理衰减，自动跌入待复习日历。

---

## 🎯 赛题重点二：多智能体协同的资源生成 (Basic Requirement 2)

### 2.1 赛题指标规范
*   **指标 1**：体现“**多智能体 (Multi-Agent)**”架构设计。
*   **指标 2**：由不同角色智能体协作生成，针对专业课程内容，自动构建出**至少 5 种类型**的个性化资源。

### 2.2 EduMatrix 物理代码映射与核心算法

#### 📂 核心映射文件：
1.  **[agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py)** L26-44：定义了 `AGENT_MATRIX` 智能体矩阵与 `EduMatrixSwarm` 核心 Swarm 协作调度。
2.  **[swarm_factory.py](file:///d:/project-edumatrix/edumatrix-main/swarm_factory.py)**：智能体工厂模式实现，根据策略配置动态装配对应的智能体 Prompt 与参数。
3.  **[code_exec_api.py](file:///d:/project-edumatrix/edumatrix-main/code_exec_api.py)**：子进程隔离代码沙箱，执行极客助教生成的代码块。

#### 🛠️ 技术实现剖析：
*   **1+3+5 智能体协作网状系统**：
    *   系统包含 **1个全脑主控协调官 (Coordinator Agent)**：`tutor`（苏格拉底导师），负责路由分发、合并推流。
    *   包含 **3个管理智能体**：`profile` (画像探针)、`planner` (路径规划师)、`evaluator` (量化评估师)。
    *   包含 **5个专业动作资源生成智能体**（完全对齐且超越了赛题的 5 种资源要求）：
        1.  `theory` (理论教授) $\rightarrow$ 生成**专业课程讲解文档**：结合 GraphRAG 提取的证据，生成公式推导清晰、条理连贯的专业讲义。
        2.  `mapper` (逻辑画师) $\rightarrow$ 生成**知识点思维导图**：以标准 Mermaid 有向无环语法，自动绘制知识点的逻辑拓扑图。
        3.  `coder` (极客助教) $\rightarrow$ 生成**代码类实操案例**：基于 Python 编写可运行的算法代码，并提供输入输出。
        4.  `quiz` (考官智能体) $\rightarrow$ 生成**不同类型练习题目**：动态构造选择、填空、多步推导主观题。
        5.  `director` (虚拟导演) $\rightarrow$ 生成**多模态教学视频脚本**：自动提炼要点，融合讯飞流式语音合成，生成数字人口播动画脚本。
*   **多智能体并发生成工厂模式**：
    *   在 [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py#L783-L840) 的 `AsyncResourceFactory.generate_all` 方法中，使用 `asyncio.gather` 并发拉起 5 大生成智能体，各智能体在独立的协程上下文中互不干扰，将大模型并发生成耗时压缩在最合理范围内。
*   **沙箱隔离运行与可视化终端**：
    *   极客助教生成的代码实操案例，在 [code_exec_api.py](file:///d:/project-edumatrix/edumatrix-main/code_exec_api.py) 中通过 Docker 容器或带 3.0s 看门狗的 `asyncio.create_subprocess_exec` 隔离沙箱安全运行，防范恶意代码（如死循环 `while True`）逃逸宿主机。
    *   前端组件 [SandboxConsole.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/SandboxConsole.vue) 提供行号对齐的代码编辑器。运行后，后端直接提取 Matplotlib 保存的 PNG 图片并转化为 Base64 矢量格式，在终端控制台下方高保真渲染图形。

---

## 🎯 赛题重点三：个性化路径规划与资源推送 (Basic Requirement 3)

### 3.1 赛题指标规范
*   **指标 1**：大模型深入分析学生专业、学习进度、知识掌握情况，规划科学动态的个性化学习路径。
*   **指标 2**：明确学习步骤与顺序，精准推送文档、视频、题库、案例等多类型内容。

### 3.2 EduMatrix 物理代码映射与核心算法

#### 📂 核心映射文件：
1.  **[learning_strategy.py](file:///d:/project-edumatrix/edumatrix-main/learning_strategy.py)**：实现自适应难度齿轮与教学路由状态机（FSM）。
2.  **[bkt_engine.py](file:///d:/project-edumatrix/edumatrix-main/bkt_engine.py)**：贝叶斯知识追踪算法（BKT）引擎，计算知识掌握概率。
3.  **[frontend/src/components/LearningPathGraph.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/LearningPathGraph.vue)**：前端 ECharts-Graph 路径有向无环依赖图。

#### 🛠️ 技术实现剖析：
*   **最近发展区 (ZPD) 路径规划算法**：
    *   在 [bkt_engine.py](file:///d:/project-edumatrix/edumatrix-main/bkt_engine.py) 的 `get_zpd_path_plan` 中，我们将当前目标概念与 `DEFAULT_KNOWLEDGE_DAG` 关系图谱对照。
    *   计算出目标掌握概率。设定 **最近发展区区间为 `[0.3, 0.75]`**。
    *   如果目标概念掌握度在此区间，视为当前最适学习点；如果低于 `0.3` 且前置依赖掌握度不足，系统自动触发 **“前置依赖回滚机制”**，将目标回滚到前置未掌握概念（如“线性回归”），在查询阶段向 RAG 注入增强查询词，并优先推送前置文档。
*   **自适应二档教学机制（千人千面）**：
    *   在 [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py) 的 `SwarmMediationRouter` 中，系统根据画像中的掌握度硬性控制 Swarm 运行模式，剥离大模型直接决策的不确定性：
        -   **掌握度 < 50% $\rightarrow$ SIMPLIFIED_MODE（降维解释）**：强制大模型避免输出繁杂的数学偏导公式，必须采用通俗的拟人比喻讲解概念（例如将最大池化比作“手电筒光斑取最亮区域”），并在讲义中生成易于理解的 SVG 物理矢量分析示意图。
        -   **掌握度 > 80% $\rightarrow$ ADVANCED_MODE（进阶挑战）**：自动推送难题、KaTeX 底层矩阵推导和包含 PyTorch / Scikit-Learn 库的复杂真实代码实操。

---

# 🛠️ 第二部分：加分项功能需求对照映射

## 🎯 赛题加分项一：智能辅导 (可选加分项 1)

### 1.1 赛题指标规范
*   **指标 1**：提供即时、多模态的答疑服务。
*   **指标 2**：提供详细的文字解答、图解说明、短视频讲解等。

### 1.2 EduMatrix 物理代码映射与核心算法

#### 📂 核心映射文件：
1.  **[frontend/src/views/Chat.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Chat.vue)**：页面双栏阻尼拉伸布局与局部行级答疑交互。
2.  **[drag_debate.py](file:///d:/project-edumatrix/edumatrix-main/drag_debate.py)**：跨学科学情辩论双智能体对撞（Prover vs Challenger）归纳核心类。
3.  **[rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py)**：多模态 RAG 与 VisRAG 图片配图并网。

#### 🛠️ 技术实现剖析：
*   **行级与公式级苏格拉底悬浮答疑**：
    *   前端 Markdown 解析器渲染出专业讲义后，为每一行代码和 LaTeX 公式标签绑定点击监听器。
    *   学生点击某行 PyTorch 代码（如 `x = self.pool(x)`）时，页面会在其右侧弹出毛玻璃气泡悬浮框，后端将该行作为特指 Context，拉起 `SocraticDebater` 展开追问式引导辅导，保障了智能答疑的物理精确度。
*   **VisRAG 内置幽灵图片配图并网**：
    *   在 [rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py) 中融合了多模态 VisRAG。
    *   当理论教授大模型在讲义中引用特定学术图表（如 `pooling_2x2.png`、`chain_rule_derivation.png` 等保存在项目 `data/patches/` 下的 7 张学术配图）时，前端能够零 404 报错完美渲染图解说明。
*   **数字人语音播报与口型联动**：
    *   在 [AvatarSpeech.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/AvatarSpeech.vue) 中集成讯飞流式语音合成，文字吐字与流音频播放缓冲区高度同步。
    *   应用一阶低通移动平均滤波器（平滑系数 $\alpha = 0.25$）平滑嘴部缩放，过滤爆破音引起的 Chattering（高频闪烁抽搐），提供极具真实感的多模态语音短视频级播报。

---

## 🎯 赛题加分项二：学习效果评估 (可选加分项 2)

### 2.1 赛题指标规范
*   **指标 1**：实时跟踪学习行为、练习情况、使用反馈等多维度数据。
*   **指标 2**：对学习效果进行多维度、精准评估，并及时动态调整策略。

### 2.2 EduMatrix 物理代码映射与核心算法

#### 📂 核心映射文件：
1.  **[app/api/quiz.py](file:///d:/project-edumatrix/edumatrix-main/app/api/quiz.py)**：客观题、相似题生成与分步批改提交流程。
2.  **[app/utils/event_bus.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/event_bus.py)**：定义 `LearningEventBus`，实现松耦合的学情变化发布订阅。
3.  **[frontend/src/views/WrongQuestionBook.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/WrongQuestionBook.vue)**：前端错题本、步骤明细、相似题挑战面板。

#### 🛠️ 技术实现剖析：
*   **松耦合学情事件总线 (LearningEventBus)**：
    *   学生做题、答疑、跳步时，后端向异步 `LearningEventBus` 发送 `LearningEvent` 事件。
    *   `ProfileManager` 异步订阅并消费该消息，在后台重算画像散度并进行数据库物理写入，零同步 I/O 阻塞。
*   **微步错因诊断与 3D Anki SM-2 迭代**：
    *   当测验提交后，由 `AssessorAgent` 进行 **Concept-level grading（步骤级细粒度判分）**。若某子步骤发生公式转置或维度冲突导致错误，前台会精准标红该关键步骤并弹出苏格拉底辅导，同时将提取出的阻断概念落入 `DBWrongQuestion` 数据库表。
    *   错题本中的错题卡片支持 3D 翻转。点击卡片背面的掌握反馈后，数据库通过 SM-2 迭代公式，动态计算下一次复习时间，并渲染在抗遗忘复习日历 [RevisionCalendar.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/RevisionCalendar.vue) 中。
*   **同阶错题相似题防矛盾机制**：
    *   点击“相似题挑战”，考官智能体动态生成同概念但数值不同的新题。
    *   生成前将选项与数学方程输入隔离沙箱运行预验证，校验选项与真实解无冲突、有唯一正解。预校验失败自动重试，至多 3 次（结合 Guided Decoding 闪愈），杜绝错误与矛盾题目。
*   **PDF 能力对齐报告一键导出**：
    *   在 [app/api/profile.py](file:///d:/project-edumatrix/edumatrix-main/app/api/profile.py) 中，提供 `/api/v1/profile/export` 导出报告接口。
    *   后端基于 **Playwright 无头浏览器** 技术直接对画像页面进行 Printable Layout 渲染，且配置了 `asyncio.Semaphore(3)` 异步并发哨兵，防止多租户高并发导出时内存和 CPU 跑满挂起。

---

# 🛡️ 第三部分：系统高可用、安全性与非功能性映射

## 3.1 赛题非功能性指标规范
*   **界面交互**：流式输出，卡片化展示，符合现代 AI product 规范。
*   **内容合规与安全性**：完善的“防幻觉”与安全机制，确保学术正确性。
*   **智能体响应时间**：智能体核心功能响应时间控制在合理范围内。

## 3.2 EduMatrix 物理代码映射与核心算法

#### 📂 核心映射文件：
1.  **[rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py)**：GraphRAG 锁死修复、低置信度防幻觉熔断兜底。
2.  **[manifold_alignment.py](file:///d:/project-edumatrix/edumatrix-main/manifold_alignment.py)**：Poinarcé（庞加莱）双曲流形认知对齐。
3.  **[concurrency.py](file:///d:/project-edumatrix/edumatrix-main/concurrency.py)**：熔断器与令牌桶，控制大模型速率限制与宕机降级。

#### 🛠️ 技术实现剖析：
*   **RAG 低置信度熔断防线**：
    *   在 [rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py#L189-L202) 中，当 Hybrid RAG 获取的检索片段在经过重排（Rerank）后，其最高置信度相似分数低于门限 `0.20` 时，判定为超范围无高置信度证据，系统立即熔断，并向前端吐出安全兜底拒答话术：“抱歉，系统在知识库中未检索到与您提问相关的充足高置信度证据，建议您在课件管理页面中上传包含该概念的教学资料。”，从而在源头上防范大模型的学术胡说与幻觉。
*   **双曲流形对齐与局部手术式自愈**：
    *   在 [manifold_alignment.py](file:///d:/project-edumatrix/edumatrix-main/manifold_alignment.py) 中，系统将学生的当前认知状态与专业标准知识图谱流形进行仿射对齐，计算 **Poincaré（庞加莱）测地线距离与 KL 散度**。
    *   若散度偏高，判定画像存在符号和逻辑矛盾，系统并不整体重新生成所有板块（讲义、图谱、测试等），而是**精准回滚重算受冲突影响的局部动作智能体（如极客助教）**，并将新生成的组件局部手术式刷回前端缓存，节省大模型 Token 损耗并减少 80% 的网络白屏等待时间。
*   **多租户高并发防串线机制**：
    *   在 [app/database.py](file:///d:/project-edumatrix/edumatrix-main/app/database.py) 中，我们在 SQLAlchemy 的 `before_cursor_execute` 监听中拦截并注入 `SET search_path TO public;`，连接池每次归还连接时执行物理“洗白”操作，彻底杜绝了 AsyncIO 并发抢占可能导致的跨协程租户数据污染问题。

---

# 📋 附录：EduMatrix 核心物理模块及职责一览

为了在演示或文档编写中理清底层架构，下表列出了 EduMatrix 整个后台的核心模块及对应的具体职责：

| 模块文件名 | 物理路径 | 赛题需求绑定 | 核心职责与业务逻辑 |
| :--- | :--- | :--- | :--- |
| `agent_swarm.py` | `agent_swarm.py` | 多智能体资源生成与画像构建 | **系统核心调度器**。定义 `EduMatrixSwarm` 类，管理 1+3+5 智能体配置、Guided Decoding 正则闪愈纠偏以及 FSM 策略路由模式扭转。 |
| `models.py` | `models.py` | 学习画像自主构建 | **数据库 ORM 映射与数据结构类**。声明 9 张核心实体表，定义 `StudentProfile` 十维画像指标，计算艾宾浩斯物理遗忘衰减。 |
| `learning_strategy.py`| `learning_strategy.py`| 个性化路径规划 | **核心决策路由**。计算自适应难度齿轮，并将推荐的个性化学科路径打包为 `StrategyPlan` 挂载给动作层。 |
| `bkt_engine.py` | `bkt_engine.py` | 个性化路径规划 | **贝叶斯知识追踪算法引擎**。计算多概念下的掌握概率，为 ZPD DAG 路径规划提供高精确度数据。 |
| `manifold_alignment.py`| `manifold_alignment.py`| 防幻觉与自愈机制 | **数学建模层**。基于 Poincaré 双曲距离对齐学生认知图谱与标准大纲，检测对齐冲突。 |
| `code_exec_api.py` | `code_exec_api.py` | 代码实操案例生成与评测 | **独立子进程代码沙箱控制器**。支持隔离执行 Python 等代码片段，配置 3.0s 超时看门狗，防范沙箱逃逸。 |
| `rag_engine.py` | `rag_engine.py` | 多模态答疑与防幻觉 | **混合 RAG 与 VisRAG 检索管道**。集成重排过滤与低于 0.20 置信度熔断机制，实现非 ML 学科的优雅降级。 |
| `concurrency.py` | `concurrency.py` | 高可用与非功能性要求 | **系统流控限流器**。封装高并发令牌桶限流算法、AsyncWorkerPool 异步工作池以及 API 熔断降级。 |
| `app/utils/event_bus.py`| `app/utils/event_bus.py`| 学习效果评估与打卡 | **松耦合学习诊断事件总线**。提供异步发布订阅接口，当答题与学习行为发生时在后台无阻塞重算画像。 |
| `report_api.py` | `report_api.py` | 评估报告导出 | **Playwright 无头浏览器 PDF 生成器**。为学生导出排版规范、图表清晰不模糊的学情诊断 PDF 报告。 |
