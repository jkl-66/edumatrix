# EduMatrix 评委环境安装与复现备忘录

> **推荐验收路径**：评委无需安装 Docker 即可验收核心学习闭环。若要演示实时 Python 代码，研究演示机可设置 `EDUMATRIX_SANDBOX_MODE=trusted_local`；这会使用受限本地子进程而不是容器，明确不提供 Docker 隔离。只有需要容器级隔离时才设置 `docker` 并安装 Docker Engine/Desktop。

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

### 2.2 不安装 Docker：可信本地研究演示

如果需要演示代码运行但不安装 Docker，可在可信本机将 `.env` 设置为：

```dotenv
EDUMATRIX_SANDBOX_MODE=trusted_local
EDUMATRIX_SANDBOX_MAX_OUTPUT_BYTES=100000
```

重启后端并执行 `.venv\Scripts\python.exe scripts\trusted_local_smoke.py`。该模式真实运行受限 Python 子进程，但没有 Docker 容器隔离；演示时必须明确这一点，不能称作生产级安全沙箱，也不能用于不可信用户代码。

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
EDUMATRIX_RELOAD=0
EDUMATRIX_AUTH_SECRET_KEY=<至少32字符的随机值>
EDUMATRIX_DEMO_MODE=0
EDUMATRIX_MAX_UPLOAD_BYTES=20971520
EDUMATRIX_SANDBOX_MODE=disabled
EDUMATRIX_LLM_PROVIDER=deterministic
EDUMATRIX_EMBEDDING_PROVIDER=hash
```

本地开发和比赛演示必须保持 `EDUMATRIX_AUTH_SECRET_KEY` 不变；如果留空，开发模式会为每次后端进程生成新的临时密钥，后端重启后浏览器旧 Token 会失效并需要重新登录。提交包不包含真实 `.env`，评委应自行生成并保存该值。

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

### 4.1 多模态图片与公式识别

提交包不包含真实 API Key。评委可在浏览器打开 `/settings`，在“多模态视觉模型设置”中填写视觉模型的 API Key、Endpoint 和 Model，保存后点击“测试视觉”。也可以在 `.env` 中配置：

```dotenv
EDUMATRIX_MULTIMODAL_LLM_PROVIDER=openai
EDUMATRIX_MULTIMODAL_LLM_ENDPOINT=https://your-endpoint/v1/chat/completions
EDUMATRIX_MULTIMODAL_LLM_API_KEY=<vision-secret>
EDUMATRIX_MULTIMODAL_LLM_MODEL=<vision-model-name>
```

当主文本模型不支持图片时，系统会将带图片的请求路由到上述视觉模型；如果只配置视觉模型而没有外部文本模型，系统使用本地确定性引擎处理文本、使用视觉模型处理图片。视觉 Endpoint 必须兼容 OpenAI Chat Completions 的 `messages[].content[].image_url` 格式，并允许发送 Base64 data URL。

“测试连接”只验证文本模型；“测试视觉”才会发送一张最小 PNG 并验证视觉请求链路。没有外部视觉 API Key 时，系统可以启动，但图片识别仅为确定性降级演示，不代表真实视觉模型能力。

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
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/runtime_security_matrix.py
.venv\Scripts\python.exe scripts/e2e_no_docker.py
```

正式自动化回归：

```powershell
.venv\Scripts\python.exe -m pytest -q
```

`pytest.ini` 将正式入口限定为 `tests/`；FAISS 未安装时对应可选测试模块跳过。当前工作区结果为 145 passed、1 skipped。无 Docker 模式可以完成核心 API、学习闭环和安全契约验收；`trusted_local` smoke 可在可信本机验证代码演示。浏览器 E2E 的当前证据位于 `outputs/e2e_no_docker/report.json`，脚本通过浏览器上下文显式携带 `X-EduMatrix-LLM-Mode: deterministic`，因此不依赖 `.env` 中的外部 LLM。测试报告必须记录实际命令、日期、依赖版本、网络状态、沙箱模式和失败原因，不能把可选环境依赖未满足写成核心代码缺陷，也不能把专项测试通过写成全系统安全认证。

## 8. 当前机器验证快照

截至 2026-07-19，当前工作区已验证：Python 3.11.9、NumPy 2.4.6、PyTorch 2.13.0、OpenAI 2.46.0、Instructor 1.15.4、python-docx 1.2.0、pytest 9.1.1、Playwright 1.61.0 和 Docker SDK 7.2.0 可导入。正式 pytest 结果为 145 passed、1 skipped；运行时安全矩阵为 47/47；当前机器的 Playwright Chromium 已实际用于无 Docker 浏览器 E2E，`trusted_local` API smoke 也已通过；PDF 导出和目标评委机浏览器仍需单独复核。提交包默认模式为 `disabled`，本地演示 `.env` 使用 `trusted_local`；Docker daemon 未运行不影响核心应用导入、启动和默认学习闭环。Docker 模式只验证了“不可用时拒绝执行”的安全行为。

