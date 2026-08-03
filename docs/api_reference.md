# 📖 内存宫殿 OS：内部接口与企微回调 API 手册 (V1.2.0)

本文档旨在规范 **Memory Palace OS** 内部组件间的通讯协议，以及与企业微信 (WeChat Work) 的回调交互标准。所有开发必须严格遵守此规范，以确保生产环境的稳定性。

---

## 1. 外部接入：企业微信 Webhook 回调
系统通过 `core/gateway.py` 暴露 HTTP 端点，接收企微服务器推送的加密 XML 报文。

### 1.1 接口定义
- **URL**: `http://<server_ip>:<port>/wechat/callback`
- **Method**: `POST`
- **内容类型**: `application/xml` (由腾讯侧推送)

### 1.2 回调校验 (鉴权)
每次 POST 请求都会携带以下 URL 参数，必须使用 `WXBizMsgCrypt` 进行摘要对比：
- `msg_signature`: 消息签名。
- `timestamp`: 时间戳。
- `nonce`: 随机数。

### 1.3 解密后的 JSON 结构 (内部消费)
网关层会将 XML 转换为标准 JSON，供调度器 `orchestrator.py` 使用：
| 字段名 | 类型 | 描述 |
| :--- | :--- | :--- |
| `FromUserName` | String | 发送消息的员工 ID (Userid) |
| `MsgType` | String | 消息类型：`text`, `image`, `voice`, `event` |
| `Content` | String | 文本内容 (仅在 MsgType 为 text 时有效) |
| `MsgId` | String | 64位消息唯一流水号，用于去重 |
| `AgentID` | Int | 企业应用 ID |

---

## 2. 调度核心：Orchestrator 契约
`orchestrator.py` 是系统的神经中枢，通过统一的 `dispatch` 函数处理任务流。

- **方法签名**: `async def dispatch(payload: Dict[str, Any]) -> None`
- **上下文注入**: 调度器会自动为每次请求生成一个 UUID 作为 `trace_id`。
- **状态流转**: 
  - `Router` -> `Target Agent` -> `Log Sink` -> `WeChat Reply`

---

## 3. 智能体统一输出协议 (SkillOutput)
所有 `skills/` 目录下的 Agent 必须通过 `SkillOutput` DTO (Data Transfer Object) 返回结果，禁止直接返回原始字符串或不规范的字典。

```json
{
  "success": true,               // 执行是否成功
  "reply_text": "最终答复文案",    // 呈现给一线员工的文字
  "action_taken": "router_jump", // 本次执行的具体业务动作标签
  "structured_data": {           // 附加业务元数据
    "severity": "P0",
    "need_audit": true,
    "reference_ids": ["HIST_001"]
  },
  "tokens_used": 450,            // 本次 LLM 调用消耗的 Token
  "latency_ms": 1250.8           // 接口总响应耗时
}
```

---

## 4. 工具集成层 (Tools API)

### 4.1 WeChat Client (主动推送)
- `send_text(to_user, content)`: 下发标准文本。
- `send_markdown(to_user, md_text)`: 结合 `SOP` 模板下发排版精美的指令。
- `send_textcard(to_user, title, desc, url)`: 下发带跳转按钮的高亮告警卡片。

### 4.2 SMS/Voice Client (紧急告警)
- `send_p1_alert(phones, event_desc)`: 下发 P1 级业务短信告警。
- `send_p0_critical(phones, event_desc)`: 触发 **短信 + 语音电话** 强制唤醒值班经理。

### 4.3 Vector Store (RAG 检索)
- `query_experience(text, top_k=3, threshold=0.75)`: 从 ChromaDB 召回历史案例。

---

## 5. 存储层查询标准 (DB Client)
系统采用 `SQLAlchemy` 进行持久化，主要模型标准如下：

| 表名 | 核心索引 | 用途 |
| :--- | :--- | :--- |
| `sop_documents` | `category` | 存储标准作业程序 (SOP) |
| `incident_logs` | `case_id`, `is_resolved` | 存储突发事件流水，供 Watcher 审计 |
| `audit_reports` | `audit_date` | 存储鹰眼巡检生成的每日合规报告 |

---

## 6. 错误码规范 (Error Codes)
正式接口错误统一返回结构化 `detail.code`、业务可读消息、下一步动作、`retryable` 和请求 `trace_id`。统一员工助手 MVP 新增或强化的错误码如下：

