EduMatrix 作品安装/可执行文件包

1. 双击 install_and_run.bat；如果系统有 winget 且没有 Python 3.11，脚本会尝试自动安装 Python 3.11。
2. 首次运行会在 `%LOCALAPPDATA%\EduMatrix\00015352\.venv` 创建短路径虚拟环境，并优先从 requirements-lock.txt 安装固定的 Python 3.11 依赖；需要网络连接，可能耗时数分钟。短路径用于规避 Windows 安装 PyTorch 时的路径长度限制，可通过 EDUMATRIX_VENV_PATH 覆盖。
3. 依赖安装完成后，程序会启动后端，同时由 FastAPI 托管 frontend/dist 前端构建产物。
4. 浏览器会自动打开 http://127.0.0.1:8000/。
5. 默认 deterministic 模式无需外部大模型 API Key。需要真实模型时，请在作品根目录的 .env 中填写 EDUMATRIX_LLM_*；多模态模型使用 EDUMATRIX_MULTIMODAL_LLM_*。密钥只由后端读取，浏览器设置页不会保存或发送密钥。
6. 作品模板显式启用演示模式，预置账号如下：学生 lzz / 404404aA；教师 teacher / admin123；管理员 demo-admin / EduMatrix-Demo-2026。账号只用于本机评审演示；部署到共享或生产环境前必须关闭 EDUMATRIX_DEMO_MODE，并创建独立账号与稳定认证密钥。
7. 作品包默认启用 trusted_local 代码演示。它只允许受限 Python 语法并在独立子进程中执行，适合可信评委本机的比赛演示；它不具备 Docker 容器、虚拟机或操作系统级隔离，不应运行未知来源代码，也不用于共享或生产环境。源码模板 .env.example 仍默认为 disabled。
8. 可在后端启动后运行 scripts\e2e_no_docker.py，检查展示页、登录、学习空间、预置知识库和 trusted_local 安全/拦截路径。完整桌面验收证据由项目测试报告提供，不由该窄烟测替代。
9. 双击 stop_services.bat 可停止后端。运行 verify_runtime.bat 可检查环境和健康接口。
10. 预置课程原始输入位于 data/raw/github_repos；仓库来源、主题和许可证策略见 data/manifest/source_manifest.jsonl，实际打包清单见 data/manifest/github_repos_package_manifest.json。

说明：完整开发机虚拟环境不能直接搬运。本包包含依赖清单、锁定版本快照和自动安装脚本；不包含开发机路径、API Key、.env 密钥、数据库 WAL 文件或个人数据。
