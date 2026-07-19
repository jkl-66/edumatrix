# EduMatrix 部署与运维说明书

## 1. 适用范围

本文档描述开发、演示和生产化前的部署方法。比赛提交采用“无 Docker 默认运行、Docker 可选增强”的策略：核心学习闭环使用本机 Python/SQLite 即可启动，代码执行沙箱只有在显式设置 `EDUMATRIX_SANDBOX_MODE=docker` 且 Docker daemon 可用时才开启。当前项目主要是单机 SQLite 原型；主要业务接口已加入认证、学生范围和 RAG owner 过滤，但生产多用户部署仍需独立 sandbox worker、完整跨用户回归和容量治理。评委安装顺序见 `outputs/EduMatrix_评委环境安装与复现备忘录.md`。

## 2. 目录与运行组件

```text
frontend/                  Vue 3 + Vite 前端
app/                       FastAPI 应用、认证、数据库、CRUD
agent_swarm.py             Agent 编排和资源工厂
rag_engine.py              混合 RAG
knowledge_api.py           文档摄入
code_exec_api.py           代码执行
report_api.py              PDF 导出
scripts/                   种子、校准、导入和专项测试
tests/                     单元/集成测试
data/                      运行期数据、索引和资源
```

## 3. 本地开发部署

### 3.1 前端

```powershell
cd D:\project-edumatrix\edumatrix-main\frontend
npm install
npm run dev
```

默认开发地址：`http://localhost:5173`。

### 3.2 后端

在网络可用的环境中执行：

```powershell
cd D:\project-edumatrix\edumatrix-main
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

当前工作区已按 `requirements.txt` 安装核心依赖；干净机器仍需保证 PyPI 或内部镜像可访问。安装后如需 PDF 导出，再单独执行 `python -m playwright install chromium`，因为浏览器二进制不随 Python 包自动提供。Playwright 与 Docker 是两套独立依赖；不演示 PDF 时可以暂不安装 Chromium。

### 3.3 启动检查

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/health
```

检查 HTTP 200、SQLite 可写、`/docs` 可访问、前端能请求后端、无默认密钥警告，以及沙箱、Playwright 和 LLM 状态符合当前演示模式。无 Docker 默认模式下，`GET /api/code/status` 应返回 `mode=disabled`、`execution_enabled=false`；这表示可选代码执行未开启，不影响核心学习功能。

## 4. 无 Docker 默认验收

这是比赛评委的推荐路径：

```powershell
$env:EDUMATRIX_SANDBOX_MODE="disabled"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Invoke-WebRequest http://127.0.0.1:8000/api/health
Invoke-WebRequest http://127.0.0.1:8000/api/code/status
```

该模式不连接 Docker daemon，也不执行宿主 Python 子进程。登录、画像、对话、知识检索、测验、反馈和报告等核心功能可以独立验收；代码运行按钮会被前端禁用，并给出“代码沙箱未启用”的明确状态。

## 5. Docker 可选沙箱部署

现有 Dockerfile 使用 Node 20 Alpine 构建前端，再使用 Python 3.11 slim 运行后端；compose 暴露 8000 端口并挂载 `edumatrix_data` volume。

```powershell
docker compose build
docker compose up -d
docker compose ps
Invoke-WebRequest http://127.0.0.1:8000/api/health
```

### 5.1 当前 Docker 说明

- 可选 RAG provider 尚未拆分为完全锁定的依赖组；核心运行依赖已补入 `requirements.txt`；
- Dockerfile 已安装 Playwright Chromium 及其系统依赖；目标机器仍需实际构建和启动验收；
- Docker Python SDK 已补入依赖；Docker daemon/socket 是否可被应用访问仍取决于部署方式；
- 单进程 Uvicorn 不等于高可用部署；
- compose 中存在外部 LLM endpoint，需确认网络、密钥和合规性；
- 生产环境缺少合规 JWT secret 会启动失败；
- SQLite volume 需要备份、锁竞争和恢复方案。

### 5.2 生产启动门禁

