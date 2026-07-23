# EduMatrix 风险与整改清单

> **代码执行风险声明**：`trusted_local` 的目标是降低学术演示环境的安装成本，不是替代 Docker 的安全边界。该模式不提供容器隔离，不能对抗恶意或不可信代码；默认提交配置仍为 `disabled`，Docker 模式作为可选增强保留。

> 状态更新时间：2026-07-19。以下“已修复”表示源码与对应专项/运行时证据已覆盖；不等同于在所有生产依赖、真实 Docker 执行、PDF 导出、外部网络和目标评委机器上完成全量验收。默认无 Docker 核心路径已经完成浏览器 E2E 验证。

## 0. 本轮整改结果

| 状态 | 范围 | 证据 |
|---|---|---|
| 已修复并有专项测试 | 显式 Demo 模式、JWT 密钥门禁与失效 Token 处理、主要 API 学生范围校验、RAG owner 过滤、Docker 不可用时拒绝宿主执行、上传/下载大小上限 | `tests/test_security_contracts.py` 11/11 通过 |
| 已完成选定运行时回归 | A/B/教师访问边界和关键业务拒绝矩阵 | `outputs/runtime_security_matrix.json` 47/47 通过；仍不等于覆盖全部 API |
| 已完成默认路径 E2E | 无 Docker 注册、登录、初始化、仪表盘、对话、学习路径和沙箱状态 | `outputs/e2e_no_docker/report.json` 标记 `passed`，6 张截图 |
| 环境待验证 | 真实 Docker daemon 代码执行、PDF 导出、目标评委机清洁复现、真实外部 LLM/联网搜索 | 见评委环境安装备忘录 |
| 尚未完成 | 生产级独立 sandbox worker、正式指标标注集、所有可选 provider 锁定、目标机 Docker/PDF 验收 | 不应在答辩中宣称已完成 |

## 1. 立即整改（阻断比赛演示或生产安全）

| 编号 | 风险 | 证据 | 影响 | 整改方案 | 验收标准 |
|---|---|---|---|---|---|
| RISK-01 | 缺 Token 自动进入 demo 用户 | `app/auth.py`、`config.py` | 鉴权绕过、身份混淆 | 生产无 Token 直接 401；demo 用显式配置 | **已修复；契约测试通过** |
| RISK-02 | API 信任客户端 student_id | 主要 API 路由和旧版笔记/复习接口 | IDOR/BOLA、跨用户读写 | 从认证用户生成 effective_student_id，教师仅接受显式目标 | **选定关键路由已修复；运行时矩阵 47/47 通过，全部 API 仍需边界复核** |
| RISK-03 | 用户 RAG 全局索引 | `rag_engine.py` | 私有知识泄露 | 按 owner metadata 过滤摄入、检索和删除 | **已修复；契约测试通过** |
| RISK-04 | Docker 不可用退化宿主子进程 | `code_exec_api.py` | 代码可接触宿主文件/环境 | Docker 不可用直接拒绝执行，后续生产使用独立 worker | **已修复；Docker 离线拒绝测试通过** |
| RISK-05 | JWT 密钥未稳定配置导致重启后旧 Token 失效 | `config.py`、`.env.example`、`frontend/src/api/common.js` | 用户被留在业务页并看到原始 401 | 本地演示固定随机密钥；401 自动清理登录态并回到登录页；生产缺少合规密钥时启动失败 | **已修复；重启稳定性与前端回归通过** |

## 2. 高优先级整改

