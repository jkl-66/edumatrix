# EduMatrix 智教矩阵

EduMatrix 是面向高校机器学习课程的多智能体个性化学习平台。系统以团队预置并完成解析的垂直课程知识库为事实来源，通过自然语言画像、入学诊断、学习路径、九类学习资源、证据化任务完成、智能组卷和学习反馈，形成可连续使用的学习闭环。

本仓库是当前比赛作品的源码工作区，不代表现有压缩包已包含最新修改。接手开发先读 [AGENTS.md](AGENTS.md)、[作品与代码地图](docs/PROJECT_MAP.md) 的相关部分和 [当前事项](docs/CURRENT.md)。企业治理、专家认证、组织集成和自动视频生成不属于当前比赛主闭环，但部分服务仍被其他入口消费，不应仅凭名称删除。

## 1. 运行与体验

### 1.1 当前源码与历史作品包

当前源码按第 8 节运行。`packaging/` 和旧 ZIP 保留历史交付方式，未经重新打包、重新运行不能作为当前作品版本。新的评委包需按 [提交材料规则](docs/SUBMISSION_RULES.md) 核对材料、报名信息、许可证及真实运行结果；本轮接管整理没有生成最终提交包。

本地确定性模型和哈希嵌入可用于隔离测试及部分已有数据展示。新用户入学诊断和真实资源生成依赖外部模型；不能把无 API Key 的本地运行描述为完整新用户闭环。

### 1.2 演示账号

登录页提供学生、教师和管理员身份选择及演示账号填入功能；是否可登录取决于当前数据库和 `EDUMATRIX_DEMO_MODE`，不以旧文档中的密码为准。新学生可自行注册。本轮核验使用隔离数据库中的合成账号，未改正式账号或课程数据。

### 1.3 推荐体验顺序

1. 打开展示页并使用学生账号登录。
2. 在首页查看当前课程、今日任务、学习焦点和下一步。
3. 进入“学习画像”，查看知识图谱、证据、薄弱点和学习建议。
4. 进入“学习空间 -> 学习路径”，查看总路径、科目路径和今日必做任务。
5. 在今日知识点上生成完整资源包，并打开各类资源继续学习。
6. 完成今日必做任务后，观察路径勾选和智能组卷解锁状态。
7. 进入“测评中心 -> 智能组卷”完成作答，查看报告与错题。
8. 在错题本、复习中心、笔记本和资源中心继续深度学习。
9. 在智能对话中提出动态问题，查看来源与可审计的 Agent 决策摘要，并把生成产物归档到学习空间。
10. 分别使用教师和管理员账号查看最小角色闭环与后端权限边界。

## 2. 产品闭环

~~~
预置课程知识库
  -> 自然语言多轮画像
  -> 入学诊断
  -> 画像与路径
  -> 选择今日知识点
  -> 一键生成九类资源包
  -> 完成今日必做任务
  -> 智能组卷解锁
  -> 作答、判分与报告
  -> 画像 / 路径 / 错题 / 复习同步更新
  -> 下一日继续学习
~~~

### 2.1 自然语言画像

系统通过多轮对话主动了解学生的学习背景、目标、基础、困难和偏好，逐轮确认后形成画像。课程资料由团队预置知识库提供，学生首次使用不需要上传教材或课件；成绩单、课程表等个人资料仅作为可选辅助输入。

### 2.2 入学诊断

新课程先进行入学诊断。题目根据课程、知识点和当前画像动态生成，学生作答时可以记录理解程度。诊断报告不仅显示分数，还给出知识点掌握判断、强弱项、证据、建议和进入学习路径的动作。

### 2.3 学习路径与今日任务

总路径统筹不同课程，科目路径展示当前课程进度。今日任务明确给出知识点、资源类型、预计时长、完成条件、状态和进入动作。普通浏览不会改变掌握度；只有测验、代码运行、交互实验、费曼复述、正式组卷等产生可信结果的行为才写入学习事件。

### 2.4 九类学习资源

学生在总路径选择今日知识点后，一次生成并分发完整资源包：

