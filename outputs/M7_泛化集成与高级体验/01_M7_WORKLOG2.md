# EduMatrix M7 WORKLOG2

## WL2-M7-20260728-002 - 受限垂直领域插件契约

- 状态：`PARTIAL`（M7-007/009）。
- 契约：新增 `edumatrix.domain-plugin.v1`，声明稳定插件/领域 ID、SemVer、许可、数据资产、受支持正式工件 checker 和白名单动作。
- 安全边界：插件是声明式数据包，不加载 Python；Schema 强制 `requires_network=false`、`requires_secrets=false`、`executable_code=false`，动作只允许校验数据、注册领域和注册 checker。
- 完整性：资产只能是安全相对路径，限制为 JSON/Markdown/CSV；验证文件存在、SHA-256、字节数，JSON 资产还必须可解析；路径穿越、重复资产、篡改和越权能力均拒绝。
- 验证：插件 2 项、xAPI/outbox 3 项、企业门禁 7 项合计 `12 passed`。
- 真实声明：测试构造的 robotics JSON 只用于验证契约，不是正式第二领域数据包，不能视为 M7-008 第二领域迁移通过。正式注册/卸载、兼容性矩阵、领域包 UI 和无复制迁移报告仍待实现。
- 时间：2026-07-28（Asia/Shanghai）。

## WL2-M7-20260728-001 - xAPI 映射与可重放企业集成出站箱

- 状态：`PARTIAL`（M7-005/006/009）。
- 正式对象：新增 `integration_deliveries`，保存组织、适配器类型/版本、目标、幂等键、内部来源对象、最小化 payload、哈希、状态、尝试次数、错误码、重试时间和投递时间。
- 迁移：新增 `20260728_011` 幂等建表与索引；空库顺序迁移和注册迁移治理测试均通过。
- xAPI：将正式学习事件映射为 actor/verb/object/result/context/timestamp，并保留内部事件 ID、课程和 Schema 版本；不复制聊天正文、答案或原始 Prompt。当前映射版本声明为 `xapi-1.0.3-map-v1`。
- 可靠性：同一组织/目标/内部事件幂等入队；外部失败只更新出站状态并指数退避，达到上限进入 dead letter，不回滚或修改本地学习事件；成功投递为终态。
- 验证：xAPI/outbox 3 项与企业门禁 7 项合计 `10 passed`；语法、空库迁移和迁移治理均通过。
- 当前问题：未连接真实 LRS、SSO、HR 或 LMS，也未验证具体客户字段和协议；本批只能声明服务层映射、模拟投递和队列语义，不能声明完整 xAPI/cmi5 或企业兼容。
- 当前问题：出站 worker、签名 Webhook、服务账号、速率/IP 治理、周期对账、人工修复、cmi5 启动/退出语义尚未实现。
- 时间：2026-07-28（Asia/Shanghai）。
