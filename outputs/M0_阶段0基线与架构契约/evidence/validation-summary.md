# M0 验证摘要

验证日期：2026-07-23（Asia/Shanghai）  
工作树基线提交：`62eb18570a8a26daa48e94e43603de225041efc1`

## 1. 自动测试

命令：

```powershell
.venv\Scripts\python.exe -m pytest -q --junitxml="outputs/M0_阶段0基线与架构契约/evidence/pytest-junit.xml"
```

结果：`150 passed, 1 skipped, 6 warnings`，耗时 102.17 秒，返回码 0。JUnit 顶层 `tests=151` 包括 150 个通过测试和 1 个 collection skip；跳过项是可选 FAISS 加速依赖。

警告：Starlette/httpx 兼容弃用、FastAPI `on_event` 弃用、PyTorch tensor 转 float 警告。它们未导致本次失败，但应在后续可靠性阶段登记升级。

## 2. M0 专项契约测试

`tests/test_m0_baseline_contracts.py` 共 5 项通过：

- 9 个课程文件存在、字节数和 SHA-256 与 manifest 一致。
- 9 个 Markdown 文件可由当前 `document_parser` 读取并产生非空分块。
- 3 个合成画像唯一，脚手架等级存在明确差异。
- 32 个核心知识点唯一，覆盖分母固定为 32。
- 60 个案例唯一，六个评测域各 10 项，均含知识点、金标和失败分支。
- 412 个竞品来源 ID 唯一、每条只有一个主能力域和处置结论，三产品计数正确，待复核为 0，Markdown 逐项报告包含 412 行。

## 3. 前端构建

命令：`npm.cmd run build`（`frontend/`）  
结果：构建成功，3089 个模块转换，返回码 0。  
警告：`StudentAnalysis` 产物约 567.74 kB，超过 Vite 500 kB 提示线；不影响构建，但建议后续代码分割。

## 4. trusted_local 运行验证

2026-07-23 在 deterministic 后端、`EDUMATRIX_SANDBOX_MODE=trusted_local` 下运行 `scripts/trusted_local_smoke.py`：

- `/api/code/status` 返回 `execution_enabled=true`。
- 隔离说明为 `trusted_local_child_process` / `research_only_no_container_isolation`。
- 安全代码 `print(6 * 7)` 输出包含 42。
- `import os; os.system(...)` 被阻止，无输出且有错误信息。
- 结果：passed。原始报告：`outputs/trusted_local_smoke.json`。

该模式不是 Docker 容器隔离，只适用于本机研究和比赛演示；生产环境代码会回退到 disabled。

## 5. 浏览器 E2E

- 2026-07-23 当前版本在 `trusted_local` 模式通过 9 页 Chromium E2E。
- 流程覆盖注册/引导、仪表盘、确定性问答、学习路径、知识库、画像分析和多模态设置。
- 代码沙箱按钮可用，页面实际运行 `print(6 * 7)` 并显示 `42`；安全等级明确为 `research_only_no_container_isolation`。
- 机器报告：`evidence/e2e-no-docker-trusted-local-20260723.json`；最新截图：`outputs/e2e_no_docker/01-login.png` 至 `09-settings-multimodal.png`，其中代码页为 `05-code-sandbox-trusted-local.png`。
- 截图抽查同时确认知识库页面仍显示旧 25 章人工智能课程，因此不能据此宣称 M0 的 RAG 基准课程已完成前端摄入。

## 6. 编码说明

M0 JSON/Markdown 使用 UTF-8 无 BOM。Windows PowerShell 5 读取时必须显式指定 `-Encoding UTF8`；默认 ANSI 读取会产生乱码并造成假性 JSON 解析失败。显式 UTF-8 校验后，3 画像、32 KP、60 案例和 9 个课程哈希全部通过。