| 资源 | 主要作用 | 完成证据 |
|---|---|---|
| 个性化讲义 | 结构化概念、例子、反例、公式、代码和小测 | 阅读检查点与必做小测 |
| 思维导图 | 展示概念、先修关系和知识结构 | 节点学习与任务确认 |
| 测验题资源 | 就地作答、即时判分、答案解析和追问 | 真实答案与判分结果 |
| 实训任务书 | 说明目标、环境、数据、步骤、检查点和提交物 | 实训检查点 |
| 代码沙盒 | 编辑、运行、停止、查看输出和接受 AI 点评 | 真实运行与任务检查点 |
| 视频推荐 | 按知识点和画像组织可信视频来源 | 今日任务要求的观看检查点 |
| PPT / 网页课件 | 可预览、编辑、保存版本和导出 | 课件学习检查点 |
| 可交互模型 | 调整参数、观察图表和理解模型规律 | 实验参数与观察结果 |
| 费曼复述 | 两轮复述、真实追问、反馈和提升对比 | 两轮原文、评分与改进证据 |

完整产物不会堆在对话消息中。每类资源都有独立空间、来源、版本、历史和生成状态；部分生成失败时保留成功项，只重试失败步骤。

### 2.5 智能组卷与反馈

测评中心只包含“入学诊断”和“智能组卷”。学习中的测验属于测验题资源，不是第三类正式测评。

智能组卷的解锁条件是当日必做任务全部完成，可选资源不会阻塞。未解锁时系统列出缺少的任务、完成条件和直达入口；解锁后仍由后端再次校验。正式交卷会更新画像、路径、下一日安排、错题本和复习计划，部分下游聚合失败不会丢失本次测评结果。

## 3. 核心页面

学生一级入口固定为：

| 入口 | 职责 |
|---|---|
| 首页 | 当前课程、今日任务、学习焦点、趋势和下一步 |
| 个人中心 | 资料、学习统计、热力图、趋势和最近动态 |
| 学习画像 | 知识图谱、掌握证据、薄弱点、建议和历史 |
| 学习空间 | 测评、路径、资源中心、错题、复习和笔记 |
| 智能对话 | 多模态问题、流式回答、来源、Agent 审计摘要和资源生成动作 |
| 知识库 | 预置课程书架、文档阅读、检索、图谱、来源和文件级资源生成 |
| 学习市场 | 发现、预览、发布和保存资源、资源包与学习路径副本 |
| 设置 | 学习偏好、模型连接状态和本地能力说明 |

知识库支持课程与章节组织、大窗口阅读、页码或章节定位、文本划选提问、图片区域框选提问、来源查看、导出、记笔记和针对当前文件生成资源。

教师端只保留课程、学生、测评和干预任务；管理员端只保留账号、模型、内容审核和系统状态。教师不能直接修改学生掌握度，角色和课程范围由后端授权校验。

## 4. 多智能体协同

产品层至少包含三类明确职责：

1. 学情分析 Agent：读取课程、画像、诊断和最近学习事件，判断当前学习需求。
2. 资源生成 Agent：根据知识点、来源和教学策略生成个性化资源候选。
3. 校验决策 Agent：检查来源、课程一致性、难度匹配和输出结构，记录分歧、修订与最终决策摘要。