## 9. 常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动即提示生产密钥错误 | `EDUMATRIX_ENV=production` 但没有合规密钥 | 注入至少 32 字符的唯一随机密钥 |
| `/api/code/run` 返回代码沙箱未启用 | 默认 `EDUMATRIX_SANDBOX_MODE=disabled`，或 Docker 模式下 daemon 不可用 | 核心验收可忽略并展示 `/api/code/status`；需要实时执行时安装并启动 Docker、设置 `EDUMATRIX_SANDBOX_MODE=docker`；不要启用宿主 Python 回退 |
| PDF 导出失败 | Chromium 二进制未安装或系统库缺失 | Windows 执行 `playwright install chromium`；Linux 执行 `--with-deps chromium` |
| 前端无法请求后端 | 后端 8000 端口未启动或 CORS/代理配置不一致 | 先访问 `/api/health`，再检查 Vite 代理 |
| 联网搜索超时 | 外部搜索站点或网络不可用 | 使用本地已有资料或 deterministic 演示数据，并标注证据等级 |

## 10. 一键启动故障修复记录（2026-07-19）

本轮已将 Windows 一键启动流程统一为项目虚拟环境，不再允许启动脚本静默落到系统 Python：

1. `start.bat` 首先调用 `.venv\Scripts\python.exe scripts\runtime_preflight.py`，检查当前解释器路径以及 FastAPI、Uvicorn、Matplotlib、Pandas、scikit-learn 是否可导入。
2. 启动后端时统一调用 `.venv\Scripts\python.exe run.py`，默认 `EDUMATRIX_RELOAD=0`，减少 Windows 重载进程造成的环境混用。
3. `run.py` 启动前只清理命令属于 EduMatrix 的旧后端；如果 8000 被其他程序占用，会拒绝误杀并提示原因。
4. BKT/Poincare 算法的 Windows 多进程池显式使用当前解释器和 `spawn` 上下文，避免科学计算 worker 找不到项目依赖。
5. 前端启动前检查 5173；已有 EduMatrix Vite 服务时直接复用，其他程序占用时停止启动，不会静默跳到其他端口。
6. `/api/code/status` 会返回非敏感的 `python_executable`、`multiprocessing_executable` 和进程号，便于评委现场确认运行环境。

一键启动命令：

```powershell
cd D:\project-edumatrix\edumatrix-main
start.bat
```

本机复验结果：

| 项目 | 结果 |
|---|---|
| `.venv` 预检 | PASS；Matplotlib 3.11.1、Pandas 3.0.3、scikit-learn 1.9.0 |
| 后端健康检查 | HTTP 200 |
| `/api/code/status` | `trusted_local`、执行已启用、两个解释器字段均指向项目 `.venv` |
| trusted_local smoke | PASS |
| Matplotlib 绘图 | 成功返回 Base64 图片 |
| Pandas 示例 | 输出 `6` |
| scikit-learn 示例 | 输出 `2.0` |
| 正式 pytest | `141 passed, 1 skipped` |
| 前端 production build | PASS |
| 重复执行 `start.bat` | 后端重启成功，已有 5173 Vite 服务被复用 |

> 本节是最新复验结果，覆盖前文测试快照中的旧数量。文本输出上限仍为 100KB；Matplotlib 图片使用独立的 5MB 可视化上限，不再占用文本输出额度。

## 11. 当前故障排查优先级

如果评委现场再次看到 `No module named 'matplotlib'`，不要直接向系统 Python 安装包。按以下顺序检查：

```powershell
.venv\Scripts\python.exe scripts\runtime_preflight.py
Invoke-RestMethod http://127.0.0.1:8000/api/code/status | ConvertTo-Json
.venv\Scripts\python.exe scripts\trusted_local_smoke.py
```

重点确认 `python_executable` 和 `multiprocessing_executable` 都包含：

```text
D:\project-edumatrix\edumatrix-main\.venv\Scripts\python.exe
```

若预检失败，应先执行全新环境安装；若预检通过但状态接口不一致，应关闭旧后端后再次执行 `start.bat`。不要通过给系统 Python 单独安装 Matplotlib 来掩盖启动入口错误。

## 12. 3D 可视化输出上限

本地研究模式对普通控制台文本保持 `EDUMATRIX_SANDBOX_MAX_OUTPUT_BYTES=100000` 的限制，防止无限打印造成内存和响应体膨胀。Matplotlib 生成的 PNG Base64 数据不再写入文本缓冲区，而是通过独立可视化通道传输，默认上限为：

```dotenv
EDUMATRIX_SANDBOX_MAX_VISUAL_BYTES=5000000
```

因此前端内置的 3D 曲面示例可以完整返回图片；如果图片超过 5MB，系统会返回明确的“可视化输出已截断”提示，而不会返回损坏的普通文本。
