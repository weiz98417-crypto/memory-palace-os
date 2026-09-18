from pathlib import Path


CLIENT_PATH = Path(__file__).parents[2] / "static" / "index.html"


def test_formal_client_exposes_every_prd_product_area():
    html = CLIENT_PATH.read_text(encoding="utf-8")
    required_views = {
        "dashboard",
        "events",
        "sessions",
        "tasks",
        "approvals",
        "actions",
        "knowledge",
        "experience",
        "watcher",
        "sops",
        "management",
        "settings",
        "diagnostics",
    }

    for view in required_views:
        assert f'id="view-{view}"' in html
        assert f'data-view="{view}"' in html


def test_formal_client_uses_real_mvp_api_contracts():
    html = CLIENT_PATH.read_text(encoding="utf-8")
    required_api_paths = {
        "/messages/",
        "/sessions/",
        "/admin/events",
        "/admin/tasks",
        "/admin/approvals",
        "/admin/action-requests",
        "/admin/push_logs",
        "/admin/knowledge",
        "/admin/experts",
        "/admin/experience-interviews",
        "/admin/experience-cards",
        "/admin/watcher/policies",
        "/admin/sops",
        "/admin/users",
        "/admin/settings",
        "/admin/integrations",
        "/admin/feature-registry",
        "/admin/health",
        "/admin/queue",
        "/admin/llm-calls",
        "/admin/audit-logs",
    }

    for path in required_api_paths:
        assert path in html


def test_formal_client_contains_no_static_success_or_fake_operational_data():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert "echarts" not in html.lower()
    assert "Math.random" not in html
    assert "declared_severity" not in html
    assert "SOP 发布成功，已同步至一线终端" not in html
    assert "成功拉通医疗与安保组" not in html
    assert "激活特种 Agent</div>\n                    <div class=\"sc-n\">5</div>" not in html


def test_formal_client_clears_login_credentials_when_showing_login_screen():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'showLogin:function(){byId("login-form").reset();' in html


def test_formal_client_venue_id_pattern_is_valid_in_modern_chromium():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'pattern="[A-Za-z0-9._\\-]+"' in html
    assert 'pattern="[A-Za-z0-9._-]+"' not in html


def test_formal_client_uses_supported_action_dialogs():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'id="action-dialog"' in html
    assert "function requestInput(" in html
    assert "function confirmAction(" in html
    assert "prompt(" not in html
    assert "confirm(" not in html


def test_action_dialog_settles_submitted_values_from_its_close_event():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert "var actionDialogResult=null;" in html
    assert 'actionDialogResult=values;closeDialog("action-dialog")' in html
    assert "var result=actionDialogResult;" in html
    assert "if(resolve)resolve(result)" in html
    assert 'closeDialog("action-dialog");if(resolve)resolve(values)' not in html


def test_formal_client_uses_authoritative_task_done_status():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert '<option>DONE</option>' in html
    assert '"DONE","CLOSED"' in html
    assert '["DONE"].indexOf(String(task.status).toUpperCase())' in html
    assert "task.attempts||0" in html
    assert "task.attempt_count||0" not in html


def test_admin_experience_detail_renders_human_readable_usage_records():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert "item.usage_records" in html
    assert "item.usage_summary" in html
    assert "采用记录" in html
    for label in (
        "检索命中",
        "查看详情",
        "助手回答引用",
        "反馈：有帮助",
        "反馈：不适用",
        "反馈：需要专家",
    ):
        assert label in html


def test_formal_client_explains_and_recovers_manually_blocked_tasks():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert "人工阻塞原因：" in html
    assert "task.block_reason" in html
    assert 'data-action="view-task"' in html
    assert '"view-task":this.openTask' in html
    assert 'data-action="unblock-task"' in html
    assert '"unblock-task":this.unblockTask' in html
    assert 'state==="BLOCKED"&&task.block_reason&&App.isManager()' in html
    assert 'api("/admin/tasks/"+encodeURIComponent(id)+"/unblock",{method:"POST"})' in html
    assert "人工阻塞已解除" in html

    unblock_body = html.split("unblockTask:async function(id){", 1)[1].split(
        "assignTask:async function(id){", 1
    )[0]
    assert "await this.loadTasks()" in unblock_body
    assert "error.action" in unblock_body
    assert "error.traceId" in unblock_body