当前资源包生成使用共享 Planner/Supervisor、资源生成、审核与发布检查；聊天流、M3 四角色任务和资源包不是同一条执行链。具体关系见 [代码地图第 3 节](docs/PROJECT_MAP.md#3-真实调用链和数据流)。普通聊天不能笼统称为每次都执行独立的 Prover/Challenger/Judge 辩论。

用户界面应展示职责、来源、校验、修订和最终决策摘要，不展示系统提示词、密钥或私有思维链。是否实际执行各阶段，以相应任务事件和模型调用记录为准。

## 5. 技术架构

~~~
Vue 3 + Vite + Pinia
        |
        | HTTP / 流式响应
        v
FastAPI + Uvicorn
        |
        +-- 认证与角色授权
        +-- 课程、画像、路径与学习事件
        +-- 资源、测评、错题、复习与笔记
        +-- RAG、知识图谱与来源定位
        +-- 多智能体编排与模型网关
        +-- 受限本地代码执行
        |
        v
SQLAlchemy + SQLite
~~~

主要技术：

- 前端：Vue 3、Vue Router、Pinia、Vite、ECharts、Monaco Editor。
- 后端：Python 3.11、FastAPI、Uvicorn、Pydantic、SQLAlchemy。
- 数据：SQLite 作为比赛单机运行数据库；课程、画像、路径、资源、事件和审计对象采用统一标识与版本。
- 检索：预置课程解析、结构化来源引用、哈希嵌入；FAISS 和句向量模型为可选增强。
- 模型：后端配置统一决定供应商；确定性模式用于本地测试，真实文本和多模态接口通过后端 .env 接入。
- 测试：Pytest、隔离 SQLite、Playwright 桌面 E2E、前端生产构建和结构化规格交叉校验。

## 6. 预置课程与来源

当前默认课程为机器学习基础与人工智能/深度学习两门，实质资产位于 `data/curated/`。根 `course_catalog.py` 还读取 `outputs/M0_阶段0基线与架构契约/datasets/`，该目录不能作为旧输出删除。部分原始公开课程材料位于：

    data/raw/github_repos/

来源、主题和许可证策略：

    data/manifest/source_manifest.jsonl
    data/manifest/github_repos_package_manifest.json

系统中的比赛演示课程使用冻结的合成教学上下文和明确来源引用。公开仓库材料的许可证文件随素材清单保留；使用和再分发仍须遵守各仓库许可证与原平台条款。

## 7. 运行模式与安全边界

### 7.1 默认模型

隔离测试可显式选择：

    EDUMATRIX_LLM_PROVIDER=deterministic
    EDUMATRIX_EMBEDDING_PROVIDER=hash
    EDUMATRIX_USE_FAISS=0

该模式只证明所测本地行为，不代表真实模型质量。当前入学诊断明确拒绝确定性回退，要求 `deepseek-v4-flash / thinking enabled / reasoning max`；真实资源工作流也必须按实际服务条件验证。

### 7.2 真实模型

真实模型只通过后端 .env 配置：

    EDUMATRIX_LLM_PROVIDER=openai
    EDUMATRIX_LLM_ENDPOINT=https://your-endpoint.example/v1
    EDUMATRIX_LLM_MODEL=your-model
    EDUMATRIX_LLM_API_KEY=your-key

    EDUMATRIX_MULTIMODAL_LLM_PROVIDER=openai
    EDUMATRIX_MULTIMODAL_LLM_ENDPOINT=https://your-endpoint.example/v1
    EDUMATRIX_MULTIMODAL_LLM_MODEL=your-vision-model
    EDUMATRIX_MULTIMODAL_LLM_API_KEY=your-key

诊断模型策略还要求 `.env.example` 中的 thinking 与 reasoning 配置。浏览器设置页不管理后端密钥。2026-10-24 原配置的 HTTP 401 已在用户更新凭据后解除，认证和简短真实 JSON 生成已通过；完整诊断和资源生成闭环尚未重新验证，详见 [当前事项](docs/CURRENT.md)。

### 7.3 代码沙盒

源码环境变量模板 .env.example 默认：

    EDUMATRIX_SANDBOX_MODE=disabled

历史作品包启动器为可信本机演示显式启用 `trusted_local`。该模式有语法、导入、超时和输出限制，但不具备 Docker 或虚拟机隔离。本轮运行使用 `disabled`，未验证 Docker。

## 8. 源码开发运行

首次从 GitHub 克隆时，可直接使用仓库中的课程资料；默认课程清单会校验文件及哈希。按下述步骤安装依赖、配置环境并初始化数据库即可。其他本地资产见 [课程输入与本地资产](data/README.md)。

环境要求：

- Windows 10/11
- Python 3.11
- Node.js 20.19+（20 系列）或 22.12+，按当前 Vite 依赖的 engines 要求
- npm

后端：

    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    # 首次配置且 .env 不存在时才复制，保留已有配置
    if (-not (Test-Path .env)) { Copy-Item .env.example .env }
    .\.venv\Scripts\python.exe run.py

前端开发服务：

    Set-Location frontend
    npm ci
    npm run dev -- --host 127.0.0.1

访问：

- 前端开发服务：http://127.0.0.1:5173/
- 后端与作品包构建前端：http://127.0.0.1:8000/
- OpenAPI：http://127.0.0.1:8000/docs

已安装项目依赖后，也可双击根目录 `start.bat`。它会运行预检和数据库修复；`run.py` 会处理占用端口的进程。只核验页面时可直接用 `.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`，并将 `EDUMATRIX_DB_PATH` 指向隔离库。其他脚本的用途见 [scripts/README.md](scripts/README.md)。

## 9. 验证

运行前检查：

    .\.venv\Scripts\python.exe scripts\runtime_preflight.py

语音与自动视频运行时在预检中为可选能力，缺失会提示，不阻止主体启动。核心依赖缺失仍使预检失败。

历史评委窄烟测需先检查其账号和环境，再启动隔离服务：

    .\.venv\Scripts\python.exe scripts\e2e_no_docker.py

该烟测检查健康接口、展示页、登录页、学习空间、预置知识库、允许的安全代码和被拦截的危险代码。它只证明评委运行链可用，不替代完整功能验收。

聚焦测试（PowerShell）：

    $env:PYTHON_DOTENV_DISABLED='1'
    $env:EDUMATRIX_ENV='test'
    $env:EDUMATRIX_LLM_PROVIDER='deterministic'
    $env:EDUMATRIX_EMBEDDING_PROVIDER='hash'
    $env:EDUMATRIX_SANDBOX_MODE='disabled'
    .\.venv\Scripts\python.exe -m pytest -q tests\test_runtime_preflight_optional_media.py tests\test_f3_profile_onboarding.py

前端行为测试与独立构建输出：

    Set-Location frontend
    npm test
    npm run build -- --outDir ../scratch/frontend-check-dist

当前验证结果和证据入口见 [CURRENT.md](docs/CURRENT.md)。`outputs/原系统融合重构执行/evidence/` 保存历史验证，不能无日期地当成本次结果。项目不以代码行数或测试数量代替逐功能证据，也不宣称未经独立评测的模型质量指标。

更新自有源码/配置索引：在根目录运行 `.venv/Scripts/python.exe scripts/update_code_index.py`。它还解析索引内全部 Python 文件，不启动服务或修改数据库。

## 10. 项目结构

~~~
app/                         FastAPI 领域服务、统一对象、授权与数据协议
frontend/src/                Vue 页面、组件、路由、状态和 API 客户端
data/                        课程输入、清单、缓存和模型辅助数据
scripts/                     初始化、审计、迁移、烟测和 E2E
tests/                       单元、集成、权限、数据与契约测试
docs/                        当前作品地图、当前事项和源码索引
docs/history/                旧协作、分工和实施资料，仅作历史线索
packaging/                   Windows 一键运行和交付说明
outputs/                     技术文档、规格、测试与验收证据
run.py                       后端启动入口
start.bat                    本地源码开发启动器
requirements.txt             Python 依赖
frontend/package.json        前端依赖与构建命令
~~~

## 11. 交付边界

- 当前周期只验收桌面端，移动端延期。
- 作品以高校机器学习课程学习闭环为核心，不扩展企业治理、专家认证和真实组织集成。
- 视频推荐已进入九类资源；自动视频生成不是当前交付项。
- 确定性模式只覆盖相应本地测试；真实生成还依赖有效模型认证、策略、额度、网络和服务容量。
- trusted_local 只解决可信本机比赛演示，不等于生产级安全沙箱。
- 现有比赛 ZIP 只有在单独执行最终打包任务后才会包含其后的代码和文档更新；源码工作区的完成状态不能自动推断到旧压缩包。

## 12. 关键文档

- [AGENTS.md](AGENTS.md)：轻量工作约定。
- [作品与代码地图](docs/PROJECT_MAP.md)：功能、审美、真实调用链和定位入口。
- [当前事项](docs/CURRENT.md)：近期改动、实际验证及剩余限制。
- [code-index.csv](docs/code-index.csv)：自有文件索引。
- [提交材料规则](docs/SUBMISSION_RULES.md)：编写材料和正式打包时使用。
- [历史资料](docs/history/README.md)、`outputs/` 旧方案、旧恢复包和 `packaging/` 旧说明：仅作线索，不是现行执行门禁。

## 13. 许可证

项目自身许可见 LICENSE 和 NOTICE。第三方代码、模型、字体和课程来源按照各自许可证使用；课程素材来源与许可证候选记录见 data/manifest/。
