# EduMatrix 第一轮事实审计报告

> **历史基线声明**：本文记录 2026-07-18 首轮审计时的环境、代码和证据，不代表 2026-07-19 整改后的最终状态。文中“依赖缺失”“51/62 通过”“接口未认证”“E2E 未验证”等结论可能已被后续整改取代；最终状态以 `EduMatrix_完整技术文档总稿.md`、`EduMatrix_测试说明书.md`、`EduMatrix_风险整改清单.md` 和当前运行证据为准。

## 1. 审计基线

- 审计项目：`EduMatrix 智教矩阵`
- 当前源码基线：`2952dc1b17d793e5d76f54e1764348ebe50e4d5e`
- 当前 HEAD 提交时间：2026-07-18 17:41:23 +0800
- 当前工作区：存在用户已有修改、删除和未跟踪的 `reports/`，本审计未修改这些内容。
- 比赛题目：XH-202630《领域知识个性化生成与多智能体协同决策系统研究》
- 比赛关键要求：至少 3 个职责明确的 Agent、至少 3 种个性化资源、至少 2 组差异化学习者初始数据；实用价值评分还要求测试方案、至少 3 组不同背景画像，以及幻觉率 <5%、适配准确率 >=85%、知识点覆盖率 >=90% 等证据。

## 2. 当前系统事实

项目由 Python/FastAPI 后端、Vue 3/Vite 前端、SQLite/WAL 持久层、RAG/图谱/向量检索、Swarm 资源生成、BKT/DKT/EKF 学情算法和代码执行模块组成。

当前报告目录共有 11 份 Markdown 报告。报告使用了两个不同的 Git 基线：一部分使用 `2952dc1b...`，另一部分使用 `c2f0d6c384d5318a29379b047b8ab851428354ab`；因此报告不能直接视为同一版本的事实证明。

已验证的验证结果：

- 前端 `npm.cmd run build` 成功，Vite 转换 3033 个模块并生成生产包。
- 前端构建存在警告：主 JS 压缩后约 1.91 MB；KaTeX CSS 资源构建时不存在；Axios 动态导入无法形成独立分包。
- 当前 Python 环境没有 `pytest`、`fastapi`、`sqlalchemy`，因此无法复现报告中的全量 pytest 结果。
- `python -m unittest scripts.test_member6_all_tasks -v` 实际运行 62 个用例，其中 51 个通过、11 个因依赖缺失而错误；这不是“全量通过”的可复现证据。

## 3. 高优先级发现

### F-001 [Critical] 缺少 Token 时全局自动登录演示账号

证据：`app/auth.py:38-54`。`get_current_user` 在 Token 为空时创建或返回 `demo-student`，而不是返回 401。

影响：所有使用 `Depends(get_current_user)` 的路由在无 Authorization 头时都会获得一个合法用户上下文。该逻辑若部署到可访问环境，会将演示便利逻辑变成鉴权绕过。

建议：只允许在显式测试/演示配置下启用；生产配置缺少 Token 必须返回 401，并为演示账号关闭写入敏感数据的权限。

### F-002 [Critical] 用户身份与 `student_id` 未绑定，存在 IDOR 和跨用户读写

证据：

- `code_exec_api.py:539-545`、`602-614` 的执行和历史接口无认证依赖，直接接受客户端 `student_id`。
- `stream_api.py:386-408`、`1492-1518`、`1656-1671` 的多个接口无认证依赖并直接读取客户端 `student_id`。
- `profile_api.py:266-278` 和 `453-464` 的画像读取、更新接口也没有把路径用户与当前认证用户绑定。
- `app/main.py:587-604` 虽然声明了 `get_current_user`，但仍使用请求体中的 `student_id`，没有校验其等于当前用户。

影响：攻击者可以读取、修改或删除其他学生的画像、错题、笔记、对话、代码历史和知识文档。

建议：从 JWT 的 `sub` 生成服务端用户 ID，禁止普通学生提交任意 `student_id`；教师接口单独校验班级/学生授权关系；所有子路由统一使用认证依赖。

### F-003 [Critical] 用户知识文档进入全局 RAG 索引，存在跨用户知识泄露

证据：

- `knowledge_api.py:103-129` 将带有某个 `student_id` 的上传文档解析后调用全局 `hybrid_rag.ingest_user_documents`。
- `rag_engine.py:390-406` 只有一个全局 `user_index`，证据对象没有携带租户过滤条件。
- `rag_engine.py:490-491` 检索时直接搜索全局 `user_index`，没有按 `student_id` 过滤。

