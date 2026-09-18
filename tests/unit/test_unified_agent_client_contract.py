from pathlib import Path


ROOT = Path(__file__).parents[2]
MAIN_PATH = ROOT / "main.py"
SHARED_CLIENT_PATH = ROOT / "static" / "shared" / "client.js"
ASSISTANT_HTML_PATH = ROOT / "static" / "assistant" / "index.html"
ASSISTANT_SCRIPT_PATH = ROOT / "static" / "assistant" / "app.js"
ASSISTANT_STYLE_PATH = ROOT / "static" / "assistant" / "styles.css"
SIMULATOR_HTML_PATH = ROOT / "static" / "simulator" / "wecom" / "index.html"
SIMULATOR_SCRIPT_PATH = ROOT / "static" / "simulator" / "wecom" / "app.js"
SIMULATOR_STYLE_PATH = ROOT / "static" / "simulator" / "wecom" / "styles.css"
COMPOSE_PATH = ROOT / "deploy" / "docker-compose.yml"


def test_unified_agent_clients_have_independent_product_routes():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert 'RedirectResponse(url="/assistant/", status_code=302)' in source
    assert 'app.mount("/assistant", StaticFiles(directory="static/assistant", html=True)' in source
    assert 'RedirectResponse(url="/simulator/wecom/", status_code=302)' in source
    assert '"/simulator/wecom",' in source
    assert 'StaticFiles(directory="static/simulator/wecom", html=True)' in source
    assert 'app.mount("/admin", StaticFiles(directory="static", html=True)' in source


def test_shared_client_uses_formal_auth_and_unified_assistant_contracts():
    source = SHARED_CLIENT_PATH.read_text(encoding="utf-8")

    required_paths = {
        "/auth/login",
        "/auth/refresh",
        "/auth/logout",
        "/auth/me",
        "/assistant/messages",
        "/assistant/sessions",
        "/channels/simulator-identities",
        "/channels/simulator/sessions/",
    }
    for path in required_paths:
        assert path in source

    assert 'var API_BASE = "/api/v1"' in source
    assert 'headers.set("Authorization", "Bearer " + session.accessToken)' in source
    assert "sessionStorage" in source
    assert "external_message_id" in source
    assert "external_conversation_id" in source
    assert "acting_user_id" in source
    assert "attachments" in source
    assert "window.MemoryPalaceClient" in source
    assert "Math.random" not in source
    assert "setInterval" not in source
    assert "mock" not in source.lower()


def test_shared_client_exposes_employee_owned_work_contract():
    source = SHARED_CLIENT_PATH.read_text(encoding="utf-8")

    required_paths = {
        '"/assistant/work"',
        '"/assistant/work/tasks/"',
        '"/start"',
        '"/complete"',
        '"/block"',
    }
    for path in required_paths:
        assert path in source

    assert "work: {" in source
    assert "list: listWork" in source
    assert "task: getWorkTask" in source
    assert "start: startWorkTask" in source
    assert "complete: completeWorkTask" in source
    assert "block: blockWorkTask" in source
    assert 'request("/admin/tasks' not in source


def test_shared_client_exposes_governed_employee_experience_contract():
    source = SHARED_CLIENT_PATH.read_text(encoding="utf-8")

    required_paths = {
        '"/assistant/experience"',
        '"/assistant/experience/interviews/"',
        'experienceInterviewPath(interviewId, options, "accept")',
        'experienceInterviewPath(interviewId, options, "answers")',
        'experienceInterviewPath(interviewId, options, "pause")',
        'experienceInterviewPath(interviewId, options, "resume")',
        '"/assistant/experience/cards/"',
        'experienceCardPath(cardId, options, "confirm")',
        '"/assistant/experience/search"',
        'experienceCardPath(cardId, options, "feedback")',
    }
    for path in required_paths:
        assert path in source

    required_methods = {
        "home: getExperienceHome",
        "interview: getExperienceInterview",
        "acceptInterview: acceptExperienceInterview",
        "answerInterview: answerExperienceInterview",
        "pauseInterview: pauseExperienceInterview",
        "resumeInterview: resumeExperienceInterview",
        "completeInterview: completeExperienceInterview",
        "reviseCard: reviseExperienceCard",
        "confirmCard: confirmExperienceCard",
        "search: searchExperience",
        "feedback: sendExperienceFeedback",
    }
    assert "experience: {" in source
    for method in required_methods:
        assert method in source

    assert '"Idempotency-Key"' in source
    complete_signature = "async function completeExperienceInterview(interviewId, options)"
    assert complete_signature in source
    complete_source = source[
        source.index(complete_signature) : source.index("async function reviseExperienceCard")
    ]
    assert 'experienceRequestOptions(options, "POST")' in complete_source
    assert "body:" not in complete_source


