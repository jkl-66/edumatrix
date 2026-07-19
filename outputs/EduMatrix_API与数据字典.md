# EduMatrix API 与数据字典

基线：`2952dc1b17d793e5d76f54e1764348ebe50e4d5e`  
来源：FastAPI 路由源码、SQLAlchemy 模型、前端 API client  这份文件用于支撑主技术文档，不等同于 OpenAPI 在线文档。最终部署后应以 `/docs` 和实际响应为准。

## 1. 通用约定

### 1.1 基础地址

```text
开发环境前端：http://localhost:5173
开发环境后端：http://localhost:8000
```

### 1.2 认证头

```http
Authorization: Bearer <JWT>
Content-Type: application/json
```

前端还可能发送以下模型配置头：

```http
X-Edumatrix-Api-Key: <optional>
X-Edumatrix-Endpoint: <optional>
X-Edumatrix-Model: <optional>
X-Edumatrix-Temperature: <optional>
X-Edumatrix-Max-Tokens: <optional>
```

当前认证行为：`app/auth.py:get_current_user` 在默认配置下 Token 缺失返回 401；只有显式 `EDUMATRIX_DEMO_MODE=1` 才返回或创建 `demo-student`。以下标记为“未绑定”表示当前路由函数没有使用 `Depends(get_current_user)`，不表示前端没有发送 Token。

### 1.3 状态分类

- `200`：成功读取或处理；
- `201`：创建成功；
- `400`：输入无效；
- `401`：身份无效（当前部分接口不会返回该状态）；
- `403`：角色或资源权限不足；
- `404`：资源不存在；
- `409`：用户名等资源冲突；
- `500`：服务器或第三方依赖异常；
- `503`：建议用于外部模型、Docker、浏览器池不可用。

## 2. 认证与应用入口 API

### `POST /api/auth/login`

文件：`app/main.py:102`  
认证：公开  
输入：OAuth2 Password Form，字段 `username`、`password`；可选 `x-anon-student-id`。  
输出：

```json
{
  "access_token": "jwt",
  "token_type": "bearer",
  "username": "student-a",
  "display_name": "学生 A",
  "role": "student",
  "student_id": "student-a"
}
```

说明：内置 `demo-student/demo-password` 分支用于演示。生产环境应关闭硬编码演示账号或限制为显式 demo 配置。

### `POST /api/auth/register`

文件：`app/main.py:145`  
认证：公开  
输入：`username`、`password`、`display_name`、`major`、`cognitive_style`、`motivation_type`。  
行为：创建 `DBUser` 和 `DBStudentProfile`，尝试执行 Peer 先验校准，并迁移匿名数据。  
风险：密码长度要求仅 4 位；建议增加强度策略、登录限流、失败审计和验证码/锁定机制。

### `GET /api/health`

文件：`app/main.py:692`  
认证：公开  
用途：健康检查。Dockerfile 的 HEALTHCHECK 调用此地址。

### `GET /api/llm/test`

文件：`app/main.py:712`  
认证：当前未绑定用户  
用途：检测外部 LLM 或当前配置。

### `GET /api/metrics`

文件：`app/main.py:754`  
认证：当前未绑定用户  
用途：返回运行时指标。生产环境应限制访问，避免暴露内部信息。

## 3. 对话与 Agent 流式 API

路由前缀：`/api/stream`，文件：`stream_api.py`

### `POST /api/stream/chat`

认证：当前未绑定用户  
前端调用：`frontend/src/api/stream.js:streamChat`。  
请求示例：

```json
{
  "message": "请解释精确率和召回率的区别",
  "student_id": "student-a",
  "mode": "chat",
  "images": [],
  "active_doc_ids": []
}
```

响应：`text/event-stream`。前端解析 `event:` 和 `data:`，常见事件包括 Agent 开始、Agent 完成、内容增量、资源、完成和错误事件。

返回的完整结果可能包含：

```json
{
  "content": "...",
  "resources": [
    {"agent": "理论教授", "type": "专业讲义", "content": "..."}
  ],
  "profile": {},
  "alignment": {},
  "rdi": {},
  "strategy_plan": {},
  "safety": {},
  "metrics": {}
}
```