def test_formal_client_keeps_task_table_readable_on_phone_widths():
    html = CLIENT_PATH.read_text(encoding="utf-8")
    tasks_view = html.split('<section id="view-tasks" class="view">', 1)[1].split(
        "</section>", 1
    )[0]
    phone_styles = html.split("@media(max-width:560px){", 1)[1].split(
        "@media(prefers-reduced-motion:reduce)", 1
    )[0]

    assert tasks_view.count('<table class="task-table">') == 1
    assert ".task-table{min-width:880px}" in phone_styles


def test_formal_client_uses_delegated_session_actions_instead_of_inline_javascript():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'data-action="close-session"' in html
    assert '"close-session":this.closeSession' in html
    assert 'onclick="App.closeSession' not in html


def test_formal_client_exposes_real_todo_write_and_human_task_execution():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'data-action="decompose-task"' in html
    assert 'id="task-decompose-form"' in html
    assert 'id="task-decompose-result"' in html
    assert 'api("/admin/tasks/decompose"' in html
    assert "result.tasks_created" in html
    assert "result.trace_id" in html
    assert "人工执行" in html
    assert 'id="task-agent"' not in html
    assert 'label:"执行 Agent"' not in html
    assert 'assigned_agent:byId("task-agent")' not in html


def test_todo_write_timeout_stops_waiting_and_preserves_recovery_trace():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'id="task-decompose-cancel"' in html
    assert "var TODO_DECOMPOSE_TIMEOUT_MS=120000;" in html
    assert "new AbortController()" in html
    assert 'headers:{"X-Trace-ID":traceId,"Idempotency-Key":idempotencyKey}' in html
    assert "sessionStorage.setItem(TODO_DECOMPOSE_STORAGE_KEY" in html
    assert 'CHECK_REQUIRED:"结果待确认"' in html
    assert 'api("/admin/tasks/decompositions/status?idempotency_key="+encodeURIComponent' in html
    assert "recoverTaskDecomposition" in html
    assert "todoDecompositionController.abort()" in html


def test_todo_write_success_is_not_overwritten_when_task_refresh_fails():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert "this.completeTaskDecomposition(result);await this.refreshTasksAfterDecomposition();" in html
    assert "this.completeTaskDecomposition(statusResult);await this.refreshTasksAfterDecomposition();" in html
    assert "refreshTasksAfterDecomposition:async function()" in html
    assert "拆解已成功，仅任务列表刷新失败" in html
    assert "operation.status=\"SUCCEEDED\"" in html
    assert "operation.trace_id" in html
    assert "completeTaskDecomposition(result);await this.loadTasks()" not in html
    assert "completeTaskDecomposition(statusResult);await this.loadTasks()" not in html


def test_todo_write_unknown_outcomes_and_logout_abort_stay_recoverable():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'outcomeUnknown=waitingWasStopped||!error.status||error.status>=500' in html
    assert 'if(this.todoDecomposition!==operation)return' in html
    assert 'operation.owner_user_id' in html
    assert 'operation.venue_id' in html
    assert 'this.restoreTaskDecomposition();this.showApp()' in html

    submit_body = html.split("submitTodoDecomposition:async function(operation){", 1)[1].split(
        "completeTaskDecomposition:function(result){", 1
    )[0]
    assert submit_body.index("clearTimeout(this.todoDecompositionTimer)") < submit_body.index(
        "this.completeTaskDecomposition(result)"
    )


def test_client_embeds_favicon_and_caps_visible_notifications():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert '<link rel="icon" href="/admin/brand/logo-primary.svg?v=20260804-3"' in html
    assert 'while(region.children.length>=3)region.firstElementChild.remove();' in html


