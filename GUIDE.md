# 软件杯 A3 赛题 — AI 全栈高效开发终极操作手册（含 Skill 系统 · 向量引擎中转增强版）

本手册旨在指导开发团队充分释放 **Antigravity IDE**、**Claude Code** 及多智能体框架的潜能，高效应对软件杯 A3 赛题（基于大模型的个性化资源生成与学习多智能体系统开发）。本手册已全量整合**“向量引擎 API 中转方案”**、**“SOP 极速团队 Git 协作流”**、**“本地一键启动与离线熔断机制”**、**“西西弗斯分级调度自愈协议”**与**“去 AI 视觉味 UI/UX 调优规范”**，是一份开箱即用、直击国赛特等奖的保姆级实操宝典。

---

## 一、 目标与工具概览

### 1. 赛题与目标
* **赛题**：A3 “基于大模型的个性化资源生成与学习多智能体系统开发”
* **目标**：基于 GitHub 基础框架，使用 AI 辅助完成前端、后端、算法开发，打通 1+3+5 智能体诊断与自适应推荐闭环，冲击国赛一等奖及以上。

### 2. 核心工具链
* **Antigravity IDE** (免费)：开发总控中心，内置高速 Gemini 3.1 Pro 智能体。
* **Claude Code**：主力编程引擎，集成在 Antigravity 终端内。**通过向量引擎 API 中转调用，无需直接订阅 Claude Pro，规避封号风险，国内低延迟直连。**
* **oh-my-ag** (免费)：多智能体编排框架，作为您的“AI 项目经理”。
* **GLM-5.1** (通过 CCSwitch 引入)：替代 Claude 处理长时、高负载的后端与算法开发任务。
* **antigravity-awesome-skills** (免费)：内置 243+ 专业技能库，为每个 Agent 配备开箱即用的专业工具箱。

### 3. AI 全明星队最佳分工矩阵

| 角色 | 负责模型 | 接入方式 | 选用理由 | 推荐绑定 Skill |
| :--- | :--- | :--- | :--- | :--- |
| **🧠 总指挥 / 计划制定 (Sisyphus)** | **Claude Opus 4.6/4.7** | Antigravity 内置 / 向量引擎 | 顶级战略推理、1M 超长上下文，极其稳定的任务拆解与 Agent 团队调度能力 | `solution-architect` |
| **⚙️ 后端 / 核心算法** | **GLM-5.1** | CCSwitch → oh-my-ag | 8 小时自主工作、SWE-Bench Pro 第一、对中文教研概念理解深厚且成本极低 | `backend-api`, `database-design` |
| **🎨 前端 / 视觉开发** | **Gemini 3.1 Pro** | Antigravity 内置 (免费) | 绝佳的多模态视觉理解与实时渲染，快速缩短“设计到代码”的迭代循环 | `frontend-design`, `ui-ux-pro-max-skill` |
| **📄 文档与注释** | **混合**：日常 Gemini，终稿 Opus | 内置接口 / 向量引擎 | 日常轻量日志快速低成本，最终报告高一致性与专业规范度 | `doc-coauthoring` |
| **🔍 代码审查 / 安全审计** | **Claude Opus 4.6/4.7** | **向量引擎 API 中转 → Claude Code** | 顶级批判性思维，专门用于拦截跨文件异步死锁、SQL 注入与逻辑越权防御 | `code-reviewer`, `security-auditor` |

---

## 二、 环境搭建与工具安装（从零开始）