def test_wecom_simulator_exposes_the_real_expert_experience_journey():
    html = SIMULATOR_HTML_PATH.read_text(encoding="utf-8")
    script = SIMULATOR_SCRIPT_PATH.read_text(encoding="utf-8")
    shared = SHARED_CLIENT_PATH.read_text(encoding="utf-8")

    for element_id in {
        'id="experience-summary"',
        'id="interview-dialog"',
        'id="interview-progress"',
        'id="interview-turns"',
        'id="interview-answer-form"',
        'id="interview-answer"',
        'id="interview-pause-button"',
        'id="interview-resume-button"',
        'id="interview-complete-form"',
        'id="experience-card-dialog"',
        'id="experience-card-readonly"',
        'id="experience-card-revise-form"',
        'id="experience-card-change-note"',
        'id="experience-card-confirm-button"',
    }:
        assert element_id in html

    assert "function experiencePath(path, options)" in shared
    assert 'queryString(options, ["acting_user_id"])' in shared
    assert "async function loadExperience()" in script
    assert "Client.experience.home(experienceOptions(signal, userId))" in script
    assert 'kind: "interview"' in script
    assert 'kind: "experience-card"' in script
    assert "Client.experience.acceptInterview(interview.id, experienceOptions())" in script
    assert "Client.experience.answerInterview(interview.id" in script
    assert "Client.experience.pauseInterview(interview.id, experienceOptions())" in script
    assert "Client.experience.resumeInterview(interview.id, experienceOptions())" in script
    assert "Client.experience.completeInterview(interview.id, experienceOptions())" in script
    assert "Client.experience.reviseCard(card.id" in script
    assert "Client.experience.confirmCard(card.id, experienceOptions())" in script
    assert "await Promise.all([loadEmployeeSessions" in script
    refresh_source = script[
        script.index("async function refresh()") : script.index("async function handleLogin")
    ]
    assert "await Promise.all([loadEmployeeSessions" in refresh_source


def test_employee_assistant_is_a_real_api_driven_work_surface():
    html = ASSISTANT_HTML_PATH.read_text(encoding="utf-8")
    script = ASSISTANT_SCRIPT_PATH.read_text(encoding="utf-8")
    styles = ASSISTANT_STYLE_PATH.read_text(encoding="utf-8")

    required_surfaces = {
        'id="login-form"',
        'id="session-list"',
        'id="message-stream"',
        'id="message-form"',
        'id="attachment-note"',
        'id="task-list"',
        'id="event-list"',
        'id="experience-own-card-list"',
        'data-section="chat"',
        'data-section="work"',
        'data-section="experience"',
        'data-section="me"',
        'aria-live="polite"',
    }
    for surface in required_surfaces:
        assert surface in html

    assert 'src="/shared/client.js"' in html
    assert 'href="/shared/base.css"' in html
    assert 'href="/assistant/styles.css?v=20260915-1"' in html
    assert html.count('src="/admin/brand/logo-primary.svg"') == 4
    assert ">AI<" not in html
    assert 'src="/assistant/app.js"' in html
    assert "Client.auth.login" in script
    assert "Client.auth.restore" in script
    assert "Client.assistant.sessions" in script
    assert "Client.assistant.messages" in script
    assert "Client.assistant.send" in script
    assert "Client.assistant.follow" in script
    assert "business_cards" in script
    assert "@media (max-width: 720px)" in styles
    assert "safe-area-inset-bottom" in styles
    assert "Math.random" not in script
    assert "setInterval" not in script
    assert "target_agent" not in script
    assert "trace_id" not in script


