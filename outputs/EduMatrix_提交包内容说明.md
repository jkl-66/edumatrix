# EduMatrix 清洁提交包内容说明

## 当前策略

生成一个“待补团队信息”的预提交包，默认采用无 Docker 核心验收模式。包内不包含真实 `.env`、数据库运行文件、`.venv`、`node_modules`、测试缓存和大体积原始数据；评委可按安装备忘录重新安装依赖、初始化数据库并运行 deterministic 演示。

## 包含内容

- Python/FastAPI 后端源码和 Vue 前端源码/构建产物；
- `requirements.txt`、`frontend/package-lock.json`、Dockerfile 和 compose 文件；
- 核心测试、运行时安全矩阵、无 Docker E2E 脚本和创新证据脚本；
- 完整技术文档 Markdown/DOCX、部署说明、评委复现备忘录、测试说明、API 字典、追踪矩阵和风险清单；
- PPT、逐页讲解备注、答辩脚本、AI 编程工具使用说明和公开引用清单；
- E2E 截图与 JSON 结果、三组合成画像、固定知识集和结构化对比结果；
- 小型算法模型/投影文件和必要的 `data/manifest`、`data/patches`。

## 刻意排除

- `.env`、API Key、JWT secret、SQLite 数据库/WAL/SHM；
- `.venv`、`node_modules`、`__pycache__`、`.git` 和临时日志；
- `data/raw`、`data/animations`、大型公开数据集等约 2.4GB 可选素材；
- 真实或无法确认授权的用户上传材料。

## 生成命令

```powershell
.venv\Scripts\python.exe scripts\create_submission_package.py
```

输出文件：`outputs/EduMatrix_软件杯提交包_待补团队信息.zip`。最终提交前仍需补团队信息、官方文件命名、视频和授权确认。