影响：学生 A 上传的私有材料可能被学生 B 的检索结果、Agent Prompt 或生成资源引用。

建议：按用户/租户建立独立索引或在 Evidence 元数据中强制加入 owner ID，并在所有检索路径执行服务端过滤；删除文档时同步删除对应 owner 的索引项。

### F-004 [High] 所谓代码沙箱在 Docker 不可用时退化为宿主机同权限子进程

证据：

- `code_exec_api.py:143-146` 在 Docker 不可用时调用 `_run_in_subprocess`。
- `code_exec_api.py:260-284` 使用当前 Python 解释器、当前环境变量和当前工作目录创建子进程。
- `code_exec_api.py:77-128` 主要依赖 AST 黑名单，而不是操作系统级隔离。
- `requirements.txt` 没有 `docker` 客户端依赖，`Dockerfile` 也没有安装 Docker Python SDK，因此容器构建后很可能默认进入回退路径。

影响：AST 黑名单不能等价替代容器隔离；代码执行请求在公开部署中可能读取本地文件、环境变量或消耗宿主资源。并且 `/api/code/run` 本身没有认证依赖。

建议：生产环境 Docker 不可用时直接拒绝执行；使用独立 worker、非特权容器、只读文件系统、网络关闭、CPU/内存/进程数限制和显式允许列表，禁止宿主机回退。

### F-005 [High] LLM 辩论防幻觉链路当前主流程未注入 LLM，并包含事件循环阻塞调用

证据：

- `agent_swarm.py:1310-1327` 将 LLM 保存为 `self.llm`，但 `self.debate = DebateAugmentedRAG()` 没有传入 `use_llm`。
- `drag_debate.py:32-41` 因 `self.llm is None` 直接走确定性清洗分支。
- `drag_debate.py:171-181` 在异步请求上下文中对协程调用 `loop.run_until_complete`。
- `agent_swarm.py:1433-1434` 的主流程确实调用了 `self.debate.clean`。

结论：多 Agent 资源生成是真实存在的，但“Prover-Challenger-Judge 大模型辩论”不能按当前代码写成默认生产路径；若后续注入异步 LLM，现有同步桥接可能在运行中的事件循环中失败。

### F-006 [High] 部署依赖与代码声明不完整

`requirements.txt` 未声明代码和文档中使用的若干运行能力，包括 `docker`、`playwright`、`torch`、`numpy`、`chromadb`、`neo4j`、`pandas`、`matplotlib` 等。部分模块采用延迟导入，因此问题会在对应功能首次调用时才暴露。

`Dockerfile` 没有执行 Playwright 浏览器安装步骤，报告声称的 Playwright PDF 导出在干净镜像中不能直接视为可用。

建议：区分 core、optional-ai、sandbox、document 和 dev 依赖；锁定版本；在 Docker 构建阶段安装浏览器和系统依赖；增加从全新环境执行 `/health`、核心 Agent 流程、代码执行和 PDF 导出的验收脚本。

### F-007 [High] JWT 默认密钥是源码中的固定值

证据：`config.py:68-71` 将 `EDUMATRIX_AUTH_SECRET_KEY` 默认设置为 `edumatrix_super_secret_v1_2026`。

影响：如果部署者忘记配置环境变量，任何知道默认值的人都可能伪造 JWT。该问题与 F-001 叠加后会显著降低系统实际鉴权强度。

建议：生产启动时强制要求随机密钥；禁止使用默认值启动；提供密钥长度和随机性校验。

### F-008 [High] Swarm 和用户画像缓存没有完整生命周期控制

证据：`swarm_factory.py:8-59` 的 `_swarm_cache` 按请求头构造 key，没有容量上限或过期淘汰；`agent_swarm.py:1315-1318` 的 `profile_store` 按学生 ID 持续保留画像和历史状态。

影响：攻击者可以构造大量不同的模型参数请求头，导致 Swarm 实例和画像缓存增长；长时间运行可能造成内存增长和状态污染。

建议：采用有上限、带 TTL 的缓存；限制允许的模型端点和参数；用户画像以数据库为主，内存只保留短期热点状态。

### F-009 [High] 知识上传接口一次性读取完整文件且没有大小限制

证据：`knowledge_api.py:67-76` 直接 `await file.read()`，随后还可能进行 PDF 视觉解析、文档分块、图谱构建和向量化。