def test_employee_work_page_operates_on_personal_tasks_and_events():
    html = ASSISTANT_HTML_PATH.read_text(encoding="utf-8")
    script = ASSISTANT_SCRIPT_PATH.read_text(encoding="utf-8")

    required_surfaces = {
        'id="work-filter-form"',
        'id="work-task-status"',
        'id="work-event-status"',
        'id="work-summary"',
        'id="work-error"',
        'id="task-list"',
        'id="event-list"',
        'id="task-detail-dialog"',
        'id="task-detail-title"',
        'id="task-complete-form"',
        'id="task-complete-summary"',
        'id="task-block-form"',
        'id="task-block-reason"',
    }
    for surface in required_surfaces:
        assert surface in html

    required_calls = {
        "Client.work.list",
        "Client.work.task",
        "Client.work.start",
        "Client.work.complete",
        "Client.work.block",
    }
    for call in required_calls:
        assert call in script

    assert 'data-task-id="' in script
    assert "business-card-region" not in html
    assert "当前会话暂无工作项" not in script


def test_published_sop_references_open_in_employee_and_simulator_clients():
    main_source = MAIN_PATH.read_text(encoding="utf-8")
    client_source = SHARED_CLIENT_PATH.read_text(encoding="utf-8")
    assistant_html = ASSISTANT_HTML_PATH.read_text(encoding="utf-8")
    assistant_script = ASSISTANT_SCRIPT_PATH.read_text(encoding="utf-8")
    simulator_script = SIMULATOR_SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"/assistant/knowledge/sop/{sop_id}"' in main_source
    assert '"/assistant/knowledge/sops/"' in client_source
    assert "knowledge: {" in client_source
    assert "sop: getKnowledgeSop" in client_source

    for surface in {
        'id="sop-detail-dialog"',
        'id="sop-detail-title"',
        'id="sop-detail-body"',
        'id="sop-detail-error"',
    }:
        assert surface in assistant_html

    assert "Client.knowledge.sop" in assistant_script
    assert 'type: "sop"' in assistant_script
    assert "publisher_name" in assistant_script
    assert "published_at" in assistant_script
    assert "employee_url" in simulator_script
    assert "publisher_name" in simulator_script
    assert "published_at" in simulator_script
    assert "card.version" in simulator_script


def test_experience_references_render_human_evidence_in_both_employee_clients():
    assistant_script = ASSISTANT_SCRIPT_PATH.read_text(encoding="utf-8")
    simulator_script = SIMULATOR_SCRIPT_PATH.read_text(encoding="utf-8")

    for script in (assistant_script, simulator_script):
        assert "card.expert_name" in script
        assert "card.source_event_business_id" in script
        assert "card.applicable_context" in script
        assert "card.authorization_scopes" in script
        assert "card.relevance" in script
        assert "非专家本人实时回复" in script


def test_employee_experience_page_completes_cocreation_and_feedback_journeys():
    html = ASSISTANT_HTML_PATH.read_text(encoding="utf-8")
    script = ASSISTANT_SCRIPT_PATH.read_text(encoding="utf-8")

    required_surfaces = {
        'id="experience-profile-summary"',
        'id="experience-error"',
        'id="interview-list"',
        'id="experience-own-card-list"',
        'id="experience-search-form"',
        'id="experience-search-query"',
        'id="experience-search-results"',
        'id="interview-dialog"',
        'id="interview-progress"',
        'id="interview-answer-form"',
        'id="interview-answer"',
        'id="interview-complete-form"',
        'id="interview-extraction-status"',
        'id="interview-complete-button"',
        'id="experience-card-dialog"',
        'id="experience-card-origin"',
        'id="experience-card-revise-form"',
        'id="experience-card-change-note"',
    }
    for surface in required_surfaces:
        assert surface in html

    required_calls = {
        "Client.experience.home",
        "Client.experience.interview",
        "Client.experience.acceptInterview",
        "Client.experience.answerInterview",
        "Client.experience.pauseInterview",
        "Client.experience.resumeInterview",
        "Client.experience.completeInterview",
        "Client.experience.reviseCard",
        "Client.experience.confirmCard",
        "Client.experience.search",
        "Client.experience.feedback",
    }
    for call in required_calls:
        assert call in script

    assert 'data-interview-id="' in script
    assert 'data-experience-card-id="' in script
    assert 'data-feedback-card-id="' in script
    assert "正在萃取" in script
    assert "Client.experience.completeInterview(interview.id)" in script
    assert "if (shouldExtract) await completeInterview();" in script
    assert "payload.extraction" in script
    for removed_interview_field in {
        'id="interview-draft-title"',
        'id="interview-applicable-context"',
        'id="interview-signals"',
        'id="interview-actions"',
        'id="interview-decision-rule"',
        'id="interview-rationale"',
        'id="interview-prohibitions"',
        'id="interview-exceptions"',
        'id="interview-source-excerpts"',
    }:
        assert removed_interview_field not in html
        assert removed_interview_field.removeprefix('id="').removesuffix('"') not in script
    assert "renderExperienceFromMessages" not in script
    assert "当前会话暂无经验内容" not in script