应用启动时应检查：

```text
EDUMATRIX_ENV=production
EDUMATRIX_AUTH_SECRET_KEY 已设置且不是默认值
`EDUMATRIX_SANDBOX_MODE=docker` 时 Docker sandbox 可用，否则仅禁用代码执行；`disabled` 模式不要求 Docker
Playwright browser 可用，否则禁用 PDF 导出
数据库路径可写且备份策略存在
LLM endpoint/API key 配置完整或明确启用 deterministic mode
```

## 6. 依赖分层建议

源码实际导入除核心 `requirements.txt` 外还包含按功能启用的 chromadb、neo4j、pandas、matplotlib、faiss、fitz、sentence-transformers、transformers 等。当前核心清单已覆盖 docker、playwright、torch、numpy、python-docx、instructor 和测试工具。建议后续拆分为：

- `requirements-core.txt`：FastAPI、Uvicorn、SQLAlchemy、认证、基础解析；
- `requirements-ai.txt`：torch、numpy、transformers、sentence-transformers、instructor；
- `requirements-rag.txt`：faiss、chromadb、neo4j、嵌入依赖；
- `requirements-docs.txt`：playwright、PDF/PPTX/Word 解析；
- `requirements-dev.txt`：pytest、覆盖率、压测、lint。

所有依赖应锁定版本，并在干净 Python 环境中执行 import smoke test。

## 7. 配置、备份与恢复

敏感配置只能来自环境变量或秘密管理系统，包括 LLM API key、JWT secret、Neo4j password 和外部 endpoint 令牌。`.env` 不应随比赛压缩包提交。`config.py:68-71` 的固定 JWT 默认值必须在生产启动时拒绝。

SQLite 备份前应停止写入或使用在线备份 API，不能只复制正在写入的主文件。至少保留主数据库、WAL/SHM、上传文档、向量索引、题库和评测数据。恢复顺序是：停止应用、恢复文件、检查表结构、重建索引、启动健康检查、执行跨用户和核心闭环测试。

## 8. 运行监控

监控请求错误率和 P95、SSE 连接数、LLM 成功率/重试/熔断、Agent 耗时、RAG 低置信度比例、文档队列、可选 Docker 容器池、PDF 浏览器池、SQLite locked 次数、内存缓存项数和私有文档异常命中。`sandbox_mode=disabled` 时不应把“无 Docker 容器池”当成故障。

## 9. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 后端无法启动 | 缺 FastAPI/SQLAlchemy/pybreaker | 使用锁定依赖，在可联网环境安装 |
| PDF 导出 500 | Playwright 浏览器未安装 | 安装浏览器和系统依赖，或禁用导出 |
| 对话只返回模板 | LLM 未配置或 fallback | 查看 provider、endpoint、日志和 fallback 标记 |
| 代码执行不可用 | 沙箱默认为 `disabled`，或 Docker 模式下 daemon 不可用 | 核心验收可继续；需要实时执行时设置 `EDUMATRIX_SANDBOX_MODE=docker` 并启动 Docker。任何模式都不使用宿主 Python 回退 |
| 用户看到他人内容 | 旧客户端或未覆盖路由的身份边界 | 主要接口已有 JWT/owner 过滤；执行跨用户回归矩阵并查看审计日志 |
| 数据库 locked | SQLite 并发写入 | 降低并发、缩短事务、迁移 PostgreSQL |
| 前端公式不显示 | KaTeX CSS 路径不存在 | 将 CSS 纳入 npm 构建并校验静态资源 |

## 10. 运维禁忌

- 不要启用固定 JWT secret；
- 不要在 Docker 不可用或沙箱未启用时执行宿主 Python 代码；
- 不要把 `.env`、API key、真实学生数据打包提交；
- 不要把 `student_id` 当作授权凭据；
- 不要直接删除 SQLite 数据库而不备份；
- 不要把 deterministic fallback 称为真实外部模型结果；
- 不要把旧报告中的 500 KB 上限、100% 测试通过等内容当作当前事实。
