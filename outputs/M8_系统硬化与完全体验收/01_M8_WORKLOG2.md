# EduMatrix M8 WORKLOG2

## WL2-M8-20260728-004 - 后端唯一密钥边界与最终验证

- 状态：`PARTIAL`（M8-002/008/009）。
- 二次扫描发现 `Settings.vue` 与 `api/common.js` 仍可将文本/视觉 API Key、端点和模型保存到 localStorage 并写入 `X-EduMatrix-*` 头；`swarm_factory.py` 仍消费这些头。这是首轮头像/健康修复之外的同类安全缺陷。
- 修复：设置页改为只读后端能力状态和学习偏好；进入页面清除旧 `edumatrix_llm_config`。公共客户端只发送认证 JWT 和非秘密教学风格。Swarm factory 忽略所有外部 provider/key/endpoint/model 头，只从后端配置构建模型；开发环境仅保留明确 deterministic 测试模式。
- 验证：安全与多模态聚焦回归 `23 passed`；前端生产构建在沙箱外成功，`3066 modules transformed`。仅有既有 `StudentAnalysis` 564.22 kB 大 chunk 警告。
- 当前预检：数据库可用、迁移 `20260728_011` 当前、5 用户/1 领域包、frontend dist 可用；文本模型、视觉模型、检索、沙箱、媒体均不可用，整体 `not_ready`，`generation_allowed=false`。
- 时间：2026-07-28（Asia/Shanghai）。

## WL2-M8-20260728-005 - 全量回归与 M2-M8 退出结论

- 全量 pytest：`304 passed, 13 failed, 11 errors, 6 warnings`。
- 13 failed 分类：动画/视频真实资产缺失 6 项；FAISS 持久化或真实 patch 资产缺失 4 项；当前 Windows 子进程/命名管道限制导致 trusted-local、spawn、视觉输出 3 项。
- 11 errors：全部在测试 setup 阶段因 `C:\Users\Administrator\AppData\Local\Temp\pytest-of-Administrator` ACL `WinError 5`，未进入业务断言。
- 本批新增模块没有出现在失败清单；聚焦证据包括 M5/M8 `31 passed`、M7/企业 `12 passed`、安全/多模态 `23 passed`、恢复 `4 passed`。
- 结论：本地代码硬化与可验证功能已继续推进，但 M2-M8 权威阶段门禁没有全部完成。不能把外部资源缺失、真实运行、独立标注、浏览器/干净机验收或性能指标伪造成 PASS。详细阻塞见 `02_M2-M8最终退出审计.md`。
- 时间：2026-07-28（Asia/Shanghai）。

## WL2-M8-20260728-001 - 健康接口与浏览器端密钥泄露修复

- 状态：`PARTIAL`（M8-002/007/008）。
- 发现：旧 `/api/health` 回显模型端点及客户端传入 Key 的存在状态；旧 `/api/llm/test` 使用请求头构建模型、提示浏览器配置 Key，并回显端点或原始异常。
- 修复：健康接口只返回数据库和能力布尔状态；不接受客户端模型 Key、不返回端点。LLM 测试只读后端环境配置，缺模型时明确警告，不回显原始异常和端点。
- 发现：`AvatarSpeech.vue` 从 localStorage 读取第三方 AppId/API Key/API Secret，在浏览器执行 HMAC 并直连第三方 WebSocket。
- 修复：删除前端密钥、HMAC 和直连路径，改为无密钥的浏览器 `speechSynthesis`，保留播放、暂停、恢复、停止、静音、自动播报和压力情境降速；不宣称后端 TTS 已接入。
- Docker：移除预填第三方地址/模型，Key 仅从部署环境注入。
- 验证：安全契约 `13 passed`，Python 编译通过。
- 时间：2026-07-28（Asia/Shanghai）。

## WL2-M8-20260728-002 - 原子恢复与完整性验证

- 状态：`PASS`（M8-005）。
- 加固：备份使用 SQLite online backup；恢复先在同父目录 staging 完整校验 manifest、成员唯一性、路径边界、SHA-256、字节数和 `PRAGMA integrity_check`，全部成功后才移动至空目标。
- 行为：拒绝非空目标、重复/缺失成员、路径穿越、校验和或大小变化、缺失数据库及损坏 SQLite；失败不留下对外可见的半恢复目录。
- 验证：数据库与中文文件往返、恢复库可查询、内容篡改拒绝、非空目标拒绝、恶意路径拒绝，共 `4 passed`。
- 环境问题：系统/Python `tempfile` 创建目录后出现 Windows ACL 拒绝访问；改用仓库预建受控目录继承 ACL 才完成业务验证。此前失败属于环境 ACL，不是业务断言失败。
- 时间：2026-07-28（Asia/Shanghai）。

## WL2-M8-20260728-003 - 认证部署预检与当前构建阻塞

- 状态：`PARTIAL`（M8-007/008）。
- 新增教师/管理员认证接口 `/api/v1/m8/deployment-preflight`，报告数据库、最新迁移、初始化数据、前端 dist、文本/视觉模型、检索、沙箱和媒体能力。
- 预检输出 `ready/not_ready`、`generation_allowed` 和可操作 blocker；不含 Key、端点或异常正文，Key 仅以“后端是否配置”布尔值表示。
- 当前前端构建失败：`@tailwindcss/oxide-win32-x64-msvc` 原生 `.node` 无法加载（stream did not contain valid UTF-8），同时 Vite 配置加载出现 `spawn EPERM`。这不是本次 Vue 源码的业务测试失败，尚不能声明构建通过。
- 当前 Windows 还阻止 multiprocessing 命名管道创建（WinError 5）；相关启动测试不能在本环境宣称通过。
- 时间：2026-07-28（Asia/Shanghai）。
