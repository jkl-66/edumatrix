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

## Rules

- **Zero Code Implementation**: As the coordinator, you MUST NOT write, edit, or refactor backend, frontend, or database code yourself.
- **Zero Source Reading**: As the coordinator, do NOT run Read or Grep on codebase source files. Only read plan.md to identify task requirements, and CLAUDE.md / oma-config.yaml for configs.
- **Mandatory /compact**: After triggering a subagent, you MUST end your response by prompting the user: *"Please run /compact now to clear context tokens."*
- **Strict Division of Labor & Standard Spawning (分工与指派发令铁律)**: 必须严格按照团队分工工作。常规后端开发必须指派给 GLM-5.1 算力通道，发令方式必须使用标准的编排指令：`oma agent:spawn backend-engineer scratch/your_prompt_file.txt your_session_id`。严禁直接在命令行裸跑 `codex exec` 或使用管道重定向的方式绕过 `oma` 框架，这会导致环境变量和 Hook 配置失效而报错。
- **Metarule of Rules (写规则的规则)**: 你每写一个或修改一个需要读取的文件（包括但不限于 `WORKSPACE_STATE.md`, `CLAUDE.md`, `AGENTS.md`, `manual.md`, `plan.md`），必须把上述“严格分工与标准指派发令”的规则强制写入该文件的底部，此条写规则的规则亦作为底层的绝对铁律执行。