### 1. 基础环境
* 安装 **Node.js LTS**（[https://nodejs.org](https://nodejs.org)），确保系统全局可用 `npm` 与 `npx` 命令。
* 可选安装 **Bun**：Linux/Mac 用户执行 `curl -fsSL https://bun.sh/install | bash`，**Windows 用户可直接跳过，用原生 npm/npx 完美代替**。

### 2. Antigravity IDE 安装
* 前往官方渠道下载并安装，使用 Google 账号登录。
* 首次启动可导入 VS Code 的配置。如需中文界面，在扩展商店搜索“Chinese”安装官方语言包。

### 3. Claude Code 集成（通过向量引擎 API 中转）
**向量引擎**是一个聚合多大模型的 API 中转平台，国内直连低延迟，按量付费，无需境外信用卡：
1. **注册并获取 API Key**：访问向量引擎官网完成注册，生成一个 API Key。
2. **配置环境变量**：在 Windows 系统中，直接配置系统环境变量，或者在您的命令行终端配置文件中添加：
   ```bash
   export ANTHROPIC_BASE_URL="https://api.vector-engine.com/v1"
   export ANTHROPIC_API_KEY="您的向量引擎API密钥"  # 兼容原生 SDK 规范
   ```
3. **安装扩展**：在 Antigravity 扩展商店搜索“Claude Code”并安装。
4. **验证连通性**：打开终端（`Ctrl + ~`），输入 `claude` 即可进入交互，测试是否正常调用。

### 4. 配置 GLM-5.1（通过 CCSwitch）
1. 前往智谱 AI 开放平台获取 **GLM API Key**。
2. 下载安装 **CCSwitch**（轻量级 API 路由工具）。
3. 在 CCSwitch 中添加 GLM 配置节点，填入 API Key 和地址（`https://open.bigmodel.cn/api/paas/v4`）。
4. 此后在 `oh-my-ag` 中指定后端/算法任务使用 GLM-5.1 时，CCSwitch 会自动路由。

### 5. 安装多智能体指挥系统
在终端中依次执行以下命令：
```bash
npx oh-my-ag                  # 核心编排器，Sisyphus 主脑 (Windows 推荐使用 npx)
npx antigravity-awesome-skills --antigravity  # 安装 243+ 本地技能库
npm install -g @cubis/foundry   # 工作流与规则一键安装向导
npm install -g @disdjj/acplugin # 跨工具配置转换器
```
* **oh-my-ag** 启动后，你将通过 `oma` 命令与总指挥 Sisyphus 对话。
* **@cubis/foundry** 可通过 `cbx init` 向导快速部署开发规范。
* **@disdjj/acplugin** 可复用 Claude Code 的插件配置到 Antigravity。

### 6. Skill 技能系统配置
Skill 是为 AI 预设的专业工作流程包，能让 AI 从“通用助手”升级为“专属专家”。一个 Skill 包含入口文件 `SKILL.md`，以及可选的工具脚本 `scripts/` 和参考资源 `resources/`。

#### A. 为什么使用 Skill？
* **普通提示词**：一次性提问，AI 容易在上下文变长后产生严重的健忘和输出质量不稳定。
* **Skill**：包含完整标准作业流程 (SOP) + 工具 + 外部权威资源，输出极其稳定、专业、符合行业规范。

#### B. Skill 加载与启用步骤
1. **找到技能目录**：克隆下来的 `antigravity-awesome-skills` 文件夹即本地技能库。
2. **复制技能到项目**：将需要的技能文件夹复制到以下任一目录：
   * **项目级（推荐）**：`<项目根目录>/.agent/skills/`（仅与本项目绑定）。
   * **全局级**：`~/.gemini/antigravity/skills/`（一次安装，所有项目可用）。
3. **重启生效**：文件复制后**务必重启 Antigravity 编辑器**，AI 会在后续对话中自动识别并激活。

#### C. 精选 Skill 推荐表

| 场景 | 推荐 Skill | 能为你的项目做什么 |
| :--- | :--- | :--- |
| **规划与架构** | `solution-architect` | 设计系统高并发架构、模块划分和技术选型 |
| **前端开发** | `frontend-design`, `ui-ux-pro-max-skill` | 生成高质量、风格化、无“廉价 AI 味”的现代极简前端界面 |
| **后端开发** | `backend-api`, `database-design` | 设计规范 RESTful API、优化多维 E-R 数据库表 |
| **质量保障** | `code-reviewer`, `security-auditor` | 进行静态代码审查、主动发现高并发死锁与逻辑漏洞 |
| **文档生成** | `doc-coauthoring` | 根据前后端代码库自动生成高质量参赛技术报告与用户手册 |

#### D. 如何在对话中调用 Skill
对 Sisyphus 下达指令时明确指定 Skill 即可，例如：
* *“Sisyphus，让前端 Agent 在设计仪表盘时，使用 `frontend-design` 技能，采用现代简约风格。”*
* *“Sisyphus，让后端 Agent 使用 `backend-api` 技能来设计用户管理模块的 API。”*

---

## 三、 本地服务启动与离线熔断机制

为了方便开发与调试，项目已深度集成了**免环境配置启动**与**离线熔断保护网**：

### 1. 一键双击启动器 (`start.bat`)
项目根目录内置了绿色便携的 [start.bat](file:///d:/桌面/edumatrix-main/start.bat)。
* **使用方法**：直接双击运行 [start.bat](file:///d:/桌面/edumatrix-main/start.bat)，或者在编辑器内按下快捷键 **`Alt + L`**。
* **工作逻辑**：
  1. 自动弹出新终端，在后台启动本地 FastAPI 后端服务（8000 端口）。
  2. 自动弹出第二个终端，在后台启动本地 Vite 前端服务（5173 端口，强制绑定 `127.0.0.1` 绕过梯子拦截）。
  3. 主引导窗口在 3 秒后**自动开启浏览器**跳转到 [http://127.0.0.1:5173](http://127.0.0.1:5173)，随后优雅关闭。
  4. *注意：留在任务栏的两个黑色“引擎”窗口请勿关闭，使用完毕后直接关闭窗口即可下线服务。*

### 2. 离线模拟熔断保护网 (Deterministic Fallback)
如果您没有配置 API 密钥，或者在中转 API 遇到网络波动、额度欠费时：
* 后端服务会自动无缝降级为本地离线教学小模型 `DeterministicEducationLLM`（模拟模式）。
* **效果**：系统所有答卷评估、画像诊断、ECharts 雷达图交互**全部可以完全离线正常演示和联调**，避免阻断前端开发进度，开发爽快度拉满。

### 3. 一劳永逸的环境变量配置
在项目根目录新建一个 `.env` 配置文件，写入大模型配置：
```ini
EDUMATRIX_LLM_PROVIDER=openai
EDUMATRIX_LLM_API_KEY=your_vector_engine_key_here
EDUMATRIX_LLM_BASE_URL=https://api.vector-engine.com/v1
EDUMATRIX_LLM_MODEL=gpt-4o-mini
```
保存后，`start.bat` 每次启动都会自动读取，从此再无需手动在控制台配置。

---

## 四、 团队高频 Git 一键协作与冲突合并

为了防止并行开发时代码产生严重混乱，团队必须遵守这套极速对称同步流：

### 1. 对称快捷键工作流
我们为您的编辑器配置了两个对称的、用纯英 ASCII 构建的极速同步脚本：
* **`Alt + P` (一键拉取更新)**：
  调用 [pull.bat](file:///d:/桌面/edumatrix-main/pull.bat)，执行 `git pull origin main --rebase`，每天开始开发前一键拉取队友最新的代码并合并。
* **`Alt + G` (一键同步推送)**：
  调用 [sync.bat](file:///d:/桌面/edumatrix-main/sync.bat)，自动将您刚才所有的开发成果（包含 Untracked 文件）一键暂存、提交并 push 到 GitHub，整个过程耗时仅需 3 秒。

### 2. 协作冲突合并标准（以 rebase 为准）
当拉取队友代码时，如果因为两人同时修改了同一个文件而发生 Merge Conflict 冲突（例如在 `frontend/vite.config.js` 或 `rag_engine.py` 中）：
1. 终端会提示：`CONFLICT (add/add): Merge conflict in...`
2. **解决步骤**：
   * 打开冲突文件，手动移除 Git 的 `<<<<<<< HEAD` 等冲突标记。
   * **冲突裁决标准**：强制保留本地的 `127.0.0.1` 绕过梯子绑定，以及本地对 RAG 初始化闪退的 Bug 修复代码。
   * 打开终端执行：`git add <冲突文件名>` 将冲突标记为已解决。
   * 执行 `git rebase --continue` 并在弹出的 Vim 窗口中输入 `:wq` 回车保存退出。
   * 运行 `git push origin main` 重新推送上云，保持版本库纯净。

---

## 五、 开发流程七步法（含防幻觉与去 AI 视觉味调优）

### 第 1 步：确立项目宪法（防幻觉基石）
1. 用 Antigravity IDE 打开项目目录。
2. 按 `Ctrl + L` 唤起对话，对 Gemini 智能体下达指令：
   > **“请通读整个项目，生成一份详细的 `AGENTS.md`，包含架构、模块、数据流、技术栈、代码规范。规则：所有函数必须单一职责，变量命名遵循驼峰规范。”**
3. 检查并确认生成的 [AGENTS.md](file:///d:/桌面/edumatrix-main/AGENTS.md)。它将作为所有 AI 协作开发的唯一“底线标准”。**凡是调用已有函数，必须先用工具查找，严禁凭大模型记忆编造。**

### 第 2 步：赛题转作战计划
1. 将赛题 PDF 拖入对话框，输入指令（调用 Opus）：
   > **“结合项目框架和赛题要求，生成详细开发计划 `plan.md`，按功能模块拆分成可独立测试的小任务，每个任务需明确输入输出和验收标准。生成计划时，请使用 `solution-architect` 技能来设计系统架构。”**
2. 审阅 `plan.md`。此文件将作为整个开发周期内的任务调度中心。

### 第 3 步：启动 AI 团队并行开发 (Oma 编排)
1. 在终端输入 `oma` 启动 Sisyphus。
2. 向 Sisyphus 明确指定角色与技能分配策略：
   > **“Sisyphus，请记住：战略规划用 Opus，后端和算法任务用 GLM-5.1，前端和UI任务用Gemini，代码审查用Opus。”**
   > **“另外，前端任务默认使用 `frontend-design` 技能，后端任务默认使用 `backend-api` 技能，文档任务默认使用 `doc-coauthoring` 技能。”**
   > **“现在按照 `plan.md` 开始第一阶段开发，为每个任务分配合适的 Agent 和技能。”**
3. 安排 Agent 并行作业，例如：
   > **“@frontend-agent 使用 `frontend-design` 技能实现用户仪表盘，@backend-agent 使用 `backend-api` 技能实现对应的 API，@algorithm-agent 实现学习路径推荐算法。”**

### 第 4 步：设置安全网与“西西弗斯分级调度自愈规则”
主脑在分配和调度任务时，必须严格遵守我们在 [AGENTS.md](file:///d:/桌面/edumatrix-main/AGENTS.md) 第十章中为它写入的 **分级调度自愈协议**：
1. **每事必读**：所有 Agent 开始任务前，必须重新读取 `plan.md` 和 `AGENTS.md`。
2. **重试上限限制**：常规 CRUD 业务代码（**Tier-1** 级别）默认指派给低价的 **GLM-5.1**。在提交前，必须运行 Linter 检查并跑通单元测试。若测试失败，GLM 自愈重试的上限为 **2 次**。
3. **自动升级派发 (Escalation)**：若 GLM 重试 2 次后测试依然报错，Sisyphus 必须立即终止 GLM 调用，**将当前任务自动升级为 Tier-2 级**。打包代码及报错日志，**派发给 Claude 智能体 (Claude Code)** 进行重构与攻坚。
4. **进展双写**：每个 Agent 完工后，必须更新 `plan.md` 并将修改记录写入 `CHANGELOG.md`。

### 第 5 步：人工打磨与去“AI 味”视觉调优
国赛评委极度反感千篇一律的 AI 生成界面。必须在前端开发中彻底剔除 AI 标志性的“大圆角蓝色高光、低质毛玻璃、重度投影阴影”的浮夸风格，进行人工与模型的定向调优：
* **去 AI 视觉味规范**：命令前端 Agent 强制使用现代高级设计风格进行改造：
  > **“将页面视觉改为现代瑞士极简主义风格（Swiss Grid Style）。强调非对称留白排版、高对比度暗色系卡片底色（Dark Mode Base）、粗字重无衬线现代字体（如 Inter/Outfit），严禁使用任何低端彩色渐变。使用 `ui-ux-pro-max-skill` 技能优化布局与微动画。”**
* **安全审计与代码审查**：在提交前，调用 **Claude Code (通过向量引擎中转)** 进行安全防线收尾：
  > **“请调用 `code-reviewer` 智能体，使用 `security-auditor` 技能审查最新提交的代码，检查 SQL 注入与 XSS 漏洞，并输出安全报告。”**

### 第 6 步：文档与答辩准备（双模混合策略）
* **日常文档**：使用免费的 Gemini 3.1 Pro 快速撰写轻量文档、更新日志或 API 注释。
* **终稿参赛文档**：项目后期，调用 Claude Opus 一次性合并生成高质量技术论文级文档：
  > **“使用 `doc-coauthoring` 技能，通读所有项目源文件和变更历史，生成《需求分析说明书》《系统概要设计》《技术难点攻克报告》与《答辩PPT演示大纲》，确保格式专业严谨、逻辑自洽一致。”**

### 第 7 步：死守截止时间
* 核对赛题所有功能点是否百分之百完成。
* **至少提前 24 小时**完成所有压缩包打包、文件名规范校对工作，严格按照官方要求格式提交。

---

## 六、 贯穿全程的效率小技巧

* **测试驱动开发 (TDD)**：命令 Agent：“先为这个功能编写单元测试用例，然后再写出能够完全通过测试的代码。”
* **单文件聚焦模式**：为每个子任务创建独立的 `task_xx.md`，使用 `@task_xx.md` 让 Agent 的注意力百分之百集中。
* **定期打 Git 标签**：在完成重要里程碑时打上标签（如 `v0.1-rag-ok`），方便随时回滚。
* **费用监控与预警**：向量引擎虽然便宜，但建议在平台上设置每日消费预警，防止死循环任务造成额度意外超支。
* **Skill 技能包复用**：定期查看 `antigravity-awesome-skills` 本地技能库更新，将通用的高级操作固化为标准 Skill 运行。

---

## 七、 角色分工与模型配置速查表

| 任务下达方式 | 对应模型 | 接入方式 | 核心赛题用途 | 推荐绑定 Skill |
| :--- | :--- | :--- | :--- | :--- |
| **在 oma 对话中直接对 Sisyphus 下达顶层战略与任务分解** | **Claude Opus 4.6/4.7** | Antigravity 内置 / 向量引擎 | 顶层规划、任务编排、计划跟踪 | `solution-architect` |
| **告诉 Sisyphus：“后端/算法任务默认使用 GLM-5.1”** | **GLM-5.1** | CCSwitch → oh-my-ag | 常规业务 API 编写、SQL 映射、基础 CRUD 逻辑 | `backend-api`, `database-design` |
| **告诉 Sisyphus：“前端/视觉任务默认使用 Gemini”** | **Gemini 3.1 Pro** | Antigravity 内置 (免费) | 视网膜 UI 界面绘制、现代组件开发、视觉审美打磨 | `frontend-design`, `ui-ux-pro-max-skill` |
| **对 Sisyphus 说：“用 Opus 审查最新的代码安全性”** | **Claude Opus 4.6/4.7** | **向量引擎中转 → Claude Code** | 高并发协程死锁拦截、多租户安全审计、复杂算法攻坚 | `code-reviewer`, `security-auditor` |
| **日常更新：“@gemini-agent 补充当前接口注释”** | **Gemini 3.1 Pro** | Antigravity 内置 (免费) | API 注释生成、日常 CHANGELOG 日志更新 | `doc-coauthoring` |
| **终稿生成：“请 Claude Opus 整合生成最终参赛技术报告”** | **Claude Opus 4.6/4.7** | 内置接口 / 向量引擎 | 最终高学术质量参赛技术报告、系统概要设计导出 | `doc-coauthoring` |

---

## 八、 费用与成本预算控制

* **Sisyphus 总指挥内置模型**：使用免费的内置 Gemini 3.1 Pro，或者根据需要订阅 Google AI Pro（约 $20/月）。
* **向量引擎 API 用量**：按实际消耗 Token 付费，团队开发初期充值 **¥50 - ¥100 即可完全满足一个月超高频的 Claude Code 深度审计与算法攻坚**。
* **GLM-5.1 API 费用**：智谱开放平台 API 价格极低，且针对比赛项目通常有充足的免费赠送额度，开发成本几乎可以忽略不计。
* **辅助工具**：Antigravity IDE、oh-my-ag、awesome-skills、start.bat 等全部免费开源。
* **总成本预算控制**：**约 $20/月 (可选) + ¥50 - ¥100 中转费用**。无需额外订阅昂贵且易封号的 Claude Pro，彻底告别开发中断焦虑。