| 错误码 | HTTP | 含义 | 是否可重试 |
| :--- | :---: | :--- | :---: |
| `EVENT_NOT_FOUND` | 404 | 当前场地无权访问或不存在该事件 | 否 |
| `EVENT_CLOSE_BLOCKED` | 409 | 仍有任务、审批或受控动作未满足闭环条件 | 否 |
| `EVENT_RESOLUTION_INSUFFICIENT` | 422 | 闭环结果不足以说明实际处置与结果 | 否 |
| `EVENT_CLOSE_PERSISTENCE_FAILED` | 503 | 闭环证据写入失败，事件已补偿回处理中 | 是 |
| `EVENT_CLOSE_ROLLBACK_FAILED` | 500 | 闭环写入与补偿均未完整完成，需要人工核对 | 否 |
| `WATCHER_EVENT_CHECK_FAILED` | 502 | 事件级 Watcher 运行失败，不得伪造成功结果 | 是 |
| `EXPERIENCE_CANDIDATE_NOT_ELIGIBLE` | 409 | 事件未闭环或当前不具备候选生成资格 | 是 |
| `EXPERIENCE_CANDIDATE_RETRY_FAILED` | 503 | 经验候选重试未能完成 | 是 |

模型超时、401、熔断、JSON 解析失败和向量库不可用继续使用平台统一错误封装；失败响应不得返回假 Agent 结果、默认分数或空引用。

## 7. 新增审计与恢复声明

| 动作或记录 | 触发条件 | 权威证据 |
| :--- | :--- | :--- |
| `EVENT_CLOSE_DENIED` | 服务端闭环门禁拒绝 | `audit_logs` 与 `event_activities` |
| `EVENT_WATCHER_CHECK` | 事件级 Watcher 成功或失败 | `audit_logs`、`watcher_runs`、`watcher_findings` |
| `EVENT_CLOSED` | 闭环状态和证据均持久化成功 | `audit_logs`、`confirmed_events`、`event_activities` |
| `EXPERIENCE_CANDIDATE_CREATED` | 候选萃取成功且保持 `DRAFT / NOT_INDEXED` | `audit_logs`、`experience_candidates`、`event_activities` |
| `EXPERIENCE_CANDIDATE_GENERATION` | 闭环后的候选生成异常 | `audit_logs` 与候选尝试记录 |
| `EXPERIENCE_CANDIDATE_RETRY` | 管理员或经理从事件卷宗重试 | `audit_logs` 与 `experience_candidate_attempts` |
| App 启动恢复记录 | 每次正式 App lifespan 启动 | `runtime_recovery_runs`，通过 `GET /admin/recovery-runs` 只读查询 |

## 8. 消息处理与回复送达状态

`GET /api/v1/messages/{message_id}` 和员工会话历史会分别返回任务处理状态与回复送达状态。两者不能混用：Agent 产出成功但真实企微回复未送达时，消息不得显示为已完成。

| 字段 | 状态 | 含义 |
| :--- | :--- | :--- |
| `status` | `QUEUED / PROCESSING / RECOVERING / RETRYING` | 消息仍在排队、处理或自动恢复 |
| `status` | `COMPLETED` | Agent 结果已持久化，且当前渠道的送达条件已满足 |
| `status` | `RETRY_REQUIRED` | 自动恢复已耗尽，或真实企微缺少配置，需要人工处理后从原消息重试 |
| `delivery_status` | `PENDING` | 回复尚未完成渠道投递 |
| `delivery_status` | `PERSISTED` | Web 或企微模拟器回复已持久化，可由客户端恢复和轮询 |
| `delivery_status` | `DELIVERED` | 真实企微客户端已确认发送成功 |
| `delivery_status` | `FAILED` | 真实企微发送失败，系统自动重试或等待人工重试 |
| `delivery_status` | `CONFIGURATION_REQUIRED` | 真实企微回复配置缺失，管理员完成配置后重试原消息 |

每条助手回复使用 `assistant-reply:{message_id}` 作为投递幂等键。企微瞬时失败只重投已保存的回复，不重新执行 Agent 或重复创建业务结果。`delivery_error` 只返回脱敏后的稳定中文说明；凭据、原始异常和私有路径不得进入员工状态、投递日志或死信输出。

---
<div align="center">
  <p>Copyright © 2026 ZhouWei. Memory Palace OS 内部技术文档。</p>
</div>
