# EduMatrix 评委环境安装与复现备忘录

> 文档版本：2026-07-19
>
> 适用赛题：软件杯 A3「基于大模型的个性化资源生成与学习多智能体系统研发」

## 1. 交付前提

评委拿到作品后，应在一台干净的 Windows 10/11 或 Linux x86_64 机器上准备以下环境：

| 类别 | 要求 | 必需性 | 说明 |
|---|---|---|---|
| Python | 3.11，64 位 | 必需 | 当前代码与测试按 Python 3.11 验证 |
| Node.js | 20 LTS | 必需 | 前端 Vue 3/Vite 构建 |
| npm | 随 Node.js 提供 | 必需 | 使用 `npm ci`，不要只复制 `node_modules` |
| Docker Engine/Desktop | 可选；仅在演示实时代码执行时安装 | 可选增强 | 默认 `EDUMATRIX_SANDBOX_MODE=disabled`，核心学习闭环无需 Docker；未启用时只关闭代码执行 |
| Chromium | Playwright 管理的浏览器 | PDF 导出必需 | Python 包和浏览器二进制是两个独立安装步骤 |
| 网络 | 安装阶段可访问 PyPI/npm；联网搜索演示需外网 | 安装/联网功能必需 | 离线 deterministic 模式仍可启动核心流程 |

## 2. Windows 安装步骤

在项目根目录执行：

```powershell
cd D:\project-edumatrix\edumatrix-main
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm ci
cd ..
```

安装 PDF 导出浏览器。该步骤与 Docker 无关；如果本次验收不演示 PDF 导出，可以暂不安装：

```powershell
.venv\Scripts\python.exe -m playwright install chromium
```

### 2.1 可选：启用 Docker 代码沙箱

只有需要现场运行学生代码时才执行以下步骤：

```powershell
docker version
docker pull python:3.10-slim
```

Windows 上运行 Docker 模式时，Docker Desktop 应处于运行状态，并允许当前用户通过 Docker named pipe 访问 Docker Engine；随后在 `.env` 中设置 `EDUMATRIX_SANDBOX_MODE=docker` 并重启后端。评委只验收核心学习闭环时保持默认 `disabled`，不需要安装 Docker Desktop。

## 3. Linux 安装步骤

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cd frontend && npm ci && cd ..
.venv/bin/python -m playwright install --with-deps chromium
```

Linux 上如需实时代码执行，再安装 Docker、拉取 `python:3.10-slim`，并设置 `EDUMATRIX_SANDBOX_MODE=docker`。如果后端运行在 Docker 容器内部，必须额外设计受限的 sandbox worker 或显式挂载 Docker socket。直接挂载宿主 Docker socket 会赋予应用较高的宿主控制权限，只适合本地比赛演示，不应直接作为生产隔离方案。

## 4. 环境变量

复制 `.env.example` 为 `.env`，至少确认：

```dotenv
EDUMATRIX_ENV=development
EDUMATRIX_AUTH_SECRET_KEY=<至少32字符的随机值>
EDUMATRIX_DEMO_MODE=0
EDUMATRIX_MAX_UPLOAD_BYTES=20971520
EDUMATRIX_SANDBOX_MODE=disabled
EDUMATRIX_LLM_PROVIDER=deterministic
EDUMATRIX_EMBEDDING_PROVIDER=hash
```

生成随机密钥：

```powershell
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

生产或正式评审环境必须设置 `EDUMATRIX_ENV=production` 和独立随机密钥。生产环境缺少密钥、使用旧固定占位值或长度少于 32 字符时，应用应拒绝启动。`EDUMATRIX_DEMO_MODE=1` 只允许临时演示，不能作为正式部署配置。

如果需要真实大模型，将以下变量替换为评委可用的服务配置，并确认 API Key 不进入压缩包：

```dotenv
EDUMATRIX_LLM_PROVIDER=openai
EDUMATRIX_LLM_ENDPOINT=https://your-endpoint/v1/chat/completions
EDUMATRIX_LLM_API_KEY=<secret>
EDUMATRIX_LLM_MODEL=<model-name>
```

没有外部模型时保持 `deterministic`，文档和答辩必须把此结果标注为本地确定性降级结果。

## 5. 启动方式

### 5.1 分离启动，推荐用于评委演示

终端一：

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

终端二：

```powershell
cd frontend
npm run dev -- --host 127.0.0.1
```

访问 `http://127.0.0.1:5173`，后端健康检查为 `http://127.0.0.1:8000/api/health`。

### 5.2 根目录快捷启动

Windows 可执行 `start.bat`。它会启动后端、Vite 前端并打开浏览器；默认只需完成 `.venv`、`npm ci` 和 `.env` 配置，不要求 Docker Desktop。若要演示实时代码执行，再按 2.1 启用 Docker 沙箱。

