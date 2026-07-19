# EduMatrix 本轮整改记录

## 1. 目的

本记录对应 2026-07-19 对软件杯 A3 作品进行的安全、依赖、测试和交付环境整改。它不是“系统已通过生产安全认证”的声明，而是源码变更、验证结果和剩余风险的可追溯记录。

## 2. 已实施变更

### 2.1 认证与数据归属

- `EDUMATRIX_DEMO_MODE` 默认关闭；无 Token 的受保护接口默认返回 401。
- `config.py` 不再使用固定 JWT 默认密钥。开发环境缺少密钥时生成临时随机值；生产环境缺少唯一、至少 32 字符的密钥时拒绝启动。
- 增加 `enforce_student_access` 和 `enforce_request_student_scope`，学生只能访问自己的数据，教师必须显式指定目标学生。
- 测验、闪卡、行为日志、画像、知识库、网页导入、代码执行、流式对话、旧版笔记、复习和学情报告接口均接入认证或学生范围校验。
- 笔记、复习计划和错题反思的更新/删除/读取增加学生归属过滤，避免只凭记录 ID 修改其他用户数据。

### 2.2 文件与 RAG

- 本地上传读取上限为 `EDUMATRIX_MAX_UPLOAD_BYTES`，默认 20 MiB，并超额返回 413。
- 远程文件下载使用 HTTP 分块读取，预检 `Content-Length`，累计超限立即中止，不再先把不受限的响应整体放入内存。
- 用户文档摄入、检索和删除均携带 `owner_id`/私有可见性过滤。

### 2.3 代码沙箱

- Docker 不可用、容器创建失败或健康检查失败时拒绝执行。
- 已删除生产路径上的宿主 Python 子进程回退逻辑的可达性；代码保留部分仅作为历史兼容实现，主执行入口不会调用。
- 日志文案已改为“代码执行保持禁用”，避免把拒绝策略描述成不安全的 subprocess fallback。

### 2.4 依赖与交付环境

已补入 `requirements.txt`：NumPy、PyTorch、OpenAI SDK、Instructor、python-docx、pytest、Playwright 和 Docker SDK。Node 20 与前端 `npm ci`、Docker Engine、Playwright Chromium 浏览器二进制的安装步骤已写入《评委环境安装与复现备忘录》。

## 3. 本轮验证

| 验证 | 结果 |
|---|---|
| 修改文件 AST 解析 | 通过 |
| 应用导入和路由注册 | 通过，44 条路由 |
| `tests.test_security_contracts` | 以当前文件中的安全契约用例为准，需随最终版本重跑并记录实际数量 |
| `scripts.test_member6_all_tasks` | 62/62 通过 |
| BKT/DKT/ZPD 目标测试 | 通过 |
| Guided decoding、DOCX 目标测试 | 通过 |
| 生产密钥门禁 | 缺失密钥拒绝；32 字符密钥通过 |
| 运行时安全矩阵 | A/B/教师选定关键路由 47/47 通过，详见 `outputs/runtime_security_matrix.json` |
| 无 Docker 浏览器 E2E | 注册/登录、初始化、仪表盘、对话、学习路径和沙箱禁用状态通过，详见 `outputs/e2e_no_docker/report.json` |
| Docker daemon | 当前机器未运行，未进行真实容器代码执行；这是可选增强路径，不阻断核心验收 |
| Playwright Chromium | 当前机器已用于无 Docker 浏览器 E2E；PDF 导出和目标评委机浏览器仍需单独复核 |
| 全量 `test_edumatrix` | 单次整套命令受外部/异步路径拖延；拆成 4 组执行共 80 个用例，80/80 通过。该结果不覆盖真实 Docker 执行、PDF 导出、生产并发和目标机清洁复现 |

## 4. 尚未完成事项

1. 将选定 47 条运行时安全矩阵扩展到全部外部 API、持久化索引和删除场景，并验证 403/404 行为。
2. 将远程 URL HTML 摄入改为同样的分块上限和响应超时策略。
3. 将代码沙箱拆为独立 worker，避免生产应用直接持有宿主 Docker 控制面。
4. 在清洁目标机完成 Dockerfile 构建、可选代码执行和 PDF 导出 smoke test；当前 Dockerfile 已包含 Chromium 安装步骤。
5. 为比赛三项指标准备可复现的正式标注集；当前已生成合成结构性证据，但不能替代真实用户实验或人工标注结论。

## 5. 对外表述边界

可以表述：本轮已完成主要业务接口的身份边界整改、用户 RAG owner 过滤、Docker 不可用时拒绝宿主执行、依赖清单补齐，并通过专项安全契约测试。

不能表述：全系统已经生产级安全、全部接口已经完成多租户验收、Docker 实时代码执行或 PDF 导出已在所有部署形态验证、幻觉率或画像适配率已经达到比赛量化结论、全量测试 100% 通过。
