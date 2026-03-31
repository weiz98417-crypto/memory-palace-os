# 🏗️ Memory Palace OS 系统架构与流转设计白皮书 (V1.2.0)

本文件详述了 **Memory Palace OS** 的核心架构设计思路。系统采用四层解耦架构，旨在解决复杂景区/娱乐场所环境下，AI 处理突发事件的实时性、合规性与可追溯性问题。

---

## 1. 逻辑分层架构 (Layered Architecture)

系统由下至上分为四层，每一层都通过标准的接口（Contract）进行通讯。



### 1.1 接入层 (Access Layer / Gateway)
- **核心组件**: `core/gateway.py`
- **职责**: 负责对接企业微信 Webhook。执行 AES 加解密、XML 报文转换，并完成初步的消息去重（Deduplication）。
- **出口**: 将标准的 `user_payload` 推送至核心调度层。

### 1.2 核心调度层 (Core Engine)
- **核心组件**: `core/orchestrator.py`, `core/skill_base.py`
- **职责**: 系统的“脊柱”。维护 `OrchestrationContext`（上下文），控制 Agent 状态机流转。
- **任务**: 确保消息在 `Router` 识别意图后，能够准确送达对应的业务 Agent。

### 1.3 业务智能体矩阵 (Agent Skills)
- **核心组件**: 5 大智能体 (`Router`, `Commander`, `MemoryOps`, `Persona`, `Watcher`)
- **职责**: 系统的大脑。每个 Agent 负责特定的业务领域（分诊、指挥、记忆、演练、质检）。

### 1.4 基础设施与知识层 (Infrastructure & Knowledge)
- **核心组件**: `tools/`, `knowledge/`
- **职责**: 系统的“手脚”与“记忆”。包含 LLM 统一接口、ChromaDB 向量库、SQLAlchemy 关系库、企微推送通道。

---

## 2. 核心业务流转 (Message Flow)

### 2.1 实时交互流 (Real-time Logic Flow)
这是系统最常见的处理路径，通常在 2-5 秒内完成。

1.  **触发**: 员工在企微群发送：“一号门有人晕倒”。
2.  **网关**: `Gateway` 收到 XML，解密并转为 JSON，赋予唯一的 `trace_id`。
3.  **分诊**: `Orchestrator` 调用 `Router` Agent。
4.  **路由决策**: `Router` 识别意图为 `emergency_dispatch` (紧急分发)，严重等级 `P0`。
5.  **接力**: `Orchestrator` 实例化 `Commander`，并传入上下文。
6.  **执行**: `Commander` 结合 `knowledge/` 下的 SOP 规则生成三条指令。
7.  **推送**: 通过 `wechat_client` 将指令发回员工手机。
8.  **归档**: 整个过程存入 `IncidentLog`。



### 2.2 离线审计流 (Offline Audit Loop)
这是系统“铁面无私”的一面，独立于实时交互运行。

1.  **唤醒**: `scheduler.py` 每天凌晨定时唤醒 `Watcher` Agent。
2.  **捞取**: 从数据库拉取过去 24 小时所有 `is_resolved=False` 的工单。
3.  **审计**: `Watcher` 逐条阅读日志，比对 `settings.yaml` 里的超时红线。
4.  **告警**: 发现超时或员工违规，立即调用 `sms_client` 给值班经理打电话，并发送企微卡片。

---

## 3. RAG 知识检索增强流 (RAG Pipeline)

当 **MemoryOps** 介入时，系统执行以下语义检索路径：

1.  **Query 转向量**: 调用 `llm_wrapper` 将求助文本转换为 1536 维向量。
2.  **向量检索**: 在 ChromaDB 中进行余弦相似度计算。
3.  **阈值过滤**: 仅提取 `Similarity > 0.75` 的历史案例。
4.  **Prompt 注入**: 将检索到的案例注入到 `advice.txt` 的 `{{history_cases}}` 占位符中。
5.  **总结输出**: LLM 结合历史经验给出针对性的避坑指南。

---

## 4. 防御性设计 (Defensive Design)

- **JSON 防抖机制**: 全局采用正则剥离技术，应对 LLM 输出的脏数据。
- **Token 熔断**: 调度器限制单次交互最大 Agent 切换步数为 5 步，防止逻辑死循环。
- **并发锁**: `wechat_client` 采用 DCL (Double-Checked Locking) 确保高并发下 Token 刷新不踩踏。
- **降级保护**: 当 LLM 挂起或超时，系统自动回复“指挥部网络繁忙”，并同步触发短信告警通知人工介入。

---
<div align="center">
  <p>Memory Palace OS - 让每个指令都具备工业级的严肃性</p>
  <p>Copyright © 2026 ZhouWei</p>
</div>