def test_wecom_simulator_is_explicitly_bounded_and_reads_real_chain_state():
    html = SIMULATOR_HTML_PATH.read_text(encoding="utf-8")
    script = SIMULATOR_SCRIPT_PATH.read_text(encoding="utf-8")
    styles = SIMULATOR_STYLE_PATH.read_text(encoding="utf-8")

    required_surfaces = {
        "企业内部系统接入环境",
        'id="login-form"',
        'id="identity-select"',
        'id="simulator-message-stream"',
        'id="simulator-message-form"',
        'id="delivery-status"',
        'id="outbox-summary"',
        'id="evidence-drawer"',
        'id="evidence-channel"',
        'id="evidence-message"',
        'id="evidence-session"',
        'id="evidence-trace"',
        'id="admin-session-link"',
        'aria-live="polite"',
    }
    for surface in required_surfaces:
        assert surface in html

    assert 'src="/shared/client.js?v=20260803-1"' in html
    assert 'href="/shared/base.css"' in html
    assert 'href="/simulator/wecom/styles.css?v=20260915-1"' in html
    assert '<div><strong>企业运营助手</strong><span>企业内部系统接入环境</span></div>' in html
    assert html.count('src="/admin/brand/logo-primary.svg"') == 3
    assert ">AI<" not in html
    assert 'src="/simulator/wecom/app.js?v=20260804-3"' in html
    assert "Client.auth.login" in script
    assert "Client.simulator.identities" in script
    assert "Client.simulator.send" in script
    assert "Client.simulator.outbox" in script
    assert "Client.assistant.messages" in script
    assert "outbox: []" in script
    assert "function renderOutboxItem" in script
    assert "item.status_summary" in script
    assert "item.supersedes_business_id" in script
    assert "替代上一张已拒绝审批" in script
    assert "item.supersedes_approval_id" not in script
    assert 'DELIVERED: "已送达内部系统接入环境"' in script
    assert '<img src="/admin/brand/logo-primary.svg" alt="">' in script
    brand_message_avatar = (
        '<span class="message-avatar brand-avatar">'
        '<img src="/admin/brand/logo-primary.svg" alt="">'
        '</span>'
    )
    assert script.count(brand_message_avatar) == 4
    for legacy_avatar in (
        '<span class="message-avatar">回</span>',
        '<span class="message-avatar">经</span>',
        '<span class="message-avatar">卡</span>',
    ):
        assert legacy_avatar not in script
    assert ': "AI"' not in script
    assert "企微" not in html
    assert "模拟" not in html
    assert "企微" not in script
    assert "模拟" not in script
    assert "state.outbox = UI.arrayFrom" in script
    assert "await syncOutbox(sessionId, userId);" in script
    assert "审批回流暂不可用 · 已保留会话" in script
    assert 'window.addEventListener("focus"' in script
    assert "loadSession(false);" in script
    assert "sessionStorage" in script
    assert "response.status" in script
    assert "response.trace_id" in script
    assert '"/admin/index.html?"' in script
    assert "@media (max-width: 980px)" in styles
    mobile_styles = styles[styles.index("@media (max-width: 620px)") :]
    assert "flex-wrap: wrap" in mobile_styles
    assert "position: static" in mobile_styles
    assert ".wecom-outbox-card" in styles
    assert "Math.random" not in script
    assert "setInterval" not in script
    assert "真实企微已接入" not in html
    assert "模拟成功" not in html

    load_session = script[
        script.index("async function loadSession") : script.index("function followRun")
    ]
    sync_outbox = script[
        script.index("async function syncOutbox") : script.index("function latestPending")
    ]
    assert "Promise.all" not in load_session
    assert load_session.index("applyMessagePayload(payload);") < load_session.index(
        "await syncOutbox(sessionId, userId);"
    )
    assert "state.outboxUnavailable = true;" in sync_outbox
    assert "timeoutMs: 15000" in sync_outbox
    assert "showError" not in sync_outbox


