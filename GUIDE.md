# 软件杯 A3 赛题 — AI 全栈高效开发终极操作手册（含 Skill 系统 · 向量引擎中转增强版）

本手册旨在指导开发团队充分释放 **Antigravity IDE**、**Claude Code** 及多智能体框架的潜能，高效应对软件杯 A3 赛题（基于大模型的个性化资源生成与学习多智能体系统开发）。本版本已深度融合 **“向量引擎 API 中转方案”** 与 **“SOP 极速协作流程与去 AI 视觉味调优方案”**，确保安全、低成本、高效率地冲击国家级奖项。

---

## 一、 目标与工具概览

### 1. 核心工具链配置

* **Antigravity IDE** (免费)：开发总控中心，内置高速 Gemini 3.1 Pro 智能体。
* **Claude Code** (主力编程引擎)：集成在 Antigravity 终端内。**通过向量引擎 API 中转调用，无需直接订阅 Claude Pro，免除海外信用卡门槛，彻底规避封号风险。**
* **oh-my-ag** (免费)：多智能体编排框架，作为您的“AI 项目经理（Sisyphus）”。
* **GLM-5.1** (通过 CCSwitch 引入)：用于处理长时、高负载的后端与算法核心任务。
* **antigravity-awesome-skills** (免费)：内置 243+ 专业技能库，为各专业 Agent 配备一键式工作流工具箱。
* **一键协作流脚本** (`sync.bat` & `pull.bat`)：纯英 ASCII 编码的高鲁棒性同步脚本，配置 `Alt + G` / `Alt + P` 键盘宏，实现极速团队协作。

### 2. AI 团队分工矩阵（推荐配置）

| 角色 | 负责模型 | 接入方式 | 职责与选用理由 | 推荐绑定 Skill |
| :--- | :--- | :--- | :--- | :--- |
| **🧠 总指挥 / 任务编排** | **Claude Opus 4.6/4.7** | Antigravity 内置 / 向量引擎 | 顶层战略规划、任务拆解与上下文路由管理 | `solution-architect` |
| **⚙️ 后端 / 核心算法** | **GLM-5.1** | CCSwitch → oh-my-ag | 8 小时自主工作、健壮后端逻辑与多模态 RAG 开发 | `backend-api`, `database-design` |
| **🎨 前端 / 视觉 UI** | **Gemini 3.1 Pro** | Antigravity 内置 (免费) | 视觉界面实时渲染、原型图设计，确保极速预览循环 | `frontend-design`, `ui-ux-pro-max-skill` |
| **📄 参赛文档提炼** | **混合**：日常 Gemini，终稿 Opus | 内置接口 / 向量引擎 | 日常接口变更更新；项目期末一键导出高一致性参赛报告 | `doc-coauthoring` |
| **🔍 代码审查 / 安全审计** | **Claude Opus 4.6/4.7** | **向量引擎中转 → Claude Code** | 负责代码质量把关、SQL 注入及敏感数据越权防御审计 | `code-reviewer`, `security-auditor` |

---

## 二、 环境搭建与工具安装