风险：请求体 `student_id` 当前可以影响画像、历史、资源和数据库写入对象。整改后必须由 JWT `sub` 生成有效学生 ID。

### `POST /api/stream/regenerate`

认证：当前未绑定用户  
文件：`stream_api.py:1493`  
输入：`student_id`、`role`、`resource_type`、`query`、可选 `overview`、`pathway`。  
用途：针对单个 Agent/资源类型重新生成。  
风险：可跨用户读取画像和复用缓存。

### `POST /api/stream/explain`

认证：当前未绑定用户  
文件：`stream_api.py:1657`  
输入：`target_text`、上下文、`student_id`、`follow_up`、`history`。  
用途：划词或公式的苏格拉底式追问。  
响应：JSON 或 SSE 双轨，取决于请求和生成路径。

## 4. 画像与学习路径 API

路由前缀：`/api/profile`，文件：`profile_api.py`。以下接口当前大多没有 `get_current_user` 依赖。

| 方法 | 路径 | 用途 | 当前身份状态 |
|---|---|---|---|
| GET | `/api/profile/{student_id}` | 画像、坐标、对齐结果 | 未绑定 |
| POST | `/api/profile/{student_id}/update` | 结构化更新画像 | 未绑定 |
| GET | `/api/profile/{student_id}/analysis` | 画像分析与诊断 | 未绑定 |
| GET | `/api/profile/{student_id}/learning-path` | 学习路径 | 未绑定 |
| GET | `/api/profile/{student_id}/goal-recommendations` | 目标推荐 | 未绑定 |
| POST | `/api/profile/{student_id}` | 兼容版画像更新 | 未绑定 |
| GET | `/api/profile/{student_id}/narrative` | 叙事成长报告 | 未绑定 |
| GET | `/api/profile/{student_id}/recommendations` | 智能资源推荐 | 未绑定 |
| POST | `/api/profile/{student_id}/rollback` | 按历史快照回滚画像 | 未绑定 |
| DELETE | `/api/profile/{student_id}/concept/{concept_name}` | 删除概念状态 | 未绑定 |

建议的安全接口形式：

```python
async def get_profile(
    current_user: DBUser = Depends(get_current_user),
) -> dict:
    student_id = current_user.username
```

教师查看学生时应增加独立授权函数，例如 `can_view_student(teacher, student_id)`。

## 5. 测验、错题和打卡 API

路由前缀：`/api/quiz`，文件：`quiz_api.py`。

| 方法 | 路径 | 作用 | 输入重点 |
|---|---|---|---|
| POST | `/api/quiz/generate` | 生成题目 | 概念、难度、画像/历史 |
| POST | `/api/quiz/evaluate` | 评估答案 | 题目、答案、学生 ID |
| POST | `/api/quiz/adapt` | 自适应调整 | 历史答题、目标难度 |
| GET | `/api/quiz/history/{student_id}` | 答题历史 | student_id、limit |
| POST | `/api/quiz/similar` | 相似题 | 请求体、数据库依赖 |
| GET | `/api/quiz/wrong-questions/{student_id}` | 错题列表 | 概念、limit |
| GET | `/api/quiz/wrong-concepts/{student_id}` | 错误概念统计 | student_id |
| DELETE | `/api/quiz/wrong-questions/{wrong_id}` | 删除错题 | wrong_id、student_id |
| PATCH | `/api/quiz/wrong-questions/{wrong_id}/pin` | 置顶/取消置顶 | wrong_id、student_id |
| PATCH | `/api/quiz/wrong-questions/{wrong_id}/notes` | 更新错题笔记 | wrong_id、请求体 |
| POST | `/api/quiz/checkin/{student_id}` | 复习打卡 | 概念、时区 |
| GET | `/api/quiz/checkin/streak/{student_id}` | 连续打卡 | student_id |
| GET | `/api/quiz/checkin/history/{student_id}` | 打卡历史 | student_id、concept |

专项测试验证了 MCQ 快速判分、题型区分、相似题模板、IRT beta 更新和时区参数等结构逻辑，但当前测试导入仍受依赖缺失影响。

