# API、事件与状态机规范

版本：`M0-v0.1-draft`  
适用：现有 `/api/*` 与 M1 之后新增的领域对象

## 1. HTTP 通用约定

| 项目 | 约定 |
|---|---|
| 基础地址 | 本地开发默认 `http://127.0.0.1:8000`；前端通过环境配置注入 |
| 版本 | 现有兼容接口保留；新领域契约使用 `/api/v1/` 或在 Schema 中声明 `api_version` |
| 编码 | UTF-8；JSON 使用 `application/json`；上传使用 multipart/form-data |
| 时间 | ISO 8601 UTC，带时区，如 `2026-07-23T08:00:00Z`；前端显示时转换本地时区 |
| ID | 服务端生成 UUID/稳定业务 ID；客户端不得伪造资源主键 |
| 认证 | `Authorization: Bearer <token>`；匿名演示必须显式开启并隔离数据 |
| 追踪 | 请求返回 `X-Trace-ID`；客户端可传合法 `X-Request-ID`，服务端不得接受任意 trace 关联他人数据 |
| 幂等 | 有副作用的 POST 支持 `Idempotency-Key`；相同用户/作用域/键/请求指纹在 TTL 内返回同一结果 |
| 分页 | 默认 cursor 分页；兼容旧接口可使用 `limit`，服务端强制上限；返回 `items,next_cursor,has_more` |
| 排序 | 必须显式、稳定、可复现；默认 `created_at desc,id desc` |
| 过滤 | 只允许白名单字段和枚举；未知字段返回 400，不拼接原始 SQL |
| 重试 | 仅对明确的 408/429/502/503/504 或可重试任务状态；非幂等写操作不得盲重试 |
| 缓存 | 读取缓存必须绑定用户、组织、课程版本和权限范围；删除/发布/回滚后失效 |

## 2. 统一成功与错误信封

成功响应推荐：

```json
{
  "data": {},
  "meta": {
    "trace_id": "uuid",
    "api_version": "v1",
    "request_time": "2026-07-23T08:00:00Z"
  }
}
```

错误响应固定字段：

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "资源不存在或当前身份不可访问",
    "details": {},
    "retryable": false
  },
  "meta": {"trace_id": "uuid", "api_version": "v1"}
}
```

`message` 面向用户，不得回显 SQL、密钥、堆栈、私有文件路径或越权对象是否存在。调试细节写服务端结构化日志并由权限控制。

## 3. 关键对象契约

| 对象 | 必需字段 | 状态字段 | 所有权/版本 |
|---|---|---|---|
| `course` | `course_id,title,domain_id,objective` | `draft/review/published/retired` | 组织/创建者；语义版本 |
| `document` | `document_id,source_uri,content_hash,license,media_type` | `uploaded/parsing/indexed/failed/archived` | owner + scope；内容哈希 |
| `knowledge_point` | `kp_id,title,definition,prerequisites` | `draft/review/published/retired` | domain_pack + gold_version |
| `profile_snapshot` | `snapshot_id,student_id,dimensions,evidence_refs` | `created/used/superseded` | 学生本人/授权课程 |
| `task` | `task_id,type,input_ref,created_by` | `queued/running/paused/succeeded/failed/cancelled` | 创建者/组织 |
| `artifact` | `artifact_id,type,content,source_refs` | `draft/checking/needs_revision/approved/published/withdrawn` | 生成任务/版本 |
| `plan` | `plan_id,goal,constraints,node_refs` | `draft/confirmed/superseded/archived` | 学生或教师作用域 |
| `path` | `path_id,plan_id,nodes` | `draft/active/paused/completed/superseded` | 学生/课程 |
| `review` | `review_id,target_ref,checks,reviewer` | `pending/running/passed/failed/overridden` | 审核人/规则版本 |
| `decision_record` | `decision_id,candidates,selected,reasons` | `proposed/confirmed/executed/reverted` | trace + 输入快照 |
| `evaluation_run` | `run_id,case_version,model_config,raw_output` | `queued/running/completed/failed` | 评测者/数据版本 |

## 4. 事件信封

```json
{
  "event_id": "uuid",
  "event_type": "learning.quiz_answered",
  "schema_version": 1,
  "occurred_at": "2026-07-23T08:00:00Z",
  "actor": {"type": "student", "id": "student-demo"},
  "subject": {"type": "knowledge_point", "id": "rag-03"},
  "scope": {"organization_id": "local-demo", "course_id": "rag-course-v1"},
  "trace_id": "uuid",
  "payload": {},
  "evidence_refs": [],
  "privacy_class": "P2"
}
```

事件不可就地修改；纠正使用补偿事件。消费者必须按 `event_id` 幂等，接受未知字段，拒绝未知 `schema_version` 并记录死信。事件不得放入密码、API key、完整敏感身份或未脱敏模型上下文。

## 5. 事件命名

命名：`<bounded_context>.<object>_<past_tense>`，全小写下划线，领域前缀使用点分隔。示例：

| 领域 | 事件 |
|---|---|
| 身份 | `identity.user_registered`、`identity.role_changed` |
| 内容 | `content.document_uploaded`、`content.document_indexed`、`content.document_archived` |
| 画像 | `profile.snapshot_created`、`profile.diagnosis_completed` |
| Agent | `agent.run_started`、`agent.run_completed`、`agent.run_failed` |
| 产物 | `artifact.generated`、`artifact.quality_checked`、`artifact.published` |
| 学习 | `learning.resource_opened`、`learning.quiz_answered`、`learning.code_tests_passed`、`learning.delayed_retest_passed` |
| 决策 | `decision.path_proposed`、`decision.path_confirmed`、`decision.path_replanned` |
| 审计 | `audit.access_denied`、`audit.export_requested`、`audit.privacy_deleted` |
| 企业 | `enterprise.standard_published`、`enterprise.exemption_approved` |

## 6. 状态机

### 6.1 产物

```text
draft -> checking -> approved -> published -> withdrawn
                 \-> needs_revision -> checking
draft -> withdrawn（仅管理员/创建者在未发布前归档）
```

发布必须有审核记录、来源/许可证检查、版本号、受众范围和回滚目标。已发布版本不可直接编辑，只能创建新版本。

### 6.2 后台任务

```text
queued -> running -> succeeded
                  \-> failed -> queued（带幂等键重试）
                  \-> paused -> running/cancelled
queued/running/paused -> cancelled
```

失败必须写 `failure_code`, `retryable`, `last_checkpoint` 和 `trace_id`。重试不得重复创建产物或重复计入指标。

### 6.3 计划和路径

```text
plan: draft -> confirmed -> superseded/archived
path: draft -> active -> paused -> active
                         \-> completed
                         \-> superseded
```

重规划创建新版本并关联触发事件；不得覆盖已完成节点的历史证据。

### 6.4 审核和企业标准

```text
review: pending -> running -> passed/failed/overridden
standard: draft -> review -> published -> replaced -> retired
```

高风险标准不可通过普通 Agent 自动 `overridden`；必须有指定人工责任人和审计原因。

## 7. 兼容与废弃

旧接口保留兼容层，兼容层只负责字段映射，不创建第二套业务逻辑。新增字段默认可选；删除字段至少经历“标记废弃—观察—迁移—删除”四步。API、事件和数据库字段的废弃必须在 ADR 与迁移记录中登记。