启动后可访问 `GET /api/code/status` 查看可选沙箱状态。默认应显示 `mode=disabled`、`execution_enabled=false`；这不是核心系统故障。

### 5.3 Docker Compose

```powershell
docker compose build
docker compose up -d
docker compose ps
Invoke-WebRequest http://127.0.0.1:8000/api/health
```

Compose 模式属于可选部署方式。请通过外部环境或 `.env` 注入 `EDUMATRIX_AUTH_SECRET_KEY`，不要把密钥写入 `docker-compose.yml`。当前 Compose 文件默认不把宿主 Docker socket 暴露给应用容器，因此代码沙箱保持未启用；这属于当前安全策略的预期行为，不影响核心学习功能。需要容器内调用宿主 Docker 时，应使用独立 worker，不能直接把宿主 socket 当作普通配置暴露。

## 6. 依赖分层

`requirements.txt` 当前包含以下核心层：

- Web/API：FastAPI、Uvicorn、SQLAlchemy、HTTPX、认证和限流组件；
- 算法：NumPy、PyTorch、NetworkX；
- AI：OpenAI SDK、Instructor；
- 文档：PDF、PPTX、Pillow、ReportLab、python-docx；
- 浏览器与测试：Playwright、pytest；
- 可选安全沙箱：Docker Python SDK；仅 `EDUMATRIX_SANDBOX_MODE=docker` 时启用。

FAISS、ChromaDB、Neo4j、Transformers、Sentence-Transformers、Pandas 和 Matplotlib 属于按功能启用的可选能力，启用对应 provider 前应在目标机器补装并执行 smoke test。

## 7. 安装后验收

```powershell
.venv\Scripts\python.exe -c "import fastapi, sqlalchemy, numpy, torch, openai, instructor, docx, playwright; print('python imports ok')"
.venv\Scripts\python.exe -c "import os; print('sandbox mode:', os.getenv('EDUMATRIX_SANDBOX_MODE', 'disabled'))"
.venv\Scripts\python.exe -c "import ast, pathlib; files=['config.py','app/auth.py','app/main.py','knowledge_api.py','quiz_api.py','flashcard_api.py','behavior_api.py','report_api.py']; [ast.parse(pathlib.Path(f).read_text(encoding='utf-8'), filename=f) for f in files]; print('AST ok')"
.venv\Scripts\python.exe -m unittest tests.test_security_contracts -v
.venv\Scripts\python.exe -m unittest scripts.test_member6_all_tasks -v
.venv\Scripts\python.exe scripts/e2e_no_docker.py
```

完整回归：

```powershell
.venv\Scripts\python.exe -m unittest test_edumatrix -v
```

完整回归涉及联网搜索、外部 LLM、可选 Docker 和 Chromium 等环境条件。无 Docker 模式可以完成核心 API、学习闭环和安全契约验收；代码执行属于单独的可选能力。浏览器 E2E 的当前证据位于 `outputs/e2e_no_docker/report.json`。测试报告必须记录实际命令、日期、依赖版本、网络状态、沙箱模式和失败原因，不能把可选环境依赖未满足写成核心代码缺陷，也不能把专项测试通过写成全系统安全认证。

## 8. 当前机器验证快照

截至 2026-07-19，当前工作区已验证：Python 3.11.9、NumPy 2.4.6、PyTorch 2.13.0、OpenAI 2.46.0、Instructor 1.15.4、python-docx 1.2.0、pytest 9.1.1、Playwright 1.61.0 和 Docker SDK 7.2.0 可导入。当前机器的 Playwright Chromium 已实际用于无 Docker 浏览器 E2E，报告标记为 `passed`；PDF 导出和目标评委机浏览器仍需单独复核。默认沙箱模式为 `disabled`，Docker daemon 未运行不影响核心应用导入、启动和默认学习闭环。Docker 模式只验证了“不可用时拒绝执行”的安全行为。

## 9. 常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动即提示生产密钥错误 | `EDUMATRIX_ENV=production` 但没有合规密钥 | 注入至少 32 字符的唯一随机密钥 |
| `/api/code/run` 返回代码沙箱未启用 | 默认 `EDUMATRIX_SANDBOX_MODE=disabled`，或 Docker 模式下 daemon 不可用 | 核心验收可忽略并展示 `/api/code/status`；需要实时执行时安装并启动 Docker、设置 `EDUMATRIX_SANDBOX_MODE=docker`；不要启用宿主 Python 回退 |
| PDF 导出失败 | Chromium 二进制未安装或系统库缺失 | Windows 执行 `playwright install chromium`；Linux 执行 `--with-deps chromium` |
| 前端无法请求后端 | 后端 8000 端口未启动或 CORS/代理配置不一致 | 先访问 `/api/health`，再检查 Vite 代理 |
| 联网搜索超时 | 外部搜索站点或网络不可用 | 使用本地已有资料或 deterministic 演示数据，并标注证据等级 |
