(function () {
  "use strict";

  var Client = window.MemoryPalaceClient;
  var UI = Client.ui;
  var CONTEXT_KEY = "mp_wecom_simulator_context";
  var state = {
    signedUser: null,
    identities: [],
    sessions: [],
    selectedUserId: null,
    sessionId: null,
    externalConversationId: null,
    newSession: false,
    sessionsLoading: false,
    sessionLoadVersion: 0,
    messages: [],
    outbox: [],
    outboxUnavailable: false,
    submitting: false,
    retryingMessageId: "",
    followController: null,
    evidence: null,
    lastContent: "",
    pendingExternalMessageId: "",
    optimisticMessages: [],
    pendingAttachment: null,
    attachmentObjectUrls: {},
    attachmentLoads: {},
    experience: {
      loading: false,
      loadVersion: 0,
      interviewLoadVersion: 0,
      expert: null,
      interviews: [],
      cards: [],
      selectedInterview: null,
      selectedCard: null,
      selectedExtraction: null,
      submitting: false,
      error: null
    }
  };
  var emptyMessageTemplate = "";

  function byId(id) {
    return document.getElementById(id);
  }

  function signedUserContextKey(user) {
    var userId = String(user && (user.id || user.user_id) || "").trim();
    var venueId = String(user && user.venue_id || "").trim();
    return userId && venueId ? venueId + ":" + userId : "";
  }

  function readContexts() {
    try {
      var contexts = JSON.parse(sessionStorage.getItem(CONTEXT_KEY) || "{}") || {};
      if (contexts.owner_key) {
        var migrated = {};
        migrated[contexts.owner_key] = contexts;
        return migrated;
      }
      return contexts;
    } catch (error) {
      return {};
    }
  }

  function normalizeEmployeeContext(value) {
    value = value && typeof value === "object" ? value : {};
    return {
      sessionId: value.sessionId || null,
      externalConversationId: value.externalConversationId || null,
      newSession: Boolean(value.newSession)
    };
  }

  function normalizeOwnerContext(ownerKey, value) {
    value = value && typeof value === "object" ? value : {};
    var employees = {};
    Object.keys(value.employees || {}).forEach(function (userId) {
      employees[userId] = normalizeEmployeeContext(value.employees[userId]);
    });
    if (value.selectedUserId && !employees[value.selectedUserId] &&
        (value.sessionId || value.externalConversationId)) {
      employees[value.selectedUserId] = normalizeEmployeeContext(value);
    }
    return {
      owner_key: ownerKey,
      selectedUserId: value.selectedUserId || null,
      employees: employees
    };
  }

  function readContext() {
    var ownerKey = signedUserContextKey(state.signedUser);
    var saved = readContexts()[ownerKey] || {};
    if (!saved.owner_key || saved.owner_key !== signedUserContextKey(state.signedUser)) return {};
    return normalizeOwnerContext(ownerKey, saved);
  }

  function readEmployeeContext(userId) {
    var saved = readContext();
    return normalizeEmployeeContext(saved.employees && saved.employees[userId]);
  }

  function saveContext() {
    var ownerKey = signedUserContextKey(state.signedUser);
    if (!ownerKey) return;
    var contexts = readContexts();
    var saved = normalizeOwnerContext(ownerKey, contexts[ownerKey]);
    saved.selectedUserId = state.selectedUserId;
    if (state.selectedUserId) {
      saved.employees[state.selectedUserId] = {
        sessionId: state.sessionId,
        externalConversationId: state.externalConversationId,
        newSession: Boolean(state.newSession)
      };
    }
    contexts[ownerKey] = saved;
    sessionStorage.setItem(CONTEXT_KEY, JSON.stringify(contexts));
  }

  function clearContext() {
    var ownerKey = signedUserContextKey(state.signedUser);
    var contexts = readContexts();
    if (ownerKey) delete contexts[ownerKey];
    if (Object.keys(contexts).length) sessionStorage.setItem(CONTEXT_KEY, JSON.stringify(contexts));
    else sessionStorage.removeItem(CONTEXT_KEY);
  }

  function roleLabel(role) {
    var labels = {
      admin: "系统管理员",
      manager: "值班经理",
      operator: "现场员工",
      api: "企业服务账号"
    };
    return labels[String(role || "").toLowerCase()] || "企业成员";
  }

  function statusClass(value) {
    var code = UI.statusCode(value);
    if (["COMPLETED", "SUCCEEDED", "DONE", "CLOSED"].indexOf(code) >= 0) return "success";
    if (["FAILED", "ERROR", "CANCELLED", "REJECTED", "RETRY_REQUIRED", "DEAD_LETTERED"].indexOf(code) >= 0) return "failed";
    if (["QUEUED", "PENDING"].indexOf(code) >= 0) return "queued";
    if (["PROCESSING", "RUNNING", "EXECUTING", "RETRYING", "OPEN", "WAITING_APPROVAL"].indexOf(code) >= 0) return "running";
    return "";
  }

  function notify(message, type) {
    var region = byId("toast-region");
    while (region.children.length >= 3) region.firstElementChild.remove();
    var toast = document.createElement("div");
    toast.className = "toast " + (type || "");
    toast.textContent = message;
    region.appendChild(toast);
    window.setTimeout(function () { toast.remove(); }, 4200);
  }

  function showError(error, retryAction) {
    var view = UI.errorView(error);
    var target = byId("simulator-error");
    target.hidden = false;
    target.innerHTML = "<strong>" + UI.escapeHTML(view.title) + "</strong><span>" +
      UI.escapeHTML(view.message) + "</span>" +
      (view.action ? "<span>建议操作：" + UI.escapeHTML(view.action) + "</span>" : "") +
      (view.retryable && retryAction
        ? '<button class="btn" type="button" data-action="' + UI.escapeHTML(retryAction) + '">重试</button>'
        : "");
  }

  function clearError() {
    byId("simulator-error").hidden = true;
    byId("simulator-error").innerHTML = "";
  }

  function showServiceRecovering() {
    byId("delivery-status").textContent = "服务正在恢复，任务仍在处理中";
  }

  function showServiceRecovered() {
    byId("delivery-status").textContent = "服务已恢复，正在同步原任务进度";
  }

  function showRecoveryDeferred() {
    byId("delivery-status").textContent = "恢复等待已到上限，原任务状态已保留，请稍后刷新";
  }

  function showLogin(error) {
    byId("simulator-app").hidden = true;
    byId("login-screen").hidden = false;
    byId("login-error").textContent = error ? UI.errorView(error).message : "";
  }

  function selectedIdentity() {
    return state.identities.find(function (item) { return item.user_id === state.selectedUserId; }) || null;
  }

  function experienceOptions(signal, actingUserId) {
    return {
      acting_user_id: actingUserId === undefined ? (state.selectedUserId || "") : actingUserId,
      signal: signal
    };
  }

  function experienceOwnerKey() {
    return signedUserContextKey(state.signedUser) + ":" + String(state.selectedUserId || "");
  }

  function resetExperienceState() {
    state.experience.loadVersion += 1;
    closeInterview();
    closeExperienceCard();
    state.experience.loading = false;
    state.experience.expert = null;
    state.experience.interviews = [];
    state.experience.cards = [];
    state.experience.selectedExtraction = null;
    state.experience.submitting = false;
    state.experience.error = null;
    var answerForm = byId("interview-answer-form");
    if (answerForm) {
      answerForm.reset();
      answerForm.removeAttribute("data-idempotency-key");
    }
    var reviseForm = byId("experience-card-revise-form");
    if (reviseForm) reviseForm.reset();
    clearInlineError("interview-action-error");
    clearInlineError("experience-card-action-error");
  }

  function lineItems(value) {
    if (Array.isArray(value)) return value.map(function (item) {
      return String(item === undefined || item === null ? "" : item).trim();
    }).filter(Boolean);
    return String(value || "").split(/\r?\n/).map(function (item) {
      return item.trim();
    }).filter(Boolean);
  }

  function joinLines(value) {
    return lineItems(value).join("\n");
  }

  function displayText(value, fallback) {
    var text = String(value === undefined || value === null ? "" : value).trim();
    return text || (fallback || "");
  }

  function readableTitle(value, fallback) {
    return displayText(value, fallback || "未命名经验");
  }

  function experienceProgress(interview) {
    var progress = interview && interview.progress || {};
    var total = Number(progress.total || 4);
    var answered = Number(progress.answered || interview && interview.current_question_index || 0);
    return {
      answered: answered,
      total: total,
      percent: Number(progress.percent || (total ? Math.round(answered / total * 100) : 0))
    };
  }

  function experienceSourceName(card) {
    var source = card && card.source || {};
    return displayText(source.expert_name || card && card.expert_name, "经验专家");
  }

  function experienceScopeLabel(scope) {
    scope = scope || {};
    var labels = {
      VENUE: "场地",
      DEPARTMENT: "部门",
      ROLE: "角色",
      JOB_TITLE: "岗位",
      USER: "指定人员"
    };
    return (labels[String(scope.scope_type || "").toUpperCase()] || "授权") +
      "：" + displayText(scope.scope_value, "未说明");
  }

  function experienceStatusClass(value) {
    var code = UI.statusCode(value);
    if (["EXPERT_CONFIRMED", "PUBLISHED", "COMPLETED"].indexOf(code) >= 0) return "success";
    if (["IN_PROGRESS", "ACCEPTED", "IN_REVIEW"].indexOf(code) >= 0) return "running";
    if (["PAUSED", "DRAFT", "INVITED"].indexOf(code) >= 0) return "queued";
    if (["FAILED", "REJECTED", "CANCELLED"].indexOf(code) >= 0) return "failed";
    return "";
  }

  function renderIdentity() {
    var identity = selectedIdentity();
    var summary = byId("identity-summary");
    var input = byId("simulator-message-input");
    var send = byId("simulator-send");
    var attachmentFile = byId("simulator-attachment-file");
    var attachmentNote = byId("simulator-attachment-note");
    if (!identity) {
      summary.innerHTML = '<span class="identity-avatar">员</span><div><strong>尚未选择员工</strong><span>请选择已授权身份</span></div>';
      byId("conversation-identity").textContent = "等待选择员工";
      input.disabled = true;
      send.disabled = true;
      attachmentFile.disabled = true;
      attachmentNote.disabled = true;
      byId("delivery-status").textContent = "等待选择员工";
      return;
    }
    var name = identity.display_name || identity.username || "企业员工";
    var profile = [identity.job_title || roleLabel(identity.role), identity.department, identity.venue_name]
      .filter(Boolean).join(" · ");
    var binding = identity.wecom_binding_status === "ACTIVE" ? "接入身份已绑定" : "接入身份未绑定";
    summary.innerHTML = '<span class="identity-avatar">' + UI.escapeHTML(name.slice(0, 1)) + '</span><div><strong>' +
      UI.escapeHTML(name) + "</strong><span>" + UI.escapeHTML(profile + " · " + binding) + "</span></div>";
    byId("conversation-identity").textContent = name + " · " + (identity.job_title || roleLabel(identity.role)) +
      " · " + (identity.venue_name || "当前场地");
    input.disabled = state.submitting;
    send.disabled = state.submitting;
    attachmentFile.disabled = state.submitting;
    attachmentNote.disabled = state.submitting;
    byId("delivery-status").textContent = state.sessionId ? "会话已恢复，可以继续发送" : "可以开始新的接入会话";
  }

  function renderIdentityOptions() {
    var select = byId("identity-select");
    var options = ['<option value="">请选择员工身份</option>'];
    state.identities.forEach(function (identity) {
      var name = identity.display_name || identity.username || "企业员工";
      var context = [identity.organization_name, identity.venue_name, identity.job_title || roleLabel(identity.role)]
        .filter(Boolean).join(" · ");
      options.push('<option value="' + UI.escapeHTML(identity.user_id) + '">' +
        UI.escapeHTML(name + " · " + context) + "</option>");
    });
    select.innerHTML = options.join("");
    select.value = state.selectedUserId || "";
    select.disabled = !state.identities.length;
  }

  function sessionOptionLabel(item) {
    var preview = String(item.last_message || "").trim();
    if (preview.length > 24) preview = preview.slice(0, 24) + "…";
    if (!preview) preview = Number(item.message_count || 0) > 0
      ? "已记录 " + Number(item.message_count) + " 条消息"
      : "尚无消息";
    return UI.dateLabel(item.updated_at || item.created_at) + " · " + preview;
  }

  function renderSessionOptions(error) {
    var select = byId("session-select");
    var status = byId("session-status");
    if (!state.selectedUserId) {
      select.innerHTML = '<option value="">请先选择员工身份</option>';
      select.value = "";
      select.disabled = true;
      status.textContent = "选择员工后读取其历史会话。";
      return;
    }
    if (state.sessionsLoading) {
      select.innerHTML = '<option value="">正在读取内部系统接入会话…</option>';
      select.value = "";
      select.disabled = true;
      status.textContent = "正在同步当前员工的内部系统接入会话。";
      return;
    }
    if (error) {
      select.innerHTML = '<option value="">会话读取失败</option>';
      select.value = "";
      select.disabled = true;
      status.textContent = UI.errorView(error).message + "，可点击刷新状态重试。";
      return;
    }
    if (!state.sessions.length) {
      select.innerHTML = '<option value="">暂无历史会话</option>';
      select.value = "";
      select.disabled = true;
      status.textContent = "该员工暂无内部系统接入会话；发送第一条消息后会自动创建。";
      return;
    }
    select.innerHTML = ['<option value="">新会话（发送后创建）</option>'].concat(
      state.sessions.map(function (item) {
        return '<option value="' + UI.escapeHTML(item.session_id) + '">' +
          UI.escapeHTML(sessionOptionLabel(item)) + "</option>";
      })
    ).join("");
    select.value = state.sessionId || "";
    select.disabled = state.submitting;
    status.textContent = state.sessionId
      ? "已恢复当前员工的内部系统接入会话，共 " + state.sessions.length + " 条。"
      : "已准备新会话；发送第一条消息后建立正式会话。";
  }

  function visibleSimulatorSessions(items, userId) {
    var identity = state.identities.find(function (item) { return item.user_id === userId; });
    var venueId = identity && identity.venue_id || state.signedUser && state.signedUser.venue_id || "";
    return items.filter(function (item) {
      return String(item.channel || "").toUpperCase() === "WECOM_SIMULATOR" &&
        item.user_id === userId && item.venue_id === venueId;
    }).sort(function (left, right) {
      var rightTime = Number(right.updated_at || right.created_at || 0);
      var leftTime = Number(left.updated_at || left.created_at || 0);
      return rightTime - leftTime || String(right.session_id).localeCompare(String(left.session_id));
    });
  }

  async function loadEmployeeSessions(userId, requestedSessionId, resume) {
    if (!userId || userId !== state.selectedUserId) {
      state.sessions = [];
      renderSessionOptions();
      return;
    }
    var ownerKey = signedUserContextKey(state.signedUser);
    var preserveNewSession = Boolean(state.newSession && !requestedSessionId);
    var requestVersion = state.sessionLoadVersion + 1;
    state.sessionLoadVersion = requestVersion;
    state.sessionsLoading = true;
    renderSessionOptions();
    try {
      var payload = await Client.recovery.run(function (signal) {
        return Client.assistant.sessions({
          acting_user_id: userId,
          channel: "WECOM_SIMULATOR",
          limit: 100,
          signal: signal
        });
      }, {
        timeoutMs: 300000,
        onRecovering: showServiceRecovering,
        onRecovered: showServiceRecovered
      });
      if (state.sessionLoadVersion !== requestVersion || state.selectedUserId !== userId ||
          signedUserContextKey(state.signedUser) !== ownerKey) return;
      state.sessions = visibleSimulatorSessions(UI.arrayFrom(payload, ["sessions", "items"]), userId);
      var matched = state.sessions.find(function (item) {
        return item.session_id === requestedSessionId;
      });
      if (!matched && !preserveNewSession && state.sessions.length) matched = state.sessions[0];
      state.sessionId = matched ? matched.session_id : null;
      state.externalConversationId = matched ? matched.external_conversation_id : null;
      state.newSession = Boolean(preserveNewSession && !matched);
      state.sessionsLoading = false;
      renderSessionOptions();
      saveContext();
      updateSessionSummary();
      if (state.sessionId) await loadSession(resume !== false);
      else {
        renderMessages();
        renderEvidence();
      }
    } catch (error) {
      if (state.sessionLoadVersion !== requestVersion || state.selectedUserId !== userId ||
          signedUserContextKey(state.signedUser) !== ownerKey) return;
      state.sessions = [];
      state.sessionsLoading = false;
      renderSessionOptions(error);
      showError(error, "reload-sessions");
      updateSessionSummary();
    }
  }

  async function loadIdentities() {
    var ownerKey = signedUserContextKey(state.signedUser);
    var select = byId("identity-select");
    select.disabled = true;
    select.innerHTML = '<option value="">正在读取可用身份…</option>';
    clearError();
    try {
      var payload = await Client.recovery.run(function (signal) {
        return Client.simulator.identities({ signal: signal });
      }, {
        timeoutMs: 300000,
        onRecovering: showServiceRecovering,
        onRecovered: showServiceRecovered
      });
      if (signedUserContextKey(state.signedUser) !== ownerKey) return;
      resetExperienceState();
      state.identities = UI.arrayFrom(payload, ["identities", "items"]);
      var saved = readContext();
      var restored = state.identities.find(function (item) { return item.user_id === saved.selectedUserId; });
      if (restored) {
        var employeeContext = readEmployeeContext(restored.user_id);
        state.selectedUserId = restored.user_id;
        state.sessionId = employeeContext.sessionId;
        state.externalConversationId = employeeContext.externalConversationId;
        state.newSession = employeeContext.newSession;
      } else {
        state.selectedUserId = null;
        state.sessionId = null;
        state.externalConversationId = null;
        state.newSession = false;
        if (saved.owner_key) saveContext();
      }
      renderIdentityOptions();
      renderIdentity();
      if (!state.identities.length) {
        select.innerHTML = '<option value="">当前租户没有可用员工身份</option>';
        byId("delivery-status").textContent = "没有可用于接入联调的员工身份";
        renderExperienceSummary();
        renderMessages();
        return;
      }
      if (state.selectedUserId) {
        await Promise.all([loadEmployeeSessions(state.selectedUserId, state.sessionId, true), loadExperience()]);
      }
      else {
        renderSessionOptions();
        renderMessages();
        renderExperienceSummary();
      }
    } catch (error) {
      if (signedUserContextKey(state.signedUser) !== ownerKey) return;
      resetExperienceState();
      state.identities = [];
      select.innerHTML = '<option value="">身份读取失败</option>';
      showError(error, "reload-identities");
      renderIdentity();
      renderExperienceSummary();
      renderMessages();
    }
  }

  async function selectIdentity(userId) {
    if (state.submitting || state.experience.submitting) {
      notify("当前操作正在提交，请稍候再切换员工身份。", "error");
      return;
    }
    if (state.followController) state.followController.abort();
    resetPendingExternalMessageId();
    resetExperienceState();
    var employeeContext = readEmployeeContext(userId);
    state.selectedUserId = userId || null;
    state.sessionId = state.selectedUserId ? employeeContext.sessionId : null;
    state.externalConversationId = state.selectedUserId ? employeeContext.externalConversationId : null;
    state.newSession = state.selectedUserId ? employeeContext.newSession : false;
    state.sessions = [];
    state.messages = [];
    state.outbox = [];
    state.outboxUnavailable = false;
    state.evidence = null;
    state.pendingAttachment = null;
    saveContext();
    renderIdentity();
    renderSessionOptions();
    renderMessages();
    renderEvidence();
    renderExperienceSummary();
    updateSessionSummary();
    clearError();
    if (state.selectedUserId) {
      byId("simulator-message-input").focus();
      await Promise.all([loadEmployeeSessions(state.selectedUserId, state.sessionId, true), loadExperience()]);
    }
  }

  async function selectSession(sessionId) {
    if (state.submitting) {
      notify("消息正在发送，请稍候再切换会话。", "error");
      renderSessionOptions();
      return;
    }
    var selected = state.sessions.find(function (item) { return item.session_id === sessionId; });
    if (!selected) {
      newSession();
      return;
    }
    if (state.followController) state.followController.abort();
    resetPendingExternalMessageId();
    state.sessionId = selected.session_id;
    state.externalConversationId = selected.external_conversation_id;
    state.newSession = false;
    state.messages = [];
    state.outbox = [];
    state.outboxUnavailable = false;
    state.evidence = null;
    saveContext();
    renderSessionOptions();
    renderMessages();
    renderEvidence();
    updateSessionSummary();
    clearError();
    await loadSession(true);
  }

  function newSession() {
    if (!state.selectedUserId) {
      notify("请先选择员工身份。", "error");
      return;
    }
    if (state.submitting) {
      notify("消息正在发送，请稍候再新建会话。", "error");
      return;
    }
    if (state.followController) state.followController.abort();
    resetPendingExternalMessageId();
    state.sessionId = null;
    state.externalConversationId = null;
    state.newSession = true;
    state.messages = [];
    state.outbox = [];
    state.outboxUnavailable = false;
    state.evidence = null;
    saveContext();
    renderSessionOptions();
    renderMessages();
    renderEvidence();
    updateSessionSummary();
    byId("delivery-status").textContent = "已新建本地会话上下文，发送后由服务端正式受理";
    byId("simulator-message-input").focus();
  }

  function updateSessionSummary() {
    var identity = selectedIdentity();
    if (!identity) {
      byId("session-summary").textContent = "选择员工后可开始新的接入会话。";
      return;
    }
    byId("session-summary").textContent = state.sessionId
      ? "正在查看 " + (identity.display_name || identity.username || "当前员工") + " 的已受理接入会话。"
      : "将以 " + (identity.display_name || identity.username || "当前员工") + " 身份创建新会话。";
  }

  function channelLabel(value) {
    var code = String(value || "").toUpperCase();
    if (code === "WECOM_SIMULATOR") return "内部系统接入渠道";
    if (code === "WEB") return "网页员工助手";
    return value ? "企业消息渠道" : "尚未产生";
  }

  function adminURL(view, values) {
    var url = new URL("/admin/index.html?", window.location.origin);
    url.searchParams.set("view", view);
    Object.keys(values || {}).forEach(function (key) {
      if (values[key]) url.searchParams.set(key, values[key]);
    });
    return url.pathname + url.search;
  }

  function renderEvidence() {
    var evidence = state.evidence;
    var empty = "尚未产生";
    byId("evidence-channel").textContent = evidence ? channelLabel(evidence.channel) : empty;
    byId("evidence-run-status").textContent = evidence ? UI.statusLabel(evidence.status) : empty;
    byId("evidence-time").textContent = evidence ? UI.dateLabel(evidence.created_at) : empty;
    byId("evidence-message").textContent = evidence && evidence.message_id || empty;
    byId("evidence-session").textContent = evidence && evidence.session_id || empty;
    byId("evidence-trace").textContent = evidence && evidence.trace_id || empty;
    var badge = byId("evidence-status-badge");
    badge.className = "status-pill " + (evidence ? statusClass(evidence.status) : "");
    badge.textContent = evidence ? UI.statusLabel(evidence.status) : empty;

    var sessionLink = byId("admin-session-link");
    var traceLink = byId("admin-trace-link");
    sessionLink.href = evidence && evidence.session_id
      ? adminURL("sessions", { session_id: evidence.session_id })
      : "/admin/";
    sessionLink.setAttribute("aria-disabled", evidence && evidence.session_id ? "false" : "true");
    traceLink.href = evidence && evidence.trace_id
      ? adminURL("diagnostics", { trace_id: evidence.trace_id })
      : "/admin/";
    traceLink.setAttribute("aria-disabled", evidence && evidence.trace_id ? "false" : "true");
  }

  function restoreEvidenceFromMessages() {
    var latest = state.messages.slice().reverse().find(function (message) {
      return message.message_id || message.trace_id;
    });
    if (!latest) return;
    state.evidence = {
      channel: latest.channel,
      status: latest.status,
      message_id: latest.message_id,
      session_id: latest.session_id || state.sessionId,
      trace_id: latest.trace_id,
      created_at: latest.created_at
    };
    renderEvidence();
  }

  function cardTypeLabel(card) {
    var type = String(card.card_type || card.type || card.kind || "").toLowerCase();
    if (/(event|incident)/.test(type)) return "事件进展";
    if (type.indexOf("task") >= 0) return "任务";
    if (type.indexOf("approval") >= 0) return "审批";
    if (/(experience|persona)/.test(type)) return "专家经验";
    if (type.indexOf("interview") >= 0) return "经验访谈";
    if (/(knowledge|sop)/.test(type)) return "知识依据";
    return "业务进展";
  }

  function safeBusinessCode(value) {
    var text = String(value || "").trim();
    return text && !/^[a-f0-9-]{24,}$/i.test(text) ? text : "";
  }

  function safeEmployeeLink(card) {
    var value = card.employee_url || card.web_url || card.detail_url;
    if (!value) return "";
    try {
      var url = new URL(value, window.location.origin);
      if (url.origin !== window.location.origin || url.pathname.indexOf("/assistant") !== 0) return "";
      return url.pathname + url.search + url.hash;
    } catch (error) {
      return "";
    }
  }

  function relevanceLabel(value) {
    var score = Number(value);
    if (!Number.isFinite(score)) return "";
    return score <= 1 ? Math.round(score * 100) + "%" : score.toFixed(2);
  }

  function authorizationScopeLabel(scopes) {
    if (!Array.isArray(scopes)) return "";
    var labels = { VENUE: "当前场地", DEPARTMENT: "部门", JOB_TITLE: "岗位", ROLE: "角色", USER: "指定员工" };
    return scopes.map(function (scope) {
      var type = String(scope.scope_type || "").toUpperCase();
      if (type === "VENUE") return labels.VENUE;
      var value = scope.scope_label || scope.scope_value;
      return value ? (labels[type] || "授权范围") + "：" + value : "";
    }).filter(Boolean).join("、");
  }

  function renderCard(card) {
    card = card || {};
    var label = cardTypeLabel(card);
    var title = card.title || card.name || card.subject || label + "更新";
    var summary = card.summary || card.description || card.content || "";
    var link = safeEmployeeLink(card);
    var experienceCard = String(card.card_type || "").toLowerCase().indexOf("experience") >= 0;
    var facts = experienceCard ? [
      ["经验编号", safeBusinessCode(card.business_code || card.reference_no || card.display_id)],
      ["经验专家", card.expert_name],
      ["适用情境", card.applicable_context],
      ["来源事件", safeBusinessCode(card.source_event_business_id)],
      ["授权范围", authorizationScopeLabel(card.authorization_scopes)],
      ["相关度", relevanceLabel(card.relevance)],
      ["版本", card.version_label || card.version],
      ["发布时间", card.published_at ? UI.dateLabel(card.published_at) : ""]
    ] : [
      ["业务编号", safeBusinessCode(card.business_code || card.reference_no || card.display_id)],
      ["当前状态", card.status ? UI.statusLabel(card.status) : ""],
      ["负责人", card.owner_name || card.assignee_name || card.owner],
      ["下一步", card.next_action || card.recommended_action],
      ["来源", card.source_title || card.source_name],
      ["版本", card.version_label || card.version],
      ["发布人", card.publisher_name],
      ["发布时间", card.published_at ? UI.dateLabel(card.published_at) : ""]
    ].filter(function (item) { return item[1] !== undefined && item[1] !== null && String(item[1]).trim(); });
    facts = facts.filter(function (item) { return item[1] !== undefined && item[1] !== null && String(item[1]).trim(); });
    var experienceDisclosure = experienceCard
      ? '<p class="experience-disclosure">由企业运营助手基于已发布并授权的专家经验生成，非专家本人实时回复。</p>'
      : "";
    return '<article class="wecom-card"><span>' + UI.escapeHTML(label) + '</span><h3>' + UI.escapeHTML(title) +
      "</h3>" + (summary ? "<p>" + UI.escapeHTML(summary) + "</p>" : "") +
      experienceDisclosure +
      (facts.length ? "<dl>" + facts.map(function (item) {
        return "<div><dt>" + UI.escapeHTML(item[0]) + "</dt><dd>" + UI.escapeHTML(item[1]) + "</dd></div>";
      }).join("") + "</dl>" : "") +
      (link ? '<div class="wecom-card-actions"><a href="' + UI.escapeHTML(link) + '">查看已发布依据</a></div>' : "") +
      "</article>";
  }

  function renderMessageRecovery(message) {
    var status = UI.statusCode(message.status);
    if (["RETRY_REQUIRED", "DEAD_LETTERED"].indexOf(status) < 0 || !message.message_id) return "";
    var disabled = state.retryingMessageId === message.message_id ? " disabled" : "";
    var label = disabled ? "正在重新提交" : "从原消息重试";
    return '<section class="wecom-recovery-card"><strong>需要人工重试</strong>' +
      '<p>自动恢复已达到上限。重试会继续原任务，不会重新发送文字或创建新消息。</p>' +
      '<button class="btn" type="button" data-retry-message-id="' + UI.escapeHTML(message.message_id) +
      '"' + disabled + ">" + label + "</button></section>";
  }

  function renderMessage(message) {
    var role = message.role === "user" ? "user" : "assistant";
    var identity = selectedIdentity();
    var name = role === "user"
      ? (identity && (identity.display_name || identity.username) || "员工")
      : "企业运营助手";
    var content = message.content || message.text || "";
    var status = UI.statusCode(message.status);
    var retryRequired = ["RETRY_REQUIRED", "DEAD_LETTERED"].indexOf(status) >= 0;
    var terminal = ["COMPLETED", "SUCCEEDED", "DONE", "FAILED", "ERROR", "CANCELLED", "RETRY_REQUIRED", "DEAD_LETTERED"].indexOf(status) >= 0;
    var text = content || (retryRequired
      ? "自动处理未完成，可以从这条原消息继续重试。"
      : terminal
        ? "本次处理未产生可展示的回复，请从管理后台运行记录确认。"
        : UI.statusLabel(message.status));
    var cards = Array.isArray(message.business_cards) ? message.business_cards : [];
    var attachments = messageAttachments(message);
    var attachmentsHTML = attachments.length
      ? '<div class="wecom-attachments">' + attachments.map(renderAttachment).join("") + "</div>"
      : "";
    var recoveryHTML = renderMessageRecovery(message);
    var senderLabel = role === "user"
      ? (message.optimistic ? name + " · " + UI.statusLabel(message.status) : name)
      : name;
    var avatarClass = role === "user" ? "message-avatar" : "message-avatar brand-avatar";
    var avatarHTML = role === "user"
      ? UI.escapeHTML(name.slice(0, 1))
      : '<img src="/admin/brand/logo-primary.svg" alt="">';
    return '<article class="wecom-message ' + role + '"><span class="' + avatarClass + '">' +
      avatarHTML + '</span><div class="message-stack"><span class="sender-name">' +
      UI.escapeHTML(senderLabel) + '</span><div class="wecom-bubble ' + (!content && !terminal ? "pending" : "") + '">' +
      UI.escapeHTML(text) + "</div>" + attachmentsHTML +
      (cards.length ? '<div class="wecom-business-cards">' + cards.map(renderCard).join("") + "</div>" : "") + recoveryHTML +
      '<time class="wecom-time">' + UI.escapeHTML(UI.dateLabel(message.created_at)) + "</time></div></article>";
  }

  function deliveryStatusLabel(value) {
    var labels = {
      DELIVERED: "已送达内部系统接入环境",
      FAILED: "送达失败",
      SENDING: "正在送达",
      PENDING: "等待送达",
      RECORDED: "已写入出站账本"
    };
    return labels[UI.statusCode(value)] || "尚无接入环境送达记录";
  }

  function renderOutboxFact(label, value) {
    if (value === undefined || value === null || String(value).trim() === "") return "";
    return "<div><dt>" + UI.escapeHTML(label) + "</dt><dd>" + UI.escapeHTML(value) + "</dd></div>";
  }

  function renderOutboxItem(item) {
    item = item || {};
    var failure = item.execution_error || item.delivery_error;
    var supersedesBusinessId = safeBusinessCode(item.supersedes_business_id);
    var facts = [
      renderOutboxFact("审批编号", safeBusinessCode(item.business_id)),
      renderOutboxFact("重新提交", supersedesBusinessId
        ? "替代上一张已拒绝审批 " + supersedesBusinessId
        : ""),
      renderOutboxFact("当前进展", item.status_summary),
      renderOutboxFact("送达状态", item.delivery_status ? deliveryStatusLabel(item.delivery_status) : "尚无接入环境送达记录"),
      renderOutboxFact("审批意见", item.review_comment),
      renderOutboxFact("失败原因", failure)
    ].filter(Boolean).join("");
    return '<article class="wecom-message assistant outbox"><span class="message-avatar brand-avatar"><img src="/admin/brand/logo-primary.svg" alt=""></span>' +
      '<div class="message-stack"><span class="sender-name">受控动作回执 · 来自真实审批与出站账本</span>' +
      '<section class="wecom-outbox-card ' + statusClass(item.status) + '"><header><strong>' +
      UI.escapeHTML(item.tool_label || "受控通知") + '</strong><span class="status-pill ' + statusClass(item.status) + '">' +
      UI.escapeHTML(UI.statusLabel(item.status)) + "</span></header><p>" + UI.escapeHTML(item.message || "未填写通知内容") +
      "</p>" + (facts ? "<dl>" + facts + "</dl>" : "") + "</section>" +
      '<time class="wecom-time">回流更新于 ' + UI.escapeHTML(UI.dateLabel(item.updated_at || item.created_at)) +
      "</time></div></article>";
  }

  function renderOutboxSummary() {
    var target = byId("outbox-summary");
    if (state.outboxUnavailable) {
      target.textContent = "审批回流暂不可用 · 已保留会话";
      return;
    }
    var count = state.outbox.filter(function (item) { return item.session_id === state.sessionId; }).length;
    target.textContent = "审批与出站回流：" + count;
  }

  function renderExperienceSummary() {
    var summary = byId("experience-summary");
    var entry = byId("experience-entry-button");
    if (!summary || !entry) return;
    if (!state.selectedUserId) {
      summary.textContent = "经验共创：等待选择员工";
      entry.disabled = true;
      return;
    }
    if (state.experience.loading) {
      summary.textContent = "经验共创：正在同步";
      entry.disabled = true;
      return;
    }
    var pendingInterviews = state.experience.interviews.filter(function (item) {
      return ["INVITED", "ACCEPTED", "IN_PROGRESS", "PAUSED"].indexOf(UI.statusCode(item.status)) >= 0;
    });
    var draftCards = state.experience.cards.filter(function (item) {
      return ["DRAFT", "EXPERT_CONFIRMED"].indexOf(UI.statusCode(item.status)) >= 0;
    });
    summary.textContent = "经验共创：" + pendingInterviews.length + " 项访谈 · " + draftCards.length + " 张待治理卡";
    entry.disabled = !pendingInterviews.length && !draftCards.length;
    entry.textContent = pendingInterviews.length ? "处理经验共创" : "查看经验卡";
  }

  function experienceFacts(items) {
    return items.filter(function (item) {
      return item && item[1] !== undefined && item[1] !== null && String(item[1]).trim() !== "";
    }).map(function (item) {
      return "<div><dt>" + UI.escapeHTML(item[0]) + "</dt><dd>" + UI.escapeHTML(String(item[1])) + "</dd></div>";
    }).join("");
  }

  function renderExperienceInterviewTimeline(interview) {
    var progress = experienceProgress(interview);
    var status = UI.statusCode(interview.status);
    var actionLabel = status === "INVITED" ? "接受邀请并开始" : "打开访谈";
    var expertName = displayText(interview.expert_name, "经验专家");
    var facts = experienceFacts([
      ["专家", expertName],
      ["进度", progress.answered + " / " + progress.total + " 轮"],
      ["访谈编号", interview.business_id || interview.id],
      ["来源事件", safeBusinessCode(interview.source_event_id)]
    ]);
    return '<article class="wecom-message assistant experience-message"><span class="message-avatar brand-avatar"><img src="/admin/brand/logo-primary.svg" alt=""></span>' +
      '<div class="message-stack"><span class="sender-name">企业运营助手 · 经验共创</span>' +
      '<section class="experience-timeline-card"><header><span>专家访谈邀请</span><span class="status-pill ' +
      experienceStatusClass(status) + '">' + UI.escapeHTML(UI.statusLabel(status)) + '</span></header>' +
      '<h3>' + UI.escapeHTML(readableTitle(interview.title, "经验访谈")) + '</h3>' +
      '<p>这是一项面向 ' + UI.escapeHTML(expertName) + ' 的经验共创任务。回答会保留为来源证据，完成后由 PersonaExtract 生成可修订草稿。</p>' +
      (facts ? '<dl>' + facts + '</dl>' : '') +
      '<footer><small>更新于 ' + UI.escapeHTML(UI.dateLabel(interview.updated_at || interview.created_at)) + '</small>' +
      '<button class="btn primary" type="button" data-action="open-interview" data-interview-id="' +
      UI.escapeHTML(interview.id) + '">' + actionLabel + '</button></footer></section>' +
      '<time class="wecom-time">' + UI.escapeHTML(UI.dateLabel(interview.updated_at || interview.created_at)) +
      '</time></div></article>';
  }

  function renderExperienceCardTimeline(card) {
    var status = UI.statusCode(card.status);
    var version = Number(card.current_version || card.published_version || card.version || 1);
    var source = card.source || {};
    var scopes = Array.isArray(card.authorization_scopes) ? card.authorization_scopes : [];
    var facts = experienceFacts([
      ["经验编号", card.business_id || card.id],
      ["来源专家", experienceSourceName(card)],
      ["来源访谈", source.interview_business_id || source.interview_id],
      ["授权范围", scopes.map(experienceScopeLabel).join("、")]
    ]);
    var actionLabel = status === "DRAFT" ? "检查并确认草稿" : "查看经验卡";
    return '<article class="wecom-message assistant experience-message"><span class="message-avatar brand-avatar"><img src="/admin/brand/logo-primary.svg" alt=""></span>' +
      '<div class="message-stack"><span class="sender-name">企业运营助手 · 经验资产</span>' +
      '<section class="experience-timeline-card"><header><span>人类可读经验卡 · 第 ' + version + ' 版</span><span class="status-pill ' +
      experienceStatusClass(status) + '">' + UI.escapeHTML(UI.statusLabel(status)) + '</span></header>' +
      '<h3>' + UI.escapeHTML(readableTitle(card.title, "未命名经验")) + '</h3>' +
      '<p>' + UI.escapeHTML(displayText(card.applicable_context, "经验适用范围待专家补充。")) + '</p>' +
      (facts ? '<dl>' + facts + '</dl>' : '') +
      '<footer><small>更新于 ' + UI.escapeHTML(UI.dateLabel(card.updated_at || card.created_at)) + '</small>' +
      '<button class="btn primary" type="button" data-action="open-experience-card" data-experience-card-id="' +
      UI.escapeHTML(card.id) + '">' + actionLabel + '</button></footer></section>' +
      '<time class="wecom-time">' + UI.escapeHTML(UI.dateLabel(card.updated_at || card.created_at)) +
      '</time></div></article>';
  }

  function renderExperienceError() {
    if (!state.experience.error) return "";
    return '<article class="wecom-message assistant experience-message"><span class="message-avatar brand-avatar"><img src="/admin/brand/logo-primary.svg" alt=""></span>' +
      '<div class="message-stack"><span class="sender-name">企业运营助手 · 经验共创</span>' +
      '<section class="wecom-recovery-card failed"><strong>经验共创暂时未同步</strong><p>' +
      UI.escapeHTML(UI.errorView(state.experience.error).message) + '</p><button class="btn" type="button" data-action="reload-experience">重新同步经验任务</button></section></div></article>';
  }

  function experienceTimelineEntries() {
    var entries = [];
    state.experience.interviews.forEach(function (interview) {
      entries.push({
        kind: "interview",
        value: interview,
        at: Number(interview.updated_at || interview.created_at || 0),
        id: interview.id || ""
      });
    });
    state.experience.cards.forEach(function (card) {
      entries.push({
        kind: "experience-card",
        value: card,
        at: Number(card.updated_at || card.created_at || 0),
        id: card.id || ""
      });
    });
    return entries.sort(function (left, right) {
      return left.at - right.at || String(left.id).localeCompare(String(right.id));
    });
  }

  async function loadExperience() {
    var userId = state.selectedUserId;
    var ownerKey = experienceOwnerKey();
    var requestVersion = state.experience.loadVersion + 1;
    state.experience.loadVersion = requestVersion;
    if (!userId) {
      state.experience.expert = null;
      state.experience.interviews = [];
      state.experience.cards = [];
      state.experience.error = null;
      state.experience.loading = false;
      renderExperienceSummary();
      renderMessages();
      return;
    }
    state.experience.loading = true;
    state.experience.error = null;
    renderExperienceSummary();
    try {
      var payload = await Client.recovery.run(function (signal) {
        return Client.experience.home(experienceOptions(signal, userId));
      }, {
        timeoutMs: 300000,
        onRecovering: showServiceRecovering,
        onRecovered: showServiceRecovered
      });
      if (state.experience.loadVersion !== requestVersion ||
          state.selectedUserId !== userId || experienceOwnerKey() !== ownerKey) return;
      state.experience.expert = payload && payload.expert || null;
      state.experience.interviews = UI.arrayFrom(payload, ["interviews"]);
      state.experience.cards = UI.arrayFrom(payload, ["cards"]);
      state.experience.error = null;
    } catch (error) {
      if (state.experience.loadVersion !== requestVersion ||
          state.selectedUserId !== userId || experienceOwnerKey() !== ownerKey) return;
      state.experience.expert = null;
      state.experience.interviews = [];
      state.experience.cards = [];
      state.experience.error = error;
    } finally {
      if (state.experience.loadVersion === requestVersion && state.selectedUserId === userId) {
        state.experience.loading = false;
        renderExperienceSummary();
        renderMessages();
      }
    }
  }

  function clearInlineError(id) {
    var target = byId(id);
    if (!target) return;
    target.hidden = true;
    target.textContent = "";
  }

  function showInlineError(id, error) {
    var target = byId(id);
    if (!target) return;
    target.hidden = false;
    target.textContent = UI.errorView(error).message;
  }

  function interviewTurns(interview) {
    return Array.isArray(interview && interview.turns) ? interview.turns : [];
  }

  function canCompleteInterview(interview) {
    var progress = experienceProgress(interview);
    return progress.answered >= progress.total &&
      ["ACCEPTED", "IN_PROGRESS", "PAUSED"].indexOf(UI.statusCode(interview && interview.status)) >= 0;
  }

  function renderInterviewExtraction(mode) {
    var form = byId("interview-complete-form");
    var status = byId("interview-extraction-status");
    var detail = byId("interview-extraction-detail");
    var button = byId("interview-complete-button");
    if (!form || !status || !detail || !button) return;
    var extracting = mode === "extracting";
    form.classList.toggle("is-extracting", extracting);
    form.setAttribute("aria-busy", extracting ? "true" : "false");
    if (extracting) {
      status.textContent = "正在萃取经验草稿";
      detail.textContent = "四轮回答已经保存，DeepSeek 正在整理判断信号、动作和边界条件。";
      button.hidden = true;
      return;
    }
    if (mode === "failed") {
      status.textContent = "萃取未完成";
      detail.textContent = "回答没有丢失，可以重新生成草稿，不需要再次作答。";
      button.textContent = "重新生成经验草稿";
    } else {
      status.textContent = "四轮回答已完成";
      detail.textContent = "生成后可以逐项修订，再由专家确认提交审核。";
      button.textContent = "生成经验草稿";
    }
    button.hidden = false;
  }

  function renderInterviewDialog(interview) {
    state.experience.selectedInterview = interview;
    var progress = experienceProgress(interview);
    var status = UI.statusCode(interview.status);
    var turns = interviewTurns(interview);
    var identity = selectedIdentity();
    byId("interview-dialog-title").textContent = readableTitle(interview.title, "专家经验访谈");
    byId("interview-identity-note").textContent =
      "当前接入身份：" + displayText(identity && (identity.display_name || identity.username), "企业员工") +
      "。访谈原话会作为不可变来源证据保存。";
    byId("interview-progress").innerHTML =
      '<div class="progress-label"><span class="status-pill ' + experienceStatusClass(status) + '">' +
      UI.escapeHTML(UI.statusLabel(status)) + '</span><strong>已回答 ' + progress.answered + ' / ' + progress.total +
      '</strong></div><progress value="' + progress.answered + '" max="' + progress.total + '"></progress>';
    byId("interview-turns").innerHTML = turns.length ? turns.map(function (turn) {
      return '<article class="interview-turn"><span>第 ' + Number(turn.turn_number || 0) + ' 题</span><h3>' +
        UI.escapeHTML(turn.question_text || "访谈问题") + '</h3><p>' +
        UI.escapeHTML(turn.answer_text || "") + '</p></article>';
    }).join("") : '<div class="wecom-empty compact"><strong>访谈尚未开始</strong><p>接受邀请后，助手会逐题提问。</p></div>';
    var active = ["ACCEPTED", "IN_PROGRESS"].indexOf(status) >= 0;
    var completeReady = canCompleteInterview(interview);
    byId("interview-command-bar").hidden = ["INVITED", "ACCEPTED", "IN_PROGRESS", "PAUSED"].indexOf(status) < 0;
    byId("interview-accept-button").hidden = status !== "INVITED";
    byId("interview-pause-button").hidden = !active;
    byId("interview-resume-button").hidden = status !== "PAUSED";
    byId("interview-answer-form").hidden = !active || !interview.next_question;
    byId("interview-complete-form").hidden = !completeReady;
    byId("interview-next-question").innerHTML = interview.next_question
      ? '<span>下一题</span><strong>' + UI.escapeHTML(interview.next_question) + '</strong>' : "";
    if (completeReady) renderInterviewExtraction("ready");
  }

  async function openInterview(interviewId) {
    if (!state.selectedUserId) return;
    var userId = state.selectedUserId;
    var ownerKey = experienceOwnerKey();
    var requestVersion = state.experience.interviewLoadVersion + 1;
    state.experience.interviewLoadVersion = requestVersion;
    state.experience.selectedInterview = null;
    var dialog = byId("interview-dialog");
    clearInlineError("interview-action-error");
    byId("interview-dialog-title").textContent = "正在读取访谈";
    byId("interview-turns").innerHTML = "";
    byId("interview-progress").innerHTML = "";
    byId("interview-command-bar").hidden = true;
    byId("interview-answer-form").hidden = true;
    byId("interview-complete-form").hidden = true;
    if (!dialog.open) dialog.showModal();
    try {
      var payload = await Client.recovery.run(function (signal) {
        return Client.experience.interview(interviewId, experienceOptions(signal, userId));
      }, { timeoutMs: 300000 });
      if (state.experience.interviewLoadVersion !== requestVersion ||
          state.selectedUserId !== userId || experienceOwnerKey() !== ownerKey) return;
      renderInterviewDialog(payload.interview || payload);
    } catch (error) {
      if (state.experience.interviewLoadVersion !== requestVersion ||
          state.selectedUserId !== userId || experienceOwnerKey() !== ownerKey) return;
      showInlineError("interview-action-error", error);
    }
  }

  function closeInterview() {
    state.experience.interviewLoadVersion += 1;
    var dialog = byId("interview-dialog");
    if (dialog && dialog.open) dialog.close();
    state.experience.selectedInterview = null;
  }

  async function refreshSelectedInterview() {
    var interview = state.experience.selectedInterview;
    if (!interview) return null;
    var userId = state.selectedUserId;
    var ownerKey = experienceOwnerKey();
    var requestVersion = state.experience.interviewLoadVersion;
    var payload = await Client.recovery.run(function (signal) {
      return Client.experience.interview(interview.id, experienceOptions(signal, userId));
    }, { timeoutMs: 300000 });
    if (state.experience.interviewLoadVersion !== requestVersion ||
        state.selectedUserId !== userId || experienceOwnerKey() !== ownerKey ||
        !state.experience.selectedInterview || state.experience.selectedInterview.id !== interview.id) return null;
    var refreshed = payload.interview || payload;
    renderInterviewDialog(refreshed);
    return refreshed;
  }

  function setExperienceSubmitting(dialogId, value) {
    state.experience.submitting = value;
    var identitySelect = byId("identity-select");
    identitySelect.disabled = value || !state.identities.length;
    if (!value) identitySelect.value = state.selectedUserId || "";
    var dialog = byId(dialogId);
    if (!dialog || !dialog.querySelectorAll) return;
    dialog.querySelectorAll("button, input, textarea").forEach(function (control) {
      var action = control.getAttribute("data-action");
      if (action !== "close-interview" && action !== "close-experience-card") control.disabled = value;
    });
  }

  async function acceptInterview() {
    var interview = state.experience.selectedInterview;
    if (!interview || state.experience.submitting) return;
    clearInlineError("interview-action-error");
    setExperienceSubmitting("interview-dialog", true);
    try {
      await Client.experience.acceptInterview(interview.id, experienceOptions());
      await refreshSelectedInterview();
      await loadExperience();
      notify("访谈邀请已接受，可以开始回答。", "success");
    } catch (error) {
      showInlineError("interview-action-error", error);
    } finally {
      setExperienceSubmitting("interview-dialog", false);
    }
  }

  async function pauseInterview() {
    var interview = state.experience.selectedInterview;
    if (!interview || state.experience.submitting) return;
    clearInlineError("interview-action-error");
    setExperienceSubmitting("interview-dialog", true);
    try {
      await Client.experience.pauseInterview(interview.id, experienceOptions());
      await refreshSelectedInterview();
      await loadExperience();
      notify("访谈进度已保存，可以稍后恢复。", "success");
    } catch (error) {
      showInlineError("interview-action-error", error);
    } finally {
      setExperienceSubmitting("interview-dialog", false);
    }
  }

  async function resumeInterview() {
    var interview = state.experience.selectedInterview;
    if (!interview || state.experience.submitting) return;
    clearInlineError("interview-action-error");
    setExperienceSubmitting("interview-dialog", true);
    try {
      await Client.experience.resumeInterview(interview.id, experienceOptions());
      await refreshSelectedInterview();
      await loadExperience();
      notify("访谈已恢复。", "success");
    } catch (error) {
      showInlineError("interview-action-error", error);
    } finally {
      setExperienceSubmitting("interview-dialog", false);
    }
  }

  async function answerInterview(event) {
    event.preventDefault();
    var interview = state.experience.selectedInterview;
    if (!interview || state.experience.submitting) return;
    var form = byId("interview-answer-form");
    var progress = experienceProgress(interview);
    var idempotencyKey = form.getAttribute("data-idempotency-key") ||
      (interview.id + "-question-" + String(progress.answered + 1));
    form.setAttribute("data-idempotency-key", idempotencyKey);
    clearInlineError("interview-action-error");
    setExperienceSubmitting("interview-dialog", true);
    try {
      await Client.experience.answerInterview(interview.id, {
        answer: byId("interview-answer").value,
        source_excerpt: byId("interview-source-excerpt").value,
        idempotency_key: idempotencyKey
      }, experienceOptions());
      form.reset();
      form.removeAttribute("data-idempotency-key");
      await refreshSelectedInterview();
      await loadExperience();
      notify("本题回答已保存。", "success");
    } catch (error) {
      showInlineError("interview-action-error", error);
    } finally {
      setExperienceSubmitting("interview-dialog", false);
    }
  }

  async function completeInterview(event) {
    if (event) event.preventDefault();
    var interview = state.experience.selectedInterview;
    if (!interview || state.experience.submitting) return;
    clearInlineError("interview-action-error");
    renderInterviewExtraction("extracting");
    setExperienceSubmitting("interview-dialog", true);
    try {
      var payload = await Client.experience.completeInterview(interview.id, experienceOptions());
      var card = payload && payload.card;
      if (!card) throw new Error("服务端没有返回经验草稿，请重新萃取。");
      closeInterview();
      await loadExperience();
      notify("经验草稿已生成，请检查字段和边界条件。", "success");
      openExperienceCard(card.id, card, payload && payload.extraction);
    } catch (error) {
      renderInterviewExtraction("failed");
      showInlineError("interview-action-error", error);
    } finally {
      setExperienceSubmitting("interview-dialog", false);
    }
  }

  function experienceDetailHTML(card) {
    function section(label, value) {
      var values = lineItems(value);
      if (!values.length) return '<section><h3>' + UI.escapeHTML(label) + '</h3><p>待补充</p></section>';
      if (Array.isArray(value) || values.length > 1) {
        return '<section><h3>' + UI.escapeHTML(label) + '</h3><ul>' + values.map(function (item) {
          return '<li>' + UI.escapeHTML(item) + '</li>';
        }).join("") + '</ul></section>';
      }
      return '<section><h3>' + UI.escapeHTML(label) + '</h3><p>' + UI.escapeHTML(values[0]) + '</p></section>';
    }
    return section("适用情境", card.applicable_context) +
      section("识别信号", card.signals) +
      section("判断规则", card.decision_rule) +
      section("建议动作", card.recommended_actions) +
      section("判断依据", card.rationale) +
      section("禁止事项", card.prohibitions) +
      section("例外情况", card.exceptions) +
      section("来源原话", card.source_excerpts);
  }

  function populateExperienceCardForm(card) {
    byId("experience-card-title").value = displayText(card.title);
    byId("experience-card-context").value = displayText(card.applicable_context);
    byId("experience-card-signals").value = joinLines(card.signals);
    byId("experience-card-actions").value = joinLines(card.recommended_actions);
    byId("experience-card-rule").value = displayText(card.decision_rule);
    byId("experience-card-rationale").value = displayText(card.rationale);
    byId("experience-card-prohibitions").value = joinLines(card.prohibitions);
    byId("experience-card-exceptions").value = joinLines(card.exceptions);
    byId("experience-card-sources").value = joinLines(card.source_excerpts);
    byId("experience-card-change-note").value = "";
  }

  function renderExperienceCardDialog(card) {
    state.experience.selectedCard = card;
    var status = UI.statusCode(card.status);
    var source = card.source || {};
    var version = Number(card.current_version || card.published_version || card.version || 1);
    byId("experience-card-dialog-title").textContent = readableTitle(card.title, "经验卡");
    byId("experience-card-status").innerHTML = '<span class="status-pill ' + experienceStatusClass(status) + '">' +
      UI.escapeHTML(UI.statusLabel(status)) + '</span><span>第 ' + version + ' 版</span><span>专家：' +
      UI.escapeHTML(experienceSourceName(card)) + '</span>';
    var scopes = Array.isArray(card.authorization_scopes) ? card.authorization_scopes : [];
    byId("experience-card-origin").innerHTML = experienceFacts([
      ["经验编号", card.business_id || card.id],
      ["来源访谈", source.interview_business_id || source.interview_id],
      ["来源事件", safeBusinessCode(source.event_id || card.source_event_id)],
      ["授权范围", scopes.map(experienceScopeLabel).join("、")]
    ]).replace(/<dt>/g, "<span>").replace(/<\/dt>/g, "</span>").replace(/<dd>/g, "<strong>").replace(/<\/dd>/g, "</strong>");
    byId("experience-card-readonly").innerHTML = experienceDetailHTML(card);
    byId("experience-card-revise-form").hidden = status !== "DRAFT";
    byId("experience-card-confirm-button").hidden = status !== "DRAFT";
    if (status === "DRAFT") populateExperienceCardForm(card);
  }

  function openExperienceCard(cardId, suppliedCard, extraction) {
    var card = suppliedCard || state.experience.cards.find(function (item) { return item.id === cardId; });
    if (!card) {
      showInlineError("experience-card-action-error", new Error("经验卡尚未同步，请刷新后重试。"));
      return;
    }
    clearInlineError("experience-card-action-error");
    state.experience.selectedExtraction = extraction || null;
    renderExperienceCardDialog(card);
    var dialog = byId("experience-card-dialog");
    if (!dialog.open) dialog.showModal();
  }

  function closeExperienceCard() {
    var dialog = byId("experience-card-dialog");
    if (dialog && dialog.open) dialog.close();
    state.experience.selectedCard = null;
    state.experience.selectedExtraction = null;
  }

  function replaceExperienceCard(card) {
    var index = state.experience.cards.findIndex(function (item) { return item.id === card.id; });
    if (index >= 0) state.experience.cards[index] = card;
    else state.experience.cards.unshift(card);
    renderExperienceSummary();
    renderExperienceCardDialog(card);
    renderMessages();
  }

  async function reviseExperienceCard(event) {
    event.preventDefault();
    var card = state.experience.selectedCard;
    if (!card || state.experience.submitting) return;
    clearInlineError("experience-card-action-error");
    setExperienceSubmitting("experience-card-dialog", true);
    try {
      var payload = await Client.experience.reviseCard(card.id, {
        title: byId("experience-card-title").value.trim(),
        applicable_context: byId("experience-card-context").value.trim(),
        signals: lineItems(byId("experience-card-signals").value),
        decision_rule: byId("experience-card-rule").value.trim(),
        recommended_actions: lineItems(byId("experience-card-actions").value),
        rationale: byId("experience-card-rationale").value.trim(),
        prohibitions: lineItems(byId("experience-card-prohibitions").value),
        exceptions: lineItems(byId("experience-card-exceptions").value),
        source_excerpts: lineItems(byId("experience-card-sources").value),
        change_note: byId("experience-card-change-note").value.trim()
      }, experienceOptions());
      replaceExperienceCard(payload.card || payload);
      notify("经验修订已保存，版本记录已保留。", "success");
    } catch (error) {
      showInlineError("experience-card-action-error", error);
    } finally {
      setExperienceSubmitting("experience-card-dialog", false);
    }
  }

  async function confirmExperienceCard() {
    var card = state.experience.selectedCard;
    if (!card || state.experience.submitting) return;
    clearInlineError("experience-card-action-error");
    setExperienceSubmitting("experience-card-dialog", true);
    try {
      var payload = await Client.experience.confirmCard(card.id, experienceOptions());
      replaceExperienceCard(payload.card || payload);
      notify("经验已由专家确认并提交审核。", "success");
    } catch (error) {
      showInlineError("experience-card-action-error", error);
    } finally {
      setExperienceSubmitting("experience-card-dialog", false);
    }
  }

  function openLatestExperience() {
    var interview = state.experience.interviews.find(function (item) {
      return ["INVITED", "ACCEPTED", "IN_PROGRESS", "PAUSED"].indexOf(UI.statusCode(item.status)) >= 0;
    });
    if (interview) {
      openInterview(interview.id);
      return;
    }
    var card = state.experience.cards.find(function (item) {
      return ["DRAFT", "EXPERT_CONFIRMED"].indexOf(UI.statusCode(item.status)) >= 0;
    });
    if (card) openExperienceCard(card.id, card);
  }

  function renderMessages() {
    var target = byId("simulator-message-stream");
    var visibleMessages = state.messages.slice();
    visibleMessages = visibleMessages.concat(state.optimisticMessages.filter(function (message) {
      if (message.user_id !== state.selectedUserId) return false;
      return state.sessionId ? message.session_id === state.sessionId : !message.session_id;
    }));
    var timeline = visibleMessages.map(function (message) {
      return { kind: "message", value: message, at: Number(message.created_at) || 0, id: message.id || message.message_id || "" };
    });
    state.outbox.filter(function (item) {
      return item.session_id === state.sessionId;
    }).forEach(function (item) {
      timeline.push({ kind: "outbox", value: item, at: Number(item.created_at) || 0, id: item.id || "" });
    });
    experienceTimelineEntries().forEach(function (entry) {
      timeline.push(entry);
    });
    timeline.sort(function (left, right) {
      return left.at - right.at || String(left.id).localeCompare(String(right.id));
    });
    renderOutboxSummary();
    renderExperienceSummary();
    if (!timeline.length && !state.experience.error) {
      target.innerHTML = emptyMessageTemplate;
      return;
    }
    var rendered = timeline.map(function (entry) {
      if (entry.kind === "outbox") return renderOutboxItem(entry.value);
      if (entry.kind === "interview") return renderExperienceInterviewTimeline(entry.value);
      if (entry.kind === "experience-card") return renderExperienceCardTimeline(entry.value);
      return renderMessage(entry.value);
    }).join("");
    target.innerHTML = rendered + renderExperienceError();
    hydrateAttachmentPreviews(target);
    window.requestAnimationFrame(function () { target.scrollTop = target.scrollHeight; });
  }

  function latestOpenEventId() {
    for (var messageIndex = state.messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
      var cards = Array.isArray(state.messages[messageIndex].business_cards)
        ? state.messages[messageIndex].business_cards
        : [];
      for (var cardIndex = cards.length - 1; cardIndex >= 0; cardIndex -= 1) {
        var card = cards[cardIndex] || {};
        var type = String(card.card_type || card.type || card.kind || "").toLowerCase();
        var status = UI.statusCode(card.status);
        if (type.indexOf("event") >= 0 &&
            ["CLOSED", "DONE", "CANCELLED"].indexOf(status) < 0) {
          return card.resource_id || card.event_id || "";
        }
      }
    }
    return "";
  }

  function messageAttachments(message) {
    return Array.isArray(message.attachments) ? message.attachments : [];
  }

  function attachmentSizeLabel(value) {
    var bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return "大小待确认";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function renderAttachment(attachment) {
    attachment = attachment || {};
    var attachmentId = String(attachment.attachment_id || "").trim();
    if (!attachmentId) return "";
    var name = attachment.name || "现场图片";
    var description = attachment.description || "未填写图片说明";
    var uploader = attachment.uploaded_by_name || "企业员工";
    var createdAt = attachment.created_at ? UI.dateLabel(attachment.created_at) : "时间待确认";
    return '<figure class="wecom-attachment"><div class="wecom-attachment-preview" data-attachment-preview-id="' +
      UI.escapeHTML(attachmentId) + '" data-attachment-name="' + UI.escapeHTML(name) +
      '"><span>缩略图加载中</span></div><figcaption><strong>' + UI.escapeHTML(name) +
      '</strong><span>' + UI.escapeHTML(description) + '</span><small>' + UI.escapeHTML(uploader + " · " + createdAt +
      " · " + attachmentSizeLabel(attachment.size_bytes)) + "</small></figcaption></figure>";
  }

  function paintAttachmentPreview(preview, objectUrl) {
    preview.textContent = "";
    preview.classList.remove("failed");
    var image = document.createElement("img");
    image.src = objectUrl;
    image.alt = preview.getAttribute("data-attachment-name") || "现场图片缩略图";
    image.loading = "lazy";
    preview.appendChild(image);
  }

  function updateAttachmentPreviews(attachmentId, objectUrl, errorText) {
    var target = byId("simulator-message-stream");
    Array.prototype.forEach.call(target.querySelectorAll("[data-attachment-preview-id]"), function (preview) {
      if (preview.getAttribute("data-attachment-preview-id") !== attachmentId) return;
      if (objectUrl) paintAttachmentPreview(preview, objectUrl);
      else {
        preview.classList.add("failed");
        preview.textContent = errorText || "缩略图暂不可用";
      }
    });
  }

  function hydrateAttachmentPreviews(target) {
    Array.prototype.forEach.call(target.querySelectorAll("[data-attachment-preview-id]"), function (preview) {
      var attachmentId = preview.getAttribute("data-attachment-preview-id");
      if (state.attachmentObjectUrls[attachmentId]) {
        paintAttachmentPreview(preview, state.attachmentObjectUrls[attachmentId]);
        return;
      }
      if (state.attachmentLoads[attachmentId]) return;
      state.attachmentLoads[attachmentId] = Client.attachments.content(attachmentId).then(function (blob) {
        if (!blob || !blob.size) throw new Error("附件内容为空");
        var objectUrl = URL.createObjectURL(blob);
        state.attachmentObjectUrls[attachmentId] = objectUrl;
        updateAttachmentPreviews(attachmentId, objectUrl);
      }).catch(function () {
        updateAttachmentPreviews(attachmentId, null, "缩略图暂不可用");
      }).finally(function () {
        delete state.attachmentLoads[attachmentId];
      });
    });
  }

  function clearAttachmentObjectUrls() {
    Object.keys(state.attachmentObjectUrls).forEach(function (attachmentId) {
      URL.revokeObjectURL(state.attachmentObjectUrls[attachmentId]);
    });
    state.attachmentObjectUrls = {};
    state.attachmentLoads = {};
  }

  function applyMessagePayload(payload) {
    state.messages = UI.arrayFrom(payload, ["messages", "items", "history"]);
    if (payload && payload.session) {
      state.sessionId = payload.session.session_id || state.sessionId;
      state.externalConversationId = payload.session.external_conversation_id || state.externalConversationId;
    }
    reconcileOptimisticMessages();
    saveContext();
    renderSessionOptions();
    renderMessages();
    restoreEvidenceFromMessages();
    updateSessionSummary();
  }

  function applyOutboxPayload(payload) {
    state.outbox = UI.arrayFrom(payload, ["items", "outbox"]);
    state.outboxUnavailable = false;
    renderMessages();
  }

  async function syncOutbox(sessionId, userId) {
    if (!sessionId || !userId) return;
    try {
      var payload = await Client.recovery.run(function (signal) {
        return Client.simulator.outbox(sessionId, userId, { signal: signal });
      }, {
        timeoutMs: 15000,
        attemptTimeoutMs: 5000
      });
      if (state.sessionId !== sessionId || state.selectedUserId !== userId) return;
      applyOutboxPayload(payload);
      return true;
    } catch (error) {
      if (state.sessionId !== sessionId || state.selectedUserId !== userId) return;
      state.outboxUnavailable = true;
      renderOutboxSummary();
      return false;
    }
  }

  function latestPending() {
    return state.messages.filter(function (message) {
      return message.role === "assistant" && [
        "COMPLETED", "SUCCEEDED", "DONE", "FAILED", "ERROR", "CANCELLED", "RETRY_REQUIRED", "DEAD_LETTERED"
      ].indexOf(UI.statusCode(message.status)) < 0;
    }).pop();
  }

  async function loadSession(resume) {
    if (!state.sessionId || !state.selectedUserId) {
      renderMessages();
      return;
    }
    var sessionId = state.sessionId;
    var userId = state.selectedUserId;
    clearError();
    byId("delivery-status").textContent = "正在读取服务端会话状态";
    try {
      var payload = await Client.recovery.run(function (signal) {
        return Client.assistant.messages(sessionId, {
          acting_user_id: userId,
          limit: 200,
          signal: signal
        });
      }, {
        timeoutMs: 300000,
        onRecovering: showServiceRecovering,
        onRecovered: showServiceRecovered
      });
      if (state.sessionId !== sessionId || state.selectedUserId !== userId) return;
      applyMessagePayload(payload);
      await syncOutbox(sessionId, userId);
      var pending = latestPending();
      if (resume && pending && pending.message_id) followRun(pending.message_id);
      else {
        var latest = state.messages.slice().reverse().find(function (message) { return message.role === "assistant"; });
        byId("delivery-status").textContent = latest ? UI.statusLabel(latest.status) : "会话已同步";
      }
    } catch (error) {
      if (state.sessionId !== sessionId || state.selectedUserId !== userId) return;
      renderMessages();
      showError(error, "refresh");
      if (Client.recovery.isTransient(error)) showRecoveryDeferred();
      else byId("delivery-status").textContent = "会话读取失败";
    }
  }

  function followRun(messageId) {
    if (!state.sessionId || !state.selectedUserId) return;
    if (state.followController) state.followController.abort();
    var sessionId = state.sessionId;
    var userId = state.selectedUserId;
    var controller = new AbortController();
    state.followController = controller;
    Client.assistant.follow(sessionId, messageId, {
      signal: controller.signal,
      timeoutMs: 300000,
      recoveryBaseDelayMs: 1000,
      recoveryMaxDelayMs: 15000,
      recoveryAttemptTimeoutMs: 15000,
      finalReadTimeoutMs: 15000,
      query: { acting_user_id: userId, limit: 200 },
      onRecovering: function () {
        if (state.sessionId === sessionId && state.selectedUserId === userId) showServiceRecovering();
      },
      onRecovered: function () {
        if (state.sessionId === sessionId && state.selectedUserId === userId) showServiceRecovered();
      },
      onUpdate: function (payload) {
        if (state.sessionId === sessionId && state.selectedUserId === userId) {
          applyMessagePayload(payload);
          var latest = state.messages.slice().reverse().find(function (message) { return message.role === "assistant"; });
          if (latest) byId("delivery-status").textContent = UI.statusLabel(latest.status);
        }
      }
    }).then(async function (payload) {
      if (state.sessionId !== sessionId || state.selectedUserId !== userId) return;
      applyMessagePayload(payload);
      await syncOutbox(sessionId, userId);
    }).catch(function (error) {
      if (error && error.name === "AbortError") return;
      if (state.sessionId !== sessionId || state.selectedUserId !== userId) return;
      showError(error, "refresh");
      if (Client.recovery.isTransient(error)) showRecoveryDeferred();
      else byId("delivery-status").textContent = UI.errorView(error).message;
    }).finally(function () {
      if (state.followController === controller) state.followController = null;
    });
  }

  function setSubmitting(value) {
    state.submitting = value;
    byId("simulator-send").disabled = value || !state.selectedUserId;
    byId("simulator-message-input").disabled = value || !state.selectedUserId;
    byId("simulator-attachment-file").disabled = value || !state.selectedUserId;
    byId("simulator-attachment-note").disabled = value || !state.selectedUserId;
    byId("identity-select").disabled = value || !state.identities.length;
    byId("session-select").disabled = value || state.sessionsLoading || !state.sessions.length;
    byId("simulator-send").textContent = value ? "提交中" : "发送";
  }

  function selectedAttachmentFile() {
    var files = byId("simulator-attachment-file").files;
    return files && files.length ? files[0] : null;
  }

  function renderAttachmentSelection(message) {
    var target = byId("simulator-attachment-selection");
    if (message) {
      target.textContent = message;
      return;
    }
    var file = selectedAttachmentFile();
    target.textContent = file
      ? file.name + " · " + attachmentSizeLabel(file.size)
      : "尚未选择现场图片";
  }

  async function uploadPendingAttachment(userId) {
    var file = selectedAttachmentFile();
    if (!file) return null;
    if (state.pendingAttachment && state.pendingAttachment.file === file) {
      return state.pendingAttachment.attachment;
    }
    renderAttachmentSelection("正在上传并检查 " + file.name + "…");
    try {
      var attachment = await Client.simulator.uploadAttachment(userId, file);
      if (!attachment || !attachment.attachment_id) {
        throw new Error("服务端没有返回附件编号，请重新上传。");
      }
      state.pendingAttachment = { file: file, attachment: attachment };
      renderAttachmentSelection(file.name + " · 已通过安全检查");
      return attachment;
    } catch (error) {
      state.pendingAttachment = null;
      renderAttachmentSelection(file.name + " · 上传未完成，消息文字已保留");
      throw error;
    }
  }

  function ensurePendingExternalMessageId() {
    if (!state.pendingExternalMessageId) {
      state.pendingExternalMessageId = Client.ids.externalMessage("wecom-sim");
    }
    return state.pendingExternalMessageId;
  }

  function resetPendingExternalMessageId(force) {
    if (state.submitting && !force) return;
    state.pendingExternalMessageId = "";
  }

  function clearOptimisticAttachmentPreviews(message) {
    (message.attachments || []).forEach(function (attachment) {
      var attachmentId = attachment.attachment_id;
      var objectUrl = state.attachmentObjectUrls[attachmentId];
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      delete state.attachmentObjectUrls[attachmentId];
    });
  }

  function optimisticAttachments(description, externalMessageId, userId) {
    var file = selectedAttachmentFile();
    if (!file) return [];
    var attachmentId = "pending-" + externalMessageId;
    var identity = state.identities.find(function (item) { return item.user_id === userId; }) || null;
    state.attachmentObjectUrls[attachmentId] = URL.createObjectURL(file);
    return [{
      attachment_id: attachmentId,
      name: file.name || "现场图片",
      description: description,
      uploaded_by_name: identity && (identity.display_name || identity.username) || "企业员工",
      created_at: Date.now() / 1000,
      size_bytes: file.size
    }];
  }

  function showOptimisticMessage(content, attachmentNote, externalMessageId, userId, sessionId) {
    var message = {
      role: "user",
      content: content,
      external_message_id: externalMessageId,
      user_id: userId,
      session_id: sessionId || "",
      status: "SENDING",
      created_at: Date.now() / 1000,
      business_cards: [],
      attachments: optimisticAttachments(attachmentNote, externalMessageId, userId),
      optimistic: true
    };
    state.optimisticMessages.push(message);
    renderMessages();
    return message;
  }

  function setOptimisticMessageStatus(message, status) {
    if (!message) return;
    message.status = status;
    renderMessages();
  }

  function removeOptimisticMessage(message) {
    var index = state.optimisticMessages.indexOf(message);
    if (index >= 0) state.optimisticMessages.splice(index, 1);
    clearOptimisticAttachmentPreviews(message);
  }

  function clearOptimisticMessages() {
    state.optimisticMessages.slice().forEach(removeOptimisticMessage);
  }

  function reconcileOptimisticMessages() {
    state.optimisticMessages.slice().forEach(function (optimistic) {
      if (UI.statusCode(optimistic.status) !== "SENT" || !optimistic.message_id) return;
      var persisted = state.messages.some(function (message) {
        return message.role === "user" && message.message_id === optimistic.message_id;
      });
      if (persisted) removeOptimisticMessage(optimistic);
    });
  }

  async function submitMessage(event) {
    event.preventDefault();
    if (state.submitting) return;
    if (!state.selectedUserId) {
      notify("请先选择员工身份。", "error");
      return;
    }
    var input = byId("simulator-message-input");
    var content = input.value.trim();
    if (!content) return;
    var attachmentNote = byId("simulator-attachment-note").value.trim();
    var targetUserId = state.selectedUserId;
    var targetExternalConversationId = state.externalConversationId;
    var targetSourceEventId = latestOpenEventId();
    state.lastContent = content;
    var externalMessageId = ensurePendingExternalMessageId();
    var optimisticMessage = showOptimisticMessage(
      content,
      attachmentNote,
      externalMessageId,
      targetUserId,
      state.sessionId
    );
    setSubmitting(true);
    clearError();
    byId("delivery-status").textContent = "正在提交到正式消息入口";
    try {
      var uploadedAttachment = await uploadPendingAttachment(targetUserId);
      var response = await Client.simulator.send({
        user_id: targetUserId,
        content: content,
        external_message_id: externalMessageId,
        external_conversation_id: targetExternalConversationId,
        attachments: uploadedAttachment ? [{
          attachment_id: uploadedAttachment.attachment_id,
          description: attachmentNote
        }] : undefined,
        metadata: {
          source: "wecom_simulator",
          attachment_note: attachmentNote || undefined,
          source_event_id: targetSourceEventId
        }
      });
      optimisticMessage.message_id = response.message_id;
      optimisticMessage.session_id = response.session_id;
      state.sessionId = response.session_id;
      state.externalConversationId = response.external_conversation_id || targetExternalConversationId;
      state.newSession = false;
      setOptimisticMessageStatus(optimisticMessage, "SENT");
      if (state.pendingExternalMessageId === externalMessageId) state.pendingExternalMessageId = "";
      state.evidence = {
        channel: response.channel,
        status: response.status,
        message_id: response.message_id,
        session_id: response.session_id,
        trace_id: response.trace_id,
        created_at: response.created_at
      };
      saveContext();
      renderEvidence();
      updateSessionSummary();
      byId("delivery-status").textContent = UI.statusLabel("SENT");
      input.value = "";
      byId("simulator-attachment-note").value = "";
      byId("simulator-attachment-file").value = "";
      state.pendingAttachment = null;
      renderAttachmentSelection();
      await loadEmployeeSessions(targetUserId, state.sessionId, false);
      followRun(response.message_id);
    } catch (error) {
      removeOptimisticMessage(optimisticMessage);
      renderMessages();
      showError(error, "retry-message");
      byId("delivery-status").textContent = "消息未成功受理";
    } finally {
      setSubmitting(false);
      input.focus();
    }
  }

  async function retryPersistedMessage(messageId) {
    if (!messageId || state.retryingMessageId || !state.selectedUserId) return;
    var retrySessionId = state.sessionId;
    var retryUserId = state.selectedUserId;
    var retryOwnerKey = signedUserContextKey(state.signedUser);
    state.retryingMessageId = messageId;
    clearError();
    renderMessages();
    byId("delivery-status").textContent = UI.statusLabel("RETRYING");
    try {
      var response = await Client.assistant.retry(messageId, { acting_user_id: state.selectedUserId });
      if (state.sessionId !== retrySessionId || state.selectedUserId !== retryUserId ||
          signedUserContextKey(state.signedUser) !== retryOwnerKey) return;
      state.sessionId = response.session_id || state.sessionId;
      var retriedSessionId = state.sessionId;
      state.externalConversationId = response.external_conversation_id || state.externalConversationId;
      saveContext();
      await loadSession(false);
      if (state.sessionId !== retriedSessionId || state.selectedUserId !== retryUserId ||
          signedUserContextKey(state.signedUser) !== retryOwnerKey) return;
      followRun(messageId);
    } catch (error) {
      if (state.sessionId !== retrySessionId || state.selectedUserId !== retryUserId ||
          signedUserContextKey(state.signedUser) !== retryOwnerKey) return;
      showError(error, "refresh");
      byId("delivery-status").textContent = UI.errorView(error).message;
    } finally {
      state.retryingMessageId = "";
      renderMessages();
    }
  }

  function retryMessage() {
    if (!state.lastContent || state.submitting) return;
    byId("simulator-message-input").value = state.lastContent;
    byId("simulator-message-form").requestSubmit();
  }

  async function refresh() {
    clearError();
    if (state.selectedUserId) {
      await Promise.all([loadEmployeeSessions(state.selectedUserId, state.sessionId, true), loadExperience()]);
    }
    else await loadIdentities();
  }

  async function handleLogin(event) {
    event.preventDefault();
    var button = byId("login-submit");
    button.disabled = true;
    button.textContent = "正在验证";
    byId("login-error").textContent = "";
    try {
      state.signedUser = await Client.auth.login(byId("login-username").value, byId("login-password").value);
      byId("login-form").reset();
      await showApp();
    } catch (error) {
      byId("login-error").textContent = UI.errorView(error).message;
    } finally {
      button.disabled = false;
      button.textContent = "进入接入环境";
    }
  }

  async function showApp() {
    byId("signed-user").textContent = state.signedUser && (state.signedUser.display_name || state.signedUser.username) || "演示账号";
    byId("login-screen").hidden = true;
    byId("simulator-app").hidden = false;
    await loadIdentities();
  }

  async function logout() {
    if (state.submitting || state.experience.submitting) {
      notify("当前操作正在提交，请稍候再退出。", "error");
      return;
    }
    if (state.followController) state.followController.abort();
    try {
      await Client.auth.logout();
    } catch (error) {
      Client.auth.clear();
    }
    state.identities = [];
    state.selectedUserId = null;
    state.sessionId = null;
    state.messages = [];
    state.outbox = [];
    state.outboxUnavailable = false;
    resetExperienceState();
    resetPendingExternalMessageId(true);
    state.lastContent = "";
    clearOptimisticMessages();
    state.pendingAttachment = null;
    clearAttachmentObjectUrls();
    state.signedUser = null;
    showLogin();
  }

  function handleClick(event) {
    var prompt = event.target.closest("[data-prompt]");
    if (prompt) {
      if (!state.selectedUserId) {
        notify("请先选择员工身份。", "error");
        return;
      }
      resetPendingExternalMessageId();
      byId("simulator-message-input").value = prompt.getAttribute("data-prompt");
      byId("simulator-message-input").focus();
      return;
    }
    var retryTarget = event.target.closest("[data-retry-message-id]");
    if (retryTarget) {
      retryPersistedMessage(retryTarget.getAttribute("data-retry-message-id"));
      return;
    }
    var actionTarget = event.target.closest("[data-action]");
    if (!actionTarget) return;
    var actions = {
      "new-session": newSession,
      refresh: refresh,
      "reload-identities": loadIdentities,
      "reload-sessions": function () {
        if (state.selectedUserId) return loadEmployeeSessions(state.selectedUserId, state.sessionId, true);
      },
      "open-interview": function () {
        return openInterview(actionTarget.getAttribute("data-interview-id"));
      },
      "accept-interview": acceptInterview,
      "pause-interview": pauseInterview,
      "resume-interview": resumeInterview,
      "close-interview": closeInterview,
      "open-experience-card": function () {
        return openExperienceCard(actionTarget.getAttribute("data-experience-card-id"));
      },
      "confirm-card": confirmExperienceCard,
      "close-experience-card": closeExperienceCard,
      "open-latest-experience": openLatestExperience,
      "reload-experience": loadExperience,
      "retry-message": retryMessage,
      logout: logout
    };
    var action = actions[actionTarget.getAttribute("data-action")];
    if (action) return action();
  }

  async function init() {
    emptyMessageTemplate = byId("simulator-message-stream").innerHTML;
    byId("login-form").addEventListener("submit", handleLogin);
    byId("simulator-message-form").addEventListener("submit", submitMessage);
    byId("interview-answer-form").addEventListener("submit", answerInterview);
    byId("interview-complete-form").addEventListener("submit", completeInterview);
    byId("experience-card-revise-form").addEventListener("submit", reviseExperienceCard);
    byId("identity-select").addEventListener("change", function (event) { return selectIdentity(event.target.value); });
    byId("session-select").addEventListener("change", function (event) { return selectSession(event.target.value); });
    byId("simulator-message-input").addEventListener("input", function () {
      resetPendingExternalMessageId();
    });
    byId("simulator-attachment-note").addEventListener("input", resetPendingExternalMessageId);
    byId("simulator-attachment-file").addEventListener("change", function () {
      resetPendingExternalMessageId();
      state.pendingAttachment = null;
      renderAttachmentSelection();
    });
    byId("simulator-message-input").addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        byId("simulator-message-form").requestSubmit();
      }
    });
    document.addEventListener("click", handleClick);
    window.addEventListener("focus", function () {
      if (!state.sessionId || !state.selectedUserId || state.submitting || state.followController) return;
      loadSession(false);
    });
    renderAttachmentSelection();
    renderEvidence();
    if (!Client.auth.isAuthenticated()) {
      showLogin();
      return;
    }
    try {
      state.signedUser = await Client.auth.restore();
      await showApp();
    } catch (error) {
      showLogin(error);
    }
  }

  init();
}());