def test_formal_client_can_initiate_and_inspect_controlled_actions():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'data-action="new-action-request"' in html
    assert 'id="controlled-actions-table"' in html
    assert 'this.requestControlledAction' in html
    assert 'api("/admin/action-requests"' in html
    assert 'byId("approval-filter").value||"ALL"' in html
    assert 'value:"send_in_app_alert"' in html
    assert "item.disabled=Boolean" in html
    assert "item.delivery_status" in html
    assert "动作已真实投递" in html
    assert "动作未完成投递" in html
    assert 'deliveryStatus==="RECORDED"' in html
    assert "审批已批准，业务决策已记录" in html
    assert "现场图片" in html
    assert "field_evidence" in html
    assert "item.delivery_error" in html


def test_formal_client_exposes_server_resolved_simulator_recipient_scope_and_delivery_summary():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'name:"recipient_scope"' in html
    assert 'value:"EVENT_PARTICIPANTS"' in html
    assert 'value:"SESSION"' in html
    assert "事件相关人员（内部系统接入）" in html
    assert "仅写入内部系统接入环境，不会发送到任何生产外部渠道" in html
    assert "recipient_scope:values.recipient_scope" in html
    assert "delivery.targets" in html
    assert "delivery.delivered_count" in html
    assert "delivery.target_count" in html
    assert "已送达内部系统接入环境" in html
    assert 'item.channel==="WECOM_SIMULATOR_OUTBOX"?"内部系统接入环境（联调）"' in html
    assert 'error.code!=="SIMULATOR_RECIPIENTS_NOT_READY"' in html
    assert "error.details.missing_recipients" in html
    assert "item.display_name" in html
    assert "item.reason" in html
    assert "批准内部系统接入通知或真实外部渠道动作后会记录在这里" in html
    assert "recipient_user_ids" not in html
    assert "recipient_session_ids" not in html


def test_formal_client_links_tasks_and_approvals_to_the_event_business_chain():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'id="task-event"' in html
    assert 'id="task-decompose-event"' in html
    assert 'event_id:byId("task-event").value' in html
    assert 'event_id:byId("task-decompose-event").value' in html
    assert 'selectedTask.event_id' in html
    assert 'selectedTask.session_id' in html
    assert 'task_id:selectedTask.id' in html
    assert '"Idempotency-Key":newRequestId()' in html
    assert "supersedes_approval_id" in html
    assert "item.business_id" in html
    assert "task.business_id" in html