def test_wecom_simulator_keeps_grid_rows_stable_when_the_error_region_is_hidden():
    styles = SIMULATOR_STYLE_PATH.read_text(encoding="utf-8")

    expected_rows = {
        ".wecom-head {": 1,
        ".simulator-error {": 2,
        ".wecom-messages {": 3,
        ".wecom-composer {": 4,
    }
    for selector, row in expected_rows.items():
        start = styles.index(selector)
        rule = styles[start : styles.index("}", start)]
        assert f"grid-row: {row};" in rule


def test_followup_messages_bind_to_the_latest_open_event_in_both_clients():
    assistant_source = ASSISTANT_SCRIPT_PATH.read_text(encoding="utf-8")
    simulator_source = SIMULATOR_SCRIPT_PATH.read_text(encoding="utf-8")

    for source in (assistant_source, simulator_source):
        assert "function latestOpenEventId()" in source
        assert "var targetSourceEventId = latestOpenEventId();" in source
        assert "source_event_id: targetSourceEventId" in source


def test_shared_client_uploads_formdata_without_forcing_json_content_type():
    source = SHARED_CLIENT_PATH.read_text(encoding="utf-8")

    assert 'var isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;' in source
    assert 'if (options.body !== undefined && !isFormData && !headers.has("Content-Type"))' in source
    assert '"/assistant/attachments"' in source
    assert '"/channels/simulator/attachments"' in source
    assert 'form.append("user_id", userId)' in source
    assert 'form.append("file", file, file.name || "attachment")' in source
    assert "uploadAttachment: uploadAssistantAttachment" in source
    assert "uploadAttachment: uploadSimulatorAttachment" in source
    assert "content: getAttachmentContent" in source
    assert 'SENDING: "发送中"' in source
    assert 'SENT: "已受理"' in source
    assert 'PROCESSING: "处理中"' in source


