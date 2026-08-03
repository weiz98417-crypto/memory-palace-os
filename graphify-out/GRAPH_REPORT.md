# Graph Report - memory-palace-os  (2026-08-03)

## Corpus Check
- 371 files · ~960,140 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4737 nodes · 10990 edges · 266 communities (216 shown, 50 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 630 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3e5b08d3`
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
- tests/init.py
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
- apply.md
- archive.md
- propose.md
- 🚨 智能体说明书：现场指挥官 (Commander_Agent)
- architecture.md
- TestTaskGraph
- TestVectorStore
- init_database
- llm_wrapper.py
- 企业演示版架构与信任边界
- close_vector_client
- 企业演示版故障处理手册
- 企业演示版关键运行流程
- Enterprise Demo V1 测试结果
- 企业演示版交付指南
- Docker 启停与恢复报告
- 企业指挥中心视觉 QA
- demo.ps1
- TestContextTier
- TestTaskGraph
- setup_logging
- 企业演示版权限与访问边界
- 企业演示版测试覆盖图
- test_agent_handoff.py
- demo_persona_finalize
- Agent 与自动化边界
- 企业演示版环境变量与密钥
- capability-matrix.md
- Intent Keyword Routing Table
- Any
- Enum
- str
- BaseModel
- Any
- Any
- Enum
- str
- Any
- BaseModel
- Enum
- Request
- str
- Any
- Enum
- Queue
- Request
- str
- Any
- BaseModel
- Enum
- Path
- str
- Any
- Any
- Queue
- Any
- Enum
- str
- Any
- BaseModel
- Exception
- Any
- Path
- Any
- Enum
- Exception
- Any
- Any
- AsyncOpenAI
- Any
- Python Dependency Manifest
- 5. Market Segments
- 6. Value Propositions
- 7.4 标准演示剧本
- ._sync_send_sms
- 7.14 Scenario Controller 详细设计
- 7.16 统一数据与证据模型
- 7.18 企业指挥中心页面规格
- 7.19 测试与验证方案
- 7.2 Docker 运行设计
- 7.5 功能需求
- sms_client.py
- 7.15 API 契约
- Workspace
- create_user
- 7. 完整演示旅程
- test_canonical_ingress.py
- request
- Any
- FakeElement
- test_event_experience_candidates.py
- 企业 MVP 备份、恢复与诊断
- 10. 实现决策
- save_confirmed_event
- Memory Palace OS 内部 UAT 发布就绪报告
- Memory Palace OS 企业 MVP 交付 PRD
- 3.3 当前不能直接交付的原因
- ExperienceUsageLedger
- 企业 MVP Windows Docker 运维手册
- 4.3 核心结果
- CanonicalMessageIngress
- test_event_closure.py
- test_m4_final.py
- simulator_session_restore.test.cjs
- 8. Release
- Any
- experienceInterviewPath
- shared_client_refresh.test.cjs
- SensitivityLevel
- init_experience_schema
- compactBody
- Formal Client QA — 2026-07-29
- event_dossier.py
- 5. Market Segments
- 7.14 质量与验收
- 7.3 端到端正式业务流程
- 4. 用户角色与核心任务
- 6. 领域模型
- .run
- Any
- 7.4 功能范围
- 13. 测试决策
- 8. 功能需求
- v1/router.py
- VectorStoreStub
- TestSLARecording
- 6. 管理后台页面
- 7.5 全功能可用标准
- 14. 发布计划
- 2. 产品方案
- 7. 核心流程
- TestDCLLock
- Memory Palace OS
- 7.11 API 与状态模型
- 7.7 数据架构
- 7.9 认证、角色与租户
- test_push_adoption_hardening.py
- DatabaseHealthChecker
- RedisHealthChecker
- verify_postgres_runtime.py
- SchedulerStub
- .__init__

## God Nodes (most connected - your core abstractions)
1. `build_app()` - 123 edges
2. `login()` - 111 edges
3. `api_error()` - 101 edges
4. `Orchestrator` - 92 edges
5. `AsyncDBClient` - 91 edges
6. `request_trace_id()` - 82 edges
7. `write_audit()` - 82 edges
8. `ScenarioController` - 77 edges
9. `SkillOutput` - 75 edges
10. `init_database()` - 69 edges

## Surprising Connections (you probably didn't know these)
- `Real-Time Message Processing Flow` --semantically_similar_to--> `30-Second Emergency Response (P0)`  [INFERRED] [semantically similar]
  docs/architecture.md → README.md
- `test_request_trace_id_is_stable_for_the_request_lifecycle()` --calls--> `request_trace_id()`  [EXTRACTED]
  tests/unit/test_runtime_hardening.py → src/memory_palace/api/audit.py
- `AsyncOnlyQueue` --uses--> `AppContainer`  [INFERRED]
  tests/integration/test_message_intake_api.py → src/memory_palace/core/container.py
- `DeterministicVectorStore` --uses--> `AppContainer`  [INFERRED]
  tests/integration/test_message_intake_api.py → src/memory_palace/core/container.py
- `DraftSopVectorStore` --uses--> `AppContainer`  [INFERRED]
  tests/integration/test_message_intake_api.py → src/memory_palace/core/container.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
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
- **Incident Detection-to-Resolution Pipeline (context_trigger -> commander -> watcher escalation)** — src_memory_palace_skills_context_trigger_two_stage_trigger_system, src_memory_palace_skills_commander_config_commander_agent, src_memory_palace_config_settings_yaml_escalation_chain [INFERRED 0.75]
- **Knowledge Extraction-to-Utilization Cycle (persona_extract interviews for logic_entries consumed by persona agent)** — src_memory_palace_skills_persona_extract_config_persona_extract_skill, src_memory_palace_skills_persona_extract_logic_entries_pattern, src_memory_palace_skills_persona_config_persona_expert_agent [EXTRACTED 1.00]
- **Safety Guard Pattern (commander mandatory_safety_check + memory_ops anti_hallucination + persona anti_jailbreak)** — src_memory_palace_skills_commander_config_commander_agent, src_memory_palace_skills_memory_ops_anti_hallucination_guard, src_memory_palace_skills_persona_anti_jailbreak_defense [INFERRED 0.75]
- **Persona Extraction Pipeline: Interview Guide + Question Prompts + Invoke Pattern** — src_memory_palace_skills_persona_extract_references_interview_guide, src_memory_palace_skills_persona_extract_prompts_extract_question_4, src_memory_palace_skills_persona_extract_prompts_extract_summary, src_memory_palace_skills_persona_extract_prompts_invoke, concept_interview_five_question_framework, concept_logic_entry_trigger_behavior_reason [EXTRACTED 1.00]
- **Watcher Audit System: Config SLA Timeouts + Audit Prompt + Skill Spec + Soul Philosophy** — src_memory_palace_skills_watcher_config, src_memory_palace_skills_watcher_prompts_audit, src_memory_palace_skills_watcher_skill, src_memory_palace_skills_watcher_soul, concept_sla_timeout_guardrails, concept_sop_compliance_audit [EXTRACTED 1.00]
- **Frontend Admin Ecosystem: Main OS + Admin Panel + Demo Console sharing API endpoints** — static_index, static_admin_frontend, static_demo_console, concept_persona_digital_twin, concept_memory_palace_strategy_pipeline [INFERRED 0.85]

## Communities (266 total, 50 thin omitted)

### Community 0 - "hot_reload.py"
Cohesion: 0.06
Nodes (36): calculate_content_hash(), calculate_file_hash(), FileChange, FileChangeType, get_hot_reload_manager(), get_reload_history(), get_skill_content(), get_skill_version() (+28 more)

### Community 1 - "ContextCompressor"
Cohesion: 0.08
Nodes (31): ColdNarrative, ContextCompressor, ContextTier, HotMessage, Any, Enum, 三层上下文压缩系统 (Three-Tier Context Compression) — STUB: Phase 1，待激活  架构设计: - Tier, 三层上下文压缩管理器      工作流程:     1. 新消息到达 -> 加入 Hot 层     2. Hot 层溢出 -> 最老批次 evict (+23 more)

### Community 2 - "health.py"
Cohesion: 0.06
Nodes (68): DeterministicScenarioAdapter, DeterministicStepFailure, Protocol, RuntimeError, Turns a versioned scenario step into truthful Demo Adapter evidence., Expected demo-only failure used to prove recovery behavior., ScenarioAdapter, tool_calls_for_attempt() (+60 more)

### Community 3 - "CircuitBreaker"
Cohesion: 0.09
Nodes (20): CircuitBreaker, CircuitOpenError, CircuitState, circuit_breaker.py · LLM 调用熔断器 ===================================== 实现经典三态熔断器, 通过熔断器调用异步函数。          CLOSED    → 正常调用，记录成功/失败         OPEN      → 直接抛 Circui, 装饰器写法。         用法：           @breaker.protect           async def call_llm(pr, 返回当前统计，供 /health 端点和管理大屏使用, OPEN 冷却到期时自动迁移至 HALF_OPEN。调用方负责加锁。 (+12 more)

### Community 4 - "TaskGraph"
Cohesion: 0.05
Nodes (30): get_assistant_work(), get_task_graph(), Any, Enum, str, 任务依赖图 (Task Graph)  核心职责: 1. 管理任务的生命周期 (PENDING -> RUNNING -> DONE/FAILED) 2, 任务依赖图管理器      使用示例:         graph = TaskGraph()          # 创建任务         ta, 创建新任务          Args:             session_id: 会话 ID             description: (+22 more)

### Community 5 - "PersonaExtractSkill"
Cohesion: 0.05
Nodes (26): main(), PersonaExtractTester, persona_extract skill - 老员工经验萃取专家, PersonaExtractSkill, Any, 老员工经验萃取专家：负责将老员工的隐性经验转化为结构化逻辑条目。      萃取流程：         start_interview(venue_id,, 继续访谈：解析回答，决定是追问还是进入下一题, 完成访谈：汇总所有条目，存入 personas 表 (+18 more)

### Community 6 - "KeywordMatcher"
Cohesion: 0.14
Nodes (11): Pattern, KeywordCategory, KeywordMatcher, any, 关键词库定义 (Keywords Library)  本模块定义了 docx 中描述的两阶段事件触发系统的关键词数据类。 包含：TRIGGER_KEYWO, 关键词匹配器     提供 Stage1 的极速关键词匹配功能（O(n) 字符串扫描）, Args:             include_scenic_types: 要加载的景区类型列表，如 ["ancient_town", "museum"], 为关键词构建正则表达式          多字符关键词（如"晕倒"）：精确子串匹配         单字符关键词（如"晕"）：不能紧跟中文字符（避免"我有 (+3 more)

### Community 7 - "SafeFileOps"
Cohesion: 0.07
Nodes (23): get_workspace_file_ops(), is_path_traversal(), Path, 安全文件操作 (Safe File Operations)  核心职责: 1. 封装文件读写操作，自动限制在工作区内 2. 防止路径遍历攻击 3. 提, 写入文件          Args:             relative_path: 相对路径             content: 文件内, 追加写入          Args:             relative_path: 相对路径             content: 追加内, 列出目录内容          Args:             relative_path: 相对路径          Returns:, 删除文件          Args:             relative_path: 相对路径          Returns: (+15 more)

### Community 8 - "AppContainer — Handwritten DI Container (dataclass + lazy property)"
Cohesion: 0.08
Nodes (45): AgentMemory Activation — Scoped Context per Agent, AppContainer — Handwritten DI Container (dataclass + lazy property), Skill Registration in Lifespan Only, AgentMemory.build_scoped_context() — Per-Agent Field Filter, ContextTier.build_tiered_context() — Three-Tier Builder, Config Module Rename (config/init.py → config/config_manager.py), AppContainer.override() / .reset() — Mock Injection, ContextTier Activation — Hot/Warm/Cold Tiers (+37 more)

### Community 9 - "SkillOutput"
Cohesion: 0.05
Nodes (149): acceptInterview(), answerInterview(), applyMessagePayload(), applyUser(), attachmentSizeLabel(), authorizationScopeLabel(), blockTask(), byId() (+141 more)

### Community 10 - "metrics/__init__.py"
Cohesion: 0.07
Nodes (19): callable, AlertingManager, get_alerting_manager(), alerting.py - Prometheus alerting rules for Memory Palace OS, 发送告警通知（同时写入 metrics 和触发处理函数）, resolve_alert(), send_alert(), AgentMetricsCollector (+11 more)

### Community 11 - "ConfigManager"
Cohesion: 0.09
Nodes (13): ConfigManager, ConfigSubscriber, get_config(), Any, config/__init__.py · 全局配置加载器 (Enhanced) =======================================, 应用环境变量覆盖          支持的格式：             MEMORY_PALACE_LLM_DEFAULT_MODEL=deepseek, 支持点号语法的配置读取          用法：             config.get('llm.default_model'), 设置配置值          用法：             config.set('llm.default_model', 'deepseek-v4-f (+5 more)

### Community 12 - "Workspace"
Cohesion: 0.08
Nodes (17): get_workspace_manager(), Any, Path, 工作区隔离 (Workspace Isolation) — STUB: Phase 4，待激活  核心职责: 1. 为每个复杂任务创建独立的隔离工作目录, 销毁工作区          Args:             archive: 是否先存档          Returns:, 打包存档工作区          Returns:             存档文件路径, 验证路径在工作区内 (防止路径遍历)          Args:             target_path: 目标路径          Re, 工作区管理器 (全局单例)      负责工作区的创建、销毁、查询 (+9 more)

### Community 13 - "metrics.py"
Cohesion: 0.08
Nodes (20): AsyncMetricsCollector, get_metrics_registry(), init_metrics(), MetricsConfig, MetricsRegistry, metrics.py · Prometheus 指标采集模块 ================================================, 记录 Stage1 关键词匹配结果      Args:         excluded: 是否被排除         excluded_catego, 记录 Stage2 LLM 调用      Args:         status: 调用状态 (success/error/fallback) (+12 more)

### Community 15 - "AppContainer"
Cohesion: 0.06
Nodes (29): lifespan(), 启动阶段：拉起队列消费者 + 定时任务调度器     关机阶段：等待队列排空（最多 30 秒）后优雅退出      [Phase 3] 新增:, get_scoped_context_builder(), 获取全局 Scoped Context 构造器, AppContainer, AppContainer — 轻量依赖注入容器  设计原则： - 零外部依赖，手写 dataclass + 懒加载 @property - 每个 pro, 注入 Mock 实例用于测试。e.g. container.override(llm_client=mock_llm), 清除所有 override 和缓存，恢复原始行为。 (+21 more)

### Community 16 - "gateway.py"
Cohesion: 0.05
Nodes (51): load_scenario(), Demo seed data loader. Loads scenario YAMLs into in-memory cache + SQLite.  Us, Load seed data for a scenario., get_skill(), list_skills(), Request, add_knowledge(), _check_auth() (+43 more)

### Community 17 - "PermissionEngine"
Cohesion: 0.17
Nodes (8): ApprovalRequest, PermissionEngine, Any, 权限引擎核心类      使用示例:         engine = PermissionEngine()         engine.regist, 检查权限并执行工具          Args:             tool_name: 工具名称             args: 工具参数, 审批通过          Args:             approval_id: 审批单 ID             reviewer: 审批, 审批拒绝          Args:             approval_id: 审批单 ID             reviewer: 审批, test_cooldown_is_isolated_by_venue()

### Community 18 - "tool_executor.py"
Cohesion: 0.13
Nodes (12): execute_with_permission(), get_tool(), list_tools(), Any, 通过权限引擎执行工具      这是推荐的工具调用方式。      Args:         tool_name: 工具名称         ar, 注册工具      Args:         name: 工具名称         func: 工具函数 (可以是 async 或 sync), register_tool(), 工具执行器 (ToolExecutor) 单元测试  覆盖: 工具注册、执行、列表、错误处理  Copyright (c) 2026 ZhouWei & (+4 more)

### Community 19 - "env_validator.py"
Cohesion: 0.14
Nodes (14): 8.10 最终交付物, 8.1 发布策略, 8.2 Milestone 0：建立真实基线, 8.3 Milestone 1：一键可运行, 8.4 Milestone 2：四个场景闭环, 8.5 Milestone 3：企业演示界面, 8.6 Milestone 4：稳定性与交付, 8.7 V1 范围 (+6 more)

### Community 20 - "WeChatWorkClient"
Cohesion: 0.13
Nodes (16): list_runtime_recovery_runs(), Return recent global App recovery evidence without tenant payloads., _count_value(), list_recent_global_recovery_runs(), public_recovery_run(), Any, BaseException, Persistent application-start recovery audit and safe diagnostics. (+8 more)

### Community 21 - "SessionStateManager"
Cohesion: 0.12
Nodes (16): 7.10 安全与信任, 7.11 兼容性, 7.12 假设, 7.13 已知技术债务处理策略, 7.17 代码模块落位, 7.1 总体方案, 7.3.1 首屏：企业指挥中心, 7.3.2 核心交互原则 (+8 more)

### Community 22 - "Orchestrator"
Cohesion: 0.11
Nodes (28): Skill Registration Center, WeChat Crypto Module (WXBizMsgCrypt), ChromaDB Vector Store, Commander Agent, Context Tier System (Hot/Warm/Cold), 30-Second Emergency Response (P0), Gateway, Memory Ops Agent (+20 more)

### Community 23 - "app_settings.py"
Cohesion: 0.26
Nodes (13): api_error(), _error_payload(), HTTPException, Request, block_assistant_task(), complete_assistant_task(), get_assistant_sop_reference(), get_assistant_task() (+5 more)

### Community 24 - "Stabilization Hardening Design Document"
Cohesion: 0.14
Nodes (24): demo_knowledge ChromaDB Collection, Demo Scenario Switching (daily/emergency), Core Message Pipeline (receive->queue->route->agent), OpenSpec Spec-Driven Schema, sanitize_llm_output() Centralized Utility, Strangler Fig Pattern for DI Migration, WeChat Reply Loop Architecture, Knowledge Seed Data Spec (demo-full-feast) (+16 more)

### Community 25 - "Demo Full Feast Initiative (expanded 6-tab console covering all core functions)"
Cohesion: 0.08
Nodes (28): FastAPI StaticFiles mount order (StaticFiles after include_router to prevent 307), Landing Refactor (prerequisite: lazy loading, DB init, core chain), LLMClient.ask() DEMO_MODE check (os.environ DEMO_MODE=true returns mock LLMResponse), MemoryOps vector_client.search() to query_experience() API fix, Watcher Cron Activation (10:00/20:00 cron job, manual trigger on start), Skill Stabilization Initiative (from 'runnable' to 'robust'), DEMO_MODE Capability (mock LLM, no API key needed), Route Fix (/admin and /api/v1/skills 307 redirect) (+20 more)

### Community 26 - "SkillValidationError"
Cohesion: 0.13
Nodes (6): LLM 调用异常时返回 success=False, 缺少 goal 字段应抛出 SkillValidationError, 缺少 session_id 字段应抛出 SkillValidationError, LLM 返回空内容时返回 success=False, LLM 返回非列表 JSON 时返回 success=False, TestTodoWriteSkill

### Community 27 - "AgentMemoryScope"
Cohesion: 0.12
Nodes (13): AgentMemoryScope, AgentMemoryTurn, get_agent_memory_scope(), Any, Agent 内存隔离模块 (Agent Memory Isolation) — STUB: Phase 1，待激活  核心职责: 1. 为每个 Agent, 获取指定 Agent 的对话历史          返回格式兼容 OpenAI Message:         [{"role": "user", "c, 设置共享上下文          用于: Router -> Commander 传递 case_id, severity 等必要信息, Scoped Context 构造器      核心功能:     1. Router 输出仅作为分发元数据，不原封传递给下游     2. 每个 Ag (+5 more)

### Community 28 - "WatcherSkill"
Cohesion: 0.23
Nodes (6): Any, 鹰眼巡检专家：负责后台定时巡检、SOP 合规性审查与超时工单追办 (异步版本)。, 加载巡检审计规则 Prompt (对应项目树中的 audit.txt), 巡检专家的入参契约：必须提供待审计的数据源集合 (audit_target_logs), 工业级数据清洗与格式化：         将数据库查出的原始 JSON 日志清洗成大模型易读的 Markdown 文本，防止 Token 浪费。, WatcherSkill

### Community 29 - "admin.py"
Cohesion: 0.07
Nodes (53): Request, request_trace_id(), admin_stats(), ApprovalResponse, approve_request(), ApproveRequest, continue_interview(), ControlledActionRequest (+45 more)

### Community 30 - "WXBizMsgCrypt"
Cohesion: 0.14
Nodes (11): Exception, PKCS7 填充         企微使用 AES-256-CBC，块大小 32 字节, AES-256-CBC 加密（符合企业微信协议）。         加密结构: random(16B) + msg_len(4B big-endian) +, AES-256-CBC 解密（符合企业微信协议）。         加密结构: random(16B) + msg_len(4B big-endian) +, 企微管理后台配置 Webhook URL 时触发的验签接口（GET 请求）。          :param msg_signature: 企微传递的签名, 解密接收到的企微消息（POST 请求）。          :param encrypt_xml:   XML 字符串（包含 <Encrypt> 节点）, 加密要发送的回复消息（被动回复 / 回调响应）。          :param reply_xml: 要发送的回复 XML 原文         :pa, 企业微信消息加解密类      初始化参数：       token:         企微后台配置的回调 Token       encoding_a (+3 more)

### Community 31 - "main.py"
Cohesion: 0.10
Nodes (9): health_check(), FastAPI, memory-palace-os · 主入口 ======================== 职责：   1. 启动 FastAPI 应用，挂载企微 W, Kubernetes / Docker 健康探针端点。     返回队列积压深度，便于运维监控。, create_limiter(), Rate limiting middleware using slowapi (Redis backend in prod, in-memory for dem, Create a rate limiter instance. Uses Redis in production, memory in demo., _auto_register_skills() (+1 more)

### Community 32 - "Request"
Cohesion: 0.11
Nodes (34): create_token(), decode_token(), hash_password(), _jwt_secret(), Decode and validate a signed JWT and its required claims., Hash a password with scrypt and a per-password random salt., Verify a password without exposing parsing or timing details., Create a signed access or refresh JWT. (+26 more)

### Community 33 - "orchestrator.py"
Cohesion: 0.05
Nodes (34): BaseModel, 工业级标准输出结构。     强制所有子类智能体必须以此统一的强类型格式，将结果返回给调度中枢 (Orchestrator)。     任何非该结构的返回值, SkillOutput, 智能体转办集成测试 (Integration Test for Agent Handoff)  Copyright (c) 2026 ZhouWei & T, 用户报告紧急事件 → Router → Commander。, test_router_to_commander_flow(), 情境触发集成测试 (Context Trigger Integration Test)  验证：Stage1 关键词命中 → ContextTrigger, 紧急关键词命中后仍由 Router 分诊到 Commander。 (+26 more)

### Community 34 - "PalaceVectorStore"
Cohesion: 0.09
Nodes (13): PalaceVectorStore, Any, 语义检索逻辑：带相似度阈值过滤，防止召回毫无相关的噪音。, MockEmbeddingFunction, RAG 链路集成测试 (Memory Retrieval)  验证: 向量库 upsert → query 完整回路，mock embedding 绕过外部, 注入测试用 vector_store 替换全局 get_vector_client, get_vector_client 返回 fixture 注入的实例, TestMemoryRetrieval (+5 more)

### Community 35 - "llm_wrapper.py"
Cohesion: 0.06
Nodes (125): acceptInterview(), adminURL(), answerInterview(), applyMessagePayload(), applyOutboxPayload(), attachmentSizeLabel(), authorizationScopeLabel(), byId() (+117 more)

### Community 36 - "PersonaSkill"
Cohesion: 0.13
Nodes (12): persona_agent(), 滑动窗口截断测试 (Unit Test for Persona Context)  工业级测试要点： 1. 边界值测试：对话轮数为 N-1, N, N+1, 验证：当对话超过 5 轮时，是否只保留最近的 5 轮, test_sliding_window_truncation(), PersonaSkill, Any, Generate a governed assistant response from explicit evidence., Express authorized experience without impersonating the source expert. (+4 more)

### Community 37 - "VersionManager"
Cohesion: 0.05
Nodes (85): MessageRunRepository, Store and retrieve traceable message processing state., MessageQueueWorker, 异步消息队列消费者。     在 main.py lifespan 中以 asyncio.create_task 方式运行。, 等待已领取消息完成；超时任务取消后由 Redis pending 在重启时回收。, init_attachment_schema(), AsyncDBClient, 异步数据库客户端（原始 SQL）          使用示例：         db = AsyncDBClient()         row = a (+77 more)

### Community 38 - "Persona Expert Agent (Multi-Turn Roleplay with State Tracking)"
Cohesion: 0.14
Nodes (19): Escalation Chain (commander -> watcher -> admin), Global Runtime Configuration (settings.yaml v1.2.0), Skills Router Configuration (regex-first + semantic fallback), SLA Policy (P0-P4 Priority Tiers), Commander Agent (Emergency Incident Dispatcher), Emergency Dispatch SOP (P0/P1 Life-Safety Protocol), Context Trigger Skill (Two-Stage Event Detection), Two-Stage Trigger System (Stage1 Keywords + Stage2 LLM) (+11 more)

### Community 39 - "tools/db_client.py"
Cohesion: 0.19
Nodes (16): _business_reference(), _CandidateDecision, _decode_json_list(), _decode_json_object(), _experience_content(), _hit_record(), _lexical_relevance(), Any (+8 more)

### Community 40 - "ContextTriggerSkill"
Cohesion: 0.15
Nodes (10): context_trigger skill, ContextTriggerSkill, Any, 情境触发专家：负责对消息进行两阶段判断。      Stage1（关键词极速预过滤）：       - 使用 TRIGGER_KEYWORDS 和 EXCLUD, 触发 WeChat 推送 + 延迟确认卡片          流程：         1. 立即发送事件推送卡片         2. 延迟 confirm_d, 延迟发送确认卡片（协程任务）          Args:             delay_seconds: 延迟秒数, 加载 Stage2 LLM 判断 Prompt, ContextTrigger 的入参契约：必须提供 raw_text (+2 more)

### Community 41 - "v1/schemas.py"
Cohesion: 0.08
Nodes (54): AssistantTaskBlockRequest, AssistantTaskCompleteRequest, create_assistant_message(), _employee_event_row(), _employee_task_row(), get_assistant_event(), get_assistant_session_messages(), list_assistant_sessions() (+46 more)

### Community 42 - "Orchestrator"
Cohesion: 0.17
Nodes (26): PostgreSQL-backed Watcher scheduling for the formal runtime., collect_event_watcher_snapshot(), collect_watcher_targets(), _decoded_row(), _deterministic_event_issues(), _ensure_event_watcher_policy(), _event_audit_target(), _event_finding_from_escalation() (+18 more)

### Community 43 - "tools/__init__.py"
Cohesion: 0.13
Nodes (19): 工具集成层 (Atomic Tools Layer) - __init__.py ======================================, calculate_elapsed_minutes(), format_for_log(), get_now(), get_relative_time_desc(), is_business_hours(), parse_to_datetime(), 工业级时间与时区工具库 (Time Utilities)  核心特性： 1. 时区安全 (Timezone Aware)：强制使用 UTC 进行内部存储与 (+11 more)

### Community 44 - "memory_ops/skill.py"
Cohesion: 0.19
Nodes (8): MemoryOpsSkill, Any, 处突与记忆专家：负责通过向量数据库打捞历史处置经验，提供决策参考 (异步版本)。, 加载带有 RAG 占位符的 System Prompt, 入参校验：专家只需要用户的原始提问即可进行检索, 工业级文本拼装：将召回的多个向量文档格式化为 LLM 易读的 XML/Markdown 结构。, 执行 RAG 检索与增强生成逻辑 (异步版本), test_memory_ops_fails_when_llm_client_is_unavailable()

### Community 45 - "get_permission_engine"
Cohesion: 0.13
Nodes (67): accept_interview(), _acting_audit_metadata(), answer_interview_question(), AuthorizationScope, _business_id(), _card_draft(), _card_payload(), _card_row() (+59 more)

### Community 46 - "Phase 1: 能上线"
Cohesion: 0.12
Nodes (13): AgentTurn, ConversationStage, 会话状态管理器 (Session State Manager)  核心职责： 1. 用户会话生命周期管理：跟踪用户与系统的多轮交互状态 2. Agent, 生成会话 ID：user_id + 时间戳, 获取或创建用户会话                  Args:             user_id: 企微用户 ID             fo, 更新会话阶段（状态机推进）                  这是 Orchestrator 调用最频繁的方法，用于推进 Agent 流转, 记录一次 Agent 交互（用于历史追溯和 Persona 的滑动窗口）, [升级] 记录单 Agent 的交互（用于 Agent 内存隔离）          与 record_turn 的区别:         - recor (+5 more)

### Community 47 - "CommanderSkill"
Cohesion: 0.23
Nodes (6): CommanderSkill, Any, 现场指挥官：负责突发事件 (incident_report) 的实时分派与处置建议 (异步版本)。, 从 prompts/dispatch.txt 加载原始指令模板, 指挥官准入契约：必须具备 Router 识别出的核心字段, test_commander_fails_when_llm_client_is_unavailable()

### Community 48 - "EmbeddingClient"
Cohesion: 0.09
Nodes (17): _detect_device(), EmbeddingClient, get_embedding_client(), LocalEmbeddingBackend, embedding_client.py · 统一 Embedding 接口 =========================================, 同步批量 embedding（在线程池中调用，不阻塞事件循环）。         bge-m3 推荐加前缀 "Represent this sentence:, 调用兼容 OpenAI embedding 协议的远程接口（硅基流动、智谱、本地 Ollama 等）。     仅在本地模型加载失败时作为降级兜底。, 异步批量调用远程 embedding 接口 (+9 more)

### Community 49 - "get_vector_client"
Cohesion: 0.10
Nodes (23): Base, Session, 种子数据注入器 (Knowledge Seeder)  功能： 1. 强行同步 SOP 数据库。 2. 预热向量库，灌入历史典型的处突经验案例。, seed_knowledge_base(), _seed_knowledge_base_async(), 知识库与数据持久化层入口 (Knowledge Layer Entry) - __init__.py ============================, migrate_v1_to_v2(), _migrate_v1_to_v2_async() (+15 more)

### Community 50 - "Logic Entry Structure: trigger+behavior+reason"
Cohesion: 0.18
Nodes (14): Five-Question Interview Framework for Persona Extraction, Logic Entry Structure: trigger+behavior+reason, Memory Palace Strategy Pipeline: Ingest -> Extract -> Generate SOP, Persona Digital Twin: LLM-generated Expert Avatar from Historical Logic Entries, Task Decomposition: LLM-driven Goal Breakdown into Executable Task Graph, Persona Extract: Question 4 - Counter-Intuitive Handling Pattern, Persona Extract: Question 5 - Summary and Synthesis Prompt, Persona Extract: Invoke/Answer Role Setting Prompt (+6 more)

### Community 51 - "BaseAgentSkill"
Cohesion: 0.15
Nodes (6): BaseHealthChecker, DependencyCheckResult, LLMRuntimeHealthChecker, SkillsRegistryHealthChecker, VectorStoreHealthChecker, WeChatCryptoHealthChecker

### Community 52 - "test_orchestrator.py"
Cohesion: 0.20
Nodes (9): 1. Summary, 2.1 决策方式, 2. Contacts, Appendix A：建议演示节奏, Appendix B：默认决策与评审项, Appendix C：批准记录, Appendix D：需求与验收证据追踪, Appendix E：实施顺序与变更闸门 (+1 more)

### Community 53 - "RedisStreamsQueue"
Cohesion: 0.11
Nodes (8): _resolve_database_uri(), test_legacy_database_manager_forbids_production_sqlite(), test_redis_block_timeout_is_treated_as_empty_poll(), test_redis_queue_atomically_requeues_failed_pending_message(), test_redis_queue_diagnostics_reports_stream_pending_consumers_and_dead_letters(), test_redis_queue_lists_dead_letters_as_safe_business_records(), test_redis_queue_put_deduplicates_business_message_ids(), test_request_trace_id_is_stable_for_the_request_lifecycle()

### Community 54 - "invoke.py"
Cohesion: 0.15
Nodes (23): ask_persona(), _generate_first_person_reply(), Any, query_persona_logic(), _rank_entries_by_relevance(), 数字分身调用模块 (Persona Invocation)  对应 PRD 中描述的 F-014： - 员工@分身名称并描述情况 - 系统检索逻辑档案，, 检索最相关的逻辑条目      策略：     1. 优先从 personas 表精确匹配 job_title     2. 如果匹配到，用向量检索en, 对逻辑条目按问题相关性排序（轻量级关键词匹配，无LLM开销）      策略：     1. 提取问句中的关键词     2. 计算每条条目的 trig (+15 more)

### Community 55 - "router/skill.py"
Cohesion: 0.23
Nodes (6): Any, 路由大管家：系统的意图分发与风险分诊中枢 (异步版本)。, 工业级配置加载：确保文件缺失时有安全默认值, 从独立 txt 文件中读取 Prompt，实现业务与代码分离, RouterSkill, test_router_fails_when_llm_client_is_unavailable()

### Community 56 - "embedding_client.py"
Cohesion: 0.10
Nodes (64): apiFromPage(), approvalContainsMarker(), assertExpectedDecompositionTransportFailure(), assertPlainFileInside(), assertRuntimeClean(), attachRuntime(), { chromium }, clearRuntime() (+56 more)

### Community 57 - "TestMemoryRetrieval"
Cohesion: 0.21
Nodes (16): aggregate_status(), check_specific(), CheckStatus, create_health_response(), get_health_registry(), health_check(), HealthCheckConfig, HealthCheckResponse (+8 more)

### Community 58 - "watcher/skill.py"
Cohesion: 0.25
Nodes (9): Dual-Layer Routing Architecture: L1 Regex + L2 LLM, SLA Timeout Guardrails: P0=3min, P1=10min, P2=30min, P3=120min, SOP Compliance Audit: Comparing Commander Instructions to Employee Replies, Router Agent: Runtime Configuration (config.yaml), Router Agent: System Prompt with Intent Taxonomy, Router Agent: Soul Charter / Design Philosophy, Watcher Agent: Runtime Configuration with SLA Timeouts, Watcher Agent: Audit Prompt with SLA and SOP Guardrails (+1 more)

### Community 59 - "push_logger.py"
Cohesion: 0.08
Nodes (34): demo_store_result(), 存储处理结果供轮询（由 queue_worker 调用）, _card_list_value(), _card_value(), _is_duplicate(), _markdown_text(), MessageDeliveryFailure, MessageProcessingFailure (+26 more)

### Community 60 - "skills.py"
Cohesion: 0.11
Nodes (18): 10. 最终完成定义, 1. 结论, 2.1 明确排除项, 2. 固定技术基线, 3.1 Graphify, 3.2 已存在的主要实现证据, 3.3 当前 PostgreSQL 业务样本, 3. 当前状态快照 (+10 more)

### Community 61 - "skills/__init__.py"
Cohesion: 0.08
Nodes (32): 核心引擎层 (Core Engine Layer) - __init__.py =======================================, BaseAgentSkill, Exception, 智能体核心抽象基类 (Agent Skill Base)  本模块定义了系统中所有智能体（Router, Commander, MemoryOps 等）的最, 加载任务 prompt，自动检测同目录下的 soul.txt 并前置拼接。          目录约定：           prompts/, 热更新 soul/prompt 文件后调用，强制下次重新读取磁盘。, 业务级校验异常。     当流入智能体的上下文 (Context) 缺少必要字段或脏数据时抛出。     此异常不会触发系统熔断报警，只会优雅阻断当前调用。, 5 大特种智能体的最高抽象基类。     外部调度中枢只允许调用 `run()` 方法，绝不允许直接调用内部实现。      Soul 注入机制： (+24 more)

### Community 62 - "TodoWriteSkill"
Cohesion: 0.08
Nodes (64): install_error_handlers(), FastAPI, test_event_candidate_retry_enforces_roles_and_tenant_scope(), test_event_close_keeps_closed_state_when_candidate_generation_is_retryable(), test_admin_event_detail_returns_tenant_scoped_readable_dossier(), test_event_dossier_includes_persisted_watcher_and_experience_candidate(), _seed_complete_event(), test_event_watcher_check_does_not_fake_success_when_skill_fails() (+56 more)

### Community 63 - "wechat_crypto.py"
Cohesion: 0.23
Nodes (6): ContextTriggerTester, main(), 批量测试          Args:             file_path: 每行一条消息的文本文件路径, 查看某次推送的完整上下文          Args:             push_log_id: 推送日志 ID, ContextTrigger 调试工具      提供以下功能：     1. 单条消息测试 (--test)     2. 批量消息测试 (--bat, 测试单条消息          Returns:             {                 "message": str,

### Community 64 - "demo.sh"
Cohesion: 0.57
Nodes (7): scene1(), scene2(), scene3(), scene4(), scene5(), send(), demo.sh script

### Community 65 - "FastAPI"
Cohesion: 0.11
Nodes (24): HTTPAuthorizationCredentials, _api_key_principal(), _current_jwt_principal(), _error(), get_request_db(), Any, HTTPException, Request (+16 more)

### Community 66 - "PostgresDBClient"
Cohesion: 0.18
Nodes (7): _PostgresTransaction, Any, PostgreSQL async database client using asyncpg. Implements the same interface a, Database interface bound to one asyncpg transaction connection., Yield the database interface bound to one asyncpg transaction., Translate SQLite ? placeholders to PostgreSQL $1, $2, ..., _rowcount()

### Community 67 - "v2/schemas.py"
Cohesion: 0.47
Nodes (5): AgentInvokeRequest, BatchMessageRequest, MessageCreateV2, BaseModel, v2/schemas.py - API v2 schemas

### Community 68 - "demo_send_message"
Cohesion: 0.44
Nodes (10): get_attachment_content(), Any, Request, _raise_attachment_error(), _read_upload(), _simulator_owner(), _store(), upload_assistant_attachment() (+2 more)

### Community 69 - "logger_config.py"
Cohesion: 0.15
Nodes (24): EvidenceBackedKnowledgeRetriever, KnowledgeRetrievalError, KnowledgeSnapshotPersistenceError, Raised after a failed retrieval attempt has been durably recorded., Raised when retrieval evidence cannot be durably persisted., Retrieve candidates, verify relational truth, and persist evidence first., RetrievalRequest, ExperienceVectorStore (+16 more)

### Community 84 - "InMemoryQueue"
Cohesion: 0.20
Nodes (4): InMemoryQueue, Any, In-memory asyncio.Queue adapter implementing MessageQueueProtocol for DEMO_MODE., Wraps asyncio.Queue to implement MessageQueueProtocol.

### Community 85 - "MessageQueueProtocol"
Cohesion: 0.20
Nodes (5): MessageQueueProtocol, Any, Protocol, Message queue protocol for backend switching (Redis Streams / asyncio.Queue)., Async message queue interface (put, get, task_done, qsize, empty).

### Community 86 - "👴 智能体说明书：知识分身专家 (Persona_Expert_Agent)"
Cohesion: 0.15
Nodes (8): EmergencyNotifier, RuntimeError, 下发 P0 级致命事件告警（短信 + 连环语音呼叫）, Stop worker threads so application and test processes can exit cleanly., 通过已注入的真实供应商 Adapter 发送短信。, 通过已注入的真实供应商 Adapter 发起语音电话。, P0 告警：短信和语音电话应并行发出（不串行阻塞），         验证 sms_client 的 ThreadPoolExecutor 机制, 防轰炸测试：同一手机号 60 秒内多次 P0 告警，第2次起应被拦截

### Community 87 - "explore.md"
Cohesion: 0.12
Nodes (16): 1.1 PostgreSQL 迁移, 1.2 Redis 消息队列, 1.3 Docker 部署, 1.4 基础认证, 2.1 结构化日志, 2.2 LLM Fallback, 2.3 健康检查增强, 2.4 密钥管理 (+8 more)

### Community 88 - "MemoryPalaceUser"
Cohesion: 0.20
Nodes (5): HttpUser, MemoryPalaceUser, Locust load test for Memory Palace OS. Usage: locust -f scripts/locustfile.py -, Simulate emergency incident report, Simulate daily tourist query

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
Cohesion: 0.17
Nodes (6): APIChange, APIEndpoint, APIVersion, APIVersionStatus, api_versions.py · API 版本路由映射表 =================================================, VersionManager

### Community 93 - "AsyncDBClientProtocol"
Cohesion: 0.22
Nodes (5): AsyncDBClientProtocol, Any, Protocol, Database client protocol — defines the interface both PostgresDBClient and SQLi, Async database client interface (fetch_one, fetch_all, execute, transaction, clo

### Community 94 - "🚨 智能体说明书：现场指挥官 (Commander_Agent)"
Cohesion: 0.11
Nodes (59): Assert-BackupId(), Assert-DeploymentParameters(), Assert-DockerVolumeName(), Assert-ProjectName(), Assert-RestoreParameters(), Assert-VolumeEmpty(), Expand-VolumeArchive(), Get-ContainerStatusRows() (+51 more)

### Community 95 - "set_venue_id"
Cohesion: 0.11
Nodes (18): demo_send_message(), Demo 消息入口：直接构造 payload 推入队列，跳过企微加密。     仅在 DEMO_MODE=true 时可用。, get_venue_id(), Token, Multi-tenant isolation via contextvars — venue_id propagation., Set venue_id for current async context., Get current venue_id. Returns None if not set (wildcard mode)., Return (WHERE clause fragment, params) for tenant-aware queries.     Returns em (+10 more)

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
Cohesion: 0.10
Nodes (55): assign_task(), _audit_decomposition_failure(), _cleanup_decomposition_attempt(), close_event(), complete_task(), create_task(), _decode_json_field(), _decode_task() (+47 more)

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
Cohesion: 0.29
Nodes (10): _await_futures(), notification_action_readiness(), notification_channel_readiness(), NotificationUnavailable, Any, 紧急通讯组件 (Emergency SMS/Voice Client)  核心特性： 1. 异步非阻塞发送：使用 ThreadPoolExecutor，防止发短, 发送告警通知（便捷函数）      Args:         message: 告警消息         level: 告警级别 (P0/P1/P2/P3/P, send_alert() (+2 more)

### Community 106 - "test_core_pipeline.py"
Cohesion: 0.12
Nodes (53): adoptPendingPush(), apiFromPage(), apiResponseMatches(), captureWatcherScreenshot(), { chromium }, closeLatestLiveEvent(), collectApprovalDecisionRecords(), createApprovalRequests() (+45 more)

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
Cohesion: 0.11
Nodes (16): Secrets management — centralized validation at startup., Return list of missing REQUIRED secrets. Empty list = all good., Read a secret from an environment variable or its Docker-style file., read_secret(), Secrets, build_fallback_chain(), LLMFallbackChain, ModelConfig (+8 more)

### Community 113 - "cache.py"
Cohesion: 0.50
Nodes (3): Simple async TTL cache for hot queries., Decorator: caches async function results for ttl_seconds., ttl_cache()

### Community 114 - ".query_experience"
Cohesion: 0.11
Nodes (37): AsyncClient, main(), Initialize the frozen enterprise UAT baseline through the running API., _run(), Operational workflows exposed through stable, auditable entry points., _assert_pristine_journey(), bootstrap_uat_master_data(), _create_user() (+29 more)

### Community 115 - "apply.md"
Cohesion: 0.11
Nodes (47): apiRequest(), assert(), assertNoRuntimeErrors(), beginExpectedRejection(), BROWSER_EXECUTABLE, captureWorkspace(), { chromium }, compactAudit() (+39 more)

### Community 116 - "archive.md"
Cohesion: 0.18
Nodes (10): 1. 🔍 业务逻辑说明 (Business Logic), 2. 📥 输入契约 (Input Contract), 3. 🧠 交互红线与状态机 SOP (State Machine SOP), 4. 🧪 冒烟测试用例 (Smoke Test Cases), 5. 📤 输出契约 (Output Schema), 🔴 安全与防越狱红线 (Anti-Jailbreak), 👴 智能体说明书：知识分身专家 (Persona_Expert_Agent), 核心处理链路： (+2 more)

### Community 117 - "propose.md"
Cohesion: 0.10
Nodes (14): Orchestrator, Any, 默认路由          Args:             payload: 消息载荷          Returns:, 执行目标 Agent          [升级] 支持两种上下文模式:         - legacy_mode: 原有的 flat context (, 派发消息（queue_worker 的入口）, Agent 之间的交接          [升级] Scoped Context 模式下:         - 记录 from_agent 的 turn, 多智能体协作中枢     负责协调 Router、Commander、MemoryOps、Persona 等 Agent      [M2] 接受 App, 路由决策          集成 ContextTrigger 两阶段过滤：         1. 先调用 ContextTrigger 进行 Stage (+6 more)

### Community 118 - "🚨 智能体说明书：现场指挥官 (Commander_Agent)"
Cohesion: 0.20
Nodes (9): 1. 🔍 业务逻辑说明 (Business Logic), 2. 📥 输入契约 (Input Contract), 3. 🧠 决策 SOP (Standard Operating Procedures), 4. 🧪 验收测试用例 (Acceptance Test Cases), 5. 📤 输出契约 (Output Schema), 🔴 P0 级：生命安全 / 紧急火灾, 🟡 P2 级：普通客诉 / 财物丢失, 🚨 智能体说明书：现场指挥官 (Commander_Agent) (+1 more)

### Community 120 - "TestTaskGraph"
Cohesion: 0.12
Nodes (40): Requirement, _agent_success_rows(), _apply_journey_evidence(), _apply_runtime_evidence(), FeatureRegistryError, _live_deepseek_trace(), load_feature_registry(), Any (+32 more)

### Community 121 - "TestVectorStore"
Cohesion: 0.20
Nodes (4): query_experience 返回正确的数据结构, 写入后 query_experience 可以召回, 任何向量检索都必须显式绑定场地，缺失时拒绝执行。, TestVectorStore

### Community 122 - "init_database"
Cohesion: 0.25
Nodes (8): 4.1 产品目标, 4.2 成功指标, 4.3 非目标, 4. Objective, Objective A：任何演示人员都能稳定启动, Objective B：核心演示流程可重复, Objective C：企业能力可见且声明真实, Objective D：具备可交付质量

### Community 123 - "llm_wrapper.py"
Cohesion: 0.12
Nodes (14): _auto_validate(), EnvRule, EnvValidator, get_validator(), Any, Enum, str, env_validator.py · 环境变量验证器 (Fail-Fast) ======================================== (+6 more)

### Community 124 - "企业演示版架构与信任边界"
Cohesion: 0.29
Nodes (7): 产品边界, 企业演示版架构与信任边界, 信任边界, 已知风险与假设, 技术栈, 相关文档, 运行结构

### Community 125 - "close_vector_client"
Cohesion: 0.33
Nodes (5): close_vector_client(), Release Chroma's background runtime when the store is no longer used., Close and clear the lazily-created process-wide vector client., close_global_notification_workers(), Ensure imported notification workers never keep pytest alive.

### Community 126 - "企业演示版故障处理手册"
Cohesion: 0.33
Nodes (6): Verify 测试容器不退出, 企业演示版故障处理手册, 场景卡在 RUNNING, 演示前恢复基线, 页面打不开, 页面显示连接中断

### Community 127 - "企业演示版关键运行流程"
Cohesion: 0.33
Nodes (6): Pause、Stop 与 Reset, 企业演示版关键运行流程, 启动与健康检查, 场景运行, 断线与重连, 确定性失败恢复

### Community 128 - "Enterprise Demo V1 测试结果"
Cohesion: 0.29
Nodes (6): Enterprise Demo V1 测试结果, Graphify 架构校验, 已知非阻断警告, 浏览器 QA, 结论, 自动化测试

### Community 129 - "企业演示版交付指南"
Cohesion: 0.40
Nodes (5): 交付索引, 企业演示版交付指南, 启动, 推荐演示顺序, 演示话术边界

### Community 130 - "Docker 启停与恢复报告"
Cohesion: 0.40
Nodes (4): Docker 启停与恢复报告, 命令行为, 隔离确认, 验证结果

### Community 131 - "企业指挥中心视觉 QA"
Cohesion: 0.40
Nodes (4): 企业指挥中心视觉 QA, 修复记录, 截图, 视口结果

### Community 132 - "demo.ps1"
Cohesion: 0.38
Nodes (4): Invoke-Compose(), Invoke-DemoApi(), Test-LiveScenarios(), Wait-DemoHealth()

### Community 133 - "TestContextTier"
Cohesion: 0.20
Nodes (4): Any, Schedules persisted Watcher policies on the application event loop., Rebuild runtime jobs from persisted enabled policies., TaskScheduler

### Community 134 - "TestTaskGraph"
Cohesion: 0.11
Nodes (25): get_message(), get_session(), list_sessions(), _build_memory_content(), create_or_update_session(), delete_session(), get_message(), get_message_by_id() (+17 more)

### Community 135 - "setup_logging"
Cohesion: 0.50
Nodes (3): 工业级日志管理系统 (Global Logging System)  核心特性： 1. 多文件归档：将 Access, App, Error, Watch, 配置全局日志处理器。     在 main.py 或 orchestrator.py 启动时调用一次。, setup_logging()

### Community 136 - "企业演示版权限与访问边界"
Cohesion: 0.50
Nodes (4): 企业演示版权限与访问边界, 当前角色, 明确缺口, 资源操作矩阵

### Community 137 - "企业演示版测试覆盖图"
Cohesion: 0.50
Nodes (4): 企业演示版测试覆盖图, 已有覆盖, 建议新增, 缺口

### Community 138 - "test_agent_handoff.py"
Cohesion: 0.33
Nodes (6): 3.1 项目背景, 3.2 当前问题, 3.3 为什么现在做, 3.4 当前基线与差距, 3.5 当前工作区快照（2026-07-25）, 3. Background

### Community 139 - "demo_persona_finalize"
Cohesion: 0.40
Nodes (4): Enterprise Demo V1 审阅结果, 最终门禁, 结论, 问题闭环

### Community 141 - "Agent 与自动化边界"
Cohesion: 0.67
Nodes (3): Agent 与自动化边界, Kill switch 与恢复, Steering 与强制控制

### Community 142 - "企业演示版环境变量与密钥"
Cohesion: 0.67
Nodes (3): 企业演示版环境变量与密钥, 密钥结论, 生产化前检查

### Community 148 - "BaseModel"
Cohesion: 0.22
Nodes (25): _answer_all_questions(), _build_app(), _create_authorized_expert_and_interview(), RecordingExperienceExtractor, _set_principal(), _synchronize_next_transactions(), test_acting_employee_identity_rejects_impersonation_and_tenant_escape(), test_answer_and_interview_progress_are_committed_atomically() (+17 more)

### Community 149 - "Any"
Cohesion: 0.18
Nodes (30): create_knowledge(), create_sop(), _decode_knowledge(), delete_knowledge(), get_knowledge(), get_sop(), import_knowledge(), _knowledge_metadata() (+22 more)

### Community 150 - "Any"
Cohesion: 0.15
Nodes (24): ErrorContext, list_audit_logs(), list_llm_calls(), _is_raw_error_key(), _is_sensitive_key(), _normalized_key(), _OmitType, public_error_message() (+16 more)

### Community 151 - "Enum"
Cohesion: 0.12
Nodes (23): DeepSeekExperienceDraftExtractor, _evidence_source_excerpts(), ExperienceDraftExtractionError, ExperienceStateError, next_experience_status(), Any, RuntimeError, ValueError (+15 more)

### Community 152 - "str"
Cohesion: 0.24
Nodes (13): _attachment_payload(), attachment_storage_root(), AttachmentError, link_message_attachments(), LocalAttachmentStore, message_attachments(), prepare_message_attachments(), Any (+5 more)

### Community 153 - "Any"
Cohesion: 0.13
Nodes (17): AppSettings, Config, get_settings(), LLMSettings, MetricsSettings, BaseModel, QueueSettings, app_settings.py · Pydantic 强类型配置 (可选增强层) ====================================== (+9 more)

### Community 154 - "BaseModel"
Cohesion: 0.15
Nodes (25): AccountStatus, _coerce_setting(), _collect_registry_evidence(), create_user(), create_venue(), _decode_setting(), feature_registry(), get_trace_timeline() (+17 more)

### Community 155 - "Enum"
Cohesion: 0.20
Nodes (3): HealthCheckerRegistry, init_health_checks(), MessageQueueHealthChecker

### Community 156 - "Request"
Cohesion: 0.14
Nodes (21): arrayFrom(), attachmentForm(), clearSession(), emitAuthChange(), followMessage(), isTerminal(), isTransientRecoveryError(), listMessages() (+13 more)

### Community 157 - "str"
Cohesion: 0.12
Nodes (13): CompletedProcess, run_mvp_script(), test_deployment_commands_require_explicit_environment_file(), test_help_lists_complete_enterprise_mvp_command_set(), test_restore_accepts_prd_positional_backup_id(), test_restore_rejects_backup_id_path_traversal(), test_restore_rejects_shared_global_secrets_volume(), test_restore_rejects_tampered_artifact_checksum() (+5 more)

### Community 169 - "Any"
Cohesion: 0.11
Nodes (18): _decode_redis_text(), Any, Redis Streams message queue implementing MessageQueueProtocol for production., Return pending plus undelivered messages, excluding completed history., Return a stable operational view without exposing Redis internals to callers., Return newest dead letters in a backend-neutral representation., Atomically requeue one dead letter and prevent duplicate manual retries., Atomically enqueue the next attempt and acknowledge the failed attempt. (+10 more)

### Community 170 - "Queue"
Cohesion: 0.08
Nodes (24): 10.1 三层信息结构, 10.2 各入口规则, 10.3 永不显示的内容, 10. 技术详情折叠规则, 11. 响应式范围, 12. 现有页面迁移关系, 13. 页面级完成门禁, 1. 页面状态标记 (+16 more)

### Community 174 - "Any"
Cohesion: 0.15
Nodes (24): BlockingTodoLLMStub, insert_session(), test_complete_task_and_dependency_release_survive_restart_as_one_change(), test_complete_task_atomic_write_failure_keeps_memory_and_database_unchanged(), test_concurrent_same_key_returns_processing_and_rejects_new_fingerprint(), test_decompose_tasks_audits_task_graph_unavailable(), test_decompose_tasks_creates_tenant_scoped_graph_and_audit(), test_decompose_tasks_rejects_cross_tenant_session_and_assignee() (+16 more)

### Community 175 - "BaseModel"
Cohesion: 0.10
Nodes (19): LLMClient, Any, AsyncOpenAI, BaseException, 获取或初始化异步 OpenAI 客户端（单例懒加载）, 显式 MOCK_LLM 测试模式下按输出契约返回可识别的模拟结果。, 发起大模型调用，自带指数退避重试与防抖机制 (异步版本)。, [新] 带参考上下文的 LLM 调用          用于三层上下文压缩系统:         - context_messages: 从 Cold - (+11 more)

### Community 176 - "Exception"
Cohesion: 0.26
Nodes (19): _attempt_id(), _candidate_id(), _collect_evidence(), _decode_candidate(), DeepSeekEventExperienceCandidateExtractor, ensure_event_experience_candidate(), _fingerprint(), _json_text() (+11 more)

### Community 177 - "Any"
Cohesion: 0.16
Nodes (12): _auth_header(), PermissionEngineStub, _record_queue_event(), RecoverableQueueStub, seed_interrupted_runtime(), TaskGraphStub, test_admin_recovery_api_is_admin_only_and_never_reads_tenant_rows(), test_application_recovery_persists_global_run_and_all_phase_counts() (+4 more)

### Community 178 - "Path"
Cohesion: 0.10
Nodes (20): 10. 可读性验收, 11. 证据包规范, 12. 最终通过门禁, 1. 文档目的, 2.1 三类界面, 2.2 模拟器的真实性边界, 2.3 禁止项, 2. 产品边界 (+12 more)

### Community 182 - "Any"
Cohesion: 0.10
Nodes (20): 7.10.1 客户端输入, 7.10.2 企业微信, 7.10.3 短信与语音, 7.10 外部集成策略, 7.12.1 管理命令, 7.12.2 日志和指标, 7.12.3 升级要求, 7.12 运维与可观测性 (+12 more)

### Community 183 - "Any"
Cohesion: 0.07
Nodes (27): 0.1 摘要, 0.2 决策责任, 0.3 核心价值主张, 0. 摘要与文档责任, 11. 权限矩阵, 12. 用户体验与可读性规则, 15. 完成定义, 16. 不在本期范围 (+19 more)

### Community 184 - "AsyncOpenAI"
Cohesion: 0.30
Nodes (14): _active_recipient(), _approval_item(), _approval_status(), build_event_participant_delivery(), _candidate_label(), _json_object(), load_simulator_outbox(), _orphan_push_item() (+6 more)

### Community 185 - "Any"
Cohesion: 0.14
Nodes (9): PostgresDBClient, PostgreSQL client with asyncpg connection pool., _AcquireContext, _Connection, _Pool, test_postgres_execute_reports_conditional_update_rowcount(), test_postgres_password_with_url_reserved_characters_stays_out_of_dsn(), test_postgres_transaction_reuses_one_connection_with_database_interface() (+1 more)

### Community 188 - "5. Market Segments"
Cohesion: 0.40
Nodes (5): 5.1 企业决策者, 5.2 现场运营管理者, 5.3 企业技术评估者, 5.4 演示主讲人, 5. Market Segments

### Community 189 - "6. Value Propositions"
Cohesion: 0.40
Nodes (5): 6.1 对企业决策者, 6.2 对运营管理者, 6.3 对技术评估者, 6.4 价值曲线, 6. Value Propositions

### Community 190 - "7.4 标准演示剧本"
Cohesion: 0.40
Nodes (5): 7.4 标准演示剧本, Scenario 1：P0 应急事件处置, Scenario 2：运营知识问答, Scenario 3：老员工经验萃取与数字分身, Scenario 4：复杂任务拆解与恢复

### Community 191 - "._sync_send_sms"
Cohesion: 0.17
Nodes (21): Any, Tenant-aware audit helpers shared by formal API endpoints., write_audit(), check_event_before_closure(), close_watcher_finding(), create_watcher_policy(), _decode_policy(), FindingCloseRequest (+13 more)

### Community 192 - "7.14 Scenario Controller 详细设计"
Cohesion: 0.50
Nodes (4): 7.14.1 模块边界, 7.14.2 运行状态机, 7.14.3 并发和生命周期, 7.14 Scenario Controller 详细设计

### Community 193 - "7.16 统一数据与证据模型"
Cohesion: 0.50
Nodes (4): 7.16.1 场景定义, 7.16.2 运行快照, 7.16.3 步骤证据, 7.16 统一数据与证据模型

### Community 194 - "7.18 企业指挥中心页面规格"
Cohesion: 0.50
Nodes (4): 7.18.1 桌面布局, 7.18.2 视觉语义, 7.18.3 完整状态, 7.18 企业指挥中心页面规格

### Community 195 - "7.19 测试与验证方案"
Cohesion: 0.50
Nodes (4): 7.19.1 测试分层, 7.19.2 必测用例, 7.19.3 容器验收命令目标, 7.19 测试与验证方案

### Community 196 - "7.2 Docker 运行设计"
Cohesion: 0.50
Nodes (4): 7.2.1 默认 Demo 栈, 7.2.2 企业技术验证栈, 7.2.3 辅助命令, 7.2 Docker 运行设计

### Community 197 - "7.5 功能需求"
Cohesion: 0.50
Nodes (4): 7.5 功能需求, P0：V1 必须交付, P1：强烈建议交付, P2：后续版本

### Community 198 - "sms_client.py"
Cohesion: 0.08
Nodes (17): _send_wecom_delivery(), Any, 企业微信 API 工业级封装 (WeChat Work Client) - 异步版本  核心变更： 1. 使用 httpx.AsyncClient 替代 req, 下发 Markdown 消息 (异步版本), 发送确认卡片消息（企业微信交互卡片）          卡片包含：         - 事件摘要         - 两个按钮：「一键确认」「补充说明」, 企业微信服务端 API 客户端 (异步版本), 获取企微 Access Token (异步版本)。         采用 DCL (Double-Checked Locking) 机制，适配协程并发模型。, 底层消息发送引擎 (异步版本)，包含针对企微特定错误码的自愈逻辑 (+9 more)

### Community 199 - "7.15 API 契约"
Cohesion: 0.67
Nodes (3): 7.15.1 端点, 7.15.2 轮询策略, 7.15 API 契约

### Community 200 - "Workspace"
Cohesion: 0.20
Nodes (10): 6. 工作包与任务, W0：验收合同和执行骨架, W1：统一入口、消息和事件, W2：任务图、审批与通知, W3：Watcher、闭环与经验候选, W4：访谈、治理与 Chroma 发布, W5：经验复用和全链审计, W6：真实 App 重启恢复 (+2 more)

### Community 201 - "create_user"
Cohesion: 0.20
Nodes (17): test_employee_block_reason_survives_restart_until_manager_resumes_task(), test_employee_can_open_only_own_task_detail(), test_employee_can_open_published_sop_reference(), test_employee_can_start_and_complete_own_task_with_readable_result(), test_employee_sop_reference_hides_unpublished_foreign_and_wrong_version(), test_employee_task_result_and_block_reason_must_contain_readable_text(), test_employee_work_actions_hide_other_people_and_other_tenants_tasks(), test_employee_work_list_contains_only_own_tasks_and_related_events() (+9 more)

### Community 202 - "7. 完整演示旅程"
Cohesion: 0.11
Nodes (18): 7. 完整演示旅程, E2E-00 管理员确认运行配置和渠道真实性, E2E-01 打开企微助手并确认身份, E2E-02 发送自由文本和现场附件, E2E-03 完成智能受理并返回事件、SOP 和处置建议, E2E-04 在同一会话补充现场信息, E2E-05 使用 TodoWrite 生成可执行任务图, E2E-06 验证任务依赖、员工权限并回填检修证据 (+10 more)

### Community 204 - "test_canonical_ingress.py"
Cohesion: 0.22
Nodes (16): 设置全局消息队列（main.py lifespan 中调用）, set_message_queue(), _build_app(), test_approved_in_app_action_flows_from_real_approval_chain_into_simulator_outbox(), test_employee_cannot_retry_another_users_or_tenants_message(), test_employee_retries_own_dead_letter_once_without_duplicate_business_result(), test_event_participant_fanout_is_visible_only_in_each_frozen_simulator_session(), test_manager_can_restore_selected_employee_simulator_conversation_with_cards() (+8 more)

### Community 205 - "request"
Cohesion: 0.17
Nodes (17): blockWorkTask(), completeWorkTask(), employeeTaskPath(), errorDetails(), getAttachmentContent(), getKnowledgeSop(), getSimulatorOutbox(), getWorkEvent() (+9 more)

### Community 206 - "Any"
Cohesion: 0.27
Nodes (8): RuntimeError, Reject delivery when any frozen target is no longer simulator-safe., SimulatorRecipientsNotReady, validate_frozen_simulator_targets(), get_openai_tools_format(), 工具执行器 (Tool Executor)  核心职责: 1. 统一管理所有工具的注册和执行 2. 集成权限引擎，所有工具调用都经过权限检查 3. 提, 获取 OpenAI tools API 格式的工具定义      Returns:         OpenAI compatible tools lis, _register_builtin_tools()

### Community 208 - "test_event_experience_candidates.py"
Cohesion: 0.23
Nodes (10): EventExperienceCandidateError, RuntimeError, Raised when an event cannot participate in candidate extraction., _database(), RecordingCandidateExtractor, RetryableCandidateExtractor, _seed_closed_event_evidence(), test_closed_event_creates_one_unindexed_candidate_with_complete_evidence() (+2 more)

### Community 209 - "企业 MVP 备份、恢复与诊断"
Cohesion: 0.15
Nodes (9): 与升级流程的关系, 企业 MVP 备份、恢复与诊断, 创建备份, 前置条件, 恢复到新 Compose project, 查看状态, 独立恢复验收, 覆盖保护 (+1 more)

### Community 210 - "10. 实现决策"
Cohesion: 0.14
Nodes (14): 10.10 模型策略, 10.11 模拟器真实性, 10.12 展示数据契约, 10.13 重启恢复, 10.1 单一标准消息入口, 10.2 统一助手与内部 Agent 分离, 10.3 通用对话与专家 Persona 分离, 10.4 人类访谈文案与萃取 Prompt 分离 (+6 more)

### Community 212 - "Memory Palace OS 内部 UAT 发布就绪报告"
Cohesion: 0.15
Nodes (13): 1. 审计范围与当前基线, 2. PRD 7.15 功能完整性门禁, 3. PRD 7.16 发布阻断条件复核, 4. PRD 8.1 发布策略符合性, 5. UAT 证据索引, 6. 证据资产与文档完整性, 7. 运维、配置与 Secret 边界, 8. 发布决定与剩余门槛 (+5 more)

### Community 213 - "Memory Palace OS 企业 MVP 交付 PRD"
Cohesion: 0.15
Nodes (13): 1. Summary, 2.1 决策原则, 2. Contacts, 6.1 把现场消息变成可执行工作, 6.2 把个人经验变成组织能力, 6.3 把 AI 判断变成可审计过程, 6.4 把分散功能变成一个产品闭环, 6.5 用 MVP 验证真实业务价值 (+5 more)

### Community 214 - "3.3 当前不能直接交付的原因"
Cohesion: 0.15
Nodes (13): 3.1 产品定位, 3.2 现有能力基础, 3.3 当前不能直接交付的原因, 3.4 企业 MVP 的定义, 3.5 MVP 与 Demo、生产版的区别, 3.6 旧企业演示方案的处置, 3. Background, Demo 模式改变了产品行为 (+5 more)

### Community 215 - "ExperienceUsageLedger"
Cohesion: 0.14
Nodes (14): build_business_id(), Any, Stable human-readable identifiers for persisted business resources., ExperienceUsageContext, ExperienceUsageLedger, ExperienceUsagePersistenceError, Any, RuntimeError (+6 more)

### Community 216 - "企业 MVP Windows Docker 运维手册"
Cohesion: 0.17
Nodes (12): App 单服务重启, 企业 MVP Windows Docker 运维手册, 停机, 升级, 启动与迁移, 命令清单, 备份与恢复, 安全模型 (+4 more)

### Community 217 - "4.3 核心结果"
Cohesion: 0.17
Nodes (12): 4.1 产品目标, 4.2 试点规模假设, 4.3 核心结果, 4.4 非目标, 4. Objective, Objective A：试点用户可以独立完成工作, Objective B：每个产品功能都真实可用, Objective C：真实企业技术栈进入运行路径 (+4 more)

### Community 218 - "CanonicalMessageIngress"
Cohesion: 0.15
Nodes (23): CanonicalIngressError, CanonicalMessageIngress, IngressMessage, Any, Exception, A caller-visible canonical ingress rejection., Resolve identity, persist one message run, then enqueue one payload., APIInfoResponse (+15 more)

### Community 219 - "test_event_closure.py"
Cohesion: 0.53
Nodes (11): _assert_close_denied(), _create_event(), _event_detail(), _seed_approval(), _seed_task(), test_event_close_denies_approved_action_with_failed_execution(), test_event_close_denies_pending_approval(), test_event_close_denies_unfinished_task_and_keeps_event_open() (+3 more)

### Community 220 - "test_m4_final.py"
Cohesion: 0.27
Nodes (5): TodoWrite Skill - 任务分解, Any, 任务分解智能体      将复杂目标分解为具有依赖关系的任务图      输入:         - goal: 目标描述         - se, TodoWriteSkill, test_todo_rejects_decomposition_with_no_valid_tasks()

### Community 221 - "simulator_session_restore.test.cjs"
Cohesion: 0.18
Nodes (9): assert, createSimulatorHarness(), fs, memoryStorage(), path, simulatorHtml, simulatorScript, test (+1 more)

### Community 222 - "8. Release"
Cohesion: 0.18
Nodes (11): 8.10 MVP 完成定义, 8.1 发布策略, 8.2 Milestone 0：冻结范围并恢复正确基线, 8.3 Milestone 1：正式运行与安全基线, 8.4 Milestone 2：事件处理核心闭环, 8.5 Milestone 3：知识、Persona、Watcher 和 SOP, 8.6 Milestone 4：外部集成与运维交付, 8.7 Milestone 5：全功能验收与客户 UAT (+3 more)

### Community 223 - "Any"
Cohesion: 0.32
Nodes (3): _json_default(), Any, Persistent state for asynchronous message processing runs.

### Community 224 - "experienceInterviewPath"
Cohesion: 0.31
Nodes (10): acceptExperienceInterview(), completeExperienceInterview(), experienceInterviewPath(), experiencePath(), experienceRequestOptions(), getExperienceHome(), getExperienceInterview(), pauseExperienceInterview() (+2 more)

### Community 225 - "shared_client_refresh.test.cjs"
Cohesion: 0.22
Nodes (7): assert, fetchMock(), fs, jsonResponse(), path, test, vm

### Community 226 - "SensitivityLevel"
Cohesion: 0.13
Nodes (16): IntEnum, list_tool_permissions(), get_permission_engine(), 权限引擎 (Permissions Engine)  核心职责: 1. 定义工具敏感级别 (Level 0/1/2) 2. 在工具调用前插入权限检查 H, SensitivityLevel, _insert_formal_action_context(), test_event_participant_action_freezes_readable_simulator_targets(), test_event_participant_request_fails_without_creating_approval_when_recipient_is_not_ready() (+8 more)

### Community 227 - "init_experience_schema"
Cohesion: 0.28
Nodes (5): init_experience_schema(), Protocol, Portable relational schema for governed expert experience assets., Create experience asset tables and lookup indexes idempotently., _SchemaDatabase

### Community 228 - "compactBody"
Cohesion: 0.28
Nodes (9): answerExperienceInterview(), compactBody(), confirmExperienceCard(), experienceCardPath(), externalId(), reviseExperienceCard(), sendAssistantMessage(), sendExperienceFeedback() (+1 more)

### Community 229 - "Formal Client QA — 2026-07-29"
Cohesion: 0.25
Nodes (7): Coverage, Evidence, Finding, Formal Client QA — 2026-07-29, QA-RESP-001 — Task table is nearly unreadable at 375px, Runtime Health, Task Wait Recovery

### Community 230 - "event_dossier.py"
Cohesion: 0.42
Nodes (9): calculate_event_closure_conditions(), Any, _resource_label(), _activity_summary(), build_event_dossier(), _decode_json(), _person(), Any (+1 more)

### Community 231 - "5. Market Segments"
Cohesion: 0.29
Nodes (7): 5.1 试点企业运营负责人, 5.2 一线值班人员, 5.3 值班经理和审批人, 5.4 组织知识负责人, 5.5 客户系统管理员, 5.6 企业技术评估者, 5. Market Segments

### Community 232 - "7.14 质量与验收"
Cohesion: 0.29
Nodes (7): 7.14.1 自动化测试, 7.14.2 Live DeepSeek 验收, 7.14.3 浏览器 UAT, 7.14.4 持续运行与性能, 7.14.5 备份恢复验收, 7.14.6 客户可演示验收旅程, 7.14 质量与验收

### Community 233 - "7.3 端到端正式业务流程"
Cohesion: 0.29
Nodes (7): 7.3.1 事件上报, 7.3.2 智能判断与处置, 7.3.3 任务与审批, 7.3.4 通知与执行, 7.3.5 闭环与知识沉淀, 7.3.6 Watcher 审计, 7.3 端到端正式业务流程

### Community 234 - "4. 用户角色与核心任务"
Cohesion: 0.29
Nodes (7): 4.1 一线员工, 4.2 值班经理, 4.3 领域专家, 4.4 知识负责人, 4.5 系统管理员, 4.6 演示与交付人员, 4. 用户角色与核心任务

### Community 235 - "6. 领域模型"
Cohesion: 0.29
Nodes (7): 6.1 统一助手, 6.2 内部 Agent, 6.3 专家档案, 6.4 经验卡片, 6.5 SOP、案例和经验的边界, 6.6 渠道身份, 6. 领域模型

### Community 236 - ".run"
Cohesion: 0.38
Nodes (4): Any, 【模板方法】外部调度的唯一合法入口。         内部自动封装：高精度耗时统计、防崩溃全局异常捕获、前置安全护栏。          ⚠️  asyn, 子类强制契约 1：数据清洗与准入校验（同步）。         检查 context 是否包含 LLM 需要的字段，不满足则 raise SkillValid, 子类强制契约 2：核心业务逻辑（async）。         在此进行 Prompt 组装、大模型接口调用、结果 JSON 解析。         无论成

### Community 238 - "7.4 功能范围"
Cohesion: 0.33
Nodes (6): 7.4.1 业务功能, 7.4.2 Agent 功能, 7.4.3 企业治理功能, 7.4.4 数据与可靠性功能, 7.4.5 外部集成功能, 7.4 功能范围

### Community 239 - "13. 测试决策"
Cohesion: 0.33
Nodes (6): 13.1 测试原则, 13.2 必需测试层, 13.3 必需成功旅程, 13.4 必需失败旅程, 13.5 验收证据, 13. 测试决策

### Community 240 - "8. 功能需求"
Cohesion: 0.25
Nodes (3): FREE 工具 check_and_execute 返回 ok, APPROVAL 工具 check_and_execute 返回 pending_approval, TestPermissionEngine

### Community 241 - "v1/router.py"
Cohesion: 0.47
Nodes (5): _integration_status_rows(), integration_statuses(), external_integration_readiness(), Shared readiness rules for external channel integrations., wechat_integration_readiness()

### Community 244 - "6. 管理后台页面"
Cohesion: 0.40
Nodes (5): 6.1 运营协同, 6.2 互动与渠道, 6.3 组织知识, 6.4 组织与系统, 6. 管理后台页面

### Community 245 - "7.5 全功能可用标准"
Cohesion: 0.40
Nodes (5): 7.5.1 功能状态, 7.5.2 单项完成定义, 7.5.3 可见功能可用率, 7.5.4 系统管理与诊断, 7.5 全功能可用标准

### Community 246 - "14. 发布计划"
Cohesion: 0.40
Nodes (5): 14. 发布计划, P0：产品入口与真实性, P1：经验资产生命周期, P2：闭环采用, P3：真实企微验收

### Community 247 - "2. 产品方案"
Cohesion: 0.40
Nodes (5): 2.1 一个统一员工助手, 2.2 一个企微员工端模拟器, 2.3 一个管理后台, 2.4 一套经验资产, 2. 产品方案

### Community 249 - "TestDCLLock"
Cohesion: 0.50
Nodes (4): 5.1 员工助手, 5.2 企微接入模拟器, 5.3 管理后台, 5. 产品界面

### Community 250 - "Memory Palace OS"
Cohesion: 0.50
Nodes (3): Client Scope, Memory Palace OS, Workspace

### Community 251 - "7.11 API 与状态模型"
Cohesion: 0.50
Nodes (4): 7.11.1 核心 API 能力, 7.11.2 通用状态, 7.11.3 错误契约, 7.11 API 与状态模型

### Community 252 - "7.7 数据架构"
Cohesion: 0.50
Nodes (4): 7.7.1 权威数据源, 7.7.2 持久化要求, 7.7.3 备份与恢复, 7.7 数据架构

### Community 253 - "7.9 认证、角色与租户"
Cohesion: 0.50
Nodes (4): 7.9.1 MVP 角色, 7.9.2 认证要求, 7.9.3 租户要求, 7.9 认证、角色与租户

### Community 260 - "test_push_adoption_hardening.py"
Cohesion: 0.83
Nodes (3): insert_push_log(), test_push_adoption_concurrent_reviews_have_one_winner(), test_push_adoption_terminal_state_cannot_return_to_pending()

## Ambiguous Edges - Review These
- `RAG Retrieval Pipeline` → `Error Code Specification`  [AMBIGUOUS]
  docs/architecture.md · relation: conceptually_related_to

## Knowledge Gaps
- **590 isolated node(s):** `{ execFileSync }`, `{ randomUUID }`, `fs`, `path`, `{ chromium }` (+585 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **50 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `RAG Retrieval Pipeline` and `Error Code Specification`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `PersonaExtractSkill` connect `PersonaExtractSkill` to `verify_postgres_runtime.py`, `gateway.py`, `admin.py`, `skills/__init__.py`, `TodoWriteSkill`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Why does `SkillOutput` connect `orchestrator.py` to `PersonaSkill`, `PersonaExtractSkill`, `ContextTriggerSkill`, `.run`, `memory_ops/skill.py`, `WatcherSkill`, `CommanderSkill`, `AppContainer`, `propose.md`, `router/skill.py`, `SkillValidationError`, `test_m4_final.py`, `skills/__init__.py`, `TodoWriteSkill`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Why does `AsyncDBClient` connect `VersionManager` to `Request`, `logger_config.py`, `TestTaskGraph`, `SchedulerStub`, `.__init__`, `test_canonical_ingress.py`, `BaseModel`, `test_event_experience_candidates.py`, `Any`, `VectorStoreStub`, `save_confirmed_event`, `BaseModel`, `Enum`, `7. 核心流程`, `TodoWriteSkill`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **Are the 38 inferred relationships involving `Orchestrator` (e.g. with `AppContainer` and `ExperienceUsageContext`) actually correct?**
  _`Orchestrator` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `AsyncDBClient` (e.g. with `knowledge/db_client.py` and `VectorStoreStub`) actually correct?**
  _`AsyncDBClient` has 24 INFERRED edges - model-reasoned connections that need verification._
- **What connects `{ execFileSync }`, `{ randomUUID }`, `fs` to the rest of the system?**
  _590 weakly-connected nodes found - possible documentation gaps or missing edges._