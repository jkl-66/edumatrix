EduMatrix 作品安装/可执行文件包

1. 双击 install_and_run.bat；如果系统有 winget 且没有 Python 3.11，脚本会尝试自动安装 Python 3.11。
2. 首次运行会创建 .venv，并从 requirements.txt 安装 Python 3.11 依赖；需要网络连接，可能耗时数分钟。
3. 依赖安装完成后，程序会启动后端，同时由 FastAPI 托管 frontend/dist 前端构建产物。
4. 浏览器会自动打开 http://127.0.0.1:8000/。
5. 默认 deterministic 模式无需外部大模型 API Key；需要真实模型时可在前端设置页填写评委自己的 Endpoint、Model 和 API Key。
6. 默认代码执行为 disabled。trusted_local 仅适用于可信本机研究演示，不具备 Docker 容器隔离；docker 模式不属于本包默认验收路径。
7. 双击 stop_services.bat 可停止后端。运行 verify_runtime.bat 可检查环境和健康接口。
8. 预置课程原始输入位于 data/raw/github_repos；仓库来源、主题和许可证策略见 data/manifest/source_manifest.jsonl，实际打包清单见 data/manifest/github_repos_package_manifest.json。

说明：赛方上传包上限为 1 GB，完整开发机虚拟环境不能直接搬运。本包包含依赖清单、锁定版本快照和自动安装脚本；不包含开发机路径、API Key、.env 密钥、数据库 WAL 文件或个人数据。
