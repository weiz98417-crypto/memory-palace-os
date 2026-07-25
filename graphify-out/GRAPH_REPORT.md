# Graph Report - memory-palace-os  (2026-07-25)

## Corpus Check
- 224 files · ~110,195 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2121 nodes · 3651 edges · 118 communities (104 shown, 14 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 270 edges (avg confidence: 0.59)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `5f25cf6f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- hot_reload.py
- ContextCompressor
- health.py
- CircuitBreaker
- TaskGraph
- PersonaExtractSkill
- KeywordMatcher
- SafeFileOps
- AppContainer — Handwritten DI Container (dataclass + lazy property)
- SkillOutput
- metrics/__init__.py
- ConfigManager
- Workspace
- metrics.py
- knowledge/db_client.py
- AppContainer
- gateway.py
- PermissionEngine
- tool_executor.py
- env_validator.py
- WeChatWorkClient
- SessionStateManager
- Orchestrator
- app_settings.py
- Stabilization Hardening Design Document
- Demo Full Feast Initiative (expanded 6-tab console covering all core functions)
- SkillValidationError
- AgentMemoryScope
- WatcherSkill
- admin.py
- WXBizMsgCrypt
- main.py
- Request
- orchestrator.py
- PalaceVectorStore
- llm_wrapper.py
- PersonaSkill
- VersionManager
- Persona Expert Agent (Multi-Turn Roleplay with State Tracking)
- tools/db_client.py
- ContextTriggerSkill
- v1/schemas.py
- Orchestrator
- tools/__init__.py
- memory_ops/skill.py
- get_permission_engine
- Phase 1: 能上线
- CommanderSkill
- EmbeddingClient
- get_vector_client
- Logic Entry Structure: trigger+behavior+reason
- BaseAgentSkill
- test_orchestrator.py
- RedisStreamsQueue
- invoke.py
- router/skill.py
- embedding_client.py
- TestMemoryRetrieval
- watcher/skill.py
- push_logger.py
- skills.py
- skills/__init__.py
- TodoWriteSkill
- wechat_crypto.py
- demo.sh
- FastAPI
- PostgresDBClient
- v2/schemas.py
- demo_send_message
- logger_config.py
- Watcher Agent
- DI Container (10 services, architecture C)
- run.sh
- v1/__init__.py
- v2/__init__.py
- memory_palace/__init__.py
- static/__init__.py
- Persona Agent
- TodoWrite Agent
- Core Pipeline Spec (Landing Refactor)
- Lazy Init Spec (Landing Refactor)
- Windows Compatibility Spec (Landing Refactor)
- memory-palace-os
- InMemoryQueue
- MessageQueueProtocol
- 👴 智能体说明书：知识分身专家 (Persona_Expert_Agent)
- explore.md
- MemoryPalaceUser
- proposal.md
- ADDED Requirements
- ADDED Requirements
- check_connection
- AsyncDBClientProtocol
- 🚨 智能体说明书：现场指挥官 (Commander_Agent)
- set_venue_id
- Tasks: 技能层稳定化
- Requirement: API Key authentication
- Requirement: Knowledge entry management
- Requirement: Multi-model fallback chain
- ADDED Requirements
- data_seeder.py
- ADDED Requirements
- ADDED Requirements
- ADDED Requirements
- init_database
- test_core_pipeline.py
- ADDED Requirements
- Requirement: Rate limiting middleware
- Requirement: Secrets validation at startup
- demo-console/tasks.md
- design.md
- secrets.py
- cache.py
- .query_experience

## God Nodes (most connected - your core abstractions)
1. `SkillOutput` - 69 edges
2. `Orchestrator` - 56 edges
3. `CircuitBreaker` - 42 edges
4. `AppContainer` - 40 edges
5. `PersonaExtractSkill` - 35 edges
6. `ConfigManager` - 31 edges
7. `PermissionEngine` - 29 edges
8. `BaseAgentSkill` - 28 edges
9. `WXBizMsgCrypt` - 28 edges
10. `SkillValidationError` - 26 edges

## Surprising Connections (you probably didn't know these)
- `Real-Time Message Processing Flow` --semantically_similar_to--> `30-Second Emergency Response (P0)`  [INFERRED] [semantically similar]
  docs/architecture.md → README.md
- `Claude Development Guidelines` --semantically_similar_to--> `Lazy Loading Factory Pattern`  [INFERRED] [semantically similar]
  CLAUDE.md → openspec/changes/archive/2026-05-09-landing-refactor/design.md
- `TestContainerPermissions` --uses--> `AppContainer`  [INFERRED]
  tests/integration/test_permissions.py → src/memory_palace/core/container.py
- `TestPermissionEngine` --uses--> `AppContainer`  [INFERRED]
  tests/integration/test_permissions.py → src/memory_palace/core/container.py
- `test_router_to_commander_flow()` --indirect_call--> `Orchestrator`  [INFERRED]
  tests/integration/test_agent_handoff.py → src/memory_palace/core/orchestrator.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **OpenSpec Workflow Lifecycle (Propose -> Apply -> Archive)** — claude_skills_openspec_propose_SKILL_openspec_propose, claude_skills_openspec_apply_change_SKILL_openspec_apply, claude_skills_openspec_archive_change_SKILL_openspec_archive, claude_skills_openspec_explore_SKILL_openspec_explore [EXTRACTED 1.00]
- **Memory Palace OS Core Agent Matrix (Router -> Commander -> MemoryOps -> Persona -> Watcher)** — README_router_agent, README_commander_agent, README_memory_ops_agent, README_persona_agent, README_watcher_agent, README_orchestrator [EXTRACTED 1.00]
- **Four-Phase Architecture (Context Tier -> Permission Engine -> Task Graph -> Workspace Isolation)** — README_context_tier, README_permission_engine, README_task_graph, README_workspace_isolation [EXTRACTED 1.00]
- **Six-Phase Container Architecture (C-level Design)** — concept_app_container, concept_context_tier_activation, concept_agent_memory_activation, concept_permission_engine, concept_tool_executor, concept_task_graph_reload, concept_workspace_manager [EXTRACTED 1.00]
- **Tool Execution Middleware Chain** — concept_tool_executor, concept_permission_engine, concept_tool_middleware_chain [EXTRACTED 1.00]
- **Lazy Initialization Factory Pattern (get_xxx_client)** — concept_get_vector_client, concept_get_embedding_client, concept_get_wechat_client, concept_scheduler_delayed_init [EXTRACTED 1.00]
- **Skill Stabilization Capabilities (DEMO_MODE + Secure Defaults + Route Fix + Test Health + MemoryOps fix + Watcher)** — openspec_changes_archive_2026-05-11-skill-stabilization_specs_demo-mode_spec_demo_mode, openspec_changes_archive_2026-05-11-skill-stabilization_specs_secure-defaults_spec_secure_defaults, openspec_changes_archive_2026-05-11-skill-stabilization_specs_route-fix_spec_route_fix, openspec_changes_archive_2026-05-11-skill-stabilization_specs_test-health_spec_test_health, openspec_changes_archive_2026-05-11-skill-stabilization_design_memory_ops_vector_api_fix, openspec_changes_archive_2026-05-11-skill-stabilization_design_watcher_cron_activation [EXTRACTED 1.00]
- **Demo Full Feast Capabilities (Auto-Play + Pipeline Animation + Report Export + PersonaExtract + Todo + Knowledge Seed + Watcher Log)** — openspec_changes_demo-full-feast_specs_demo-auto-play_spec_demo_auto_play, openspec_changes_demo-full-feast_specs_demo-pipeline-animation_spec_demo_pipeline_animation, openspec_changes_demo-full-feast_specs_demo-report-export_spec_demo_report_export, openspec_changes_demo-full-feast_proposal_persona_extract_interview_demo, openspec_changes_demo-full-feast_proposal_todo_decompose_demo, openspec_changes_demo-full-feast_proposal_knowledge_seed_data, openspec_changes_demo-full-feast_proposal_watcher_log_demo [EXTRACTED 1.00]
- **Demo Console Backend Endpoints (gateway demo_router serves stats, tasks, and console UI)** — openspec_changes_demo-console_design_gateway_demo_router, openspec_changes_demo-console_specs_demo-stats_spec_demo_stats_endpoint, openspec_changes_demo-console_specs_demo-tasks_spec_demo_tasks_endpoint, openspec_changes_demo-console_specs_demo-console_spec_demo_console_ui [EXTRACTED 1.00]
- **Demo Mode Feature Bundle (scenario switch + interview + todo decompose + watcher log)** — openspec_changes_demo_full_feast_specs_knowledge_seed_data_spec, openspec_changes_demo_full_feast_specs_persona_interview_demo_spec, openspec_changes_demo_full_feast_specs_todo_decompose_demo_spec, openspec_changes_demo_full_feast_specs_watcher_log_demo_spec, openspec_changes_demo_full_feast_tasks [EXTRACTED 1.00]
- **System Stabilization Hardening Bundle (6 concurrent fixes)** — openspec_changes_stabilization_hardening_specs_llm_output_sanitization_spec, openspec_changes_stabilization_hardening_specs_wechat_reply_loop_spec, openspec_changes_stabilization_hardening_specs_dead_code_removal_spec, openspec_changes_stabilization_hardening_specs_di_container_unification_spec, openspec_changes_stabilization_hardening_specs_queue_config_alignment_spec, openspec_changes_stabilization_hardening_specs_test_suite_resurrection_spec, openspec_changes_stabilization_hardening_proposal, openspec_changes_stabilization_hardening_design, openspec_changes_stabilization_hardening_tasks [EXTRACTED 1.00]
- **Scenic Area Operations Demo System (landing page + agent registry + seed data)** — prototype_index_html, src_memory_palace_config_registry_yaml, scripts_seed_data_daily_yaml, scripts_seed_data_emergency_yaml, concept_p0_event_simulation, concept_intent_keyword_routing [INFERRED 0.85]
- **Incident Detection-to-Resolution Pipeline (context_trigger -> commander -> watcher escalation)** — src_memory_palace_skills_context_trigger_two_stage_trigger_system, src_memory_palace_skills_commander_config_commander_agent, src_memory_palace_config_settings_yaml_escalation_chain [INFERRED 0.75]
- **Knowledge Extraction-to-Utilization Cycle (persona_extract interviews for logic_entries consumed by persona agent)** — src_memory_palace_skills_persona_extract_config_persona_extract_skill, src_memory_palace_skills_persona_extract_logic_entries_pattern, src_memory_palace_skills_persona_config_persona_expert_agent [EXTRACTED 1.00]
- **Safety Guard Pattern (commander mandatory_safety_check + memory_ops anti_hallucination + persona anti_jailbreak)** — src_memory_palace_skills_commander_config_commander_agent, src_memory_palace_skills_memory_ops_anti_hallucination_guard, src_memory_palace_skills_persona_anti_jailbreak_defense [INFERRED 0.75]
- **Persona Extraction Pipeline: Interview Guide + Question Prompts + Invoke Pattern** — src_memory_palace_skills_persona_extract_references_interview_guide, src_memory_palace_skills_persona_extract_prompts_extract_question_4, src_memory_palace_skills_persona_extract_prompts_extract_summary, src_memory_palace_skills_persona_extract_prompts_invoke, concept_interview_five_question_framework, concept_logic_entry_trigger_behavior_reason [EXTRACTED 1.00]
- **Watcher Audit System: Config SLA Timeouts + Audit Prompt + Skill Spec + Soul Philosophy** — src_memory_palace_skills_watcher_config, src_memory_palace_skills_watcher_prompts_audit, src_memory_palace_skills_watcher_skill, src_memory_palace_skills_watcher_soul, concept_sla_timeout_guardrails, concept_sop_compliance_audit [EXTRACTED 1.00]
- **Frontend Admin Ecosystem: Main OS + Admin Panel + Demo Console sharing API endpoints** — static_index, static_admin_frontend, static_demo_console, concept_persona_digital_twin, concept_memory_palace_strategy_pipeline [INFERRED 0.85]

## Communities (118 total, 14 thin omitted)

### Community 0 - "hot_reload.py"
Cohesion: 0.06
Nodes (41): calculate_content_hash(), calculate_file_hash(), FileChange, FileChangeType, get_hot_reload_manager(), get_reload_history(), get_skill_content(), get_skill_version() (+33 more)

### Community 1 - "ContextCompressor"
Cohesion: 0.08
Nodes (33): ColdNarrative, ContextCompressor, ContextTier, HotMessage, Any, Enum, 三层上下文压缩系统 (Three-Tier Context Compression) — STUB: Phase 1，待激活  架构设计: - Tier 0 (, 三层上下文压缩管理器      工作流程:     1. 新消息到达 -> 加入 Hot 层     2. Hot 层溢出 -> 最老批次 evict -> 调 (+25 more)

### Community 2 - "health.py"
Cohesion: 0.07
Nodes (31): aggregate_status(), BaseHealthChecker, check_specific(), CheckStatus, create_health_response(), DatabaseHealthChecker, DependencyCheckResult, get_health_registry() (+23 more)

### Community 3 - "CircuitBreaker"
Cohesion: 0.05
Nodes (40): CircuitBreaker, CircuitOpenError, CircuitState, Any, Enum, Exception, circuit_breaker.py · LLM 调用熔断器 ===================================== 实现经典三态熔断器, 通过熔断器调用异步函数。          CLOSED    → 正常调用，记录成功/失败         OPEN      → 直接抛 Circui (+32 more)

### Community 4 - "TaskGraph"
Cohesion: 0.06
Nodes (25): get_task_graph(), Any, Enum, str, 任务依赖图 (Task Graph)  核心职责: 1. 管理任务的生命周期 (PENDING -> RUNNING -> DONE/FAILED) 2. 支持, 创建新任务          Args:             session_id: 会话 ID             description: 任务描述, 获取可执行的任务 (依赖已满足)          Args:             session_id: 会话 ID             limit:, 标记任务开始执行          Args:             task_id: 任务 ID             agent_name: 执行 Ag (+17 more)

### Community 5 - "PersonaExtractSkill"
Cohesion: 0.06
Nodes (24): main(), PersonaExtractTester, persona_extract skill - 老员工经验萃取专家, PersonaExtractSkill, Any, 继续访谈：解析回答，决定是追问还是进入下一题, 完成访谈：汇总所有条目，存入 personas 表, 将不同格式的条目统一转换为 {trigger, behavior, reason} (+16 more)

### Community 6 - "KeywordMatcher"
Cohesion: 0.09
Nodes (17): Pattern, ContextTriggerTester, main(), 批量测试          Args:             file_path: 每行一条消息的文本文件路径, 查看某次推送的完整上下文          Args:             push_log_id: 推送日志 ID, ContextTrigger 调试工具      提供以下功能：     1. 单条消息测试 (--test)     2. 批量消息测试 (--batch), 测试单条消息          Returns:             {                 "message": str,, KeywordCategory (+9 more)

### Community 7 - "SafeFileOps"
Cohesion: 0.07
Nodes (23): get_workspace_file_ops(), is_path_traversal(), Path, 安全文件操作 (Safe File Operations)  核心职责: 1. 封装文件读写操作，自动限制在工作区内 2. 防止路径遍历攻击 3. 提供异步文件, 写入文件          Args:             relative_path: 相对路径             content: 文件内容, 追加写入          Args:             relative_path: 相对路径             content: 追加内容, 列出目录内容          Args:             relative_path: 相对路径          Returns:, 删除文件          Args:             relative_path: 相对路径          Returns: (+15 more)

### Community 8 - "AppContainer — Handwritten DI Container (dataclass + lazy property)"
Cohesion: 0.08
Nodes (45): AgentMemory Activation — Scoped Context per Agent, AppContainer — Handwritten DI Container (dataclass + lazy property), Skill Registration in Lifespan Only, AgentMemory.build_scoped_context() — Per-Agent Field Filter, ContextTier.build_tiered_context() — Three-Tier Builder, Config Module Rename (config/init.py → config/config_manager.py), AppContainer.override() / .reset() — Mock Injection, ContextTier Activation — Hot/Warm/Cold Tiers (+37 more)

### Community 9 - "SkillOutput"
Cohesion: 0.08
Nodes (23): 核心引擎层 (Core Engine Layer) - __init__.py ========================================, 核心引擎层 (Core Engine Layer)  本包为 Memory Palace OS 提供底层的运行时基础设施，涵盖： 1. 企微 Webhoo, BaseModel, 智能体核心抽象基类 (Agent Skill Base)  本模块定义了系统中所有智能体（Router, Commander, MemoryOps 等）的最, 工业级标准输出结构。     强制所有子类智能体必须以此统一的强类型格式，将结果返回给调度中枢 (Orchestrator)。     任何非该结构的返回值, SkillOutput, 智能体转办集成测试 (Integration Test for Agent Handoff)  Copyright (c) 2026 ZhouWei & Tea, 用户报告紧急事件 → Router → Commander。 (+15 more)

### Community 10 - "metrics/__init__.py"
Cohesion: 0.07
Nodes (19): callable, AlertingManager, get_alerting_manager(), alerting.py - Prometheus alerting rules for Memory Palace OS, 发送告警通知（同时写入 metrics 和触发处理函数）, resolve_alert(), send_alert(), AgentMetricsCollector (+11 more)

### Community 11 - "ConfigManager"
Cohesion: 0.10
Nodes (12): ConfigManager, ConfigSubscriber, get_config(), Any, config/__init__.py · 全局配置加载器 (Enhanced) =======================================, 应用环境变量覆盖          支持的格式：             MEMORY_PALACE_LLM_DEFAULT_MODEL=gpt-4o, 支持点号语法的配置读取          用法：             config.get('llm.default_model'), 设置配置值          用法：             config.set('llm.default_model', 'gpt-4') (+4 more)

### Community 12 - "Workspace"
Cohesion: 0.08
Nodes (17): get_workspace_manager(), Any, Path, 工作区隔离 (Workspace Isolation) — STUB: Phase 4，待激活  核心职责: 1. 为每个复杂任务创建独立的隔离工作目录 2., 销毁工作区          Args:             archive: 是否先存档          Returns:             存档, 打包存档工作区          Returns:             存档文件路径, 验证路径在工作区内 (防止路径遍历)          Args:             target_path: 目标路径          Returns, 工作区管理器 (全局单例)      负责工作区的创建、销毁、查询 (+9 more)

### Community 13 - "metrics.py"
Cohesion: 0.08
Nodes (21): CollectorRegistry, metrics_endpoint(), Prometheus 指标端点     - /metrics 由 Prometheus 主动抓取, AsyncMetricsCollector, get_metrics_registry(), init_metrics(), MetricsConfig, MetricsRegistry (+13 more)

### Community 14 - "knowledge/db_client.py"
Cohesion: 0.10
Nodes (28): Connection, list_sessions(), get_message(), get_session(), list_messages(), list_sessions(), AsyncDBClient, _build_memory_content() (+20 more)

### Community 15 - "AppContainer"
Cohesion: 0.06
Nodes (25): get_scoped_context_builder(), 获取全局 Scoped Context 构造器, AppContainer, AppContainer — 轻量依赖注入容器  设计原则： - 零外部依赖，手写 dataclass + 懒加载 @property - 每个 propert, 注入 Mock 实例用于测试。e.g. container.override(llm_client=mock_llm), 清除所有 override 和缓存，恢复原始行为。, DI Container 集成测试  验证：AppContainer 懒加载、override Mock 注入、reset 恢复、Orchestrator 使用, total_budget=5 时 Hot 层最多 5 条 (+17 more)

### Community 16 - "gateway.py"
Cohesion: 0.06
Nodes (39): load_scenario(), Demo seed data loader. Loads scenario YAMLs into in-memory cache + SQLite.  Usag, Load seed data for a scenario., add_knowledge(), APIInfoResponse, APIVersion, demo_get_result(), demo_kb_reindex() (+31 more)

### Community 17 - "PermissionEngine"
Cohesion: 0.08
Nodes (18): IntEnum, ApprovalRequest, PermissionEngine, Any, 权限引擎 (Permissions Engine)  核心职责: 1. 定义工具敏感级别 (Level 0/1/2) 2. 在工具调用前插入权限检查 Hook, 检查权限并执行工具          Args:             tool_name: 工具名称             args: 工具参数, 审批通过          Args:             approval_id: 审批单 ID             reviewer: 审批人, 审批拒绝          Args:             approval_id: 审批单 ID             reviewer: 审批人 (+10 more)

### Community 18 - "tool_executor.py"
Cohesion: 0.06
Nodes (30): EmergencyNotifier, Any, 紧急通讯组件 (Emergency SMS/Voice Client)  核心特性： 1. 异步非阻塞发送：使用 ThreadPoolExecutor，防, 下发 P0 级致命事件告警（短信 + 连环语音呼叫）, 发送告警通知（便捷函数）      Args:         message: 告警消息         level: 告警级别 (P0/P1/P2/, 底层同步发短信逻辑（此处为云厂商 SDK 占位）, # TODO: 此处替换为真实的 Aliyun/Tencent SDK 调用, 底层同步打语音电话逻辑（此处为云厂商 SDK 占位） (+22 more)

### Community 19 - "env_validator.py"
Cohesion: 0.09
Nodes (14): _auto_validate(), EnvRule, EnvValidator, get_validator(), Any, Enum, str, env_validator.py · 环境变量验证器 (Fail-Fast) ======================================== (+6 more)

### Community 20 - "WeChatWorkClient"
Cohesion: 0.08
Nodes (16): Any, 企业微信 API 工业级封装 (WeChat Work Client) - 异步版本  核心变更： 1. 使用 httpx.AsyncClient 替代, 下发 Markdown 消息 (异步版本), 发送确认卡片消息（企业微信交互卡片）          卡片包含：         - 事件摘要         - 两个按钮：「一键确认」「补充说明」, 企业微信服务端 API 客户端 (异步版本), 获取企微 Access Token (异步版本)。         采用 DCL (Double-Checked Locking) 机制，适配协程并发模型。, 底层消息发送引擎 (异步版本)，包含针对企微特定错误码的自愈逻辑, WeChatWorkClient (+8 more)

### Community 21 - "SessionStateManager"
Cohesion: 0.12
Nodes (16): AgentTurn, ConversationStage, Any, Enum, str, 会话状态管理器 (Session State Manager)  核心职责： 1. 用户会话生命周期管理：跟踪用户与系统的多轮交互状态 2. Agent, 生成会话 ID：user_id + 时间戳, 获取或创建用户会话                  Args:             user_id: 企微用户 ID             fo (+8 more)

### Community 22 - "Orchestrator"
Cohesion: 0.09
Nodes (33): Skill Registration Center, WeChat Crypto Module (WXBizMsgCrypt), Claude Development Guidelines, ChromaDB Vector Store, Commander Agent, Context Tier System (Hot/Warm/Cold), 30-Second Emergency Response (P0), Gateway (+25 more)

### Community 23 - "app_settings.py"
Cohesion: 0.12
Nodes (18): reload_config(), AppSettings, Config, get_settings(), LLMSettings, MetricsSettings, BaseModel, QueueSettings (+10 more)

### Community 24 - "Stabilization Hardening Design Document"
Cohesion: 0.11
Nodes (29): demo_knowledge ChromaDB Collection, Demo Scenario Switching (daily/emergency), Intent Keyword Routing Table, Core Message Pipeline (receive->queue->route->agent), OpenSpec Spec-Driven Schema, P0 Event Simulation Overlay, sanitize_llm_output() Centralized Utility, Strangler Fig Pattern for DI Migration (+21 more)

### Community 25 - "Demo Full Feast Initiative (expanded 6-tab console covering all core functions)"
Cohesion: 0.08
Nodes (28): FastAPI StaticFiles mount order (StaticFiles after include_router to prevent 307), Landing Refactor (prerequisite: lazy loading, DB init, core chain), LLMClient.ask() DEMO_MODE check (os.environ DEMO_MODE=true returns mock LLMResponse), MemoryOps vector_client.search() to query_experience() API fix, Watcher Cron Activation (10:00/20:00 cron job, manual trigger on start), Skill Stabilization Initiative (from 'runnable' to 'robust'), DEMO_MODE Capability (mock LLM, no API key needed), Route Fix (/admin and /api/v1/skills 307 redirect) (+20 more)

### Community 26 - "SkillValidationError"
Cohesion: 0.12
Nodes (9): Exception, 业务级校验异常。     当流入智能体的上下文 (Context) 缺少必要字段或脏数据时抛出。     此异常不会触发系统熔断报警，只会优雅阻断当前调用。, SkillValidationError, LLM 调用异常时返回 success=False, 缺少 goal 字段应抛出 SkillValidationError, 缺少 session_id 字段应抛出 SkillValidationError, LLM 返回空内容时返回 success=False, LLM 返回非列表 JSON 时返回 success=False (+1 more)

### Community 27 - "AgentMemoryScope"
Cohesion: 0.12
Nodes (13): AgentMemoryScope, AgentMemoryTurn, get_agent_memory_scope(), Any, Agent 内存隔离模块 (Agent Memory Isolation) — STUB: Phase 1，待激活  核心职责: 1. 为每个 Agent 维护, 获取指定 Agent 的对话历史          返回格式兼容 OpenAI Message:         [{"role": "user", "cont, 设置共享上下文          用于: Router -> Commander 传递 case_id, severity 等必要信息, Scoped Context 构造器      核心功能:     1. Router 输出仅作为分发元数据，不原封传递给下游     2. 每个 Agent (+5 more)

### Community 28 - "WatcherSkill"
Cohesion: 0.11
Nodes (12): 定时任务引擎 (System Scheduler)  职责： 1. 管控主动型智能体（如：鹰眼巡检专家 Watcher）的触发时机。 2. 维护系统级定, 添加一次性延迟任务（如：30分钟后如果没有闭环，则触发某逻辑）, 鹰眼巡检回调。由 APScheduler 在线程中调用。, 工业级异步定时任务管理器 (基于 APScheduler), _run_watcher_callback(), TaskScheduler, Any, 鹰眼巡检专家：负责后台定时巡检、SOP 合规性审查与超时工单追办 (异步版本)。 (+4 more)

### Community 29 - "admin.py"
Cohesion: 0.11
Nodes (22): admin_stats(), continue_interview(), create_event(), create_persona(), EventCreateRequest, finalize_interview(), InterviewContinueRequest, InterviewFinalizeRequest (+14 more)

### Community 30 - "WXBizMsgCrypt"
Cohesion: 0.14
Nodes (11): Exception, PKCS7 填充         企微使用 AES-256-CBC，块大小 32 字节, AES-256-CBC 加密（符合企业微信协议）。         加密结构: random(16B) + msg_len(4B big-endian) + m, AES-256-CBC 解密（符合企业微信协议）。         加密结构: random(16B) + msg_len(4B big-endian) + m, 企微管理后台配置 Webhook URL 时触发的验签接口（GET 请求）。          :param msg_signature: 企微传递的签名, 解密接收到的企微消息（POST 请求）。          :param encrypt_xml:   XML 字符串（包含 <Encrypt> 节点）, 加密要发送的回复消息（被动回复 / 回调响应）。          :param reply_xml: 要发送的回复 XML 原文         :param, 企业微信消息加解密类      初始化参数：       token:         企微后台配置的回调 Token       encoding_aes_k (+3 more)

### Community 31 - "main.py"
Cohesion: 0.08
Nodes (25): health_check(), lifespan(), memory-palace-os · 主入口 ======================== 职责：   1. 启动 FastAPI 应用，挂载企微 W, Kubernetes / Docker 健康探针端点。     返回队列积压深度，便于运维监控。, 启动阶段：拉起队列消费者 + 定时任务调度器     关机阶段：等待队列排空（最多 30 秒）后优雅退出      [Phase 3] 新增:, create_limiter(), Rate limiting middleware using slowapi (Redis backend in prod, in-memory for dem, Create a rate limiter instance. Uses Redis in production, memory in demo. (+17 more)

### Community 32 - "Request"
Cohesion: 0.15
Nodes (14): HTTPAuthorizationCredentials, Request, Authentication dependency. Pass to protected endpoints via Depends(require_auth), require_auth(), _check_auth(), demo_get_stats(), demo_kb_add(), get_queue_status() (+6 more)

### Community 33 - "orchestrator.py"
Cohesion: 0.17
Nodes (7): orchestrator.py · 多智能体协作中枢 ====================================================, update_sla_response(), 情境触发集成测试 (Context Trigger Integration Test)  验证：Stage1 关键词命中 → ContextTrigger 判断, 紧急关键词命中 → 直接路由到 Commander，跳过 Router, 非紧急消息：ContextTrigger 不触发 → 走 Router 正常路由, TestContextTrigger, 路由分发集成测试 (Routing Integration Test)  验证：非紧急消息通过 Router 正常路由到 Persona/PersonaExtr

### Community 34 - "PalaceVectorStore"
Cohesion: 0.20
Nodes (7): PalaceVectorStore, _make_test_vs(), MockEmbeddingFunction, 向量检索单元测试 (Unit Test for Vector Store)  使用 mock embedding 绕过 OpenAI API 依赖。  Copy, 写入后 query_experience 可以召回, query_experience 返回正确的数据结构, TestVectorStore

### Community 35 - "llm_wrapper.py"
Cohesion: 0.15
Nodes (14): 情境触发专家智能体 (Context Trigger Skill Implementation)  对应 docx 中描述的两阶段事件触发系统： - Stage, 技能注册装饰器。      用法：         @register_skill("router")         class RouterSkill(Ba, register_skill(), 老员工经验萃取专家智能体 (Persona Extract Skill Implementation)  对应 PRD 中描述的结构化访谈萃取系统（F-013）, Any, 工业级大语言模型客户端封装 (LLM Wrapper) - 异步版本  核心变更： 1. OpenAI 客户端从 `OpenAI` 改为 `AsyncOp, 工业级 JSON 解析器 (异步版本)：         注：JSON 解析本身是 CPU 密集型，但为保持与 ask() 的调用一致性，提供 async 接, 注册一个消毒 schema，供 sanitize_llm_output 按名称调用。 (+6 more)

### Community 36 - "PersonaSkill"
Cohesion: 0.14
Nodes (10): PersonaSkill, Any, 知识分身专家智能体 (Persona Skill Implementation) - 异步版本  核心变更： 1. 核心执行方法添加 async/await 2, 知识分身专家：负责深度的拟人化交互、模拟面试审查或复杂政策咨询 (异步版本)。, 加载分身人设 Prompt (对应项目树中的 interview.txt), 工业级滑动窗口机制 (Sliding Window Context):         将最近的 N 轮对话历史格式化为字符串，注入到 Prompt 中，赋予大, persona_agent(), 滑动窗口截断测试 (Unit Test for Persona Context)  工业级测试要点： 1. 边界值测试：对话轮数为 N-1, N, N+1 (+2 more)

### Community 37 - "VersionManager"
Cohesion: 0.14
Nodes (9): APIChange, APIEndpoint, APIVersion, APIVersionStatus, Any, Enum, str, api_versions.py · API 版本路由映射表 ================================================= (+1 more)

### Community 38 - "Persona Expert Agent (Multi-Turn Roleplay with State Tracking)"
Cohesion: 0.14
Nodes (19): Escalation Chain (commander -> watcher -> admin), Global Runtime Configuration (settings.yaml v1.2.0), Skills Router Configuration (regex-first + semantic fallback), SLA Policy (P0-P4 Priority Tiers), Commander Agent (Emergency Incident Dispatcher), Emergency Dispatch SOP (P0/P1 Life-Safety Protocol), Context Trigger Skill (Two-Stage Event Detection), Two-Stage Trigger System (Stage1 Keywords + Stage2 LLM) (+11 more)

### Community 39 - "tools/db_client.py"
Cohesion: 0.20
Nodes (7): Session, DatabaseManager, Any, Database Client (SQLAlchemy ORM) - for seed data & migration. For runtime queri, 专为 Watcher(鹰眼) Agent 提供的数据访问对象, 提供事务范围的会话上下文管理器。         业务层只需要: with db.session_scope() as session:         无, WatcherDAO

### Community 40 - "ContextTriggerSkill"
Cohesion: 0.14
Nodes (11): 写入推送日志      Returns:         push_id: 生成的推送日志ID, write_push_log(), context_trigger skill, ContextTriggerSkill, Any, 情境触发专家：负责对消息进行两阶段判断。      Stage1（关键词极速预过滤）：       - 使用 TRIGGER_KEYWORDS 和 EXCLUD, 触发 WeChat 推送 + 延迟确认卡片          流程：         1. 立即发送事件推送卡片         2. 延迟 confirm_d, 延迟发送确认卡片（协程任务）          Args:             delay_seconds: 延迟秒数 (+3 more)

### Community 41 - "v1/schemas.py"
Cohesion: 0.19
Nodes (15): BackgroundTasks, health_check(), queue_status(), create_message(), get_message(), v1/endpoints/messages.py - Message endpoint, 提交用户消息（异步处理，返回 message_id）, ErrorResponse (+7 more)

### Community 42 - "Orchestrator"
Cohesion: 0.14
Nodes (13): Orchestrator, Any, 路由决策          集成 ContextTrigger 两阶段过滤：         1. 先调用 ContextTrigger 进行 Stage, 多智能体协作中枢     负责协调 Router、Commander、MemoryOps、Persona 等 Agent      [M2] 接受 App, 将 intent 映射到目标 Agent          Args:             intent: Router 返回的 intent 类型, 默认路由          Args:             payload: 消息载荷          Returns:, 执行目标 Agent          [升级] 支持两种上下文模式:         - legacy_mode: 原有的 flat context (, 处理消息          Args:             payload: 消息载荷          Returns: (+5 more)

### Community 43 - "tools/__init__.py"
Cohesion: 0.27
Nodes (14): datetime, tools/__init__.py - 工具集成层导出, calculate_elapsed_minutes(), format_for_log(), get_now(), get_relative_time_desc(), is_business_hours(), parse_to_datetime() (+6 more)

### Community 44 - "memory_ops/skill.py"
Cohesion: 0.18
Nodes (8): MemoryOpsSkill, Any, 处突与记忆专家智能体 (Memory Ops Skill Implementation) - 异步版本  核心变更： 1. 核心执行方法添加 async/awa, 处突与记忆专家：负责通过向量数据库打捞历史处置经验，提供决策参考 (异步版本)。, 加载带有 RAG 占位符的 System Prompt, 入参校验：专家只需要用户的原始提问即可进行检索, 工业级文本拼装：将召回的多个向量文档格式化为 LLM 易读的 XML/Markdown 结构。, 执行 RAG 检索与增强生成逻辑 (异步版本)

### Community 45 - "get_permission_engine"
Cohesion: 0.15
Nodes (14): ApprovalResponse, approve_request(), ApproveRequest, get_admin_user(), get_approval(), list_approvals(), list_tool_permissions(), 列出审批请求      Args:         status: 筛选状态 (PENDING/APPROVED/REJECTED/ALL)      Retu (+6 more)

### Community 46 - "Phase 1: 能上线"
Cohesion: 0.12
Nodes (16): 1.1 PostgreSQL 迁移, 1.2 Redis 消息队列, 1.3 Docker 部署, 1.4 基础认证, 2.1 结构化日志, 2.2 LLM Fallback, 2.3 健康检查增强, 2.4 密钥管理 (+8 more)

### Community 47 - "CommanderSkill"
Cohesion: 0.19
Nodes (7): CommanderSkill, Any, 现场指挥官智能体 (Commander Skill Implementation) - 异步版本  核心变更： 1. 核心执行方法添加 async/await, 模拟回复生成 (纯 CPU 计算，无需 async), 现场指挥官：负责突发事件 (incident_report) 的实时分派与处置建议 (异步版本)。, 从 prompts/dispatch.txt 加载原始指令模板, 指挥官准入契约：必须具备 Router 识别出的核心字段

### Community 48 - "EmbeddingClient"
Cohesion: 0.15
Nodes (8): EmbeddingClient, 调用兼容 OpenAI embedding 协议的远程接口（硅基流动、智谱、本地 Ollama 等）。     仅在本地模型加载失败时作为降级兜底。, 异步批量调用远程 embedding 接口, 统一 Embedding 客户端。     - 优先本地 bge-m3（sentence-transformers）     - 本地失败自动降级远程 AP, 单条文本 embedding。         返回长度为 1024 的 float 列表（bge-m3 维度）。, 批量文本 embedding。         自动过滤空字符串，保持返回顺序与输入一致。, 返回向量维度，供 ChromaDB 初始化时使用, RemoteEmbeddingBackend

### Community 49 - "get_vector_client"
Cohesion: 0.22
Nodes (9): 知识库与数据持久化层入口 (Knowledge Layer Entry) - __init__.py =============================, migrate_v1_to_v2(), _migrate_v1_to_v2_async(), 工业级数据迁移适配器 (Migration Adapter)  功能： 1. 桥接旧版 events 表与新版 incident_logs 表。 2. 强制语义, get_vector_client(), 向量检索接口 (ChromaDB Vector Store)  核心特性： 1. Embedding 抽象：统一封装文本转向量过程。 2. 余弦相似度检, 返回 PalaceVectorStore 单例，首次调用时初始化。初始化失败返回 None。, IncidentLog (+1 more)

### Community 50 - "Logic Entry Structure: trigger+behavior+reason"
Cohesion: 0.18
Nodes (14): Five-Question Interview Framework for Persona Extraction, Logic Entry Structure: trigger+behavior+reason, Memory Palace Strategy Pipeline: Ingest -> Extract -> Generate SOP, Persona Digital Twin: LLM-generated Expert Avatar from Historical Logic Entries, Task Decomposition: LLM-driven Goal Breakdown into Executable Task Graph, Persona Extract: Question 4 - Counter-Intuitive Handling Pattern, Persona Extract: Question 5 - Summary and Synthesis Prompt, Persona Extract: Invoke/Answer Role Setting Prompt (+6 more)

### Community 51 - "BaseAgentSkill"
Cohesion: 0.19
Nodes (8): BaseAgentSkill, Any, 【模板方法】外部调度的唯一合法入口。         内部自动封装：高精度耗时统计、防崩溃全局异常捕获、前置安全护栏。          ⚠️  asyn, 加载任务 prompt，自动检测同目录下的 soul.txt 并前置拼接。          目录约定：           prompts/, 热更新 soul/prompt 文件后调用，强制下次重新读取磁盘。, 子类强制契约 1：数据清洗与准入校验（同步）。         检查 context 是否包含 LLM 需要的字段，不满足则 raise SkillValid, 子类强制契约 2：核心业务逻辑（async）。         在此进行 Prompt 组装、大模型接口调用、结果 JSON 解析。         无论成, 5 大特种智能体的最高抽象基类。     外部调度中枢只允许调用 `run()` 方法，绝不允许直接调用内部实现。      Soul 注入机制：

### Community 52 - "test_orchestrator.py"
Cohesion: 0.14
Nodes (6): orchestrator(), 编排器状态机测试 (Unit Test for Orchestrator)  测试核心：验证 Orchestrator 对不同优先级消息的路由决策、Agen, 常规消息走默认路由到 persona_extract, TestMessageSaving, TestRoutingDecision, TestSLARecording

### Community 53 - "RedisStreamsQueue"
Cohesion: 0.18
Nodes (6): Any, Redis Streams message queue implementing MessageQueueProtocol for production., Redis Streams-based queue with consumer group and dead letter support., Acknowledge message after successful processing., Move failed message to dead letter stream after max retries., RedisStreamsQueue

### Community 54 - "invoke.py"
Cohesion: 0.26
Nodes (12): ask_persona(), _generate_first_person_reply(), Any, query_persona_logic(), _rank_entries_by_relevance(), 数字分身调用模块 (Persona Invocation)  对应 PRD 中描述的 F-014： - 员工@分身名称并描述情况 - 系统检索逻辑档案，以第一人, 检索最相关的逻辑条目      策略：     1. 优先从 personas 表精确匹配 job_title     2. 如果匹配到，用向量检索entrie, 对逻辑条目按问题相关性排序（轻量级关键词匹配，无LLM开销）      策略：     1. 提取问句中的关键词     2. 计算每条条目的 trigger+ (+4 more)

### Community 55 - "router/skill.py"
Cohesion: 0.22
Nodes (6): Any, 路由大管家智能体 (Router Skill Implementation) - 异步版本  核心变更： 1. 所有方法添加 async/await 前缀 2., 路由大管家：系统的意图分发与风险分诊中枢 (异步版本)。, 工业级配置加载：确保文件缺失时有安全默认值, 从独立 txt 文件中读取 Prompt，实现业务与代码分离, RouterSkill

### Community 56 - "embedding_client.py"
Cohesion: 0.18
Nodes (9): _detect_device(), get_embedding_client(), LocalEmbeddingBackend, embedding_client.py · 统一 Embedding 接口 =========================================, 同步批量 embedding（在线程池中调用，不阻塞事件循环）。         bge-m3 推荐加前缀 "Represent this sentence:, 全局单例，模型只加载一次。     测试时可通过 get_embedding_client.cache_clear() 重置。, 自动检测最优推理设备：CUDA > MPS (Apple Silicon) > CPU, 使用 sentence-transformers 在本地加载 bge-m3。     首次调用时懒加载模型（避免 import 时就占用资源）。 (+1 more)

### Community 57 - "TestMemoryRetrieval"
Cohesion: 0.17
Nodes (5): MockEmbeddingFunction, RAG 链路集成测试 (Memory Retrieval)  验证: 向量库 upsert → query 完整回路，mock embedding 绕过外部依赖, 注入测试用 vector_store 替换全局 get_vector_client, get_vector_client 返回 fixture 注入的实例, TestMemoryRetrieval

### Community 58 - "watcher/skill.py"
Cohesion: 0.20
Nodes (10): Dual-Layer Routing Architecture: L1 Regex + L2 LLM, SLA Timeout Guardrails: P0=3min, P1=10min, P2=30min, P3=120min, SOP Compliance Audit: Comparing Commander Instructions to Employee Replies, Router Agent: Runtime Configuration (config.yaml), Router Agent: System Prompt with Intent Taxonomy, Router Agent: Soul Charter / Design Philosophy, Watcher Agent: Runtime Configuration with SLA Timeouts, Watcher Agent: Audit Prompt with SLA and SOP Guardrails (+2 more)

### Community 59 - "push_logger.py"
Cohesion: 0.25
Nodes (8): list_push_logs(), get_push_log(), get_recent_push_logs(), Any, 推送日志写入模块 (Push Logger)  负责记录每次 ContextTrigger 推送的完整生命周期： - push_id: 推送唯一ID - msg, 获取最近的推送日志      Args:         from_user: 按发送者筛选         limit: 返回条数         adopt, 更新推送确认状态      Args:         push_id: 推送日志ID         adoption_status: 采纳状态 ('adop, update_push_confirm()

### Community 60 - "skills.py"
Cohesion: 0.25
Nodes (9): get_skill(), list_skills(), v1/endpoints/skills.py - Skills endpoint, reload_skill(), get_skill(), get_skill_by_name(), list_skill_names(), 智能体工厂方法：根据名称获取已实例化的智能体对象。      :param name: 技能名称（如 "router", "commander", "watch (+1 more)

### Community 61 - "skills/__init__.py"
Cohesion: 0.22
Nodes (6): get_skill_info(), Any, 智能体业务技能包 (Business Agent Skills) - 统一入口 ========================================, 重新加载指定技能的配置（热更新入口）。     触发 invalidate_prompt_cache() 清除缓存。, reload_all_skills(), reload_skill()

### Community 62 - "TodoWriteSkill"
Cohesion: 0.31
Nodes (4): TodoWrite Skill - 任务分解, Any, 任务分解智能体      将复杂目标分解为具有依赖关系的任务图      输入:         - goal: 目标描述         - session_, TodoWriteSkill

### Community 63 - "wechat_crypto.py"
Cohesion: 0.25
Nodes (4): create_wechat_crypto(), MockWeChatCrypto, wechat_crypto.py · 企业微信 AES-256-CBC 加解密模块 ======================================, 工厂函数：创建企微加解密实例。      :param token:             企微 Token（优先使用参数，其次环境变量 WECHAT_TOK

### Community 64 - "demo.sh"
Cohesion: 0.57
Nodes (7): scene1(), scene2(), scene3(), scene4(), scene5(), send(), demo.sh script

### Community 65 - "FastAPI"
Cohesion: 0.15
Nodes (10): FastAPI, Authentication dependency for admin endpoints. Supports API Key (X-API-Key heade, REST API 层 (API Layer) - __init__.py =====================================  提供 F, close_session(), get_session(), v1/endpoints/sessions.py - Sessions endpoint, v1/router.py - API v1 router aggregator, Config (+2 more)

### Community 66 - "PostgresDBClient"
Cohesion: 0.20
Nodes (6): Pool, PostgresDBClient, Any, PostgreSQL async database client using asyncpg. Implements the same interface as, PostgreSQL client with asyncpg connection pool., Translate SQLite ? placeholders to PostgreSQL $1, $2, ...

### Community 67 - "v2/schemas.py"
Cohesion: 0.47
Nodes (5): AgentInvokeRequest, BatchMessageRequest, MessageCreateV2, BaseModel, v2/schemas.py - API v2 schemas

### Community 68 - "demo_send_message"
Cohesion: 0.17
Nodes (11): demo_send_message(), DemoMessage, Demo 消息入口：直接构造 payload 推入队列，跳过企微加密。     仅在 DEMO_MODE=true 时可用。, get_trace_id(), new_trace_id(), Token, contextvars-based trace_id propagation for structured logging., Get current trace_id. Returns 'UNKNOWN' if not set. (+3 more)

### Community 69 - "logger_config.py"
Cohesion: 0.50
Nodes (3): 工业级日志管理系统 (Global Logging System)  核心特性： 1. 多文件归档：将 Access, App, Error, Watch, 配置全局日志处理器。     在 main.py 或 orchestrator.py 启动时调用一次。, setup_logging()

### Community 84 - "InMemoryQueue"
Cohesion: 0.20
Nodes (4): InMemoryQueue, Any, In-memory asyncio.Queue adapter implementing MessageQueueProtocol for DEMO_MODE., Wraps asyncio.Queue to implement MessageQueueProtocol.

### Community 85 - "MessageQueueProtocol"
Cohesion: 0.20
Nodes (5): MessageQueueProtocol, Any, Protocol, Message queue protocol for backend switching (Redis Streams / asyncio.Queue)., Async message queue interface (put, get, task_done, qsize, empty).

### Community 86 - "👴 智能体说明书：知识分身专家 (Persona_Expert_Agent)"
Cohesion: 0.18
Nodes (10): 1. 🔍 业务逻辑说明 (Business Logic), 2. 📥 输入契约 (Input Contract), 3. 🧠 交互红线与状态机 SOP (State Machine SOP), 4. 🧪 冒烟测试用例 (Smoke Test Cases), 5. 📤 输出契约 (Output Schema), 🔴 安全与防越狱红线 (Anti-Jailbreak), 👴 智能体说明书：知识分身专家 (Persona_Expert_Agent), 核心处理链路： (+2 more)

### Community 87 - "explore.md"
Cohesion: 0.20
Nodes (9): Check for context, Ending Discovery, Guardrails, OpenSpec Awareness, The Stance, What You Don't Have To Do, What You Might Do, When a change exists (+1 more)

### Community 88 - "MemoryPalaceUser"
Cohesion: 0.20
Nodes (5): HttpUser, MemoryPalaceUser, Locust load test for Memory Palace OS. Usage: locust -f scripts/locustfile.py --, Simulate emergency incident report, Simulate daily tourist query

### Community 89 - "proposal.md"
Cohesion: 0.20
Nodes (9): Capabilities, Impact, Modified Capabilities, New Capabilities, Phase 1: 能上线, Phase 2: 能运维, Phase 3: 能扩展, What Changes (+1 more)

### Community 90 - "ADDED Requirements"
Cohesion: 0.20
Nodes (9): ADDED Requirements, Requirement: AsyncDBClient Protocol, Requirement: PostgresDBClient, Requirement: SQLiteDBClient, Scenario: Connection pool, Scenario: DEMO_MODE fallback, Scenario: Protocol defines interface, Scenario: SQL placeholder translation (+1 more)

### Community 91 - "ADDED Requirements"
Cohesion: 0.20
Nodes (9): ADDED Requirements, Requirement: InMemoryQueue, Requirement: MessageQueueProtocol, Requirement: RedisStreamsQueue, Scenario: Dead letter queue, Scenario: Demo mode uses memory queue, Scenario: Message deduplication, Scenario: Message enqueue and dequeue (+1 more)

### Community 92 - "check_connection"
Cohesion: 0.20
Nodes (10): create_mock_wx_crypto(), get_wx_crypto(), 创建 Mock 加解密实例 (仅用于开发测试), 就绪检查 (Readiness Probe)     - 用于 K8s readinessProbe     - 检查依赖服务是否就绪 (队列、数据库等), 企微管理后台配置 Webhook 时，触发的首次 GET 验签, 接收企微真实业务消息。     设计原则：全程耗时必须 < 50ms。解密 -> 组装 -> 入队 -> return success。, readiness_check(), receive_wechat_message() (+2 more)

### Community 93 - "AsyncDBClientProtocol"
Cohesion: 0.22
Nodes (5): AsyncDBClientProtocol, Any, Protocol, Database client protocol — defines the interface both PostgresDBClient and SQLit, Async database client interface (fetch_one, fetch_all, execute, transaction, clo

### Community 94 - "🚨 智能体说明书：现场指挥官 (Commander_Agent)"
Cohesion: 0.20
Nodes (9): 1. 🔍 业务逻辑说明 (Business Logic), 2. 📥 输入契约 (Input Contract), 3. 🧠 决策 SOP (Standard Operating Procedures), 4. 🧪 验收测试用例 (Acceptance Test Cases), 5. 📤 输出契约 (Output Schema), 🔴 P0 级：生命安全 / 紧急火灾, 🟡 P2 级：普通客诉 / 财物丢失, 🚨 智能体说明书：现场指挥官 (Commander_Agent) (+1 more)

### Community 95 - "set_venue_id"
Cohesion: 0.25
Nodes (8): get_venue_id(), Token, Multi-tenant isolation via contextvars — venue_id propagation., Set venue_id for current async context., Get current venue_id. Returns None if not set (wildcard mode)., Return (WHERE clause fragment, params) for tenant-aware queries.     Returns emp, set_venue_id(), tenant_filter()

### Community 96 - "Tasks: 技能层稳定化"
Cohesion: 0.25
Nodes (7): 1. P0: 安全, 2. P0: DEMO_MODE 降级, 3. P1: 路由修复, 4. P1: 单元测试修复, 5. P2: 技能链路验证, 6. P3: 依赖补全, Tasks: 技能层稳定化

### Community 97 - "Requirement: API Key authentication"
Cohesion: 0.25
Nodes (7): ADDED Requirements, Requirement: API Key authentication, Requirement: JWT authentication, Scenario: Demo mode bypass, Scenario: Invalid API key, Scenario: Valid API key, Scenario: Valid JWT

### Community 98 - "Requirement: Knowledge entry management"
Cohesion: 0.25
Nodes (7): ADDED Requirements, Requirement: Admin UI knowledge tab, Requirement: Knowledge entry management, Scenario: Delete knowledge entry, Scenario: List knowledge entries, Scenario: Re-index knowledge base, Scenario: View knowledge entries

### Community 99 - "Requirement: Multi-model fallback chain"
Cohesion: 0.25
Nodes (7): ADDED Requirements, Requirement: Environment variable configuration, Requirement: Multi-model fallback chain, Scenario: All models exhausted, Scenario: Fallback configured, Scenario: Primary fails, fallback succeeds, Scenario: Primary model succeeds

### Community 100 - "ADDED Requirements"
Cohesion: 0.25
Nodes (7): ADDED Requirements, Requirement: Load testing script, Requirement: Query optimization, Requirement: TTL cache, Scenario: Cache hit, Scenario: Dashboard query consolidation, Scenario: Webhook ingestion load test

### Community 101 - "data_seeder.py"
Cohesion: 0.38
Nodes (6): Base, 种子数据注入器 (Knowledge Seeder)  功能： 1. 强行同步 SOP 数据库。 2. 预热向量库，灌入历史典型的处突经验案例。, seed_knowledge_base(), _seed_knowledge_base_async(), 标准作业程序文档表：记录景区 SOP 操作规范，供 AI 指挥官查询执行, SOPDocument

### Community 102 - "ADDED Requirements"
Cohesion: 0.29
Nodes (6): ADDED Requirements, Requirement: PostgreSQL health check, Requirement: Redis health check, Scenario: PostgreSQL available, Scenario: PostgreSQL unavailable, Scenario: Redis available

### Community 103 - "ADDED Requirements"
Cohesion: 0.29
Nodes (6): ADDED Requirements, Requirement: Data isolation, Requirement: venue_id extraction, Scenario: Cross-tenant query blocked, Scenario: Demo mode no isolation, Scenario: WeChat message contains agent ID

### Community 104 - "ADDED Requirements"
Cohesion: 0.29
Nodes (6): ADDED Requirements, Requirement: JSON log format, Requirement: trace_id propagation, Scenario: Default format preserved, Scenario: JSON format enabled, Scenario: trace_id in every log line

### Community 105 - "init_database"
Cohesion: 0.38
Nodes (6): init_database(), init_database_sync(), _init_pg(), 数据库初始化脚本 (Database Initialization) - 异步版本  负责创建 memory.db 的核心表结构和索引。 在项目首次部署或, 初始化数据库 (异步版本)。     db_client=None → 使用默认 SQLite（DEMO_MODE 兼容）。     传入 Postgres, PostgreSQL database initialization using the passed PostgresDBClient.

### Community 106 - "test_core_pipeline.py"
Cohesion: 0.29
Nodes (4): 核心消息处理链路集成测试 (Core Pipeline Integration Test)  验证：消息入队 → 消费者取出 → Orchestrator 路由, 消息入队后消费者取出并派发给 Orchestrator, Orchestrator.process() 返回正确结构, TestCorePipeline

### Community 107 - "ADDED Requirements"
Cohesion: 0.33
Nodes (5): ADDED Requirements, Requirement: Demo Docker Compose, Requirement: Production Docker Compose, Scenario: All services healthy, Scenario: Demo mode deployment

### Community 108 - "Requirement: Rate limiting middleware"
Cohesion: 0.33
Nodes (5): ADDED Requirements, Requirement: Rate limiting middleware, Scenario: Exceed rate limit, Scenario: Webhook exempt, Scenario: Within rate limit

### Community 109 - "Requirement: Secrets validation at startup"
Cohesion: 0.33
Nodes (5): ADDED Requirements, Requirement: Secrets validation at startup, Scenario: All secrets present, Scenario: Demo mode skips validation, Scenario: Missing required secret

### Community 110 - "demo-console/tasks.md"
Cohesion: 0.40
Nodes (4): 1. 后端端点, 2. 演示控制台 HTML, 3. 演示脚本, 4. 验证

### Community 111 - "design.md"
Cohesion: 0.40
Nodes (4): Context, Decisions, Goals / Non-Goals, Risks / Trade-offs

### Community 112 - "secrets.py"
Cohesion: 0.40
Nodes (3): Secrets management — centralized validation at startup., Return list of missing REQUIRED secrets. Empty list = all good., Secrets

### Community 113 - "cache.py"
Cohesion: 0.50
Nodes (3): Simple async TTL cache for hot queries., Decorator: caches async function results for ttl_seconds., ttl_cache()

## Ambiguous Edges - Review These
- `RAG Retrieval Pipeline` → `Error Code Specification`  [AMBIGUOUS]
  docs/architecture.md · relation: conceptually_related_to

## Knowledge Gaps
- **166 isolated node(s):** `memory-palace-os`, `run.sh script`, `Config`, `APIChange`, `Config` (+161 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `RAG Retrieval Pipeline` and `Error Code Specification`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `AppContainer` connect `AppContainer` to `ContextCompressor`, `PostgresDBClient`, `orchestrator.py`, `TaskGraph`, `Orchestrator`, `get_permission_engine`, `get_vector_client`, `PermissionEngine`, `main.py`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `PersonaExtractSkill` connect `PersonaExtractSkill` to `gateway.py`, `BaseAgentSkill`, `llm_wrapper.py`, `admin.py`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Why does `reload_settings()` connect `app_settings.py` to `admin.py`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `SkillOutput` (e.g. with `TestContextTrigger` and `TestCorePipeline`) actually correct?**
  _`SkillOutput` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `Orchestrator` (e.g. with `AppContainer` and `MessageQueueWorker`) actually correct?**
  _`Orchestrator` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `CircuitBreaker` (e.g. with `LLMFallbackChain` and `ModelConfig`) actually correct?**
  _`CircuitBreaker` has 8 INFERRED edges - model-reasoned connections that need verification._