影响：匿名请求可以提交超大文件造成内存和 CPU 消耗；该接口同时没有认证依赖。

建议：在反向代理和应用层同时设置大小上限，采用流式写入和异步解析队列，限制 PDF 页数、压缩炸弹和视频时长。

## 4. 中优先级发现与报告纠偏

### F-010 [Medium] arXiv 缓存写入缺少 `datetime` 导入，但异常被静默吞掉

证据：`rag_engine.py:1-17` 没有导入 `datetime`，`rag_engine.py:888-901` 在缓存写入中调用 `datetime.fromisoformat` 并以 `except Exception: pass` 隐藏失败。

影响：缓存可能持续写入失败，系统反复访问外部检索服务；错误不可观测。

### F-011 [Medium] MIRT 3PL 公式确有除零路径，但 Anki 报告把可恢复错误描述成服务崩溃

证据：`mirt_engine.py:420-433` 在 `-z >= 700` 时形成 `1.0 / 0.0`；`anki_engine.py:224-237` 对 naive/aware 时间比较的 `TypeError` 进行了捕获并把卡片加入 due 列表。

结论：MIRT 公式问题需要修复；Anki 逻辑当前更准确的描述是“异常被吞掉并可能错误地把卡片判定为到期”，不能写成必然导致接口崩溃。

### F-012 [Medium] 沙箱容量在报告中写成 500KB，当前代码实际是 50KB

证据：`code_exec_api.py:130-136` 和 `539-552` 都使用 `50000` 字节，并返回 `Max 50KB`；部分报告写成 `500_000`/500KB。

建议：统一源代码、测试、部署说明和演示话术，避免评委现场按报告上传 100KB 代码时发现行为不符。

### F-013 [Medium] 报告之间存在版本漂移、失效路径和事实等级混用

已确认：`ai_agent_special_report.md`、`features_business_processes.md`、`test_deploy_security_performance.md` 等使用 `c2f0d6c3...`；其他报告使用当前 `2952dc1b...`；`architecture_report.md` 没有明确 commit。

建议：每份报告记录 commit、生成时间和审计范围；最终比赛文档只引用当前基线已复核的证据，并将历史报告作为待核对材料。

此外，部分报告中的证据路径在当前仓库不存在，例如 `AGENTS.md`、`实施方案（详细版）.md`、`frontend/src/components/AvatarSpeech.ts` 和 `frontend/src/stores/chat.ts`；当前对应文件分别缺失或实际为 `.vue`/`.js`。这些链接必须在最终文档中修正，否则评委无法按引用复核。

## 5. 比赛材料可信度判断

可以写入最终技术文档的内容：

- 9 个物理 Agent 角色定义，其中 5 个角色负责并行资源生成，见 `agent_swarm.py:34-44`、`929-938`。
- BKT/Kalman、DKT、Poincare 相关算法代码确实存在，但应分别说明算法边界、数据来源和测试证据。
- 当前系统有确定性本地 LLM fallback；真实外部 LLM 能力必须区分配置启用状态。
- 前端生产构建成功，但需要补充构建警告处理和真实运行截图。
- 项目使用虚拟种子学生和模拟 Peer 数据，不能包装成真实大学生调研或真实用户实验。

暂不能直接写成“已完成/已验证”的内容：

- 多模型 Prover-Challenger-Judge 默认生产链路；当前 Swarm 未向 DebateAugmentedRAG 注入 LLM。
- 真实用户调研、满意度和学习提升率；已有材料明确指出缺少这些数据。
- 500KB 沙箱上传上限；当前代码是 50KB。
- 全量测试 100% 通过；当前环境无法复现，且 unittest 已出现 11 个错误。
- 真实 MP4 自动合成；现有材料已指出主要是视频脚本、TTS 和前端嘴形联动。
- 多租户隔离；当前实际数据库是 SQLite 单文件，且用户 RAG 索引为全局对象。

## 6. 下一阶段审计重点

1. 修复或确认 F-001 至 F-005 后，再形成可公开演示的安全基线。
2. 在干净 Python 环境按 `requirements.txt` 安装并运行后端启动、健康检查和核心流程。
3. 增加 3 组差异化画像的输入、Agent 中间状态、最终资源和评分结果，形成比赛要求的可复核数据包。
4. 重新生成统一 commit 下的架构、AI、测试、部署和合规报告。
5. 最终技术文档采用“已实现、部分实现、待验证、未来规划”四级标注，避免把设计目标写成已交付能力。