## 6. 闪卡 API

路由前缀：`/api/flashcard`，文件：`flashcard_api.py`。

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/flashcard/generate` | 从测验/概念生成卡片 |
| POST | `/api/flashcard/review` | 提交质量评分并更新 SM-2 |
| GET | `/api/flashcard/due` | 获取到期卡片 |
| GET | `/api/flashcard/all` | 获取全部卡片 |

虽然这些函数包含数据库依赖，但请求体/查询参数中的 `student_id` 仍需与当前登录用户进行一致性校验。

## 7. 知识库与 RAG API

路由前缀：`/api/knowledge`，文件：`knowledge_api.py`。

| 方法 | 路径 | 用途 | 风险/条件 |
|---|---|---|---|
| POST | `/api/knowledge/upload` | 上传文档并异步摄入 | 当前无用户依赖，文件一次性读入 |
| GET | `/api/knowledge/list` | 文档列表 | 当前按客户端 student_id 过滤 |
| GET | `/api/knowledge/graph/stats` | 图谱统计 | 当前未绑定用户 |
| GET | `/api/knowledge/cross-search` | 跨模态搜索 | 依赖向量/图谱路径 |
| POST | `/api/knowledge/add-web-source` | 添加网页来源 | 需 URL 校验和 SSRF 防护 |
| POST | `/api/knowledge/download-web-file` | 下载网页文件 | 需大小、协议、重定向限制 |
| GET | `/api/knowledge/{doc_id}` | 获取文档详情 | 需校验文档 owner |
| DELETE | `/api/knowledge/{doc_id}` | 删除文档 | 需同步删除索引 |

上传接口建议采用 `Content-Length`、流式写入、总大小、页数、解压缩比、解析超时和后台队列限制。

## 8. 代码执行 API

路由前缀：`/api/code`，文件：`code_exec_api.py`。

### `POST /api/code/run`

当前认证：未绑定用户。  
请求：

```json
{
  "code": "print(1 + 1)",
  "language": "python",
  "student_id": "student-a"
}
```

输出：

```json
{
  "exec_id": "...",
  "output": "2\n",
  "error": "",
  "execution_time_ms": 12,
  "language": "python"
}
```

实际代码长度上限是 50,000 字节（50 KB）。Docker 不可用时会进入 `_run_in_subprocess`，生产环境应改为拒绝执行或独立沙箱 worker。

### `GET /api/code/history/{student_id}`

当前认证：未绑定用户。  
用途：读取代码执行历史。  
风险：可猜测其他学生 ID 后读取历史。

## 9. 行为、网页和动画 API

### 行为

`POST /api/behavior/logs` 接收前端停留、交互或执行行为并用于学情反馈。函数有数据库依赖，但必须增加当前用户和事件 schema 校验。

### 网页搜索

| 方法 | 路径 |
|---|---|
| POST | `/api/web/search` |
| POST | `/api/web/load-url` |
| GET | `/api/web/history/{student_id}` |
| GET | `/api/web/arxiv-search` |

网页下载和 URL 加载必须防 SSRF：拒绝内网 IP、loopback、file/gopher 等协议，限制重定向、响应大小和解析类型。

### 动画

| 方法 | 路径 |
|---|---|
| GET | `/api/v1/animations/list` |
| GET | `/api/v1/animations/for/{knowledge_point}` |
| GET | `/api/v1/animations/video/{knowledge_point}/{filename}` |
| GET | `/api/v1/animations/search` |

文件路径接口必须使用安全路径解析，不能允许 `..` 穿越；公开动画和用户上传资源应分开目录。

## 10. 报告、旧版和教师 API

### PDF

`GET /api/v1/profile/export`，文件：`report_api.py:227`。  
输入：`student_id`。  
依赖：数据库和 Playwright browser pool。  
要求：容器中安装 Playwright 浏览器；并限制并发、页面复杂度和导出队列。

### 旧版应用接口

`app/main.py` 还注册了：

- `/api/process`；
- `/api/stream/explain`；
- `/api/sessions/{student_id}`；
- `/api/notes/*`；
- `/api/progress/{student_id}`；
- `/api/history/{student_id}`；
- `/api/review/{student_id}`；
- `/api/export-notes-pdf`。

这些接口与新 router 并存，建议在最终产品中统一版本、废弃重复路径并保持认证策略一致。

### 教师

- `GET /api/teacher`；
- `GET /api/teacher/seed`；
- `GET /api/teacher/reviews`。

这些接口使用教师依赖，但 `get_current_teacher` 依赖 `get_current_user`，而后者当前缺 Token 会自动进入 demo 学生，因此生产环境必须先修复根依赖。

## 11. 数据字典

### 11.1 `users`

| 字段 | 类型 | 含义 | 约束 |
|---|---|---|---|
| `id` | integer | 内部主键 | 自增 |
| `username` | string(64) | 登录名/通常也是 student_id | 唯一、非空 |
| `hashed_password` | string(128) | bcrypt 哈希 | 非空 |
| `role` | string(16) | student/teacher | 默认 student |
| `display_name` | string(64) | 展示名 | 可空 |
| `is_active` | boolean | 是否启用 | 默认 true |
| `created_at` | datetime | 创建时间 | UTC |

### 11.2 `student_profiles`

| 字段 | 类型 | 含义 |
|---|---|---|
| `student_id` | string(64) | 学生业务主键 |
| `target_course` | string | 目标课程 |
| `knowledge_base` | string | 基础级别 |
| `cognitive_style` | string | 认知/表达偏好 |
| `motivation_type` | string | 动机类型 |
| `frustration_index` | float | 挫败指数 |
| `focus_level` | float | 专注度 |
| `cognitive_load` | float | 认知负荷 |
| `weak_points` | JSON list | 薄弱概念 |
| `learning_goals` | JSON list | 学习目标 |
| `interaction_preferences` | JSON list | 交互偏好 |
| `concept_mastery` | JSON dict | 概念掌握度 |
| `misconception_patterns` | JSON dict | 误概念模式 |
| `dimension_states` | JSON dict | 多维画像状态 |
| `learning_state_causes` | JSON dict | 不会原因占比 |
| `history_logs` | text | 历史记录 |
| `narrative_report` | text | 叙事报告 |
| `dashboard_report` | text | Dashboard 报告 |
| `major` | text | 专业 |
| `profile_evidence` | JSON list | 画像证据 |
| `customized_fields` | JSON list | 用户手动固定字段 |
| `rl_q_table` | JSON dict | 策略表 |
| `mental_state_history` | JSON list | 心智状态序列 |
| `concept_layers` | JSON dict | 层级信息 |
| `bkt_states` | JSON dict | BKT 状态 |
| `cognitive_map` | JSON dict | 认知图 |
| `fsm_mode` | string | 当前学习模式 |

### 11.3 业务关联表

| 表 | 关键字段 | 用途 |
|---|---|---|
| `alignment_logs` | student_id、target_concept、passed、distance、conflicts | 资源对齐结果 |
| `notes` | student_id、content、tags、concepts | 学习笔记 |
| `review_plans` | student_id、concept、interval_days、next_review_at、quality | 间隔复习 |
| `conversation_history` | student_id、query、response_summary、profile_snapshot | 对话与画像快照 |
| `knowledge_documents` | student_id、filename、content、chunk_count | 用户知识文档 |
| `quiz_records` | student_id、question、answer、accuracy_score、target_concept | 答题记录 |
| `web_search_history` | student_id、query、url | 网页搜索记录 |
| `code_executions` | student_id、code、output、error、execution_time_ms | 沙箱记录 |
| `wrong_questions` | student_id、question、reason、pinned、notes | 错题 |
| `checkin_logs` | student_id、concept、date | 复习打卡 |

### 11.4 数据隔离规则（目标设计）

所有上述含 `student_id` 的业务表都必须满足：

```text
普通学生只能读取/修改 student_id == JWT.sub 的记录
教师只能访问被授权班级/学生
后台任务必须携带可信 owner_id
RAG evidence 必须携带 owner_id/visibility
```

当前实现尚未在所有 API 层落实该规则，详见主文档第 10、14 节。
