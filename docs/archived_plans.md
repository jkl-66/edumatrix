# Archived Plans (docs/archived_plans.md)

This file contains the detailed specifications and requirements for modules and tasks in the EduMatrix project that have already been fully implemented, integrated, and verified.

---

## 🧱 模块一：后端高并发基建与商业级多租户重构 (已并网交付)

本模块着重提升后端在答辩和 Locust 高并发压测环境下的系统稳定性，防范死锁、租户数据串线和接口空耗。

### 任务 1.1：SQLAlchemy 连接池归还物理洗白 (BEFORE_CURSOR_EXECUTE 拦截)
*   **优先级**: High
*   **状态**: [x] 已完成并网并通过单元测试
*   **开发智能体**: GLM-5.1 (后端/常规算法专家)
*   **修改文件**: [app/database.py](file:///d:/project-edumatrix/edumatrix-main/app/database.py)
*   **输入 (Input)**:
    *   数据库连接池实例 `async_engine`
    *   SQLAlchemy `checkin` 事件与 `before_cursor_execute` 监听拦截器
*   **输出 (Output)**:
    *   在数据库连接归还连接池时执行 `SET search_path TO public;`，防范 AsyncIO 跨协程抢占式的连接串线污染。
*   **验收标准 (Acceptance Criteria)**:
    *   运行 pytest 单元测试验证并发多租户环境下连接洗白逻辑，无 search_path 残留。

### 任务 1.2：协程孤儿自杀拦截机制 (Request Disconnect Handler)
*   **优先级**: High
*   **状态**: [x] 已完成并网并通过单元测试
*   **开发智能体**: GLM-5.1 (后端/常规算法专家)
*   **修改文件**: [stream_api.py](file:///d:/project-edumatrix/edumatrix-main/stream_api.py)
*   **输入 (Input)**:
    *   FastAPI 路由注入的 `Request` 对象与 SSE 生成器循环
*   **输出 (Output)**:
    *   在 `/api/v1/stream/chat` 推流循环中前置捕获 `request.is_disconnected()`，触发并抛出 `asyncio.CancelledError` 彻底释放未决的 LLM 生成任务。
*   **验收标准 (Acceptance Criteria)**:
    *   中途切断客户端 SSE 物理连接，验证后端日志瞬间打印 `CancelledError`，且大模型 API 计费连接立即中断。

---

## ⚙️ 模块三：Swarm 多智能体自愈防线与容器隔离沙箱 (已并网交付)

本模块为智能体系统的安全性和沙箱执行的鲁棒性提供底层防护。

### 任务 3.1：Guided Decoding 概率坍塌自愈防线
*   **优先级**: High
*   **状态**: [x] 已完成并网并通过单元测试
*   **开发智能体**: Claude (安全审计与高难攻坚)
*   **修改文件**: [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py)
*   **输入 (Input)**:
    *   Pydantic 约束类，大模型返回的不完整 JSON 数据
*   **输出 (Output)**:
    *   向 Schema 决策器加装 `ValidationError` 拦截，在抛出异常的瞬间启动基于 Regex 的强行闭合与文本纠偏，返回有效 JSON。
*   **验收标准 (Acceptance Criteria)**:
    *   模拟注入受损截断的 JSON 串，验证 Guided Decoding 概率闪愈模块在 10ms 内自动补齐标签，保障系统零 500 报错。

### 任务 3.2：隔离沙箱“容器池”常驻挂载运行
*   **优先级**: High
*   **状态**: [x] 已完成并网并通过单元测试
*   **开发智能体**: Claude (安全审计与高难攻坚)
*   **修改文件**: [code_exec_api.py](file:///d:/project-edumatrix/edumatrix-main/code_exec_api.py)
*   **输入 (Input)**:
    *   常驻的隔离 Python Docker 镜像实例与 asyncio 子进程 fallback 机制
*   **输出 (Output)**:
    *   限制运行内存 `512m` 并挂载 3.0 秒超时看门狗，超时自动执行 kill 操作。
*   **验收标准 (Acceptance Criteria)**:
    *   传入 `while True: pass` 死循环代码，验证沙箱在 3 秒内强制熔断并释放 CPU 资源，宿主机零影响。

---

## 🎨 模块四：Vue3 前端 SSE 语法缓冲与视觉炫技大屏 (已并网交付)

本模块负责在前端实现平滑的流式响应，拒绝由于 SSE 截断引发的渲染报错，并展示震撼的智能体路由轨迹。

### 任务 4.1：前端 SSE 流式响应语法缓冲拦截器 (Buffer Filter)
*   **优先级**: High
*   **状态**: [x] 已完成并网并通过单元测试
*   **开发智能体**: Gemini (前端/视觉专家)
*   **修改文件**: [frontend/src/views/Chat.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Chat.vue)
*   **输入 (Input)**:
    *   推流传输中的半截未闭合 Markdown/LaTeX/Mermaid 标记
*   **输出 (Output)**:
    *   前端建立词法缓冲状态机，延迟渲染未闭合的语法块；在检测到网络断开时强制添加补齐符。
*   **验收标准 (Acceptance Criteria)**:
    *   推送 `$$\lim_{x \to` 且突然断开，验证前端自动渲染为闭合公式，控制台无任何解析异常警告。

### 任务 4.2：智能体协作轨迹时间轴与掌握度双圈雷达图
*   **优先级**: Medium
*   **状态**: [x] 已完成并网并通过单元测试
*   **开发智能体**: Gemini (前端/视觉专家)
*   **修改文件**: [frontend/src/components/AgentTimeline.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/AgentTimeline.vue), [frontend/src/components/MasteryRadar.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/MasteryRadar.vue)
*   **输入 (Input)**:
    *   FastAPI 后端推送的多智能体状态流 Status Code 与学生维度评估分
*   **输出 (Output)**:
    *   呼吸灯（`animate-pulse`）样式的智能体协同轨迹时间轴。
    *   ECharts 双圈雷达图对照展示初始学情（灰色圈）与最新学情（蓝色扩充圈）。
*   **验收标准 (Acceptance Criteria)**:
    *   问答结束后，雷达图能够依据后端返回的新画像分动态向外扩张，交互帧率达 60FPS。

---

## 🎙️ 模块五：讯飞语音合成与嘴形低通指数平滑滤波 (已并网交付)

对接科大讯飞大模型生态，提供多模态语音讲解和极具科技感的数字人嘴形丝滑联动。

### 任务 5.1：科大讯飞流式 TTS 瞬时多模态接入
*   **优先级**: Medium
*   **状态**: [x] 已完成并网并通过单元测试
*   **开发智能体**: Gemini (前端/视觉专家)
*   **修改文件**: [frontend/src/components/AvatarSpeech.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/AvatarSpeech.vue)
*   **输入 (Input)**:
    *   科大讯飞语音合成 WebSockets 接口及二进制流式音频
*   **输出 (Output)**:
    *   使用 `Web Audio API` 建立流式音频播放缓冲区，实现文本吐出与语音播报的完全同步。
*   **验收标准 (Acceptance Criteria)**:
    *   语音合成首包播放等待时间低于 200ms，声音流畅，无卡顿与爆破杂音。

### 任务 5.2：一阶低通指数平滑嘴形联动滤波器
*   **优先级**: High
*   **状态**: [x] 已完成并网并通过单元测试
*   **开发智能体**: Gemini (前端/视觉专家)
*   **修改文件**: [frontend/src/components/AvatarSpeech.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/AvatarSpeech.vue)
*   **输入 (Input)**:
    *   TTS 音频振幅（Amplitude）与指数移动平均公式
*   **输出 (Output)**:
    *   Canvas 嘴部动作滤波器，平滑系数固定为 $\alpha = 0.25$：
        $$\text{SmoothScale} = 0.25 \times \text{TargetScale} + 0.75 \times \text{LastScale}$$
*   **验收标准 (Acceptance Criteria)**:
    *   数字人嘴部动作柔顺，成功过滤由于爆破音或电噪声引起的高频瞬间抽搐（Chattering）。

---

## 🌊 第一层：底层高可用与数据持久化加固 (P0 级底层基建) (已并网交付)

本阶段致力于彻底消除高并发环境下的同步阻塞问题，解决 SQLite 并发写锁冲突，补齐物理数据库字段（包括错题本），保障学情数据的持久化完整。

### 任务 6.1：FastAPI 与 RAG 异步非阻塞化改造 (Event Loop Blocking Remediation)
*   **优先级**: High (P0)
*   **状态**: [x] 已完成并网并通过单元测试
*   **开发智能体**: backend-engineer (GLM-5.1)
*   **修改文件**: [rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py), [app/main.py](file:///d:/project-edumatrix/edumatrix-main/app/main.py)
*   **核心意图**: 解决 `rag_engine.py` 用 `future.result()` 同步阻塞以及 `app/main.py` 中 `async def` 直接运行同步 SQL/CRUD 阻塞事件循环的问题。

### 任务 6.2：数据库画像持久化扩充、错题物理表与级联删除 (Database Schema Expansion & Concurrency Fix)
*   **优先级**: High (P0)
*   **状态**: [x] 已完成并网并通过单元测试
*   **开发智能体**: db-engineer (GLM-5.1)
*   **修改文件**: [app/database.py](file:///d:/project-edumatrix/edumatrix-main/app/database.py), [models.py](file:///d:/project-edumatrix/edumatrix-main/models.py)

### 任务 6.3：隔离沙箱容器池并发互斥锁加锁 (Sandbox Concurrency Locking)
*   **优先级**: High (P1)
*   **状态**: [x] 已完成并网并通过单元测试
*   **开发智能体**: backend-engineer (GLM-5.1)
*   **修改文件**: [code_exec_api.py](file:///d:/project-edumatrix/edumatrix-main/code_exec_api.py)

---

## 🌊 第二层：RAG 检索管道修复与多模态知识图谱构建 (已交付部分)

### 任务 10.3：VisRAG 内置幽灵图片学术规范生成与文件并网
*   **优先级**: High (P0)
*   **状态**: [x] 已完成并网并物理生成 7 张学术配图
*   **开发智能体**: ui-designer (Gemini) / backend-engineer (GLM-5.1)
*   **修改文件**: `data/patches/` [NEW]
*   **核心意图**: 彻底修复 VisRAG 图片幽灵引用导致的前端 404 报错问题，物理生成 7 张符合学术规范的教学示意图并放置到 `data/patches/` 下。具体生成清单如下：
    1.  `pooling_2x2.png` (2x2 最大池化过程与边界滑动示意图)
    2.  `avg_pooling_contrast.png` (平均池化 vs 最大池化特征保留对照图)
    3.  `kernel_stride.png` (卷积核大小与步长 stride 对滑动窗口输出尺寸的影响图)
    4.  `chain_rule_derivation.png` (反向传播复合函数链式法则偏导求导推导拓扑图)
    5.  `overfitting_curve.png` (训练集 vs 验证集误差随 Epoch 变化的过拟合与欠拟合拐点曲线)
    6.  `gradient_descent_contour.png` (损失函数三维凸空间或二维等高线梯度下降收敛路径图)
    7.  `fully_connected_network.png` (多层感知机全连接前馈神经网络输入-隐藏-输出层结构图)

---

### Task 10.4: GraphRAG 领域锁死修复与非 ML 学科降级机制
*   **状态**: [x] 已完成且通过测试验证
*   **优先级**: High (P0)
*   **对应角色**: backend-engineer (GLM-5.1)
*   **修改文件**: [rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py)
*   **核心意图**: 当用户输入非机器学习概念时，系统自动优雅降级，防止锁死在默认的“池化层”节点。
*   **输入 (Input)**:
    *   用户输入的非 ML 领域查询（如 “李白”）。
*   **输出 (Output)**:
    *   跳过 GraphRAG 推理，构建无图谱上下文的检索包。
    *   在生成的“专业讲义”底部追加无图谱 fallback 提示："EduMatrix 标准学科大纲知识图谱暂未涵盖该领域，系统已自动切换至多模态混合文本检索与实时互联网检索模式进行解答，您可以上传相关课件以扩充图谱。"
*   **验收标准 (Acceptance Criteria)**:
    *   测试案例验证非 ML 领域问题正常降级且无 GraphRAG 锁死，并且回答中包含降级说明。

---

### Task 10.5: RAG 检索低置信度防幻觉回滚拦截机制
*   **状态**: [x] 已完成且通过测试验证
*   **优先级**: High (P0)
*   **对应角色**: backend-engineer (GLM-5.1)
*   **修改文件**: [rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py), [drag_debate.py](file:///d:/project-edumatrix/edumatrix-main/drag_debate.py), [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py)
*   **核心意图**: 当 RAG 检索到的证据相似度极低时，触发防幻觉熔断拦截，避免模型幻觉。
*   **输入 (Input)**:
    *   Rerank 后的证据得分。
*   **输出 (Output)**:
    *   若最高相似度分数低于 0.20，判定为低置信度，设置 `low_confidence = True`。
    *   在 Swarm 主控中检测到低置信度时直接拦截熔断，并返回统一兜底话术："抱歉，系统在知识库中未检索到与您提问相关的充足高置信度证据，为避免幻觉，建议您在‘课件管理’页面中上传包含该概念的教学资料。"
*   **验收标准 (Acceptance Criteria)**:
    *   测试案例输入不相关词汇（如 “xyz123”）能够正确触发低置信度拦截并返回兜底响应。

---

## oh-my-agent



## 🌊 Wave 7：路径图谱与自适应画像开发 (P0 & P1 核心算法与数据图表) (已完成)

### 任务 7.1：知识依赖图谱与自适应路径规划 (ZPD DAG Path Planner)
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P0)
*   **开发智能体**: architecture-reviewer (Claude)
*   **绑定 Skill**: `oma-architecture`
*   **修改文件**: [learning_strategy.py](file:///d:/project-edumatrix/edumatrix-main/learning_strategy.py), [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py), [frontend/src/components/LearningPathGraph.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/LearningPathGraph.vue) [NEW]
*   **核心意图**: 让路径规划师输出包含知识点依赖关系的 DAG 数据，并在前端使用 ECharts-Graph 可视化渲染学习依赖关系图谱，并支持点击任一概念节点展示详情与「一键定向跳转学习」按钮，打通路径可视化到学习会话的交互闭环。
*   **输入 (Input)**:
    *   由 `PathPlanner` 返回的拓扑规划路径数据，前置概念依赖关系 DAG JSON。
*   **输出 (Output)**:
    *   后端接口返回 `{ nodes: [...], links: [...], zpd_node: \"...\" }` 数据结构。
    *   前端新建 `LearningPathGraph.vue` 视图，利用 ECharts-Graph 绘制有向无环关系图，高亮标出学生当前所处的 ZPD（最近发展区）节点。
    *   在 `LearningPathGraph.vue` 中绑定节点点击事件，点击时展示浮动卡片呈现概念解析，并提供“跳转学习”按钮。点击按钮直接向后端 `/api/v1/stream/chat` 发送包含特定概念的主动学习请求。
*   **验收标准 (Acceptance Criteria)**:
    *   切换至路径规划页面，前端大屏成功渲染并动态高亮依赖线和当前节点；点击图谱中的节点，成功弹出信息悬浮框；点击“跳转学习”，系统在 1.5 秒内自动流式跳转并生成相关概念的讲义与导图。

---

### 任务 7.2：学情诊断大盘、MasteryRadar雷达图对齐与盲区清单
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P1)
*   **开发智能体**: frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-frontend`
*   **修改文件**: [frontend/src/views/ProfileDashboard.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/ProfileDashboard.vue) [MODIFY], [frontend/src/components/MasteryRadar.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/MasteryRadar.vue) [MODIFY]
*   **核心意图**: 实现学情画像的多维展示与弱项诊断，将原本写死的 MasteryRadar 与后端真实的十维画像建立映射，并加入 ECharts 饼图以展示 7 大不会原因占比分析，提供盲区清单可视化。
*   **输入 (Input)**:
    *   `StudentProfile.dimension_states` 与 `StudentProfile.misconception_causes` 真实画像数据。
*   **输出 (Output)**:
    *   在 `MasteryRadar.vue` 中建立雷达 5 指标与后端十维画像维度的加权算法，展示真实的扩圈效果。
    *   在 `ProfileDashboard.vue` 中加装 ECharts 饼图组件，渲染 7 大不会原因占比；下方新增“学情匹配盲区清单面板”，将未掌握的前置概念以红底高亮形式列出，支持点击触发针对性答疑。
*   **验收标准 (Acceptance Criteria)**:
    *   进入画像面板，雷达图双圈比例和饼图原因占比正确体现学生真实的测试与对话数据，点击盲区清单里的弱项节点，能正确跳转或触发针对性学习会话。

---

### 任务 7.2.B：画像自适应客观信号主导与偏差强行锁死机制
*   **优先级**: High (P1)
*   **开发智能体**: db-engineer (GLM-5.1)
*   **绑定 Skill**: `oma-db`
*   **修改文件**: [models.py](file:///d:/project-edumatrix/edumatrix-main/models.py) [MODIFY]
*   **核心意图**: 解决主观对话与客观测试数据的冲突问题。将答题正确率/沙箱跑通率作为强客观证据主导画像更新，防止学生主观发言对掌握度分数的盲目污染。
*   **输入 (Input)**:
    *   答题反馈、测试正确率与学生对话表达内容。
*   **输出 (Output)**:
    *   在 `models.py` 的 `_refresh_dynamic_profile` 中引入信号分级计算：客观测试权重设为 0.8，主观陈述权重设为 0.2。
    *   加入硬拦截逻辑：若某概念最近 3 次客观正确率低于 0.6，则该概念的 `concept_mastery` 物理上限强行锁死在 `0.5`，元认知偏差 `metacognitive_mismatch` 指标上调 30%。
*   **验收标准 (Acceptance Criteria)**:
    *   模拟并发答错 3 题且打字陈述“我完全懂了”，读取画像确认该概念掌握度依然被限死在 0.5 以下，且元认知偏差值发生明显上升。

---

### 任务 7.3：自适应二档教学机制（降维解释与进阶挑战）
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P1)
*   **开发智能体**: backend-engineer (GLM-5.1)
*   **绑定 Skill**: `oma-backend`
*   **修改文件**: [learning_strategy.py](file:///d:/project-edumatrix/edumatrix-main/learning_strategy.py) [MODIFY], [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py) [MODIFY]
*   **核心意图**: 根除一刀切教学。根据学生的认知水平，决定多智能体系统生成内容的难度与策略，提供千人千面的讲授风格。
*   **输入 (Input)**:
    *   `StudentProfile` 中相关概念的掌握度分数。
*   **输出 (Output)**:
    *   在 `learning_strategy.py` 中输出自适应档位。
    *   若掌握度分数 < 50%：决策触发 **“降维解释”** 模式，指示 Coordinator 限制大模型避免生成复杂公式，强制使用拟人比喻讲解，输出 STEM 二维矢量物理受力分析图/化学生成式。
    *   若掌握度分数 > 80%：决策触发 **“进阶挑战”** 模式，要求 `SessionDirector` 自动推送难题、KaTeX 底层推导和包含 Scikit-Learn/PyTorch 库的复杂代码案例。
*   **验收标准 (Acceptance Criteria)**:
    *   当掌握度低于 50% 时，AI 讲义内容为通俗白话并配有 SVG/Plot 图表；当掌握度调高至 80% 以上时，AI 响应自动变为硬核公式与 PyTorch 实战案例。

---

### 任务 7.3.B：动态时间遗忘衰减引擎 (Ebbinghaus Profile Decay)
*   **优先级**: Medium (P1)
*   **开发智能体**: db-engineer (GLM-5.1)
*   **绑定 Skill**: `oma-db`
*   **修改文件**: [models.py](file:///d:/project-edumatrix/edumatrix-main/models.py) [MODIFY]
*   **核心意图**: 解决 `StudentProfile` 中掌握度分数一旦更新就永久不降的问题，引入艾宾浩斯遗忘衰减数学模型，体现学情画像的真实时变遗忘过程。
*   **输入 (Input)**:
    *   `StudentProfile.concept_mastery` 数据字典与流逝小时数。
*   **输出 (Output)**:
    *   在 `StudentProfile` 中添加 `apply_profile_decay()` 方法：
        $$M_{decayed} = M_{last} \cdot \left( \frac{t_{elapsed} + t_{base}}{t_{base}} \right)^{-\beta}$$
        （$t_{base}$ 默认为 24.0 小时，$\beta$ 依据认知负荷 `cognitive_load` 处于 0.08 到 0.18 之间变化）。
    *   每次读取画像时自动运行此方法进行物理衰减。
*   **验收标准 (Acceptance Criteria)**:
    *   测试基准：将某一概念掌握度设为 1.0，模拟 48 小时后读取，确认其发生自然衰减。

---

### 任务 7.4：自适应错题物理入库、复习日历与打卡
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P2)
*   **开发智能体**: db-engineer (GLM-5.1) / frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-db`, `oma-frontend`
*   **修改文件**: [app/database.py](file:///d:/project-edumatrix/edumatrix-main/app/database.py) [MODIFY], [quiz_api.py](file:///d:/project-edumatrix/edumatrix-main/quiz_api.py) [MODIFY], [frontend/src/views/WrongQuestionBook.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/WrongQuestionBook.vue) [NEW], [frontend/src/components/RevisionCalendar.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/RevisionCalendar.vue) [NEW], [frontend/src/views/Dashboard.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Dashboard.vue) [MODIFY], [frontend/src/views/Quiz.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Quiz.vue) [MODIFY]
*   **核心意图**: 
    1. 当测验提交后由 `AssessorAgent` 执行步骤级评分（Concept-level grading），若得分低于 60%，则提取具体阻断概念，自动向错题表 `DBWrongQuestion` 写入包含薄弱维度的错题记录；
    2. 前端做题页面呈现清晰的微步错因阻断诊断链；
    3. 支持错题分类筛选和 Ebbinghaus 遗忘复习日历。
*   **输入 (Input)**:
    *   提交答卷接口 `/api/v1/quiz/submit` 接收到的多步推导判分结果与答题正确率。
*   **输出 (Output)**:
    *   错题数据写入数据库并更新画像，前端 `WrongQuestionBook.vue` 支持依概念筛选错题并展示其步骤判定明细。
    *   在 `Quiz.vue` 中渲染步骤级批改详情（✅ 概念正确；❌ 发生转置错误并悬浮展示苏格拉底提示，而非粗暴给出总分）。
    *   新建 `RevisionCalendar.vue` 抗遗忘日历，并在 Dashboard 挂载签到打卡卡片。
*   **验收标准 (Acceptance Criteria)**:
    *   学生测验步骤答错后，系统在 200ms 内自动持久化画像并把错题入库；前往错题本可展示其子步骤的断点分析，打卡签到正常运作。

---

### 任务 7.5：自适应 Anki 记忆闪卡与主动召回机制 (Anki Spaced Repetition Card)
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: Medium (P1)
*   **开发智能体**: frontend-engineer (Gemini) / db-engineer (GLM-5.1)
*   **绑定 Skill**: `oma-frontend`, `oma-db`
*   **修改文件**: [app/database.py](file:///d:/project-edumatrix/edumatrix-main/app/database.py) [MODIFY], [models.py](file:///d:/project-edumatrix/edumatrix-main/models.py) [MODIFY], [frontend/src/components/AnkiFlashcard.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/AnkiFlashcard.vue) [NEW], [frontend/src/views/WrongQuestionBook.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/WrongQuestionBook.vue) [MODIFY]
*   **核心意图**: 针对错题和未掌握概念，自动生成包含正反面（概念问题 vs 索格拉底解析/公式）的 Anki 记忆闪卡，支持 3D 翻转动效并收集反馈参数更新遗忘曲线。
*   **输入 (Input)**:
    *   低分概念或错题薄弱点数据集，学生点击卡片反馈（简单/一般/困难）
    *   对应 response quality $q \in \{2, 4, 5\}$（困难: 2, 一般: 4, 简单: 5）
*   **输出 (Output)**:
    *   数据库表结构（错题表 `DBWrongQuestion`）扩展 `easiness_factor` (默认 2.50) 与 `interval_days` (默认 1) 字段，新增 `next_review_time` 字段。
    *   数学换算逻辑：
        $$E' = \max\left(1.3, E + (0.1 - (5 - q) \times (0.08 + (5 - q) \times 0.02))\right)$$
        $$I_n = \begin{cases} 1 & n=1 \\ 6 & n=2 \\ I_{n-1} \times E' & n > 2 \end{cases}$$
        $$\text{next\_review\_time} = \text{now}() + I_n \text{ days}$$
    *   前端 `AnkiFlashcard.vue` 呈现 3D 翻转卡片交互动效（利用 CSS `transform: rotateY(180deg)` 与 `backface-visibility: hidden`）。
*   **验收标准 (Acceptance Criteria)**:
    *   点击错题本卡片成功触发卡片 3D 旋转翻面，选择“困难/一般/简单”反馈后，数据库下一次复习时间与 EB 因子完成增量更新。

---

### 任务 7.6：一键导出学情诊断与能力对齐 PDF 报告 (Cognitive Diagnostic Report Export)
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P1)
*   **开发智能体**: backend-engineer (GLM-5.1)
*   **绑定 Skill**: `oma-backend`
*   **修改文件**: [app/api/profile.py](file:///d:/project-edumatrix/edumatrix-main/app/api/profile.py) [MODIFY], [frontend/src/views/ProfileDashboard.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/ProfileDashboard.vue) [MODIFY]
*   **核心意图**: 为学生/评委一键生成格式精美的学情诊断与能力对齐 PDF 报告，在后端使用 Playwright headless 浏览器渲染特定 Print-only 排版页面以防止公式/图表排版截断和模糊。
*   **输入 (Input)**:
    *   学生画像 `StudentProfile`、流形散度曲线及最近学习轨迹数据
*   **输出 (Output)**:
    *   后端接口 `/api/v1/profile/export` 利用 Playwright 预渲染学情报告 PDF。
    *   **高并发安全哨兵**：在 FastAPI 启动时初始化全局单例 `BrowserPool`，内部使用 `asyncio.Semaphore(3)` 限制最大并发渲染页面数，防止压测时内存/CPU 资源耗尽。
    *   设置特定渲染超时为 10 秒，调用 `page.pdf(format="A4", printBackground=True)` 生成 PDF 字节流，由 API 端点直接以 `StreamingResponse` 返回。
    *   前端提供导出按钮和加载动画。
*   **验收标准 (Acceptance Criteria)**:
    *   点击“导出报告”，在 2.0s 内生成并下载包含掌握度雷达图、不会原因饼图和 AI 建议的 PDF 报告，图表无截断和模糊。

---

### 任务 7.7：同阶错题相似题动态自适应生成 (Concept-Level Adaptive Similar Question Generator)
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P1)
*   **开发智能体**: backend-engineer (GLM-5.1)
*   **绑定 Skill**: `oma-backend`
*   **修改文件**: [app/api/quiz.py](file:///d:/project-edumatrix/edumatrix-main/app/api/quiz.py) [MODIFY], [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py) [MODIFY], [frontend/src/views/WrongQuestionBook.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/WrongQuestionBook.vue) [MODIFY]
*   **核心意图**: 解决错题复盘“记答案”的弊端，针对错题绑定的微观薄弱点概念，动态生成相同难度的相似题供重测，闭合错题本流程。
*   **输入 (Input)**:
    *   错题记录中的子概念节点与难度等级
*   **输出 (Output)**:
    *   后端路由 `/api/v1/quiz/similar` 调用 `AssessorAgent` 动态组装 Prompt（带 Few-shot 的 json schema 结构模板，如 `SimilarQuestionSchema`）。
    *   **难度与矛盾对齐机制**：定义结构化的参数 and 数值边界，生成时将随机变量和方程输入 `SandboxEvaluator` 运行 Python 代码计算真实解，确保题解存在且非空，选项与真实解无冲突。若验证失败自动重试，至多3次（Guided Decoding 闪愈自愈）。
    *   前端错题卡片加装“相似题挑战”按钮。
*   **验收标准 (Acceptance Criteria)**:
    *   点击“相似题挑战”按钮，1.5 秒内呈现新题，答对后能正常消解错题本中该项的复习紧迫度。

---

### 任务 7.8：WebSocket 情绪延迟与控制及 TTS 动态减速
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: Medium (P2)
*   **开发智能体**: frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-frontend`
*   **修改文件**: [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py) [MODIFY], [frontend/src/components/AvatarSpeech.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/AvatarSpeech.vue) [MODIFY], [frontend/src/views/Chat.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Chat.vue) [MODIFY]
*   **核心意图**: 依据情绪韧性/负荷画像值动态调整数字人情绪及播报语速，在高压情况下提供同理心引导，减缓紧张感。
*   **输入 (Input)**:
    *   `StudentProfile` 情绪韧性与认知负荷值。
*   **输出 (Output)**:
    *   在音频流头部合并发送 1-byte 情绪标记（如 stressed, confused），前端瞬时刷新 Avatar 表情状态；
    *   TTS 端点在检测到情绪高压力时，利用 Web Audio API AudioContext 动态减慢播放语速（$\times 0.85$），并在 Prompt 前缀中强制要求生成同理心引导句。
*   **验收标准 (Acceptance Criteria)**:
    *   模拟高压力测试时，讯飞 TTS 播放语速发生明显缓和，AI 回复开头带有鼓励性前缀，数字人表情实现联动切换。

---

### 任务 7.8.B：ProfileProbeAgent 多轮语境指代消解与语义过滤 (Coreference & Semantic Extraction)
*   **优先级**: High (P1)
*   **开发智能体**: backend-engineer (GLM-5.1)
*   **绑定 Skill**: `oma-backend`
*   **修改文件**: [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py) [MODIFY]
*   **核心意图**: 解决口语化多轮对话指代不明（“那个怎么优化”、“它的代码”）导致画像建立垃圾节点的缺陷，引入指代消解滑窗与知识点白名单机制。
*   **输入 (Input)**:
    *   多轮聊天历史记录与大模型语义提取输入。
*   **输出 (Output)**:
    *   在 `ProfileProbeAgent` 的 `_async_extract_with_llm` 中，使用 3 轮滑窗机制拼接上下文；
    *   在 Prompt 中硬编码标准的知识点白名单。画像提取器必须前置解耦上下文，将主语指代指派到具体的实体上，过滤非白名单的垃圾特征标签。
*   **验收标准 (Acceptance Criteria)**:
    *   学生提问“它的代码怎么优化”且上一轮讨论的是“逻辑回归”，提取器能精准为“逻辑回归”计算 delta 更新，而不是新建一个名为“它的代码”的概念节点。

---

### 任务 10.1：学情交互与诊断事件总线 (LearningEventBus)
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: Medium (P1)
*   **开发智能体**: backend-engineer (GLM-5.1)
*   **绑定 Skill**: `oma-backend`
*   **修改文件**: [app/utils/event_bus.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/event_bus.py) [NEW], [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py) [MODIFY]
*   **核心意图**: 提供松耦合的学情变化与诊断结果发布订阅机制。当做题、聊天、跳步等事件发生时，通过异步总线通知诊断、规划和推荐引擎。
*   **输入 (Input)**:
    *   学情交互行为（`LearningEvent`，含事件类别、时间、负载）。
*   **输出 (Output)**:
    *   新建 `event_bus.py` 定义全局 `LearningEventBus`，支持 `publish`、`subscribe`。
    *   做题、RAG 答疑结束后，向总线推送消息，诊断智能体异步消费该事件并触发流形对齐更新。
*   **验收标准 (Acceptance Criteria)**:
    *   提交评测时，事件总线能捕获消息，并在后台无阻塞触发 `ProfileManager` 的异步画像重算与日志记录。

---

### 任务 10.2：个性化教学策略包注入策略模式消费
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: Medium (P2)
*   **开发智能体**: architecture-reviewer (Claude)
*   **绑定 Skill**: `oma-architecture`
*   **修改文件**: [learning_strategy.py](file:///d:/project-edumatrix/edumatrix-main/learning_strategy.py) [MODIFY], [swarm_factory.py](file:///d:/project-edumatrix/edumatrix-main/swarm_factory.py) [MODIFY]
*   **核心意图**: 配合策略模式，将...个性化学科推荐路径和推荐资源类型封装为策略包，通过工厂模式动态挂载给对应的 Agent 实例以调整生成权重。
*   **输入 (Input)**:
    *   画像中的 `learning_style` 与 `next_review_time`。
*   **输出 (Output)**:
    *   在 `learning_strategy.py` 中输出结构化策略包（`StrategyPlan`）。
    *   在 `AgentFactory` 实例化智能体时，将策略包传入其配置字典中，影响 Prompt 中的内容生成模板排版顺序。
*   **验收标准 (Acceptance Criteria)**:
    *   画像为视觉型（Visual）时，策略包指示图谱置顶，智能体返回的 Markdown 内容中 Mermaid 流程图处于首段；改为实践型（Active）时，代码沙盒控制台置顶。

---

---

## 🌊 Wave 8：多源生成扩充与行级智能答疑 (P1 & P2 交互与多模态扩展) (已完成)

### 任务 8.1：行级代码和 LaTeX 公式悬浮 Socratic 答疑交互
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P1)
*   **开发智能体**: frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-frontend`
*   **修改文件**: [frontend/src/views/Chat.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Chat.vue) [MODIFY]
*   **核心意图**: 提升即时答疑的交互精度。解决以往学生对讲义中个别公式/代码看不懂、却只能在下方大聊天框打字提问的痛点，支持针对局部代码行/公式行的即时答疑。
*   **输入 (Input)**:
    *   前端 Markdown 讲义中被点击的代码行文本、KaTeX 公式行。
*   **输出 (Output)**:
    *   为前端渲染出的代码行和 KaTeX 公式行绑定点击事件监听器。
    *   点击时在旁边唤出轻量防弹毛玻璃「苏格拉底局部辅导」悬浮气泡，后端获取该行作为特指 Context，拉起 `SocraticDebater` 进行多步拆解式逻辑推导。
*   **验收标准 (Acceptance Criteria)**:
    *   在生成的讲义中点击特定 PyTorch 代码行或数学公式，成功弹出悬浮框；点击“解释此行”，AI 可以在 1.2s 内给出针对该行代码/公式的局部详细注释与推导。

---

### 任务 8.2：流式请求 Abort 控制与 MasteryRadar 内存泄漏修复
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P1)
*   **开发智能体**: frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-frontend`
*   **修改文件**: [frontend/src/components/MasteryRadar.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/MasteryRadar.vue) [MODIFY], [frontend/src/views/Chat.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Chat.vue) [MODIFY]
*   **核心意图**: 解决切换页面或销毁组件时未断开 SSE 请求导致后台带宽和 CPU 持续占用的 Bug，并修复 MasteryRadar 在窗口 resize 时的内存泄漏。
*   **输入 (Input)**:
    *   页面路由跳转事件与 resize 监听对象。
*   **输出 (Output)**:
    *   在 `Chat.vue` 发起 streamChat 时声明 `AbortController`，并在页面组件 `onUnmounted` 时自动执行 `abort()` 中断未完成的网络推流连接。
    *   在 `MasteryRadar.vue` 中，在 `onUnmounted` 生命周期内移除全局 `window.addEventListener('resize')`，防止页面销毁后产生野指针和内存堆积。
*   **验收标准 (Acceptance Criteria)**:
    *   在流式响应还在吐字时点击切换到其他页面，浏览器 Network 面板显示 SSE 请求被瞬间 canceled 挂断，无后台带宽占用；反复切换页面，MasteryRadar 实例数量不递增，无内存泄漏。

---

### 任务 8.3：拓扑阅读 Agent 资料生成与前端讲义/代码/评测单卡片「单独重新计算」与导出
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P2)
*   **开发智能体**: backend-engineer (GLM-5.1) / frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-backend`, `oma-frontend`
*   **修改文件**: [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py) [MODIFY], [frontend/src/views/Chat.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Chat.vue) [MODIFY], [app/agents/topology_reader.py](file:///d:/project-edumatrix/edumatrix-main/app/agents/topology_reader.py) [NEW]
*   **核心意图**: 解决原讲义缺乏超链接导航的平面化缺点，引入“拓扑阅读”Agent 提供内部超链接指向前置/后续概念的交互 HTML 讲义；同时允许学生对单张讲义、代码卡片进行单独的重生成和追问，并支持一键导出。
*   **输入 (Input)**:
    *   文档切片、依赖有向图和局部重生成指令。
*   **输出 (Output)**:
    *   新建 `topology_reader.py`，生成包含知识点跳转超链接的 HTML 交互材料。
    *   后端开发组件级重生成接口 `/api/chat/regenerate_component`。
    *   前端在讲义、代码、导图、评测卡片底部均加装「🔄 单独重算」与「💬 对此项提问」以及「📥 导出为 MD/PDF」按钮，调用后端局部重算接口。
*   **验收标准 (Acceptance Criteria)**:
    *   点击生成的讲义内的概念跳转链接，页面可平滑跳转；点击某代码卡片底部的「单独重算」，大聊天框无反应，该代码卡片呈现加载动画并在一秒内局部刷新更新内容。

---

### 任务 8.4：收缩侧边栏抽屉与左右分栏高质排版 (Collapsible Sidebar Drawer & Split Resizable Layout)
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P1)
*   **开发智能体**: frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-frontend`
*   **修改文件**: [frontend/src/App.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/App.vue) [MODIFY], [frontend/src/views/Chat.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Chat.vue) [MODIFY], [frontend/src/components/SandboxConsole.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/SandboxConsole.vue) [NEW]
*   **核心意图**: 解决低分辨率下页面元素拥挤堆叠的排版瓶颈，将页面重构为科学的高对比度双面板布局，并为后端 Docker 沙箱加装可视化控制台，使学生能直接在界面内实操运行代码。
*   **输入 (Input)**:
    *   前端大屏排版网格定义与 Vue 路由视图，代码段运行结果（stdout, stderr, execute time）。
*   **输出 (Output)**:
    *   重构导航侧边栏，支持一键将 9 大导航条目折叠收起为极简图标的“抽屉（Drawer）”形态，释放横向空间。
    *   将 `Chat.vue` 重构为：左侧「沉浸式学习面板」（Markdown 讲义、Mermaid 图、沙箱代码控制台、评测面板）与右侧「智能协作面板」（多智能体时间轴、诊断饼图/雷达图、讯飞虚拟人语音）双栏布局。引入动态阻尼拉伸分割条 (Resizable Split Pane)。
    *   新建 `SandboxConsole.vue`（代码沙箱实操控制台）：提供行号对齐的代码编辑器（支持学生手动修改代码），下方带有“运行代码”按钮与“标准终端输出控制台”视图，当检测到执行结果中包含 Matplotlib 图表时，自动解析后台返回的 Base64 矢量图并在控制台下方高保真渲染图表。
*   **验收标准 (Acceptance Criteria)**:
    *   在分辨率低至 1280px 时页面自动触发双栏排版布局；在讲义中点击沙箱代码，代码自动装载入编辑器，点击“运行代码”，控制台能在 1.0s 内流畅打印 Docker 沙箱的输出日志，图表展示无错位。

---

### 任务 8.5：自适应教学动画与视频生成渲染柜/播放器面板 (VideoRenderPanel.vue)
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: Medium (P2)
*   **开发智能体**: frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-frontend`
*   **修改文件**: [frontend/src/components/VideoRenderPanel.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/VideoRenderPanel.vue) [NEW], [frontend/src/views/Chat.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Chat.vue) [MODIFY]
*   **核心意图**: 为完美闭合赛题中“生成个性化教学视频、动画资源”的要求，在右侧协作面板中挂载一个多模态视频渲染与播放组件。当系统通过 `SessionDirector` 决策生成视频时，此组件可以展示视频生成的各个流程步骤（脚本撰写 ➡️ 语音合成 ➡️ 画面渲染 ➡️ 视频压制），并以极佳的视觉动画播放成品微课视频/数学推导动画，增强赛题匹配度与演示说服力。
*   **输入 (Input)**:
    *   后端推送的视频生成进度状态、合成视频资源 URL/流。
*   **输出 (Output)**:
    *   新增 `VideoRenderPanel.vue`，实现加载阶段的任务流水线渲染（呼吸灯 + 刻度步骤条形式），完成阶段渲染原生 HTML5 视频播放器并自动播放。
*   **验收标准 (Acceptance Criteria)**:
    *   触发视频生成指令时，右侧面板能够以平滑动画展示任务流水线（脚本生成、音频合成、视频渲染、视频压制）；生成完成后显示播放器并能正常点击播放微课视频/公式推导动画。

---

### 任务 8.6：多模态课件知识图谱网络探索器 (KnowledgeBase Neo4j Graph Explorer)
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: Medium (P2)
*   **开发智能体**: frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-frontend`
*   **修改文件**: [frontend/src/views/KnowledgeBase.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/KnowledgeBase.vue) [MODIFY]
*   **核心意图**: 为白盒化展示后台 Neo4j 图数据库的三元组知识依赖关系，在前端课件管理页面集成可视化图谱网络探索器，让用户能直观查询和搜索知识节点的拓扑依存。
*   **输入 (Input)**:
    *   后端 Neo4j 导出的三元组依赖网络数据 `{ nodes: [...], edges: [...] }`
*   **输出 (Output)**:
    *   在 `KnowledgeBase.vue` 底部新增 ECharts-Graph 关联实体探索器，以星空网络形态展示所有已提取实体（节点：概念、图表、公式；链接：前置依赖、资源归属），支持输入关键字模糊过滤与节点高亮关联显示。
*   **验收标准 (Acceptance Criteria)**:
    *   点击课件库页面，图谱探索器能够自适应渲染出全量知识网，输入“最大池化”节点成功高亮其前后 2 级关联依赖边。

---

### 任务 8.7：无图场景前端可视化面板自适应折叠与讲义横向拓宽
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P1)
*   **开发智能体**: frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-frontend`
*   **修改文件**: [frontend/src/views/Chat.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Chat.vue) [MODIFY]
*   **核心意图**: 解决纯理论概念讲解讲义无须绘图、无须跑代码时，前端右侧可视化大屏呈现空洞黑色占位框、画面不饱满的缺陷，自适应隐藏画板并将讲义拓宽。
*   **输入 (Input)**:
    *   当前讲义所包含的特殊渲染标签（如 `<plot>`、`<svg>` 等）计数。
*   **输出 (Output)**:
    *   前端建立检测看门狗，若识别到讲义内容不涉及图表/代码/公式，自动平滑收缩庞加莱流形盘与可视化画布区域，将左侧讲义阅读区的横向宽度占比由 `50%` 拓宽至 `85%` 或全屏展示，并将数字人移至底部悬浮。
*   **验收标准 (Acceptance Criteria)**:
    *   提问无图场景问题（如“机器学习发展史”），右侧可视化区平滑收拢消失，排版自动拓展，无突兀黑边和空洞。

---

### 任务 8.8：SVG/Plot 渲染异常捕获与降级 Mermaid/ASCII 文本图框
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P1)
*   **开发智能体**: frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-frontend`
*   **修改文件**: [frontend/src/views/Chat.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Chat.vue) [MODIFY]
*   **核心意图**: 杜绝因大模型输出的图形标签代码存在参数中文、括号未闭合等语法毛刺导致前端 mathjax / function-plot 白屏死锁的惨剧，提供安全优雅降级防线。
*   **输入 (Input)**:
    *   前端解析 `<plot>` 或 `<svg>` 时抛出的 JS 异常。
*   **输出 (Output)**:
    *   后端在 ingestion 阶段进行 JS 词法静态扫描过滤，强行清洗非法字符；
    *   前端在初始化 function-plot 渲染时挂载 `try-except` 错误捕获屏障。若发生渲染崩溃，瞬间用备用方案顶替，在原图形位置渲染出带文字框说明的 **Mermaid 结构拓扑图** 或精美的 **ASCII 字符坐标图**。
*   **验收标准 (Acceptance Criteria)**:
    *   人为注入受损的 function-plot 代码，确认前端页面不报错、控制台不爆红，能优雅呈现出 ASCII 文本曲线卡片，且文字功能提示正常。

---

### 任务 8.9：组件级局部外科手术式重新计算 (Component-Level Regeneration)
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P1)
*   **开发智能体**: backend-engineer (GLM-5.1)
*   **绑定 Skill**: `oma-backend`
*   **修改文件**: [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py) [MODIFY]
*   **核心意图**: 优化流形对齐检验发现符号冲突时的回滚响应速度。废除以往粗暴拉起全部 5 个 Agent 重新并发生成的重负载行为，仅对失败组件进行局部手术重写。
*   **输入 (Input)**:
    *   `ManifoldAlignmentVerifier` 输出的精细到 Agent 的冲突报告 JSON。
*   **输出 (Output)**:
    *   使流形对齐校验器返回明确的错误主体（如 `failed_agent = \"极客助教\"`）；
    *   在 `agent_swarm.py` 中重构自愈循环，拦截该报告并仅对指定的 Agent 触发 `complete` 请求，同时将已生成的其他 4 个组件的数据缓存复用。
*   **验收标准 (Acceptance Criteria)**:
    *   模拟讲义与代码池化边界冲突引发回滚自愈，系统能在 2.0s 内仅重刷代码块输出，而讲义、雷达等内容保持不变，对齐修复大盘无延迟。

---

---

## 🌊 Wave 9：开源致谢与防幻觉轨迹公开化 (亮点包装与答辩准备) (已完成)

### 任务 9.1：防幻觉 DRAG 辩论与流形对齐轨迹白盒化及低分拦截
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: High (P0)
*   **开发智能体**: qa-reviewer (Claude)
*   **绑定 Skill**: `oma-qa`
*   **修改文件**: [drag_debate.py](file:///d:/project-edumatrix/edumatrix-main/drag_debate.py) [MODIFY], [manifold_alignment.py](file:///d:/project-edumatrix/edumatrix-main/manifold_alignment.py) [MODIFY], [frontend/src/components/AgentTimeline.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/AgentTimeline.vue) [MODIFY], [frontend/src/components/ManifoldVisualizer.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/ManifoldVisualizer.vue) [NEW]
*   **核心意图**: 将原本在后台默默运行的 DRAG 辩论和流形校验轨迹流式推送到前端展示，以极其震撼的“Poincare 庞加莱盘双曲对齐空间”和“三方辩论审查卡”形式向评委进行防幻觉透明力展示；优化低分过滤。
*   **输入 (Input)**:
    *   DRAG 证据评分、正反方交锋三元组与对齐 Poincare 测地线距离、散度值。
*   **输出 (Output)**:
    *   后端在 SSE 数据流中注入 `[think]` 日志信息（含辩论法官剔除机制判定与对齐散度）。
    *   在 `drag_debate.py` 中，当检索证据得分均低于 0.1 时强行拦截返回空并提示用户知识库未覆盖。
    *   前端时间轴以科技感动画动态呈现这些细节；新建 `ManifoldVisualizer.vue`，使用 Canvas 绘制一个 Poincare 双曲圆盘，将学生的“当前掌握度状态节点”和“教学大纲标准节点”作为圆盘中的两个发光粒子动态运动，展示两者沿着双曲测地线（Geodesic）进行仿射映射对齐的过程，并实时呈现 KL 散度与对齐偏差数值。
*   **验收标准 (Acceptance Criteria)**:
    *   模拟输入冲突或超范围数据，前端能实时展示辩论拦截日志；流形圆盘中两个粒子随学情推进动态靠近，检测到冲突时粒子发出红色警告并触发流形回滚动画提示。

---

### 任务 9.2：系统设置面板开源致谢墙与风格切换自定义
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: Medium (P2)
*   **开发智能体**: frontend-engineer (Gemini)
*   **绑定 Skill**: `oma-frontend`
*   **修改文件**: [frontend/src/views/Settings.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Settings.vue) [MODIFY]
*   **核心意图**: 展示团队的开源精神与系统合规性，在设置界面底部加装“开源致谢墙（Credits）”，列出 FastAPI/SQLAlchemy/ECharts/MathJax 等基础框架及许可协议；同时提供教学风格切换功能。
*   **输入 (Input)**:
    *   开源许可依赖声明列表。
*   **输出 (Output)**:
    *   在 `Settings.vue` 中挂载 Credits 弹窗，显示完整开源依赖包和协议声明。
    *   界面上提供选项：“苏格拉底式启发答疑” / “严肃严谨讲授”风格一键 Toggle。
*   **验收标准 (Acceptance Criteria)**:
    *   打开设置页，致谢墙渲染美观无缺项；更改教学风格后，AI 后续对话口吻会发生明显的角色切换。

---

### 任务 2.4：arXiv 联网学术检索本地缓存表
*   **状态**: [x] 已完成并网并通过单元测试
*   **优先级**: Medium (P2)
*   **开发智能体**: db-engineer (GLM-5.1)
*   **绑定 Skill**: `oma-db`
*   **修改文件**: [models.py](file:///d:/project-edumatrix/edumatrix-main/models.py) [MODIFY], [rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py) [MODIFY]
*   **核心意图**: 解决跨洋访问 arXiv API 经常产生的超时和频繁限制（429）痛点，在本地建立轻量级 sqlite 检索数据缓存。
*   **输入 (Input)**:
    *   用户搜索词与 arXiv 官方返回的论文实体 JSON。
*   **输出 (Output)**:
    *   在 `models.py` 中定义 `DBArxivCache` 数据模型，保存 `query_hash`、`arxiv_id`、`title`、`abstract`、`pdf_url`、`published_at`。
    *   在 `rag_engine.py` 中，发起联网检索前先比对缓存表，若命中直接召回，未命中再调外部接口并批量插入本地。
*   **验收标准 (Acceptance Criteria)**:
    *   连续两次提问相同的论文检索词，第二次查询可在 10ms 内直接从本地库毫秒级吐出，且官方请求连接数无增长。

---

## 👥 三、 人类工程师必须亲自动手做的高优任务 (Human-Led Tasks)

### 1. 教学资源库与知识图谱的“冷启动丰富化填充” (Seeding & Data Cleaning)
- 准备 ML/DL 权威 PDF/Markdown 真实课程切片并录入 RAG 语料库。
- 设计有向无环 (DAG) 概念依赖图谱，并在 Neo4j 数据库中建立关系。
- 录入真实的高质量数学/公式做题小测题库。

### 2. 科大讯飞流式 TTS 秘钥的获取与本地配置 (API Credentials)
- 获取讯飞语音合成流式版及星火 API 的密钥，并填入设置面板或 `.env` 环境变量中。

### 3. 7分钟参赛答辩演示视频的录制 (Demo Showcasing)
- 根据 MasteryRadar 和 AgentTimeline 设计演示剧本，录屏与真人口播配音。

### 4. 参赛技术申报书学术化润色 (Report Polish)
- 提炼自愈机制、并发加锁等高难工程细节，作为学术亮点写入申报书。

---

## Rules

- **Zero Code Implementation**: As the coordinator, you MUST NOT write, edit, or refactor backend, frontend, or database code yourself.
- **Zero Source Reading**: As the coordinator, do NOT run Read or Grep on codebase source files. Only read plan.md to identify task requirements, and CLAUDE.md / oma-config.yaml for configs.
- **Mandatory /compact**: After triggering a subagent, you MUST end your response by prompting the user: *"Please run /compact now to clear context tokens."*
- **Strict Division of Labor & Standard Spawning (分工与指派发令铁律)**: 必须严格按照团队分工工作。常规后端开发必须指派给 GLM-5.1 算力通道，发令方式必须使用标准的编排指令：`oma agent:spawn backend-engineer scratch/your_prompt_file.txt your_session_id`。严禁直接在命令行裸跑 `codex exec` 或使用管道重定向的方式绕过 `oma` 框架，这会导致环境变量 and Hook 配置失效而报错。
- **Metarule of Rules (写规则的规则)**: 你每写一个或修改一个需要读取的文件（包括但不限于 `WORKSPACE_STATE.md`, `CLAUDE.md`, `AGENTS.md`, `manual.md`, `plan.md`），必须把上述“严格分工与标准指派发令”的规则强制写入该文件的底部，此条写规则的规则亦作为底层的绝对铁律执行。