### 1. 基础环境
* 安装 **Node.js LTS** (https://nodejs.org)，确保全局可用 `npm` / `npx` 命令。
* 可选安装 **Bun** 加速运行依赖：`curl -fsSL https://bun.sh/install | bash`。

### 2. Antigravity IDE 部署
* 访问官方网站安装并使用 Google 账号登录。
* 首次启动可选择导入 VS Code 的配置与插件。

### 3. Claude Code 极速中转集成
**向量引擎**是一个聚合多大模型的 API 中转平台，国内直连低延迟，按量付费，无需外卡：
1. **获取 API Key**：注册向量引擎平台并生成您的 API Key。
2. **配置环境变量**：在 Windows 系统中，直接配置系统环境变量，或者在您的命令行终端配置文件中添加：
   ```bash
   export ANTHROPIC_BASE_URL="https://api.vector-engine.com/v1"
   export ANTHROPIC_API_KEY="您的向量引擎API密钥"  # 兼容原生 SDK 规范
   ```
3. **验证连通性**：在终端输入 `claude` 即可唤起 Claude Code，自动通过向量引擎的中转通道，规避网络阻碍。

### 4. 安装多智能体协作框架与依赖
在终端中依次运行以下命令：
```bash
bunx oh-my-ag                  # 安装多智能体编排器
npx antigravity-awesome-skills --antigravity  # 下载 243+ 技能库
npm install -g @cubis/foundry   # 开发规范一键安装向导
npm install -g @disdjj/acplugin # 跨工具配置转换器
```

### 5. Skill 技能系统配置
Skill 是将 Agent 从“通用助手”升级为“领域专家”的标准作业程序（SOP）。
* **安装**：将需要的技能文件夹复制到项目目录：`<项目根目录>/.agent/skills/` 中。
* **重启**：**复制后务必重启 Antigravity 编辑器**，大模型即可在多轮对话中自动识别并调用对应 Skill。

---

## 三、 开发流程七步法（含防幻觉与去 AI 视觉味调优）

### 第 1 步：确立项目宪法（防幻觉基石）
1. 用 Antigravity 打开项目目录。
2. 对内置 Gemini 智能体下达指令：
   > **“请通读整个项目，生成一份详细的 `AGENTS.md`，包含架构、模块、数据流、技术栈、代码规范。规则：所有函数必须单一职责，变量命名遵循驼峰规范。”**
3. 这份 `AGENTS.md` 将作为所有 AI 开发者的行为准则与项目背景约束，有效降低多轮对话后的上下文幻觉。

### 第 2 步：赛题转作战计划
1. 将赛题 PDF 拖入对话框，输入指令（调用 Opus）：
   > **“使用 `solution-architect` 技能，结合项目框架与赛题，生成详细开发计划 `plan.md`，按功能模块拆分成可独立测试的小任务，每个任务需明确输入输出和验收标准。”**
2. 审阅 `plan.md`。此文件将作为后续各 Agent 并行开发的唯一任务跟踪看板。

### 第 3 步：一键双击启动本地联调（熔断保护机制）
* **一键极速启动**：双击运行 [start.bat](file:///d:/桌面/edumatrix-main/start.bat)（或在编辑器内按快捷键 **`Alt + L`**），一键在后台开启本地 FastAPI 后端与 Vite 前端，3 秒后自动弹出浏览器跳转到 [http://127.0.0.1:5173](http://127.0.0.1:5173)。
* **离线降级熔断网**：在网络抖动或中转 API 欠费时，后端会自动无缝降级为本地离线小模型 `DeterministicEducationLLM`（模拟模式）。**此时前端 UI 交互与自适应逻辑完全可离线联调**，避免阻断前端开发进度。
* **大模型极速配置**：在项目根目录新建 `.env` 配置文件，写入 `EDUMATRIX_LLM_API_KEY=your_key`，后端启动时会自动静默加载，免去终端重复输入。

### 第 4 步：团队高频 Git 一键协作与冲突合并
并行开发时，必须遵守极速同步规范，防止代码产生混乱：
1. **开发前一键拉取 (`Alt + P`)**：每次开始写代码前，按下 **`Alt + P`**（运行 `pull.bat`），执行 `git pull origin main --rebase` 下载并合并队友最新的提交。
2. **小步快跑开发**：分配任务给 Agent：
   > **“@frontend-agent 使用 `frontend-design` 技能实现用户仪表盘，函数控制在 50 行内，开发完立即运行单元测试。”**
3. **完成一键同步 (`Alt + G`)**：测试通过后，按下 **`Alt + G`**（运行 `sync.bat`），自动将所有最新文件（含 Untracked 文件）暂存、提交并安全 push 到 GitHub。
4. **Git 冲突解决标准**：如果由于并行提交产生 `CONFLIT` 冲突（如 `vite.config.js` 或 `rag_engine.py`），手动保留本地回环端口绑定以及 RAG 引擎的 Bug 修复代码，完成变基并重新一键推送。

### 第 5 步：安全网与去 “AI 视觉味” 调优
为了让系统呈现高级感并杜绝低质代码，人工必须在以下方面强制审核：
* **去 AI 视觉味**：严禁让前端 Agent 生成 AI 标志性的圆角极大、蓝紫色渐变按钮及默认毛玻璃堆叠界面。必须在提示词中直接指定视觉版式：
  > **“将页面改造为瑞士极简风格（Swiss Grid Style），强调大量非对称留白、高级暗色美学（Dark Mode Base）、粗字重无衬线字体，并使用 `ui-ux-pro-max-skill` 技能进行打磨。”**
* **安全审计**：代码提交前，命令 `code-reviewer` 智能体：
  > **“请调用 `code-reviewer` 智能体，使用 `security-auditor` 技能审查最新提交的后端代码，检查 SQL 注入、跨站脚本（XSS）漏洞，并输出安全报告。”**
  *(智能体在后台启动 Claude Code，网络请求通过向量引擎安全加密传输。)*

### 第 6 步：文档与答辩报告（混合生成策略）
* **轻量级日常文档**：使用免费的 Gemini 3.1 Pro 实时生成 API 注释及 CHANGELOG 更新记录。
* **终稿参赛文档**：项目结束后，调用 Claude Opus 一次性生成高一致性报告：
  > **“使用 `doc-coauthoring` 技能，通读全套项目文件，生成《系统需求分析》《概要设计说明书》《技术难点攻克报告》与《答辩PPT演讲大纲》，确保文字逻辑一致、专业度达参赛标准。”**

### 第 7 步：严格最终检查与备份
* 核对赛题功能点是否百分之百闭环。
* 至少提前 24 小时进行多轮压缩包打包测试，严格按照官方要求格式提交。

---

## 四、 角色分工与模型配置速查表

| 指令接收模型 | 对应模型 | 接入方式 | 赛题主要用途 | 核心绑定 Skill |
| :--- | :--- | :--- | :--- | :--- |
| **Sisyphus (主脑)** | **Claude Opus 4.6/4.7** | Antigravity 内置 / 向量引擎 | 架构设计、任务编排、计划跟踪 | `solution-architect` |
| **Backend Agent** | **GLM-5.1** | CCSwitch → oh-my-ag | 核心算法、多模态 RAG、数据库事务 | `backend-api`, `database-design` |
| **Frontend Agent** | **Gemini 3.1 Pro** | Antigravity 内置 (免费) | 前端 UI 绘制、交互式原型图预览 | `frontend-design`, `ui-ux-pro-max-skill` |
| **Auditor Agent** | **Claude Opus 4.6/4.7** | **向量引擎中转 → Claude Code** | 代码审计、高频 Bug 拦截、性能重构 | `code-reviewer`, `security-auditor` |

---

## 五、 费用与预算控制
* **总指挥内置模型**：Antigravity IDE 内置 Gemini（免费），可选订阅 Google AI Pro（约 $20/月）。
* **向量引擎中转费用**：按量计费，团队开发初期充值 **¥50 - ¥100 即可支持一个月的超高频 Claude Code 深度审计与开发需求**。
* **GLM-5.1 API 费用**：智谱开放平台 API 价格极低，比赛项目压测与运行成本几乎可以忽略不计。
* **辅助工具（oma、start.bat、sync.bat）**：全部免费开源。
