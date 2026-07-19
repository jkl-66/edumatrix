# EduMatrix AI 编程工具使用说明

## 1. 使用目的

本项目在研发和参赛材料整理阶段使用 AI 编程工具辅助代码检索、测试设计、文档校对和材料组织。AI 输出均经过人工/自动化验证后才进入项目文件，不能把模型生成内容视为独立的事实来源。

## 2. 使用范围

| 使用环节 | AI 辅助内容 | 验证方式 |
|---|---|---|
| 源码审计 | 根据报告和源码定位认证、IDOR、RAG 隔离、沙箱和依赖问题 | 阅读源码、AST 检查、专项测试、80 个集成测试 |
| 安全整改 | 提出服务端身份绑定、owner 过滤和无宿主回退方案 | A/B/教师运行时矩阵 47/47，通过安全契约 10/10 |
| 环境整理 | 归纳 Python、Node、Playwright、Docker 可选模式和环境变量 | 导入检查、健康检查、无 Docker E2E |
| 测试材料 | 生成测试用例骨架、合成画像和固定知识集 | deterministic 运行、JSON 结果和截图证据 |
| 文档与答辩 | 统一术语、事实状态、风险边界、PPT 文案和演示脚本 | 对照当前源码、命令输出和提交清单 |

## 3. 使用边界

- 不使用 AI 生成真实用户数据、真实调研结论或无法追溯的比赛指标。
- 合成画像、固定知识集和结构化基线均标注为“合成演示数据”或“代码实测”。
- 外部论文、报告和标准单独列出来源，不把 AI 的常识回答当作引用。
- API Key、密码、JWT secret 和真实个人信息不进入提示词、截图或压缩包。
- 代码执行安全、身份授权和数据隔离以源码和测试为准，不以模型自我声明为准。

## 4. 可复现命令

```powershell
.venv\Scripts\python.exe -m unittest tests.test_security_contracts -v
.venv\Scripts\python.exe -m unittest tests.test_swarm_runtime -v
.venv\Scripts\python.exe scripts\runtime_security_matrix.py
.venv\Scripts\python.exe scripts\e2e_no_docker.py
.venv\Scripts\python.exe scripts\generate_innovation_evidence.py
.venv\Scripts\python.exe -m unittest test_edumatrix -v
```

## 5. 最终提交前人工确认

- 团队名称、学校、成员、指导教师和联系方式；
- 官方 PPT 模板、视频时长、文件命名和截止时间；
- 最终前端版本、录屏内容和截图授权；
- 所有引用链接的访问日期和最终文档版本号。