| 编号 | 风险 | 证据 | 整改方案 |
|---|---|---|---|
| RISK-06 | DRAG LLM 注入与异步链路 | `agent_swarm.py`、`tests/test_hardening.py` | 构造或事件循环边界错误会使真实辩论不可用 | 已注入 `llm=use_llm`，异步主链路使用 `aclean()`；外部 provider 仍需目标环境验收 |
| RISK-07 | async 中 `run_until_complete` | 历史 `drag_debate.py` 同步桥接 | 流式请求可能 RuntimeError | 已移除辩论路径中的事件循环嵌套，`aclean()` 直接 await；同步兼容入口仅保留确定性路径 |
| RISK-08 | requirements 不完整 | `requirements.txt` 与 AST import 对比 | 新环境启动失败 | 已补充 NumPy、PyTorch、OpenAI、Instructor、python-docx、pytest、Playwright、Docker SDK；可选 provider 仍需分层锁定 |
| RISK-09 | Docker 镜像/PDF 能力尚未在目标机验收 | `Dockerfile`、PDF 导出路径 | 容器构建或 PDF 导出在目标机失败 | Dockerfile 已安装 Playwright Chromium 及系统依赖；在清洁目标机完成镜像构建和 PDF smoke test |
| RISK-10 | cache 无 TTL/容量 | `cache_utils.py`、`swarm_factory.py`、画像/嵌入/搜索缓存 | 长期 OOM | 已接入线程安全 TTL+LRU、有界条目和过期清理；长期进程仍需监控命中率 |
| RISK-11 | 上传/远程下载内存和解析资源限制 | `knowledge_api.py`、`document_parser.py` | 大文件、压缩炸弹或慢解析 DoS | 已增加大小、页数、压缩包成员/展开体积、压缩比、解析超时和网页内容上限；目标机仍需压力复核 | **已修复核心限制** |

## 3. 中优先级整改

| 编号 | 风险 | 证据 | 整改方案 |
|---|---|---|---|
| RISK-12 | arXiv 缓存 datetime 导入异常被吞 | `rag_engine.py` | 缓存写入失败且不易发现 | 已补 UTC 时间、TTL 清理和容量淘汰；异常仍记录为降级 |
| RISK-13 | MIRT 极端值除零 | `mirt_engine.py`、`tests/test_hardening.py` | 极端题目或参数崩溃 | 已补有限值/范围归一化、稳定 sigmoid、协方差退化兜底和 MCMC 烧入保护 |
| RISK-14 | Anki 时间时区不一致 | `anki_engine.py` | 错误计算到期时间 | 已统一 naive/aware ISO 时间为 UTC，并补输入边界清洗 |
| RISK-15 | 沙箱文档 500KB 与代码 50KB 不一致 | `code_exec_api.py:130-136` | 评委复核时发现矛盾 | 统一代码、测试、文档、演示话术 |
| RISK-16 | 报告混用不同 commit/路径 | `reports/*.md` | 证据不可复核 | 统一基线、生成时间和路径 |
| RISK-17 | 前端主包过大、KaTeX/ECharts 构建警告 | Vite build 输出 | 首屏和公式体验风险 | 已改为本地 KaTeX、路由懒加载和按图表类型按需 ECharts；当前构建无相关警告 |
| RISK-18 | out-of-domain 查询可能被通用视频 fallback 抬高置信度 | `rag_engine.py` 视频证据注入路径 | 低相关问题被误判为高置信度 | 已限制通用视频注入仅用于领域内查询，并由低置信度回归覆盖 |

## 4. 整改顺序

```text
认证与 owner 隔离
  -> 代码执行拒绝宿主回退
  -> RAG owner 过滤
  -> 依赖/Docker/Playwright 固化
  -> DRAG LLM 注入和异步修复
  -> 算法边界与时间统一
  -> 指标数据、E2E 和性能测试
  -> 重新生成最终比赛材料
```

## 5. 不能继续使用的表述

- “所有接口均由 JWT 守护”；
- “已实现分布式多租户隔离”；
- “500KB 沙箱限制”；
- “默认在无外部模型时运行真实 Prover-Challenger-Judge 三模型辩论”（deterministic 模式只能称为结构性降级）；
- “全量测试 100% 通过”；
- “幻觉率已低于 5%”；
- “已完成真实用户学习效果实验”；
- “Dockerfile 可直接提供全部 PDF/AI 能力”。