def test_employee_clients_upload_attachment_ids_and_restore_persisted_previews():
    assistant_html = ASSISTANT_HTML_PATH.read_text(encoding="utf-8")
    assistant_script = ASSISTANT_SCRIPT_PATH.read_text(encoding="utf-8")
    assistant_styles = ASSISTANT_STYLE_PATH.read_text(encoding="utf-8")
    simulator_html = SIMULATOR_HTML_PATH.read_text(encoding="utf-8")
    simulator_script = SIMULATOR_SCRIPT_PATH.read_text(encoding="utf-8")
    simulator_styles = SIMULATOR_STYLE_PATH.read_text(encoding="utf-8")

    assert 'id="attachment-file"' in assistant_html
    assert 'id="simulator-attachment-file"' in simulator_html
    for html in (assistant_html, simulator_html):
        assert 'type="file"' in html
        assert 'accept="image/jpeg,image/png,image/webp"' in html
        assert 'maxlength="5000"' in html
    assert 'id="message-count">0 / 5000<' in assistant_html

    assistant_submit = assistant_script[
        assistant_script.index("async function submitMessage") : assistant_script.index("function retryMessage")
    ]
    assistant_retry = assistant_script[
        assistant_script.index("function retryMessage") : assistant_script.index("async function refreshCurrent")
    ]
    assistant_new_session = assistant_script[
        assistant_script.index("function newSession") : assistant_script.index("async function selectSession")
    ]
    assistant_select_session = assistant_script[
        assistant_script.index("async function selectSession") : assistant_script.index("function safeBusinessCode")
    ]
    assistant_reconcile = assistant_script[
        assistant_script.index("function reconcileOptimisticMessages") : assistant_script.index("async function submitMessage")
    ]
    assistant_logout = assistant_script[
        assistant_script.index("async function logout") : assistant_script.index("function handleClick")
    ]
    assert "Client.assistant.uploadAttachment" in assistant_script
    assert assistant_submit.index("var optimisticMessage = showOptimisticMessage(") < assistant_submit.index(
        "await uploadPendingAttachment()"
    )
    assert assistant_submit.index("await uploadPendingAttachment()") < assistant_submit.index("Client.assistant.send")
    assert 'attachment_id: uploadedAttachment.attachment_id' in assistant_submit
    assert "external_message_id: externalMessageId" in assistant_submit
    assert 'setOptimisticMessageStatus(optimisticMessage, "SENT")' in assistant_submit
    assert "optimisticMessage.message_id = response.message_id" in assistant_submit
    assert "removeOptimisticMessage(optimisticMessage)" in assistant_submit
    assert assistant_submit.index("Client.assistant.send") < assistant_submit.index('state.pendingExternalMessageId = "";')
    assert 'state.pendingExternalMessageId = "";' not in assistant_submit[assistant_submit.index("} catch (error)") :]
    assert assistant_submit.index("Client.assistant.send") < assistant_submit.index('input.value = ""')
    assert "requestSubmit()" in assistant_retry
    assert 'state.pendingExternalMessageId = "";' not in assistant_retry
    assert 'state.pendingExternalMessageId = Client.ids.externalMessage("web")' in assistant_script
    assert "var targetSessionId = state.activeSessionId;" in assistant_submit
    assert "session_id: targetSessionId" in assistant_submit
    assert "source_event_id: targetSourceEventId" in assistant_submit
    assert "attachments: optimisticAttachments(attachmentNote, externalMessageId)" in assistant_script
    assert "URL.createObjectURL(file)" in assistant_script
    assert assistant_script.count("resetPendingExternalMessageId();") >= 5
    assert "if (state.submitting)" in assistant_new_session
    assert "if (state.submitting)" in assistant_select_session
    assert "removeOptimisticMessage" not in assistant_new_session
    assert "removeOptimisticMessage" not in assistant_select_session
    assert "if (state.submitting)" in assistant_logout
    assert "message.message_id === optimistic.message_id" in assistant_reconcile
    assert "reconcileOptimisticMessages();" in assistant_script
    assert "optimisticMessages: []" in assistant_script
    assert "state.optimisticMessages.push(message)" in assistant_script
    assert "message.session_id === state.activeSessionId" in assistant_script

    simulator_submit = simulator_script[
        simulator_script.index("async function submitMessage") : simulator_script.index("function retryMessage")
    ]
    simulator_retry = simulator_script[
        simulator_script.index("function retryMessage") : simulator_script.index("async function refresh()")
    ]
    simulator_select_identity = simulator_script[
        simulator_script.index("function selectIdentity") : simulator_script.index("function newSession")
    ]
    simulator_new_session = simulator_script[
        simulator_script.index("function newSession") : simulator_script.index("function updateSessionSummary")
    ]
    simulator_reconcile = simulator_script[
        simulator_script.index("function reconcileOptimisticMessages") : simulator_script.index("async function submitMessage")
    ]
    simulator_logout = simulator_script[
        simulator_script.index("async function logout") : simulator_script.index("function handleClick")
    ]
    assert "Client.simulator.uploadAttachment" in simulator_script
    assert simulator_submit.index("var optimisticMessage = showOptimisticMessage(") < simulator_submit.index(
        "await uploadPendingAttachment(targetUserId)"
    )
    assert simulator_submit.index("await uploadPendingAttachment(targetUserId)") < simulator_submit.index(
        "Client.simulator.send"
    )
    assert 'attachment_id: uploadedAttachment.attachment_id' in simulator_submit
    assert "external_message_id: externalMessageId" in simulator_submit
    assert 'setOptimisticMessageStatus(optimisticMessage, "SENT")' in simulator_submit
    assert "optimisticMessage.message_id = response.message_id" in simulator_submit
    assert "removeOptimisticMessage(optimisticMessage)" in simulator_submit
    assert simulator_submit.index("Client.simulator.send") < simulator_submit.index('state.pendingExternalMessageId = "";')
    assert 'state.pendingExternalMessageId = "";' not in simulator_submit[simulator_submit.index("} catch (error)") :]
    assert simulator_submit.index("Client.simulator.send") < simulator_submit.index('input.value = ""')
    assert "requestSubmit()" in simulator_retry
    assert 'state.pendingExternalMessageId = "";' not in simulator_retry
    assert 'state.pendingExternalMessageId = Client.ids.externalMessage("wecom-sim")' in simulator_script
    assert "var targetUserId = state.selectedUserId;" in simulator_submit
    assert "Client.simulator.uploadAttachment(userId, file)" in simulator_script
    assert "user_id: targetUserId" in simulator_submit
    assert "external_conversation_id: targetExternalConversationId" in simulator_submit
    assert "source_event_id: targetSourceEventId" in simulator_submit
    assert "attachments: optimisticAttachments(attachmentNote, externalMessageId, userId)" in simulator_script
    assert "URL.createObjectURL(file)" in simulator_script
    assert simulator_script.count("resetPendingExternalMessageId();") >= 5
    assert "if (state.submitting)" in simulator_select_identity
    assert "if (state.submitting)" in simulator_new_session
    assert "if (state.submitting || state.experience.submitting)" in simulator_logout
    assert "message.message_id === optimistic.message_id" in simulator_reconcile
    assert "reconcileOptimisticMessages();" in simulator_script
    assert "optimisticMessages: []" in simulator_script
    assert "state.optimisticMessages.push(message)" in simulator_script
    assert "message.user_id !== state.selectedUserId" in simulator_script
    assert "message.session_id === state.sessionId" in simulator_script

    for script in (assistant_script, simulator_script):
        assert "message.attachments" in script
        assert "Client.attachments.content" in script
        assert "attachment.description" in script
        assert "attachment.uploaded_by_name" in script
        assert "attachment.created_at" in script
        assert "data-attachment-preview-id" in script
        assert "optimisticMessages" in script
        assert 'status: "SENDING"' in script
        assert "UI.statusLabel(message.status)" in script
        assert '{ type: "description"' not in script

    assert ".message-attachment" in assistant_styles
    assert ".wecom-attachment" in simulator_styles


