# EduMatrix 测试说明书

> **沙箱测试边界**：无 Docker 的核心验收与 `trusted_local` 真实执行是两类证据。前者证明默认学习闭环可运行且代码执行明确关闭；后者证明本机受限子进程可完成研究演示，但不证明容器级隔离。`scripts/trusted_local_smoke.py` 用于后者的启动后 API 验证。

## 1. 测试目标

验证系统是否能够在给定环境下完成：

```text
画像输入 -> Agent 协同 -> 证据检索 -> 个性化资源 -> 反馈更新
```

同时验证认证、数据隔离、文件上传、代码执行、外部服务降级和比赛指标计算。

## 2. 当前环境与已复现结果

| 项目 | 当前结果 |
|---|---|
| 验证基线 | `74f8f2715641da20b560571120a66477d300f5de`；结论以 2026-07-20 验证时的最终代码与证据为准 |
| Python | 3.11.9 |
| FastAPI | 已安装并可导入 |
| SQLAlchemy | 已安装并可导入 |
| Uvicorn | 已安装并可导入 |
| pytest | 已安装并可导入 |
| pybreaker | 已安装并可导入 |
| PyTorch | 已安装；BKT/DKT 目标测试通过 |
| python-docx/OpenAI/Instructor | 已安装；目标测试通过 |
| Node/Vite 前端构建 | 成功 |
| Docker 后端运行 | 本轮未执行真实容器；Docker 仅为可选代码执行增强，不是核心验收前提 |
| Playwright 浏览器 | 当前机器已用于无 Docker 浏览器 E2E 并通过；PDF 导出和目标评委机仍需单独复核 |

已执行：

```text
npm.cmd run build
```

结果：Vite 成功转换 3076 个模块；KaTeX 已改为本地依赖，Axios 和 ECharts 已按当前构建方式整理，相关构建警告已清除。大体积 chunk 仍属于后续性能优化项。

已执行：

```text
python -m unittest scripts.test_member6_all_tasks -v
```

结果：62/62 通过。

已执行正式回归：

```text
python -m pytest -q
```

结果：`pytest.ini` 将正式入口限定为 `tests/`，避免收集 `scratch/` 实验脚本；FAISS 未安装时对应模块明确跳过。当前工作区结果为 **145 passed、1 skipped**。另有运行时安全矩阵 47/47、无 Docker 浏览器 E2E、`trusted_local` API smoke 和前端 production build 通过。联网搜索、arXiv、视频搜索和外部 LLM 仍可能出现超时/降级日志；本结果不等于真实 Docker 代码执行、PDF 导出、生产并发或外部服务已完成验收。

已执行无 Docker 浏览器 E2E：

```text
python scripts/e2e_no_docker.py
```

结果：`outputs/e2e_no_docker/report.json` 标记为 `passed`，浏览器上下文显式使用 `X-EduMatrix-LLM-Mode: deterministic`，覆盖临时注册/登录、初始化、仪表盘、对话、学习路径和沙箱禁用状态，并生成 6 张截图。该证据证明默认核心路径可运行，不证明 Docker 代码执行或 PDF 导出。

本地可信研究模式 smoke：

```powershell
.venv\Scripts\python.exe scripts\trusted_local_smoke.py
```

结果：`outputs/trusted_local_smoke.json` 标记为 `passed`，真实后端返回 `trusted_local_child_process`，安全代码输出 `42`，`import os` 被拦截。该结果不等价于 Docker 容器隔离。

因此可以准确表述为“当前正式自动化测试集 145 passed、1 optional skipped，另有 trusted_local smoke 通过”，不能扩展为 Docker、PDF、外部服务和目标评委机器全部验收通过。

## 3. 测试层级

### 3.1 静态测试

检查 Python AST、路由、配置、前端模板、关键函数和文件路径。静态测试只能证明代码结构，不能证明运行结果。

### 3.2 单元测试

覆盖 BKT、MIRT、策略、题目模板、错题、Anki、AST 代码检查和事件总线。所有算法必须包含正常值、空值、极端值、全对、全错和重复调用测试。

### 3.3 集成测试

验证 Agent Swarm、RAG、DRAG、资源工厂、对齐、数据库写入和反馈事件的真实连接，不应全部替换成 Mock。

### 3.4 API 测试

重点验证：

- 缺 Token 返回 401；
- 用户 A 的 Token 不能访问 B 的画像、笔记、题目、代码历史和知识文档；
- 教师只能访问授权学生；
- Docker 不可用时 `/api/code/run` 明确拒绝执行，不回退宿主进程；默认无 Docker 路径返回 503 属于可选能力未启用；
- 文档上传有大小、类型、解析和超时限制；
- SSE 断开后后台任务被取消；
- PDF 导出失败时返回可识别错误，不泄露内部堆栈。

### 3.5 E2E 测试

推荐浏览器流程：

```text
登录 -> Onboarding -> Dashboard -> Learn -> Agent Timeline
-> 讲义/导图/代码 -> 运行代码 -> 测验 -> 错题 -> 复习计划
-> 学习路径 -> 画像分析 -> PDF 报告
```

## 4. 核心测试用例