def test_formal_client_renders_a_readable_event_dossier_with_folded_technical_ids():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert "事件卷宗 · " in html
    assert "处置时间线" in html
    assert "关联任务" in html
    assert "审批与受控动作" in html
    assert "处置依据" in html
    assert "技术与审计信息（默认隐藏）" in html
    assert 'class="technical-details"' in html
    assert "summary.business_id" in html
    assert "summary.next_action" in html
    assert "restoreBusinessLocation" in html
    assert 'history.pushState({event_id:id},"","/admin/events/"' in html

    main_source = (CLIENT_PATH.parent.parent / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/admin/events/{event_id}", include_in_schema=False)' in main_source


def test_formal_client_humanizes_event_dossier_statuses_channels_and_result_fields():
    html = CLIENT_PATH.read_text(encoding="utf-8")
    event_detail = html[
        html.index("openEvent:async function") : html.index("editEvent:async function")
    ]

    assert 'OPEN:"处理中"' in html
    assert 'COMPLETED:"已完成"' in html
    assert 'WECOM_SIMULATOR:"内部系统接入环境"' in html
    assert 'shield_clearance_mm:"护板间隙（毫米）"' in html
    assert 'brake_pad_thickness_mm:"制动片厚度（毫米）"' in html
    assert 'wheel_end_temperature_c:"轮端温度（℃）"' in html
    assert 'abnormal_noise:"是否存在异响"' in html
    assert 'brake_pull:"是否制动跑偏"' in html
    assert "humanizeActivitySummary(item.summary)" in event_detail
    assert "conversationStatusLabels" in event_detail
    assert "channelLabels" in event_detail


def test_formal_client_restores_stable_task_and_approval_detail_routes():
    html = CLIENT_PATH.read_text(encoding="utf-8")
    main_source = (CLIENT_PATH.parent.parent / "main.py").read_text(encoding="utf-8")

    assert '@app.get("/admin/tasks/{task_id}", include_in_schema=False)' in main_source
    assert '@app.get("/admin/approvals/{approval_id}", include_in_schema=False)' in main_source
    assert '/^\\/admin\\/(events|tasks|approvals)' in html
    assert 'this.navigate("tasks",true)' in html
    assert 'this.navigate("approvals",true)' in html
    assert 'history.pushState({task_id:id},"","/admin/tasks/"' in html
    assert 'history.pushState({approval_id:id},"","/admin/approvals/"' in html


def test_formal_client_brand_assets_resolve_from_nested_detail_routes():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'src="brand/' not in html
    assert 'src="/admin/brand/logo-primary.svg"' in html
    assert 'src="/admin/brand/brand-intro.mp4"' in html
    assert 'resetBusinessLocation:function(view)' in html
    assert 'historyEvent&&historyEvent.state&&historyEvent.state.view' in html


def test_formal_client_keeps_raw_approval_delivery_ids_out_of_the_business_summary():
    html = CLIENT_PATH.read_text(encoding="utf-8")
    approval_detail = html[
        html.index("openApproval:async function") : html.index(
            "requestControlledAction:async function"
        )
    ]

    assert "受控动作已完成" in approval_detail
    assert "已收到内部系统接入通知" in approval_detail
    assert "recipientNames" in approval_detail
    assert "executionSummary" in approval_detail

    business_result_position = approval_detail.index("<dt>执行结果</dt>")
    technical_details_position = approval_detail.index(
        '<details class="technical-details"'
    )
    raw_result_position = approval_detail.index("<dt>原始执行回执</dt>")
    assert business_result_position < technical_details_position < raw_result_position
    visible_detail = approval_detail[:technical_details_position]
    technical_detail = approval_detail[technical_details_position:]
    assert "businessValue(execution.result||execution" not in visible_detail
    assert "item.execution_error||\"请展开" not in visible_detail
    assert "jsonPreview(execution)" in technical_detail
    assert "<dt>原始执行错误</dt>" in technical_detail
    assert "item.execution_error" in technical_detail


def test_formal_admin_navigation_does_not_expose_management_views_to_operators():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    for view in ("dashboard", "events", "sessions", "tasks"):
        marker = f'data-view="{view}"'
        navigation = html[html.index(marker) : html.index("</button>", html.index(marker))]
        assert 'data-roles="admin,manager"' in navigation
        assert "operator" not in navigation

    assert 'if(Auth.user.role==="operator"){window.location.replace("/assistant/");return}' in html


def test_formal_client_can_initiate_and_inspect_experience_interviews():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'data-action="new-interview"' in html
    assert 'data-action="view-experience-interview"' in html
    assert "authorization_scopes" in html
    assert "item.progress||{}" in html


def test_formal_client_renders_item_level_feature_acceptance_evidence():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert "registry.items||[]" in html
    assert "item.acceptance||{}" in html
    assert "registry-item-table" in html
    assert "缺失证据" in html
    assert "阻塞覆盖项" in html


def test_formal_client_compacts_registry_trace_lists_without_losing_details():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert '.trace-cell{max-width:240px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' in html
    assert 'var traceTitle=traces.length?traces.join(" · "):"-"' in html
    assert 'var traceLabel=traces.length?traces[0]+(traces.length>1?" +"+(traces.length-1):""):"-"' in html
    assert '<td class="mono trace-cell" title="\'+escapeHtml(traceTitle)+\'">\'+escapeHtml(traceLabel)' in html


def test_formal_client_can_query_and_render_a_tenant_scoped_trace_timeline():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'id="trace-search-form"' in html
    assert 'id="trace-search-input"' in html
    assert 'id="trace-summary"' in html
    assert 'id="trace-timeline"' in html
    assert 'api("/admin/traces/"+encodeURIComponent(traceId))' in html


def test_formal_client_is_the_default_application_entrypoint():
    main_source = (CLIENT_PATH.parent.parent / "main.py").read_text(encoding="utf-8")

    assert '@app.get("/", include_in_schema=False)' in main_source
    assert 'RedirectResponse(url="/admin/", status_code=302)' in main_source


def test_formal_client_manages_the_governed_expert_experience_lifecycle():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'data-view="experience"' in html
    assert 'id="view-experience"' in html
    assert "专家经验" in html
    assert "/admin/experts" in html
    assert "/admin/experience-interviews" in html
    assert "/admin/experience-cards" in html
    assert '"/submit"' in html
    assert '"/reject"' in html
    assert '"/publish"' in html
    assert '"/deprecate"' in html
    assert 'EXPERT_CONFIRMED:"专家已确认"' in html
    assert 'DEPRECATED:"已停用"' in html
    assert 'label:"经验授权范围"' in html
    assert 'label:"当前场地全部员工"' in html
    assert 'label:"指定角色：值班经理"' in html
    assert 'label:"指定角色：现场操作员"' in html
    assert '"指定员工："+item.display_name' in html
    assert 'scope_type:"VENUE"' in html
    assert 'scope_type:"ROLE"' in html
    assert 'scope_type:"USER"' in html
    assert "scope_value:Auth.user.venue_id" in html
    assert "/admin/personas" not in html
    assert "数字分身" not in html


def test_event_dossier_runs_and_renders_event_level_watcher_checks():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert "闭环前合规检查" in html
    assert "runEventWatcher:async function(id)" in html
    assert 'api("/admin/events/"+encodeURIComponent(id)+"/watcher-check",{method:"POST"})' in html
    assert "dossier.watcher_runs" in html
    assert "target_snapshot" in html
    assert "证据完整，可闭环" in html
    assert "Watcher 检查失败" in html


def test_event_dossier_exposes_retryable_experience_candidate_journey():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert "dossier.experience_candidates" in html
    assert "经验候选生成失败 / 可重试" in html
    assert "retryExperienceCandidate:async function(id)" in html
    assert (
        'api("/admin/events/"+encodeURIComponent(id)+"/experience-candidate/retry",'
        '{method:"POST"})'
    ) in html
    assert "startInterviewFromCandidate:async function(eventId,candidateId)" in html
    assert "source_event_id:eventId" in html
    assert "发现可沉淀经验，已生成待审核候选" in html


def test_diagnostics_renders_persisted_startup_and_recovery_runs():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'id="recovery-run-list"' in html
    assert 'api("/admin/recovery-runs?limit=20")' in html
    assert "recovery_runs" in html
    assert "task_graph_recovered_count" in html
    assert "redis_claimed_count" in html
    assert "instance_id" in html


def test_diagnostics_renders_unified_runtime_agents_and_channel_policy():
    html = CLIENT_PATH.read_text(encoding="utf-8")

    assert 'api("/admin/diagnostics")' in html
    assert "diagnostics.runtime" in html
    assert "diagnostics.deepseek" in html
    assert "diagnostics.agents" in html
    assert "diagnostics.agent_coverage" in html
    assert "diagnostics.channels" in html
    assert 'data-action="deepseek-probe"' in html
    assert 'api("/admin/diagnostics/deepseek-probe",{method:"POST"})' in html
    assert 'id="diagnostic-blockers"' in html
    assert "主旅程不得开始" in html
    assert "修复：" in html
    assert 'action:"diagnostics-users"' in html
    assert 'action:"diagnostics-refresh"' in html
    assert "agentCoverage.error_type" in html
    assert "Agent 证据采集异常" in html
    assert "检查 PostgreSQL 与模型调用日志" in html
    assert 'data-action="enable-simulator-identity"' in html
    assert 'api("/channels/identities",{method:"POST"' in html
    assert 'channel:"WECOM_SIMULATOR"' in html
    assert "真实外部渠道" in html
    assert "企微" not in html
    assert "企微模拟器" not in html
    assert "DISABLED_BY_POLICY" in html