def test_clients_recover_restarted_sessions_and_retry_original_messages():
    shared_source = SHARED_CLIENT_PATH.read_text(encoding="utf-8")
    assistant_source = ASSISTANT_SCRIPT_PATH.read_text(encoding="utf-8")
    simulator_source = SIMULATOR_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "function isTransientRecoveryError(error)" in shared_source
    assert "function recoveryDelay(attempt, options)" in shared_source
    assert "Math.pow(2, attempt)" in shared_source
    assert "async function withRecovery(operation, options)" in shared_source
    assert "options.onRecovering" in shared_source
    assert "options.onRecovered" in shared_source
    assert "await wait(delayMs, options.signal)" in shared_source
    assert "recovery: {" in shared_source
    assert "run: withRecovery" in shared_source
    assert 'RETRY_REQUIRED: "需要人工重试"' in shared_source
    assert 'RETRYING: "正在重新处理"' in shared_source
    assert '"/retry"' in shared_source
    assert "retry: retryAssistantMessage" in shared_source

    assistant_load = assistant_source[
        assistant_source.index("async function loadMessages") : assistant_source.index("function displayText")
    ]
    assistant_retry = assistant_source[
        assistant_source.index("async function retryPersistedMessage") : assistant_source.index("async function refreshCurrent")
    ]
    assert "Client.recovery.run" in assistant_load
    assert "timeoutMs: 300000" in assistant_load
    assert "state.messages = [];" not in assistant_load
    assert "服务正在恢复，任务仍在处理中" in assistant_source
    assert "data-retry-message-id" in assistant_source
    assert "需要人工重试" in assistant_source
    assert "Client.assistant.retry(messageId)" in assistant_retry
    assert "followRun(state.activeSessionId, messageId)" in assistant_retry
    assert "requestSubmit" not in assistant_retry
    assert "ASSISTANT_CONTEXT_KEY" in assistant_source
    assert "function readLastSessionContexts()" in assistant_source
    assert "contexts[ownerKey]" in assistant_source
    assert "owner_key: signedUserContextKey(state.user)" in assistant_source
    assert "saved.owner_key !== signedUserContextKey(state.user)" in assistant_source
    assert "state.sessions.find" in assistant_source

    simulator_load = simulator_source[
        simulator_source.index("async function loadSession") : simulator_source.index("function followRun")
    ]
    simulator_retry = simulator_source[
        simulator_source.index("async function retryPersistedMessage") : simulator_source.index("function retryMessage")
    ]
    simulator_logout = simulator_source[
        simulator_source.index("async function logout") : simulator_source.index("function handleClick")
    ]
    assert "Client.recovery.run" in simulator_load
    assert "timeoutMs: 300000" in simulator_load
    assert "state.messages = [];" not in simulator_load
    assert "服务正在恢复，任务仍在处理中" in simulator_source
    assert "data-retry-message-id" in simulator_source
    assert "需要人工重试" in simulator_source
    assert "Client.assistant.retry(messageId, { acting_user_id: state.selectedUserId })" in simulator_retry
    assert "followRun(messageId)" in simulator_retry
    assert "requestSubmit" not in simulator_retry
    assert "function normalizeOwnerContext(ownerKey, value)" in simulator_source
    assert "owner_key: ownerKey" in simulator_source
    assert "employees: employees" in simulator_source
    assert "saved.employees[state.selectedUserId]" in simulator_source
    assert "function readContexts()" in simulator_source
    assert "contexts[ownerKey]" in simulator_source
    assert "saved.owner_key !== signedUserContextKey(state.signedUser)" in simulator_source
    assert "clearContext();" not in simulator_logout
    assert "state.identities.find" in simulator_source