| ID | 用例 | 预期 | 当前状态 |
|---|---|---|---|
| AUTH-01 | 正确账号登录 | 返回 JWT | 无 Docker E2E 已通过；目标评委机仍需复核 |
| AUTH-02 | 错误密码 | 返回 401 | 代码存在，需在干净环境复核 |
| AUTH-03 | 缺 Token 调用保护接口 | 返回 401 | 默认已修复；仅显式 Demo 模式允许匿名演示 |
| AUTH-04 | A 读取 B 画像 | 403/404 | 运行时安全矩阵覆盖并通过；矩阵是选定高风险路由，不等于所有 API |
| AUTH-05 | A 删除 B 错题 | 403/404 | 运行时矩阵覆盖主要跨用户边界；持久化数据删除场景仍需专项复核 |
| RAG-01 | A 上传私有文档，B 搜索关键词 | B 不命中 A | owner 过滤契约与运行时范围矩阵已通过；持久化索引边界仍需专项复核 |
| RAG-02 | 删除文档后搜索 | 不返回已删除证据 | 需补测试 |
| AGENT-01 | 画像探针更新弱点 | 保存证据和置信度 | 代码存在 |
| AGENT-02 | 同问题三组画像 | 路径/资源不同 | 三组合成画像、固定知识集和结构性对比证据已生成；不等于真实用户效果实验 |
| AGENT-03 | LLM 辩论 | 使用注入的 LLM | 需按真实 provider 与 deterministic 两种模式实测 |
| AGENT-04 | LLM 关闭 | 明确 deterministic fallback | 固定本地 deterministic 流程已运行并纳入创新证据 |
| RAG-03 | 低置信度检索 | 拒答或降级 | 自动化低置信度回归已通过；正式效果指标仍需人工评测 |
| QUIZ-01 | MCQ 正确 | 快速判分 | 专项结构测试通过 |
| QUIZ-02 | 主观题异常 JSON | fallback 完整 | 目标代码存在，需完整 API 回归 |
| CODE-01 | 合法代码 | 返回 stdout/耗时 | Docker 实时代码执行本轮未验证；默认无 Docker 模式明确拒绝执行 |
| CODE-02 | `os.system` | AST 拦截 | 结构代码存在 |
| CODE-03 | 超过 50 KB | 400 拒绝 | 代码确认 |
| CODE-04 | Docker 离线 | 拒绝执行宿主代码 | 已修复；安全契约、集成测试和运行时状态证据通过 |
| CODE-05 | 死循环 | 超时并杀死任务 | 有逻辑，需 Docker 实测 |
| DOC-01 | PDF/PPTX/Markdown 上传 | 解析、分块、索引 | 依赖已补齐；PDF/PPTX/DOCX 目标测试通过 |
| DOC-02 | 超大/高页数/压缩炸弹文件 | 400/413 | 已增加 20 MB、页数、压缩包成员/展开体积、压缩比和解析超时限制；目标机压力测试仍需复核 |
| REPORT-01 | PDF 导出 | 返回 PDF | 浏览器运行能力已由无 Docker E2E 间接确认；PDF 导出本身仍未单独验证 |
| FRONT-01 | 生产构建 | 资源可加载 | 构建成功；相关构建警告已清除 |

## 5. 比赛量化指标测试

### 5.1 统一样本格式

```json
{
  "case_id": "case-001",
  "learner_profile": {
    "major": "计算机科学",
    "cognitive_style": "visual",
    "prior_knowledge": {"混淆矩阵": 0.35},
    "goal": "掌握分类模型评估"
  },
  "question": "为什么 accuracy 高但 recall 低？",
  "agent_trace": [],
  "retrieval_evidence": [],
  "resources": [],
  "human_labels": {
    "hallucination": false,
    "adapted": true,
    "covered_concepts": ["accuracy", "recall", "class imbalance"]
  }
}
```

每条样本都要保留输入画像、Agent 中间数据、检索证据、最终资源和人工标签。

### 5.2 幻觉率

对生成资源中的可核验事实陈述逐条标注：正确、有证据、错误、无证据、无法判断。无法判断项不得自动算正确。

```text
幻觉率 = 不受证据支持或与权威材料冲突的陈述数 / 全部可核验陈述数
```

### 5.3 画像—资源适配准确率

对难度、表达形式、前置知识、学习目标和资源类型逐项标注，报告总体和分组准确率。应至少由两名评审独立标注。

```text
适配准确率 = 匹配资源样本数 / 全部评测样本数
```

### 5.4 知识点覆盖率

固定知识点集合，判断生成资源是否覆盖定义、关键关系、前置条件、典型应用和常见错误。

```text
覆盖率 = 被覆盖的必需知识点数 / 必需知识点总数
```

## 6. 性能测试

在记录硬件、模型、网络和并发参数后测试：

- API P50/P95/P99；
- SSE 首字延迟 TTFT；
- 完整资源包耗时；
- 代码执行正常/超时耗时；
- PDF 导出内存峰值；
- SQLite 写锁与 WAL；
- Swarm cache 增长；
- RAG 检索延迟；
- LLM 重试、熔断和 fallback 比例。

当前仓库没有可直接作为真实 TPS/TTFT 结果的证据。

## 7. 测试报告格式

每次测试必须记录：

```text
commit、日期、环境、依赖版本、命令、输入数据、输出、通过/失败、失败原因、日志/截图路径
```

测试报告不得使用“零幻觉”“生产可用”“全量通过”等结论，除非证据覆盖范围与结论完全一致。
