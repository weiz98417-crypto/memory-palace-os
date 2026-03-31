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
当系统发生非预期故障时，日志及 `SkillOutput` 应携带以下编码：

- `ERR_LLM_TIMEOUT`: 大模型接口响应超时。
- `ERR_JSON_MALFORMED`: LLM 返回的 JSON 格式无法被正则剥离。
- `ERR_WX_TOKEN_EXPIRED`: 企微 Access Token 刷新失败。
- `ERR_VDB_DISCONNECT`: 向量库连接中断或磁盘已满。

---
<div align="center">
  <p>Copyright © 2026 ZhouWei. Memory Palace OS 内部技术文档。</p>
</div>