def test_recovery_deadlines_and_context_guards_prevent_stale_client_updates():
    shared_source = SHARED_CLIENT_PATH.read_text(encoding="utf-8")
    assistant_source = ASSISTANT_SCRIPT_PATH.read_text(encoding="utf-8")
    simulator_source = SIMULATOR_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "async function recoveryAttempt(operation, timeoutMs, signal)" in shared_source
    assert "Promise.race" in shared_source
    assert "controller.abort()" in shared_source
    assert "if (signal && signal.aborted)" in shared_source
    assert "signal.removeEventListener" in shared_source
    assert "finalAssistant && isTerminal(finalAssistant.status)" in shared_source
    assert "Math.min(options.intervalMs || 1500, remainingPollingMs)" in shared_source

    assistant_load = assistant_source[
        assistant_source.index("async function loadMessages") : assistant_source.index("function displayText")
    ]
    assistant_retry = assistant_source[
        assistant_source.index("async function retryPersistedMessage") : assistant_source.index("async function refreshCurrent")
    ]
    assert "if (state.activeSessionId !== sessionId) return;" in assistant_load
    assert "var retrySessionId = state.activeSessionId;" in assistant_retry
    assert "if (state.activeSessionId !== retrySessionId) return;" in assistant_retry
    assert "var retriedSessionId = state.activeSessionId;" in assistant_retry
    assert 'setAssistantStatus("FAILED"' not in assistant_retry

    simulator_load = simulator_source[
        simulator_source.index("async function loadSession") : simulator_source.index("function followRun")
    ]
    simulator_follow = simulator_source[
        simulator_source.index("function followRun") : simulator_source.index("function setSubmitting")
    ]
    simulator_retry = simulator_source[
        simulator_source.index("async function retryPersistedMessage") : simulator_source.index("function retryMessage")
    ]
    assert "var sessionId = state.sessionId;" in simulator_load
    assert "var userId = state.selectedUserId;" in simulator_load
    assert "if (state.sessionId !== sessionId || state.selectedUserId !== userId) return;" in simulator_load
    assert "if (state.sessionId !== sessionId || state.selectedUserId !== userId) return;" in simulator_follow
    assert "var retrySessionId = state.sessionId;" in simulator_retry
    assert "var retryUserId = state.selectedUserId;" in simulator_retry
    assert "var retriedSessionId = state.sessionId;" in simulator_retry
    assert "state.sessionId !== retrySessionId || state.selectedUserId !== retryUserId" in simulator_retry


def test_compose_persists_attachment_objects_outside_the_app_container():
    source = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "ATTACHMENT_STORAGE_DIR: /app/data/attachments" in source
    assert "- attachment-data:/app/data/attachments" in source
    assert "  attachment-data:" in source
    assert "  attachment-init:" in source
    assert "chown -R appuser:appuser /app/data/attachments" in source
    assert "condition: service_completed_successfully" in source
