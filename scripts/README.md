# 脚本入口

当前定位先查 [作品与代码地图](../docs/PROJECT_MAP.md)，验证结果见 [当前事项](../docs/CURRENT.md)。不需要依次执行本目录全部脚本。

| 用途 | 入口与范围 |
| --- | --- |
| 源码开发启动 | 根 `start.bat` → `runtime_preflight.py` → `db_heal.py` → 根 `run.py`；Vite 提供前端 |
| 依赖检查 | `runtime_preflight.py`；核心 Python 依赖缺失会失败，语音与自动视频运行时不可用会报告警告 |
| 代码地图索引 | `update_code_index.py`；更新 `docs/code-index.csv`，同时解析所有纳入索引的 Python 文件；不导入服务、不修改数据库 |
| 本地运行窄烟测 | `e2e_no_docker.py`；先阅读其账号、运行环境和输出约定，再在隔离服务使用 |
| 聚焦行为测试 | 在根目录运行 `.venv/Scripts/python.exe -m pytest tests/对应文件.py`；`tests/conftest.py` 提供数据库隔离，显式禁用 dotenv |
| 前端行为与构建 | 在 `frontend/` 运行 `npm test`、`npm run build` |
| 历史材料打包 | `create_competition_packages.py` 仍绑定 `00015352` 和旧材料清单，只保留作历史构建入口；正式打包前按 [提交材料规则](../docs/SUBMISSION_RULES.md) 核对名称、版本、素材与报名表，本次不生成提交包 |
| 历史治理和审计 | `build_f*`、`fill_f*`、`finalize_f*`、`update_f*`、旧 recovery/checkpoint 脚本保留为历史工具，不是后续改动的执行前置 |

旧 `create_submission_package.py` 和 `arch_debate.py` 已归档：前者写入过时团队、赛题和材料要求，后者是打印固定文本并记账的模拟脚本，不能作为真实模型或 Agent 运行证据。
