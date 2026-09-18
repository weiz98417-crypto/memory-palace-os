(function () {
  "use strict";

  var Client = window.MemoryPalaceClient;
  var UI = Client.ui;
  var ASSISTANT_CONTEXT_KEY = "mp_assistant_last_session";
  var state = {
    user: null,
    sessions: [],
    activeSessionId: null,
    activeSession: null,
    messages: [],
    section: "chat",
    submitting: false,
    retryingMessageId: "",
    followController: null,
    lastSubmittedContent: "",
    pendingExternalMessageId: "",
    optimisticMessages: [],
    pendingAttachment: null,
    attachmentObjectUrls: {},
    attachmentLoads: {},
    scenic: null,
    scenicSubscription: null,
    scenicRefreshTimer: null,
    work: {
      tasks: [],
      events: [],
      loaded: false,
      loading: false,
      selectedTask: null,
      selectedEvent: null,
      submitting: false
    },
    experience: {
      expert: null,
      interviews: [],
      cards: [],
      searchResults: [],
      loaded: false,
      loading: false,
      selectedInterview: null,
      selectedCard: null,
      selectedExtraction: null,
      submitting: false,
      view: "cocreate"
    }
  };
  var emptyChatTemplate = "";

  function byId(id) {
    return document.getElementById(id);
  }

  function signedUserContextKey(user) {
    var userId = String(user && (user.id || user.user_id) || "").trim();
    var venueId = String(user && user.venue_id || "").trim();
    return userId && venueId ? venueId + ":" + userId : "";
  }

  function readLastSessionContexts() {
    try {
      var contexts = JSON.parse(sessionStorage.getItem(ASSISTANT_CONTEXT_KEY) || "{}") || {};
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

  function readLastSessionContext() {
    var ownerKey = signedUserContextKey(state.user);
    var saved = readLastSessionContexts()[ownerKey] || {};
    if (!saved.owner_key || saved.owner_key !== signedUserContextKey(state.user)) return {};
    return saved;
  }

  function saveLastSessionContext() {
    var ownerKey = signedUserContextKey(state.user);
    if (!ownerKey || !state.activeSessionId) return;
    var contexts = readLastSessionContexts();
    contexts[ownerKey] = {
      owner_key: signedUserContextKey(state.user),
      session_id: state.activeSessionId
    };
    sessionStorage.setItem(ASSISTANT_CONTEXT_KEY, JSON.stringify(contexts));
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
    if (["COMPLETED", "SUCCEEDED", "DONE", "CLOSED", "EXPERT_CONFIRMED", "PUBLISHED"].indexOf(code) >= 0) return "success";
    if (["FAILED", "ERROR", "CANCELLED", "DEPRECATED", "RETRY_REQUIRED", "DEAD_LETTERED"].indexOf(code) >= 0) return "failed";
    if (code === "BLOCKED") return "blocked";
    if (["SENDING", "SENT", "QUEUED", "PENDING", "INVITED", "ACCEPTED", "PAUSED"].indexOf(code) >= 0) return "queued";
    if (["PROCESSING", "RUNNING", "RETRYING", "OPEN", "WAITING_APPROVAL", "IN_PROGRESS", "IN_REVIEW"].indexOf(code) >= 0) return "running";
    return "";
  }

  function setAssistantStatus(status, detail) {
    var pill = byId("assistant-status");
    pill.className = "status-pill " + statusClass(status);
    pill.textContent = status ? UI.statusLabel(status) : "可以开始";
    byId("assistant-status-detail").textContent = detail || "工作信息将保存到组织会话";
  }

  function showServiceRecovering() {
    setAssistantStatus("PROCESSING", "服务正在恢复，任务仍在处理中");
  }

  function showServiceRecovered() {
    setAssistantStatus("PROCESSING", "服务已恢复，正在同步原任务进度");
  }

  function showRecoveryDeferred() {
    setAssistantStatus("PROCESSING", "恢复等待已到上限，原任务状态已保留，请稍后刷新");
  }

  function setPersistedAssistantStatus(detail) {
    var latest = state.messages.filter(function (message) { return message.role === "assistant"; }).pop();
    setAssistantStatus(latest ? latest.status : "PROCESSING", detail);
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

  function renderError(error, retryAction) {
    var view = UI.errorView(error);
    var target = byId("chat-error");
    target.hidden = false;
    target.innerHTML = "<strong>" + UI.escapeHTML(view.title) + "</strong>" +
      "<span>" + UI.escapeHTML(view.message) + "</span>" +
      (view.action ? "<span>建议操作：" + UI.escapeHTML(view.action) + "</span>" : "") +
      (view.retryable && retryAction
        ? '<button class="btn" type="button" data-action="' + UI.escapeHTML(retryAction) + '">重试</button>'
        : "");
  }

  function clearError() {
    var target = byId("chat-error");
    target.hidden = true;
    target.innerHTML = "";
  }

  function showLogin(error) {
    byId("app-screen").hidden = true;
    byId("login-screen").hidden = false;
    byId("login-error").textContent = error ? UI.errorView(error).message : "";
  }

  function applyUser(user) {
    state.user = user;
    var name = user && (user.display_name || user.username) || "企业成员";
    var role = roleLabel(user && user.role);
    byId("rail-user-name").textContent = name;
    byId("mobile-user-name").textContent = name;
    byId("rail-user-role").textContent = role;
    byId("rail-avatar").textContent = name.slice(0, 1);
    byId("profile-name").textContent = name;
    byId("profile-username").textContent = user && user.username || "未提供";
    byId("profile-role").textContent = role;
    byId("profile-venue").textContent = "已绑定当前工作场地";
  }

  async function showApp(user) {
    applyUser(user);
    byId("login-screen").hidden = true;
    byId("app-screen").hidden = false;
    await loadScenicSituation();
    startScenicSubscription();
    var workResource = workResourceFromLocation();
    var sopResource = sopResourceFromLocation();
    navigate(workResource ? "work" : sectionFromLocation(), true);
    await loadSessions();
    if (workResource && workResource.type === "event") {
      await openEvent(workResource.id, true);
    } else if (workResource && workResource.type === "task") {
      await openTask(workResource.id, true);
    } else if (sopResource) {
      await openSop(sopResource.id, sopResource.version, true);
    }
  }

  function sectionFromLocation() {
    var section = String(window.location.hash || "").replace(/^#/, "");
    return ["chat", "work", "experience", "me"].indexOf(section) >= 0 ? section : "chat";
  }

  function workResourceFromLocation() {
    var match = window.location.pathname.match(/^\/assistant\/work\/(event|task)\/([^/]+)\/?$/);
    if (!match) return null;
    return { type: match[1], id: decodeURIComponent(match[2]) };
  }

  function sopResourceFromLocation() {
    var match = window.location.pathname.match(/^\/assistant\/knowledge\/sop\/([^/]+)\/?$/);
    if (!match) return null;
    return {
      type: "sop",
      id: decodeURIComponent(match[1]),
      version: new URLSearchParams(window.location.search).get("version") || ""
    };
  }

  function updateWorkResourceURL(type, resourceId, replace) {
    var url = new URL(window.location.href);
    url.pathname = "/assistant/work/" + encodeURIComponent(type) + "/" + encodeURIComponent(resourceId);
    url.search = "";
    url.hash = "work";
    window.history[replace ? "replaceState" : "pushState"]({}, "", url);
  }

  function clearWorkResourceURL() {
    if (!workResourceFromLocation()) return;
    var url = new URL(window.location.href);
    url.pathname = "/assistant/";
    url.search = "";
    url.hash = "work";
    window.history.replaceState({}, "", url);
  }

  function updateSopResourceURL(sopId, version, replace) {
    var url = new URL(window.location.href);
    url.pathname = "/assistant/knowledge/sop/" + encodeURIComponent(sopId);
    url.search = "";
    if (version) url.searchParams.set("version", version);
    url.hash = "chat";
    window.history[replace ? "replaceState" : "pushState"]({}, "", url);
  }

  function clearSopResourceURL() {
    if (!sopResourceFromLocation()) return;
    var url = new URL(window.location.href);
    url.pathname = "/assistant/";
    url.search = "";
    url.hash = "chat";
    window.history.replaceState({}, "", url);
  }

  function navigate(section, replace) {
    if (["chat", "work", "experience", "me"].indexOf(section) < 0) section = "chat";
    state.section = section;
    document.querySelectorAll("[data-app-section]").forEach(function (panel) {
      var active = panel.getAttribute("data-app-section") === section;
      panel.hidden = !active;
      panel.classList.toggle("active", active);
    });
    document.querySelectorAll("[data-section]").forEach(function (item) {
      item.classList.toggle("active", item.getAttribute("data-section") === section);
      if (item.classList.contains("rail-item")) {
        item.setAttribute("aria-current", item.getAttribute("data-section") === section ? "page" : "false");
      }
    });
    var url = new URL(window.location.href);
    if (section !== "work" && workResourceFromLocation()) {
      url.pathname = "/assistant/";
      url.search = "";
    }
    url.hash = section;
    window.history[replace ? "replaceState" : "pushState"]({}, "", url);
    closeSessions();
    if (section === "work") loadWork();
    if (section === "experience") loadExperience();
  }

  function sessionFromURL() {
    return new URL(window.location.href).searchParams.get("session");
  }

  function updateSessionURL(sessionId) {
    var url = new URL(window.location.href);
    if (sessionId) url.searchParams.set("session", sessionId);
    else url.searchParams.delete("session");
    url.hash = "chat";
    window.history.replaceState({}, "", url);
  }

  function sessionTitle(item) {
    var explicit = item.display_title || item.title || item.subject;
    if (explicit) return String(explicit);
    if (item.last_message) {
      var preview = String(item.last_message).trim();
      if (preview) return preview.length > 22 ? preview.slice(0, 22) + "…" : preview;
    }
    return "与企业运营助手的会话";
  }

  function sessionPreview(item) {
    if (item.last_message) return String(item.last_message);
    if (item.message_count) return "已记录 " + Number(item.message_count) + " 条消息";
    return "尚无消息";
  }

  function renderSessionList() {
    var target = byId("session-list");
    if (!state.sessions.length) {
      target.innerHTML = '<div class="empty-state"><strong>暂无历史会话</strong><p>发送第一条消息后，会话会保存在这里。</p></div>';
      return;
    }
    target.innerHTML = state.sessions.map(function (item) {
      var active = item.session_id === state.activeSessionId;
      return '<button class="session-item ' + (active ? "active" : "") + '" type="button" data-session-id="' +
        UI.escapeHTML(item.session_id) + '">' +
        '<span class="session-title-row"><strong>' + UI.escapeHTML(sessionTitle(item)) + '</strong><time>' +
        UI.escapeHTML(UI.dateLabel(item.updated_at || item.created_at)) + '</time></span>' +
        '<span class="session-preview">' + UI.escapeHTML(sessionPreview(item)) + '</span>' +
        '<span class="session-meta"><span>' + UI.escapeHTML(item.display_name || "本人会话") + '</span><span>' +
        UI.escapeHTML(UI.statusLabel(item.last_status || item.stage)) + '</span></span></button>';
    }).join("");
  }

  async function loadSessions() {
    var ownerKey = signedUserContextKey(state.user);
    byId("session-list").innerHTML = '<div class="empty-state"><p>正在同步会话…</p></div>';
    try {
      var payload = await Client.recovery.run(function (signal) {
        return Client.assistant.sessions({ limit: 100, signal: signal });
      }, {
        timeoutMs: 300000,
        onRecovering: showServiceRecovering,
        onRecovered: showServiceRecovered
      });
      if (signedUserContextKey(state.user) !== ownerKey) return;
      state.sessions = UI.arrayFrom(payload, ["sessions", "items"]);
      var saved = readLastSessionContext();
      var requested = state.activeSessionId || sessionFromURL() || saved.session_id;
      var matched = state.sessions.find(function (item) { return item.session_id === requested; });
      if (!matched && state.sessions.length && !state.activeSessionId) matched = state.sessions[0];
      state.activeSession = matched || null;
      state.activeSessionId = matched ? matched.session_id : null;
      saveLastSessionContext();
      renderSessionList();
      if (state.activeSessionId) {
        updateSessionURL(state.activeSessionId);
        await loadMessages(state.activeSessionId, true);
      } else {
        updateSessionURL(null);
        state.messages = [];
        renderMessages();
      }
    } catch (error) {
      if (signedUserContextKey(state.user) !== ownerKey) return;
      byId("session-list").innerHTML = '<div class="empty-state"><strong>会话暂时不可用</strong><p>' +
        UI.escapeHTML(UI.errorView(error).message) + "</p></div>";
      renderError(error, "refresh-sessions");
    }
  }

  function openSessions() {
    byId("conversation-panel").classList.add("open");
    byId("conversation-backdrop").classList.add("visible");
  }

  function closeSessions() {
    byId("conversation-panel").classList.remove("open");
    byId("conversation-backdrop").classList.remove("visible");
  }

  function newSession() {
    if (state.submitting) {
      notify("消息正在发送，请稍候再新建会话。", "error");
      return;
    }
    if (state.followController) state.followController.abort();
    resetPendingExternalMessageId();
    state.activeSessionId = null;
    state.activeSession = null;
    state.messages = [];
    updateSessionURL(null);
    renderSessionList();
    renderMessages();
    navigate("chat", true);
    byId("message-input").focus();
  }

  async function selectSession(sessionId) {
    if (!sessionId || sessionId === state.activeSessionId) {
      closeSessions();
      return;
    }
    if (state.submitting) {
      notify("消息正在发送，请稍候再切换会话。", "error");
      return;
    }
    if (state.followController) state.followController.abort();
    resetPendingExternalMessageId();
    state.activeSessionId = sessionId;
    state.activeSession = state.sessions.find(function (item) { return item.session_id === sessionId; }) || null;
    saveLastSessionContext();
    updateSessionURL(sessionId);
    renderSessionList();
    closeSessions();
    navigate("chat", true);
    await loadMessages(sessionId, true);
  }

  function safeBusinessCode(value) {
    var text = String(value || "").trim();
    if (!text) return "";
    if (/^[a-f0-9-]{24,}$/i.test(text)) return "";
    return text;
  }

  function cardType(card) {
    return String(card.card_type || card.type || card.kind || "update").toLowerCase();
  }

  function cardTypeLabel(card) {
    var type = cardType(card);
    if (type.indexOf("event") >= 0 || type.indexOf("incident") >= 0) return "事件进展";
    if (type.indexOf("task") >= 0) return "任务";
    if (type.indexOf("approval") >= 0) return "审批";
    if (type.indexOf("experience") >= 0 || type.indexOf("persona") >= 0) return "专家经验";
    if (type.indexOf("interview") >= 0) return "经验访谈";
    if (type.indexOf("knowledge") >= 0 || type.indexOf("sop") >= 0) return "知识依据";
    if (type.indexOf("failure") >= 0 || type.indexOf("error") >= 0) return "处理提醒";
    return "业务进展";
  }

  function cardCategory(card) {
    var type = cardType(card);
    if (/(experience|persona|interview|knowledge|sop)/.test(type)) return "experience";
    if (/(event|incident|task|approval|action|work)/.test(type)) return "work";
    return "other";
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

  function cardFacts(card) {
    var experienceCard = cardType(card).indexOf("experience") >= 0;
    var candidates = experienceCard ? [
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
      ["地点", card.location_name || card.location],
      ["截止时间", card.due_at ? UI.dateLabel(card.due_at) : card.deadline],
      ["下一步", card.next_action || card.recommended_action],
      ["来源", card.source_title || card.source_name],
      ["发布人", card.publisher_name],
      ["发布时间", card.published_at ? UI.dateLabel(card.published_at) : ""],
      ["经验专家", card.expert_name],
      ["版本", card.version_label || card.version]
    ];
    return candidates.filter(function (item) {
      return item[1] !== undefined && item[1] !== null && String(item[1]).trim() !== "";
    }).slice(0, 8);
  }

  function safeDetailLink(card) {
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

  function renderBusinessCard(card) {
    card = card || {};
    var label = cardTypeLabel(card);
    var title = card.title || card.name || card.subject || label + "更新";
    var summary = card.summary || card.description || card.content || card.reason || "";
    var status = card.status;
    var facts = cardFacts(card);
    var link = safeDetailLink(card);
    var experienceDisclosure = cardType(card).indexOf("experience") >= 0
      ? '<p class="experience-disclosure">由企业运营助手基于已发布并授权的专家经验生成，非专家本人实时回复。</p>'
      : "";
    return '<article class="business-card">' +
      '<div class="business-card-head"><div><span class="business-card-type">' + UI.escapeHTML(label) +
      '</span><h3>' + UI.escapeHTML(title) + '</h3></div>' +
      (status ? '<span class="status-pill ' + statusClass(status) + '">' + UI.escapeHTML(UI.statusLabel(status)) + '</span>' : "") +
      "</div>" +
      (summary ? "<p>" + UI.escapeHTML(summary) + "</p>" : "") +
      experienceDisclosure +
      (facts.length ? "<dl>" + facts.map(function (item) {
        return "<div><dt>" + UI.escapeHTML(item[0]) + "</dt><dd>" + UI.escapeHTML(item[1]) + "</dd></div>";
      }).join("") + "</dl>" : "") +
      (link ? '<div class="business-card-actions"><a href="' + UI.escapeHTML(link) + '">查看详情</a></div>' : "") +
      "</article>";
  }

  function messageCards(message) {
    return Array.isArray(message.business_cards) ? message.business_cards : [];
  }

  function latestOpenEventId() {
    for (var messageIndex = state.messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
      var cards = messageCards(state.messages[messageIndex]);
      for (var cardIndex = cards.length - 1; cardIndex >= 0; cardIndex -= 1) {
        var card = cards[cardIndex] || {};
        var status = UI.statusCode(card.status);
        if (cardType(card).indexOf("event") >= 0 &&
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
    return '<figure class="message-attachment"><div class="attachment-thumbnail" data-attachment-preview-id="' +
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
    var target = byId("message-stream");
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

  function renderMessageRecovery(message) {
    var status = UI.statusCode(message.status);
    if (["RETRY_REQUIRED", "DEAD_LETTERED"].indexOf(status) < 0 || !message.message_id) return "";
    var disabled = state.retryingMessageId === message.message_id ? " disabled" : "";
    var label = disabled ? "正在重新提交" : "从原消息重试";
    return '<section class="message-recovery-card"><strong>需要人工重试</strong>' +
      '<p>自动恢复已达到上限。重试会继续原任务，不会重新发送文字或创建新消息。</p>' +
      '<button class="btn secondary" type="button" data-retry-message-id="' +
      UI.escapeHTML(message.message_id) + '"' + disabled + ">" + label + "</button></section>";
  }

  function renderMessage(message) {
    var role = message.role === "user" ? "user" : "assistant";
    var content = message.content || message.text || "";
    var cards = messageCards(message);
    var status = UI.statusCode(message.status);
    var retryRequired = ["RETRY_REQUIRED", "DEAD_LETTERED"].indexOf(status) >= 0;
    var terminal = ["COMPLETED", "SUCCEEDED", "DONE", "FAILED", "ERROR", "CANCELLED", "RETRY_REQUIRED", "DEAD_LETTERED"].indexOf(status) >= 0;
    var contentHTML = content
      ? '<p class="message-content">' + UI.escapeHTML(content) + "</p>"
      : (retryRequired
        ? '<p class="message-content">自动处理未完成，可以从这条原消息继续重试。</p>'
        : !terminal
        ? '<div class="message-pending">' + UI.escapeHTML(UI.statusLabel(message.status)) + "</div>"
        : '<p class="message-content">本次处理未产生可展示的回复，请稍后刷新或联系管理员查看运行记录。</p>');
    var cardsHTML = cards.length
      ? '<div class="business-cards">' + cards.map(renderBusinessCard).join("") + "</div>"
      : "";
    var attachments = messageAttachments(message);
    var attachmentsHTML = attachments.length
      ? '<div class="message-attachments">' + attachments.map(renderAttachment).join("") + "</div>"
      : "";
    var recoveryHTML = renderMessageRecovery(message);
    var senderLabel = role === "user"
      ? (message.optimistic ? "我 · " + UI.statusLabel(message.status) : "我")
      : "企业运营助手";
    return '<article class="message-row ' + role + '"><div class="message-bubble">' + contentHTML + attachmentsHTML + cardsHTML + recoveryHTML +
      '<footer class="message-meta"><span>' + senderLabel + '</span><time>' +
      UI.escapeHTML(UI.dateLabel(message.created_at)) + "</time></footer></div></article>";
  }

  function renderMessages() {
    var target = byId("message-stream");
    var visibleMessages = state.messages.slice();
    visibleMessages = visibleMessages.concat(state.optimisticMessages.filter(function (message) {
      return state.activeSessionId ? message.session_id === state.activeSessionId : !message.session_id;
    }));
    if (!visibleMessages.length) {
      target.innerHTML = emptyChatTemplate;
      setAssistantStatus(null, "工作信息将保存到组织会话");
      return;
    }
    target.innerHTML = visibleMessages.map(renderMessage).join("");
    hydrateAttachmentPreviews(target);
    var latestAssistant = state.messages.filter(function (message) { return message.role === "assistant"; }).pop();
    if (latestAssistant) {
      setAssistantStatus(latestAssistant.status, latestAssistant.content ? "会话已同步" : "正在读取服务端处理状态");
    }
    window.requestAnimationFrame(function () { target.scrollTop = target.scrollHeight; });
  }

  function applyMessagePayload(payload) {
    state.messages = UI.arrayFrom(payload, ["messages", "items", "history"]);
    if (payload && payload.session) state.activeSession = payload.session;
    reconcileOptimisticMessages();
    renderMessages();
  }

  function pendingAssistantMessage() {
    return state.messages.filter(function (message) {
      return message.role === "assistant" && [
        "COMPLETED", "SUCCEEDED", "DONE", "FAILED", "ERROR", "CANCELLED", "RETRY_REQUIRED", "DEAD_LETTERED"
      ].indexOf(UI.statusCode(message.status)) < 0;
    }).pop();
  }

  async function loadMessages(sessionId, resume) {
    clearError();
    setAssistantStatus("PROCESSING", "正在同步会话记录");
    try {
      var payload = await Client.recovery.run(function (signal) {
        return Client.assistant.messages(sessionId, { limit: 200, signal: signal });
      }, {
        timeoutMs: 300000,
        onRecovering: showServiceRecovering,
        onRecovered: showServiceRecovered
      });
      if (state.activeSessionId !== sessionId) return;
      applyMessagePayload(payload);
      if (resume) {
        var pending = pendingAssistantMessage();
        if (pending && pending.message_id) followRun(sessionId, pending.message_id);
      }
    } catch (error) {
      if (state.activeSessionId !== sessionId) return;
      renderMessages();
      renderError(error, "refresh-current");
      if (Client.recovery.isTransient(error)) showRecoveryDeferred();
      else setPersistedAssistantStatus("会话同步未完成，请按提示处理");
    }
  }

  function displayText(value) {
    if (value === undefined || value === null) return "";
    if (typeof value === "string" || typeof value === "number") return String(value).trim();
    if (typeof value === "object") {
      return displayText(value.title || value.summary || value.content || value.description || "");
    }
    return "";
  }

  function readableTitle(value, fallback) {
    var text = displayText(value).replace(/\s+/g, " ");
    if (!text) return fallback;
    return text.length > 64 ? text.slice(0, 64) + "…" : text;
  }

  function taskDescription(task) {
    return displayText(task.description || task.summary || task.content) || "任务说明待负责人补充";
  }

  function taskTitle(task) {
    return readableTitle(task.title || task.subject || taskDescription(task), "待处理任务");
  }

  function taskResult(task) {
    var result = task && task.result;
    return displayText(result && (result.summary || result.description || result)) || "";
  }

  function eventTypeLabel(value) {
    var labels = {
      INCIDENT: "现场事件",
      SAFETY: "安全事件",
      EQUIPMENT: "设备事件",
      SERVICE: "服务事件",
      COMPLAINT: "客户反馈",
      WEATHER: "天气影响",
      OPERATION: "运营事件",
      OTHER: "其他事件"
    };
    var code = String(value || "OTHER").trim().toUpperCase();
    return labels[code] || "现场事件";
  }

  function severityLabel(value) {
    var labels = { P0: "最高优先", P1: "紧急", P2: "较高", P3: "一般", P4: "较低", "P3/P4": "一般" };
    return labels[String(value || "").toUpperCase()] || "优先级待确认";
  }

  function renderTaskItem(task) {
    var description = taskDescription(task);
    var title = taskTitle(task);
    var result = taskResult(task);
    return '<button class="work-item task-item" type="button" data-action="open-task" data-task-id="' +
      UI.escapeHTML(task.id) + '">' +
      '<span class="work-item-head"><span><span class="work-kind">任务</span><strong>' + UI.escapeHTML(title) +
      '</strong></span><span class="status-pill ' + statusClass(task.status) + '">' +
      UI.escapeHTML(UI.statusLabel(task.status)) + '</span></span>' +
      (description !== title ? '<span class="work-description">' + UI.escapeHTML(description) + '</span>' : "") +
      (result ? '<span class="work-result"><b>完成结果</b>' + UI.escapeHTML(result) + '</span>' : "") +
      '<span class="work-meta"><span>本人负责</span><time>更新于 ' +
      UI.escapeHTML(UI.dateLabel(task.updated_at || task.created_at)) + '</time></span></button>';
  }

  function renderEventItem(eventItem) {
    var type = eventTypeLabel(eventItem.event_type);
    var title = readableTitle(eventItem.title || eventItem.memory_content || eventItem.raw_text, type);
    var summary = displayText(eventItem.memory_content || eventItem.raw_text || eventItem.resolution);
    return '<button class="work-item event-item" type="button" data-event-id="' +
      UI.escapeHTML(eventItem.event_id) + '">' +
      '<span class="work-item-head"><span><span class="work-kind">' + UI.escapeHTML(type) + '</span><strong>' +
      UI.escapeHTML(title) + '</strong></span><span class="status-pill ' + statusClass(eventItem.status) + '">' +
      UI.escapeHTML(UI.statusLabel(eventItem.status)) + '</span></span>' +
      (summary && summary !== title ? '<span class="work-description">' + UI.escapeHTML(summary) + '</span>' : "") +
      '<span class="work-meta"><span>' + UI.escapeHTML(severityLabel(eventItem.severity)) + '</span><time>更新于 ' +
      UI.escapeHTML(UI.dateLabel(eventItem.updated_at || eventItem.created_at)) + '</time></span></button>';
  }

  function renderWorkSummary() {
    var tasks = state.work.tasks;
    var events = state.work.events;
    var running = tasks.filter(function (item) { return UI.statusCode(item.status) === "RUNNING"; }).length;
    var waiting = tasks.filter(function (item) { return UI.statusCode(item.status) === "PENDING"; }).length;
    var attention = tasks.filter(function (item) {
      return ["BLOCKED", "FAILED"].indexOf(UI.statusCode(item.status)) >= 0;
    }).length + events.filter(function (item) {
      return UI.statusCode(item.status) === "OPEN" && ["P0", "P1"].indexOf(String(item.severity || "").toUpperCase()) >= 0;
    }).length;
    var done = tasks.filter(function (item) { return UI.statusCode(item.status) === "DONE"; }).length;
    byId("work-summary").innerHTML = [
      ["待开始", waiting], ["进行中", running], ["需要关注", attention], ["已完成", done]
    ].map(function (item) {
      return '<div><span>' + item[0] + '</span><strong>' + item[1] + '</strong></div>';
    }).join("");
  }

  function renderWork() {
    renderWorkSummary();
    byId("task-count").textContent = state.work.tasks.length + " 项";
    byId("event-count").textContent = state.work.events.length + " 项";
    byId("task-list").innerHTML = state.work.tasks.length
      ? state.work.tasks.map(renderTaskItem).join("")
      : '<div class="empty-state compact"><strong>当前没有本人任务</strong><p>新任务分配后会出现在这里。</p></div>';
    byId("event-list").innerHTML = state.work.events.length
      ? state.work.events.map(renderEventItem).join("")
      : '<div class="empty-state compact"><strong>当前没有本人事件</strong><p>与本人工作相关的现场事件会出现在这里。</p></div>';
  }

  function renderScenicSituation(snapshot) {
    state.scenic = snapshot || {};
    var target = byId("scenic-situation-card");
    var run = state.scenic.run;
    var incidents = state.scenic.incidents || [];
    var alerts = state.scenic.alerts || [];
    var incident = incidents[0];
    var activeAlerts = alerts.filter(function (item) { return item.status === "ACTIVE"; });
    var action = (state.scenic.next_actions || [])[0];
    var advice = state.scenic.advice;
    var title = incident ? incident.title : (activeAlerts[0] && activeAlerts[0].title) || "景区态势稳定";
    var meta = [
      "事件 " + (incident ? incident.lifecycle : "未建立"),
      "活动告警 " + activeAlerts.length,
      "序号 " + (state.scenic.latest_sequence || 0),
      run ? ("模拟时间 " + UI.dateLabel(run.simulated_at)) : "等待运行准备"
    ];
    var adviceHtml = "";
    if (advice) {
      var citations = (advice.citations || []).map(function (item) {
        return '<span>' + UI.escapeHTML(item.title || item.source_id) + ' · v' + UI.escapeHTML(item.version || "-") + '</span>';
      }).join("");
      adviceHtml = '<div class="scenic-readonly-advice"><strong>处置建议 · ' +
        UI.escapeHTML(advice.display_status || advice.status) + '</strong>' +
        (advice.advice ? '<p>' + UI.escapeHTML(advice.advice) + '</p>' : "") +
        (citations ? '<div class="scenic-situation-meta">' + citations + '</div>' : "") + '</div>';
    }
    var nextHtml = action ? '<div class="scenic-readonly-next"><strong>' + UI.escapeHTML(action.label || "下一步处置") +
      '</strong><span>' + UI.escapeHTML(action.description || "") + '</span></div>' : "";
    var evidenceForm = "";
    if (incident && incident.lifecycle === "DETECTED" && state.user && state.user.username === "liming" && !(incident.evidence || []).length) {
      evidenceForm = '<form id="scenic-evidence-form" class="scenic-evidence-form">' +
        '<strong>补充现场文字与图片</strong>' +
        '<textarea id="scenic-evidence-text" maxlength="1000" required placeholder="说明 12 号车右后轮现场情况"></textarea>' +
        '<input id="scenic-evidence-file" type="file" accept="image/jpeg,image/png,image/webp" required>' +
        '<button class="btn primary" type="submit">提交到正式事件卷宗</button></form>';
    }
    target.innerHTML = '<div><span class="eyebrow">共享景区态势</span><h2>' + UI.escapeHTML(title) + '</h2></div>' +
      '<p>' + UI.escapeHTML(incident ? (incident.business_id + " · " + incident.lifecycle) : "监测信号、态势告警与运营事件来自同一 PostgreSQL 事实源。") + '</p>' +
      '<div class="scenic-situation-meta">' + meta.map(function (item) { return '<span>' + UI.escapeHTML(item) + '</span>'; }).join("") + '</div>' +
      nextHtml + adviceHtml + evidenceForm;
    var form = byId("scenic-evidence-form");
    if (form) form.addEventListener("submit", submitScenicEvidence);
  }

  async function loadScenicSituation() {
    try {
      renderScenicSituation(await Client.scenic.snapshot());
    } catch (error) {
      byId("scenic-situation-card").innerHTML = '<div><span class="eyebrow">共享景区态势</span><h2>态势暂时不可用</h2></div><p>' + UI.escapeHTML(UI.errorView(error).message) + '</p>';
    }
  }

  function startScenicSubscription() {
    if (state.scenicSubscription) return;
    state.scenicSubscription = Client.scenic.subscribe({
      afterSequence: state.scenic && state.scenic.latest_sequence,
      onSnapshot: renderScenicSituation,
      onEvent: function () {
        window.clearTimeout(state.scenicRefreshTimer);
        state.scenicRefreshTimer = window.setTimeout(loadScenicSituation, 120);
      },
      onAdvice: function (eventName) {
        var message = eventName === "ADVICE_PENDING" ? "模型建议分析中" :
          eventName === "ADVICE_READY" ? "处置建议已就绪" : "未获得模型建议";
        notify(message, eventName === "ADVICE_FAILED" ? "warning" : "success");
        window.clearTimeout(state.scenicRefreshTimer);
        state.scenicRefreshTimer = window.setTimeout(loadScenicSituation, 120);
      }
    });
  }

  async function submitScenicEvidence(event) {
    event.preventDefault();
    var incident = state.scenic && (state.scenic.incidents || [])[0];
    var fileInput = byId("scenic-evidence-file");
    var form = event.currentTarget;
    if (!incident || !fileInput.files.length) return;
    form.querySelectorAll("button,textarea,input").forEach(function (control) { control.disabled = true; });
    try {
      var attachment = await Client.assistant.uploadAttachment(fileInput.files[0]);
      await Client.scenic.command("ADD_EVIDENCE", {
        incident_id: incident.incident_id,
        text: byId("scenic-evidence-text").value,
        attachment_id: attachment.attachment_id
      });
      notify("现场证据已写入运营事件卷宗。", "success");
      await loadScenicSituation();
    } catch (error) {
      notify(UI.errorView(error).message, "error");
      form.querySelectorAll("button,textarea,input").forEach(function (control) { control.disabled = false; });
    }
  }

  function showInlineError(targetId, error) {
    var target = byId(targetId);
    target.hidden = false;
    target.textContent = UI.errorView(error).message;
  }

  function clearInlineError(targetId) {
    var target = byId(targetId);
    target.hidden = true;
    target.textContent = "";
  }

  async function loadWork() {
    if (state.work.loading) return;
    state.work.loading = true;
    clearInlineError("work-error");
    byId("task-list").innerHTML = '<div class="empty-state compact"><p>正在同步本人任务…</p></div>';
    byId("event-list").innerHTML = '<div class="empty-state compact"><p>正在同步关联事件…</p></div>';
    try {
      var payload = await Client.work.list({
        task_status: byId("work-task-status").value,
        event_status: byId("work-event-status").value,
        limit: 100,
        offset: 0
      });
      state.work.tasks = UI.arrayFrom(payload, ["tasks"]);
      state.work.events = UI.arrayFrom(payload, ["events"]);
      state.work.loaded = true;
      renderWork();
    } catch (error) {
      state.work.tasks = [];
      state.work.events = [];
      renderWork();
      showInlineError("work-error", error);
    } finally {
      state.work.loading = false;
    }
  }

  function renderTaskDetail(task) {
    state.work.selectedTask = task;
    var status = UI.statusCode(task.status);
    var result = taskResult(task);
    byId("task-detail-title").textContent = taskTitle(task);
    byId("task-detail-body").innerHTML =
      '<div class="task-detail-status"><span class="status-pill ' + statusClass(status) + '">' +
      UI.escapeHTML(UI.statusLabel(status)) + '</span><span>本人负责</span></div>' +
      '<p class="task-detail-description">' + UI.escapeHTML(taskDescription(task)) + '</p>' +
      '<dl class="task-detail-facts"><div><dt>创建时间</dt><dd>' + UI.escapeHTML(UI.dateLabel(task.created_at)) +
      '</dd></div><div><dt>最近更新</dt><dd>' + UI.escapeHTML(UI.dateLabel(task.updated_at || task.created_at)) +
      '</dd></div></dl>' +
      (result ? '<div class="result-panel"><strong>完成结果</strong><p>' + UI.escapeHTML(result) + '</p></div>' : "") +
      (task.error ? '<div class="result-panel blocked"><strong>最近阻塞原因</strong><p>' +
        UI.escapeHTML(displayText(task.error)) + '</p></div>' : "");
    byId("task-start-button").hidden = status !== "PENDING";
    byId("task-complete-form").hidden = status !== "RUNNING";
    byId("task-block-form").hidden = status !== "RUNNING";
    byId("task-action-region").hidden = ["PENDING", "RUNNING"].indexOf(status) < 0;
    configureStructuredTaskResult(task, status);
  }

  function configureStructuredTaskResult(task, status) {
    var region = byId("task-structured-result");
    var primary = byId("task-result-primary");
    var secondary = byId("task-result-secondary");
    var kind = String(task.assigned_agent || "");
    region.hidden = status !== "RUNNING" || ["field-technician", "field-operator"].indexOf(kind) < 0;
    if (region.hidden) return;
    if (kind === "field-technician") {
      byId("task-result-primary-label").textContent = "12 号车检查结论";
      byId("task-result-secondary-label").textContent = "7 号备用车状态";
      primary.innerHTML = '<option value="ISOLATED">确认异常，继续停运</option><option value="SAFE">检查正常</option>';
      secondary.innerHTML = '<option value="READY">检查合格，可启用</option><option value="NOT_READY">暂不可用</option>';
    } else {
      byId("task-result-primary-label").textContent = "东门分流措施";
      byId("task-result-secondary-label").textContent = "现场风险状态";
      primary.innerHTML = '<option value="ONE_WAY_DIVERSION">已启用单向分流</option><option value="ADDITIONAL_STAFF">已增派引导人员</option>';
      secondary.innerHTML = '<option value="CLEAR">风险已解除</option><option value="MONITORING">继续观察</option>';
    }
  }

  async function openTask(taskId, preserveURL) {
    var dialog = byId("task-detail-dialog");
    clearInlineError("task-action-error");
    byId("task-detail-title").textContent = "正在读取任务";
    byId("task-detail-body").innerHTML = '<div class="empty-state compact"><p>正在同步最新任务状态…</p></div>';
    byId("task-action-region").hidden = true;
    if (!dialog.open) dialog.showModal();
    if (!preserveURL) updateWorkResourceURL("task", taskId);
    try {
      var payload = await Client.work.task(taskId);
      renderTaskDetail(payload.task || payload);
    } catch (error) {
      showInlineError("task-action-error", error);
    }
  }

  function closeTask() {
    var dialog = byId("task-detail-dialog");
    if (dialog.open) dialog.close();
    state.work.selectedTask = null;
    clearWorkResourceURL();
  }

  function renderEventDetail(eventItem) {
    state.work.selectedEvent = eventItem;
    var type = eventTypeLabel(eventItem.event_type);
    var status = UI.statusCode(eventItem.status);
    var title = readableTitle(eventItem.title || eventItem.memory_content || eventItem.raw_text, type);
    byId("event-detail-title").textContent = title;
    byId("event-detail-body").innerHTML =
      '<div class="task-detail-status"><span class="status-pill ' + statusClass(status) + '">' +
      UI.escapeHTML(UI.statusLabel(status)) + '</span><span>' +
      UI.escapeHTML(eventItem.assigned_to ? "已分派责任人" : "待值班经理分派") + '</span></div>' +
      '<p class="task-detail-description">' + UI.escapeHTML(displayText(eventItem.raw_text || eventItem.memory_content)) + '</p>' +
      '<dl class="task-detail-facts"><div><dt>事件编号</dt><dd>' + UI.escapeHTML(eventItem.business_id || "编号生成中") +
      '</dd></div><div><dt>风险等级</dt><dd>' + UI.escapeHTML(String(eventItem.severity || "待确认") + " · " + severityLabel(eventItem.severity)) +
      '</dd></div><div><dt>事件类型</dt><dd>' + UI.escapeHTML(type) +
      '</dd></div><div><dt>创建时间</dt><dd>' + UI.escapeHTML(UI.dateLabel(eventItem.created_at)) +
      '</dd></div><div><dt>最近更新</dt><dd>' + UI.escapeHTML(UI.dateLabel(eventItem.updated_at || eventItem.created_at)) +
      '</dd></div></dl>' +
      (eventItem.resolution ? '<div class="result-panel"><strong>闭环结果</strong><p>' +
        UI.escapeHTML(displayText(eventItem.resolution)) + '</p></div>' : '');
  }

  async function openEvent(eventId, preserveURL) {
    var dialog = byId("event-detail-dialog");
    clearInlineError("event-detail-error");
    byId("event-detail-title").textContent = "正在读取事件";
    byId("event-detail-body").innerHTML = '<div class="empty-state compact"><p>正在同步最新事件状态…</p></div>';
    if (!dialog.open) dialog.showModal();
    if (!preserveURL) updateWorkResourceURL("event", eventId);
    try {
      var payload = await Client.work.event(eventId);
      renderEventDetail(payload.event || payload);
    } catch (error) {
      showInlineError("event-detail-error", error);
    }
  }

  function closeEvent() {
    var dialog = byId("event-detail-dialog");
    if (dialog.open) dialog.close();
    state.work.selectedEvent = null;
    clearWorkResourceURL();
  }

  function renderSopDetail(sop) {
    var status = UI.statusCode(sop.status);
    byId("sop-detail-title").textContent = readableTitle(sop.title, "已发布 SOP");
    byId("sop-detail-body").innerHTML =
      '<div class="task-detail-status"><span class="status-pill ' + statusClass(status) + '">' +
      UI.escapeHTML(sop.status_label || UI.statusLabel(status)) + '</span><span>' +
      UI.escapeHTML(sop.source_label || "已发布 SOP") + '</span></div>' +
      '<p class="task-detail-description">' + UI.escapeHTML(displayText(sop.content)) + '</p>' +
      '<dl class="task-detail-facts"><div><dt>分类</dt><dd>' + UI.escapeHTML(displayText(sop.category)) +
      '</dd></div><div><dt>版本</dt><dd>' + UI.escapeHTML("v" + displayText(sop.version)) +
      '</dd></div><div><dt>发布人</dt><dd>' + UI.escapeHTML(displayText(sop.publisher_name) || "知识负责人") +
      '</dd></div><div><dt>发布时间</dt><dd>' + UI.escapeHTML(UI.dateLabel(sop.published_at)) +
      '</dd></div></dl>';
  }

  async function openSop(sopId, version, preserveURL) {
    var dialog = byId("sop-detail-dialog");
    clearInlineError("sop-detail-error");
    byId("sop-detail-title").textContent = "正在读取 SOP";
    byId("sop-detail-body").innerHTML = '<div class="empty-state compact"><p>正在核验已发布版本…</p></div>';
    if (!dialog.open) dialog.showModal();
    if (!preserveURL) updateSopResourceURL(sopId, version);
    try {
      var payload = await Client.knowledge.sop(sopId, version);
      renderSopDetail(payload.sop || payload);
    } catch (error) {
      showInlineError("sop-detail-error", error);
    }
  }

  function closeSop() {
    var dialog = byId("sop-detail-dialog");
    if (dialog.open) dialog.close();
    clearSopResourceURL();
  }

  function replaceWorkTask(task) {
    var index = state.work.tasks.findIndex(function (item) { return item.id === task.id; });
    if (index >= 0) state.work.tasks[index] = task;
    else state.work.tasks.unshift(task);
    renderWork();
    renderTaskDetail(task);
  }

  function setTaskSubmitting(value) {
    state.work.submitting = value;
    byId("task-action-region").querySelectorAll("button, textarea").forEach(function (control) {
      control.disabled = value;
    });
  }

  async function startTask() {
    if (!state.work.selectedTask || state.work.submitting) return;
    clearInlineError("task-action-error");
    setTaskSubmitting(true);
    try {
      var payload = await Client.work.start(state.work.selectedTask.id);
      replaceWorkTask(payload.task || payload);
      notify("任务已开始，处理进度已同步。", "success");
    } catch (error) {
      showInlineError("task-action-error", error);
    } finally {
      setTaskSubmitting(false);
    }
  }

  async function completeTask(event) {
    event.preventDefault();
    if (!state.work.selectedTask || state.work.submitting) return;
    clearInlineError("task-action-error");
    setTaskSubmitting(true);
    try {
      var result = {};
      if (!byId("task-structured-result").hidden) {
        if (state.work.selectedTask.assigned_agent === "field-technician") {
          result.vehicle_12 = byId("task-result-primary").value;
          result.backup_vehicle_7 = byId("task-result-secondary").value;
          result.inspection_items = ["右后轮", "制动", "底盘", "备用车辆"];
        } else {
          result.diversion_action = byId("task-result-primary").value;
          result.risk_status = byId("task-result-secondary").value;
        }
      }
      var payload = await Client.work.complete(state.work.selectedTask.id, {
        summary: byId("task-complete-summary").value,
        result: result
      });
      byId("task-complete-form").reset();
      replaceWorkTask(payload.task || payload);
      notify("完成结果已保存。", "success");
    } catch (error) {
      showInlineError("task-action-error", error);
    } finally {
      setTaskSubmitting(false);
    }
  }

  async function blockTask(event) {
    event.preventDefault();
    if (!state.work.selectedTask || state.work.submitting) return;
    clearInlineError("task-action-error");
    setTaskSubmitting(true);
    try {
      var payload = await Client.work.block(
        state.work.selectedTask.id,
        byId("task-block-reason").value
      );
      byId("task-block-form").reset();
      replaceWorkTask(payload.task || payload);
      notify(UI.statusCode((payload.task || payload).status) === "PENDING"
        ? "阻塞已记录，任务已进入重试队列。"
        : "阻塞已记录，负责人可以继续协调处理。", "success");
    } catch (error) {
      showInlineError("task-action-error", error);
    } finally {
      setTaskSubmitting(false);
    }
  }

  function lineItems(value) {
    if (Array.isArray(value)) {
      return value.map(function (item) { return displayText(item); }).filter(Boolean);
    }
    return displayText(value).split(/\r?\n/).map(function (item) { return item.trim(); }).filter(Boolean);
  }

  function joinLines(value) {
    return lineItems(value).join("\n");
  }

  function expertDisplayName(expert) {
    return displayText(expert && (expert.display_name || expert.expert_name || expert.name)) || "经验专家";
  }

  function renderExpertSummary() {
    var target = byId("experience-profile-summary");
    var expert = state.experience.expert;
    if (!expert) {
      target.innerHTML = '<div class="expert-identity"><span class="expert-mark">经</span><div><strong>当前账号尚未登记为经验专家</strong>' +
        '<span>仍可检索组织已发布经验</span></div></div>';
      return;
    }
    var expertise = lineItems(expert.expertise);
    target.innerHTML = '<div class="expert-identity"><span class="expert-mark">' +
      UI.escapeHTML(expertDisplayName(expert).slice(0, 1)) + '</span><div><strong>' +
      UI.escapeHTML(expertDisplayName(expert)) + '</strong><span>' +
      UI.escapeHTML([expert.job_title, expert.department].filter(Boolean).join(" · ") || "经验专家") + '</span></div></div>' +
      '<div class="expert-meta"><span>' + UI.escapeHTML(Number(expert.years_experience || 0) + " 年现场经验") + '</span>' +
      (expertise.length ? '<span>' + UI.escapeHTML(expertise.join("、")) + '</span>' : "") + '</div>';
  }

  function interviewProgress(interview) {
    var progress = interview.progress || {};
    return {
      answered: Number(progress.answered || interview.current_question_index || 0),
      total: Number(progress.total || 4),
      percent: Number(progress.percent || 0)
    };
  }

  function renderInterviewItem(interview) {
    var progress = interviewProgress(interview);
    return '<button class="experience-item" type="button" data-interview-id="' + UI.escapeHTML(interview.id) + '">' +
      '<span class="experience-item-head"><span><span class="work-kind">专家访谈</span><strong>' +
      UI.escapeHTML(readableTitle(interview.title, "经验访谈")) + '</strong></span><span class="status-pill ' +
      statusClass(interview.status) + '">' + UI.escapeHTML(UI.statusLabel(interview.status)) + '</span></span>' +
      '<span class="experience-item-meta"><span>' + UI.escapeHTML(expertDisplayName(interview)) + '</span><span>已回答 ' +
      progress.answered + ' / ' + progress.total + '</span><time>' +
      UI.escapeHTML(UI.dateLabel(interview.updated_at || interview.created_at)) + '</time></span></button>';
  }

  function experienceSourceName(card) {
    return displayText((card.source || {}).expert_name || card.expert_name) || "经验专家";
  }

  function renderOwnExperienceCard(card) {
    var version = Number(card.current_version || card.published_version || card.version || 1);
    return '<button class="experience-item" type="button" data-experience-card-id="' + UI.escapeHTML(card.id) + '">' +
      '<span class="experience-item-head"><span><span class="work-kind">经验卡 · 第 ' + version + ' 版</span><strong>' +
      UI.escapeHTML(readableTitle(card.title, "未命名经验")) + '</strong></span><span class="status-pill ' +
      statusClass(card.status) + '">' + UI.escapeHTML(UI.statusLabel(card.status)) + '</span></span>' +
      (card.applicable_context ? '<span class="work-description">' + UI.escapeHTML(card.applicable_context) + '</span>' : "") +
      '<span class="experience-item-meta"><span>' + UI.escapeHTML(experienceSourceName(card)) + '</span><time>' +
      UI.escapeHTML(UI.dateLabel(card.updated_at || card.created_at)) + '</time></span></button>';
  }

  function renderExperienceHome() {
    renderExpertSummary();
    byId("interview-count").textContent = state.experience.interviews.length + " 项";
    byId("experience-card-count").textContent = state.experience.cards.length + " 项";
    byId("interview-list").innerHTML = state.experience.interviews.length
      ? state.experience.interviews.map(renderInterviewItem).join("")
      : '<div class="empty-state compact"><strong>暂无访谈邀请</strong><p>新的经验共创任务会显示在这里。</p></div>';
    byId("experience-own-card-list").innerHTML = state.experience.cards.length
      ? state.experience.cards.map(renderOwnExperienceCard).join("")
      : '<div class="empty-state compact"><strong>暂无本人经验卡</strong><p>完成访谈后生成的经验草稿会显示在这里。</p></div>';
  }

  async function loadExperience() {
    if (state.experience.loading) return;
    state.experience.loading = true;
    clearInlineError("experience-error");
    byId("interview-list").innerHTML = '<div class="empty-state compact"><p>正在同步访谈邀请…</p></div>';
    byId("experience-own-card-list").innerHTML = '<div class="empty-state compact"><p>正在同步经验卡…</p></div>';
    try {
      var payload = await Client.experience.home();
      state.experience.expert = payload.expert || null;
      state.experience.interviews = UI.arrayFrom(payload, ["interviews"]);
      state.experience.cards = UI.arrayFrom(payload, ["cards"]);
      state.experience.loaded = true;
      renderExperienceHome();
    } catch (error) {
      state.experience.expert = null;
      state.experience.interviews = [];
      state.experience.cards = [];
      renderExperienceHome();
      showInlineError("experience-error", error);
    } finally {
      state.experience.loading = false;
    }
  }

  function switchExperienceView(view) {
    if (["cocreate", "search"].indexOf(view) < 0) view = "cocreate";
    state.experience.view = view;
    document.querySelectorAll("[data-experience-view]").forEach(function (button) {
      var active = button.getAttribute("data-experience-view") === view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll("[data-experience-panel]").forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-experience-panel") !== view;
    });
    if (view === "search") byId("experience-search-query").focus();
  }

  function interviewTurns(interview) {
    return Array.isArray(interview.turns) ? interview.turns : [];
  }

  function canExtractInterview(interview) {
    if (!interview) return false;
    var progress = interviewProgress(interview);
    var status = UI.statusCode(interview.status);
    return progress.answered >= progress.total &&
      ["ACCEPTED", "IN_PROGRESS", "PAUSED"].indexOf(status) >= 0;
  }

  function renderInterviewExtraction(mode) {
    var form = byId("interview-complete-form");
    var status = byId("interview-extraction-status");
    var detail = byId("interview-extraction-detail");
    var button = byId("interview-complete-button");
    var extracting = mode === "extracting";
    form.classList.toggle("is-extracting", extracting);
    form.setAttribute("aria-busy", extracting ? "true" : "false");
    if (extracting) {
      status.textContent = "正在萃取";
      detail.textContent = "正在根据已保存的四轮回答生成结构化经验草稿，请稍候。";
      button.hidden = true;
      return;
    }
    if (mode === "failed") {
      status.textContent = "萃取未完成";
      detail.textContent = "四轮回答已经保存，可以直接重新萃取，不需要再次作答。";
      button.textContent = "重新萃取经验草稿";
    } else {
      status.textContent = "四轮回答已完成";
      detail.textContent = "智能助手将依据访谈原话生成草稿，生成后可继续修订并确认。";
      button.textContent = "生成经验草稿";
    }
    button.hidden = false;
  }

  function renderInterview(interview) {
    state.experience.selectedInterview = interview;
    var progress = interviewProgress(interview);
    var status = UI.statusCode(interview.status);
    var turns = interviewTurns(interview);
    byId("interview-dialog-title").textContent = readableTitle(interview.title, "经验访谈");
    byId("interview-progress").innerHTML =
      '<div class="progress-label"><span class="status-pill ' + statusClass(status) + '">' +
      UI.escapeHTML(UI.statusLabel(status)) + '</span><strong>已回答 ' + progress.answered + ' / ' + progress.total +
      '</strong></div><progress value="' + progress.answered + '" max="' + progress.total + '"></progress>';
    byId("interview-turns").innerHTML = turns.length
      ? turns.map(function (turn) {
        return '<article class="interview-turn"><span>第 ' + Number(turn.turn_number || 0) + ' 题</span><h3>' +
          UI.escapeHTML(turn.question_text || "访谈问题") + '</h3><p>' + UI.escapeHTML(turn.answer_text || "") + '</p></article>';
      }).join("")
      : '<div class="empty-state compact"><strong>访谈尚未开始</strong></div>';
    var active = ["ACCEPTED", "IN_PROGRESS"].indexOf(status) >= 0;
    var completeReady = canExtractInterview(interview);
    byId("interview-accept-button").hidden = status !== "INVITED";
    byId("interview-pause-button").hidden = !active;
    byId("interview-resume-button").hidden = status !== "PAUSED";
    byId("interview-answer-form").hidden = !active || !interview.next_question;
    byId("interview-complete-form").hidden = !completeReady;
    byId("interview-next-question").innerHTML = interview.next_question
      ? '<span>下一题</span><strong>' + UI.escapeHTML(interview.next_question) + '</strong>'
      : "";
    if (completeReady) renderInterviewExtraction("ready");
    byId("interview-command-bar").hidden = ["INVITED", "ACCEPTED", "IN_PROGRESS", "PAUSED"].indexOf(status) < 0;
  }

  async function openInterview(interviewId) {
    var dialog = byId("interview-dialog");
    clearInlineError("interview-action-error");
    byId("interview-dialog-title").textContent = "正在读取访谈";
    byId("interview-progress").innerHTML = '<div class="empty-state compact"><p>正在同步访谈进度…</p></div>';
    byId("interview-turns").innerHTML = "";
    byId("interview-command-bar").hidden = true;
    byId("interview-answer-form").hidden = true;
    byId("interview-complete-form").hidden = true;
    if (!dialog.open) dialog.showModal();
    try {
      var payload = await Client.experience.interview(interviewId);
      renderInterview(payload.interview || payload);
    } catch (error) {
      showInlineError("interview-action-error", error);
    }
  }

  function closeInterview() {
    var dialog = byId("interview-dialog");
    if (dialog.open) dialog.close();
    state.experience.selectedInterview = null;
  }

  async function refreshSelectedInterview() {
    if (!state.experience.selectedInterview) return;
    var payload = await Client.experience.interview(state.experience.selectedInterview.id);
    var interview = payload.interview || payload;
    renderInterview(interview);
    return interview;
  }

  function setExperienceSubmitting(dialogId, value) {
    state.experience.submitting = value;
    byId(dialogId).querySelectorAll("button, input, textarea").forEach(function (control) {
      if (control.getAttribute("data-action") !== "close-interview" &&
          control.getAttribute("data-action") !== "close-experience-card") {
        control.disabled = value;
      }
    });
  }

  async function acceptInterview() {
    if (!state.experience.selectedInterview || state.experience.submitting) return;
    clearInlineError("interview-action-error");
    setExperienceSubmitting("interview-dialog", true);
    try {
      await Client.experience.acceptInterview(state.experience.selectedInterview.id);
      await refreshSelectedInterview();
      notify("访谈邀请已接受。", "success");
    } catch (error) {
      showInlineError("interview-action-error", error);
    } finally {
      setExperienceSubmitting("interview-dialog", false);
    }
  }

  async function pauseInterview() {
    if (!state.experience.selectedInterview || state.experience.submitting) return;
    clearInlineError("interview-action-error");
    setExperienceSubmitting("interview-dialog", true);
    try {
      await Client.experience.pauseInterview(state.experience.selectedInterview.id);
      await refreshSelectedInterview();
      notify("访谈进度已保存。", "success");
    } catch (error) {
      showInlineError("interview-action-error", error);
    } finally {
      setExperienceSubmitting("interview-dialog", false);
    }
  }

  async function resumeInterview() {
    if (!state.experience.selectedInterview || state.experience.submitting) return;
    clearInlineError("interview-action-error");
    setExperienceSubmitting("interview-dialog", true);
    try {
      await Client.experience.resumeInterview(state.experience.selectedInterview.id);
      await refreshSelectedInterview();
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
    var progress = interviewProgress(interview);
    var idempotencyKey = form.getAttribute("data-idempotency-key") ||
      (interview.id + "-question-" + String(progress.answered + 1));
    form.setAttribute("data-idempotency-key", idempotencyKey);
    clearInlineError("interview-action-error");
    setExperienceSubmitting("interview-dialog", true);
    var shouldExtract = false;
    try {
      await Client.experience.answerInterview(interview.id, {
        answer: byId("interview-answer").value,
        source_excerpt: byId("interview-source-excerpt").value,
        idempotency_key: idempotencyKey
      });
      form.reset();
      form.removeAttribute("data-idempotency-key");
      var refreshedInterview = await refreshSelectedInterview();
      shouldExtract = canExtractInterview(refreshedInterview);
      notify("本题回答已保存。", "success");
    } catch (error) {
      showInlineError("interview-action-error", error);
    } finally {
      setExperienceSubmitting("interview-dialog", false);
    }
    if (shouldExtract) await completeInterview();
  }

  async function completeInterview(event) {
    if (event) event.preventDefault();
    var interview = state.experience.selectedInterview;
    if (!interview || state.experience.submitting) return;
    clearInlineError("interview-action-error");
    renderInterviewExtraction("extracting");
    setExperienceSubmitting("interview-dialog", true);
    try {
      var payload = await Client.experience.completeInterview(interview.id);
      var card = payload && payload.card;
      if (!card) throw new Error("服务端没有返回经验草稿，请重新萃取。");
      closeInterview();
      await loadExperience();
      notify("经验草稿已生成，请检查并确认。", "success");
      openExperienceCard(card.id, card, (payload && payload.extraction) || null);
    } catch (error) {
      renderInterviewExtraction("failed");
      showInlineError("interview-action-error", error);
    } finally {
      setExperienceSubmitting("interview-dialog", false);
    }
  }

  function detailList(label, values) {
    values = lineItems(values);
    if (!values.length) return "";
    return '<section><h3>' + UI.escapeHTML(label) + '</h3><ul>' + values.map(function (item) {
      return '<li>' + UI.escapeHTML(item) + '</li>';
    }).join("") + '</ul></section>';
  }

  function experienceDetail(card) {
    return '<section><h3>适用情境</h3><p>' + UI.escapeHTML(card.applicable_context || "待补充") + '</p></section>' +
      detailList("识别信号", card.signals) +
      '<section><h3>判断规则</h3><p>' + UI.escapeHTML(card.decision_rule || "待补充") + '</p></section>' +
      detailList("建议动作", card.recommended_actions) +
      '<section><h3>判断依据</h3><p>' + UI.escapeHTML(card.rationale || "待补充") + '</p></section>' +
      detailList("禁止事项", card.prohibitions) + detailList("例外情况", card.exceptions) +
      detailList("来源原话", card.source_excerpts);
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

  function renderExperienceCard(card) {
    state.experience.selectedCard = card;
    var status = UI.statusCode(card.status);
    var version = Number(card.current_version || card.published_version || card.version || 1);
    byId("experience-card-dialog-title").textContent = readableTitle(card.title, "经验详情");
    byId("experience-card-status").innerHTML = '<span class="status-pill ' + statusClass(status) + '">' +
      UI.escapeHTML(UI.statusLabel(status)) + '</span><span>第 ' + version + ' 版</span><span>经验专家：' +
      UI.escapeHTML(experienceSourceName(card)) + '</span>';
    var origin = byId("experience-card-origin");
    if (state.experience.selectedExtraction) {
      origin.innerHTML = '<strong>智能萃取草稿</strong><span>已根据四轮访谈回答生成，请在确认前复核关键判断与边界条件。</span>';
      origin.hidden = false;
    } else {
      origin.textContent = "";
      origin.hidden = true;
    }
    byId("experience-card-readonly").innerHTML = experienceDetail(card);
    byId("experience-card-revise-form").hidden = status !== "DRAFT";
    byId("experience-card-confirm-button").hidden = status !== "DRAFT";
    if (status === "DRAFT") populateExperienceCardForm(card);
  }

  function openExperienceCard(cardId, suppliedCard, extraction) {
    var card = suppliedCard || state.experience.cards.find(function (item) { return item.id === cardId; });
    if (!card) {
      showInlineError("experience-error", new Error("经验卡尚未同步，请刷新后重试。"));
      return;
    }
    clearInlineError("experience-card-action-error");
    state.experience.selectedExtraction = extraction || null;
    renderExperienceCard(card);
    var dialog = byId("experience-card-dialog");
    if (!dialog.open) dialog.showModal();
  }

  function closeExperienceCard() {
    var dialog = byId("experience-card-dialog");
    if (dialog.open) dialog.close();
    state.experience.selectedCard = null;
    state.experience.selectedExtraction = null;
  }

  function replaceExperienceCard(card) {
    var index = state.experience.cards.findIndex(function (item) { return item.id === card.id; });
    if (index >= 0) state.experience.cards[index] = card;
    else state.experience.cards.unshift(card);
    renderExperienceHome();
    renderExperienceCard(card);
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
      });
      replaceExperienceCard(payload.card || payload);
      notify("经验修订已保存。", "success");
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
      var payload = await Client.experience.confirmCard(card.id);
      replaceExperienceCard(payload.card || payload);
      notify("经验已由专家确认并提交治理流程。", "success");
    } catch (error) {
      showInlineError("experience-card-action-error", error);
    } finally {
      setExperienceSubmitting("experience-card-dialog", false);
    }
  }

  function renderSearchResults() {
    var target = byId("experience-search-results");
    if (!state.experience.searchResults.length) {
      target.innerHTML = '<div class="empty-state compact"><strong>没有匹配的已发布经验</strong><p>可调整现场信号或处置目标后重新检索。</p></div>';
      return;
    }
    target.innerHTML = state.experience.searchResults.map(function (card) {
      var score = Number(card.score);
      var feedback = card._feedback;
      return '<article class="search-result-card"><div class="experience-item-head"><div><span class="work-kind">已发布经验' +
        (Number.isFinite(score) ? ' · 匹配度 ' + Math.round(score * 100) + '%' : '') + '</span><h3>' +
        UI.escapeHTML(readableTitle(card.title, "组织经验")) + '</h3></div><span class="status-pill success">已发布</span></div>' +
        '<p>' + UI.escapeHTML(card.applicable_context || "") + '</p>' + detailList("识别信号", card.signals) +
        '<section><h4>判断规则</h4><p>' + UI.escapeHTML(card.decision_rule || "") + '</p></section>' +
        detailList("建议动作", card.recommended_actions) + detailList("禁止事项", card.prohibitions) +
        '<footer><span>经验专家：' + UI.escapeHTML(experienceSourceName(card)) + ' · 第 ' +
        Number(card.version || 1) + ' 版</span>' + (feedback
          ? '<strong>反馈已记录</strong>'
          : '<div class="feedback-actions"><button class="btn quiet" type="button" data-feedback-card-id="' +
            UI.escapeHTML(card.id) + '" data-feedback-value="HELPFUL">有帮助</button><button class="btn quiet" type="button" data-feedback-card-id="' +
            UI.escapeHTML(card.id) + '" data-feedback-value="NOT_APPLICABLE">不适用</button><button class="btn quiet" type="button" data-feedback-card-id="' +
            UI.escapeHTML(card.id) + '" data-feedback-value="NEEDS_EXPERT">需要专家</button></div>') + '</footer></article>';
    }).join("");
  }

  async function searchExperience(event) {
    event.preventDefault();
    clearInlineError("experience-error");
    byId("experience-search-results").innerHTML = '<div class="empty-state compact"><p>正在检索已发布经验…</p></div>';
    try {
      var payload = await Client.experience.search({
        query: byId("experience-search-query").value,
        top_k: 8,
        session_id: state.activeSessionId
      });
      state.experience.searchResults = UI.arrayFrom(payload, ["experiences", "items"]);
      renderSearchResults();
    } catch (error) {
      state.experience.searchResults = [];
      renderSearchResults();
      showInlineError("experience-error", error);
    }
  }

  async function sendExperienceFeedback(cardId, feedback) {
    var card = state.experience.searchResults.find(function (item) { return item.id === cardId; });
    if (!card || card._feedback) return;
    try {
      await Client.experience.feedback(cardId, { feedback: feedback, session_id: state.activeSessionId });
      card._feedback = feedback;
      renderSearchResults();
      notify("经验反馈已记录。", "success");
    } catch (error) {
      showInlineError("experience-error", error);
    }
  }

  function followRun(sessionId, messageId) {
    if (state.followController) state.followController.abort();
    if (state.scenicSubscription) state.scenicSubscription.abort();
    state.scenicSubscription = null;
    var controller = new AbortController();
    state.followController = controller;
    Client.assistant.follow(sessionId, messageId, {
      signal: controller.signal,
      timeoutMs: 300000,
      recoveryBaseDelayMs: 1000,
      recoveryMaxDelayMs: 15000,
      recoveryAttemptTimeoutMs: 15000,
      finalReadTimeoutMs: 15000,
      onRecovering: function () {
        if (state.activeSessionId === sessionId) showServiceRecovering();
      },
      onRecovered: function () {
        if (state.activeSessionId === sessionId) showServiceRecovered();
      },
      onUpdate: function (payload) {
        if (state.activeSessionId === sessionId) applyMessagePayload(payload);
      }
    }).then(function (payload) {
      if (state.activeSessionId === sessionId) applyMessagePayload(payload);
      return refreshSessionSummaries();
    }).catch(function (error) {
      if (error && error.name === "AbortError") return;
      if (state.activeSessionId === sessionId) {
        renderError(error, "refresh-current");
        if (Client.recovery.isTransient(error)) showRecoveryDeferred();
        else setPersistedAssistantStatus(UI.errorView(error).message);
      }
    }).finally(function () {
      if (state.followController === controller) state.followController = null;
    });
  }

  async function refreshSessionSummaries() {
    try {
      var payload = await Client.assistant.sessions({ limit: 100 });
      state.sessions = UI.arrayFrom(payload, ["sessions", "items"]);
      state.activeSession = state.sessions.find(function (item) { return item.session_id === state.activeSessionId; }) || state.activeSession;
      renderSessionList();
    } catch (error) {
      notify("会话列表刷新失败，当前消息记录仍可继续查看。", "error");
    }
  }

  function setSubmitting(value) {
    state.submitting = value;
    byId("message-submit").disabled = value;
    byId("message-input").disabled = value;
    byId("attachment-file").disabled = value;
    byId("attachment-note").disabled = value;
    byId("message-submit").textContent = value ? "提交中" : "发送";
    byId("composer-state").textContent = value ? "正在提交给企业正式服务" : "消息由企业正式服务处理";
  }

  function selectedAttachmentFile() {
    var files = byId("attachment-file").files;
    return files && files.length ? files[0] : null;
  }

  function renderAttachmentSelection(message) {
    var target = byId("attachment-selection");
    if (message) {
      target.textContent = message;
      return;
    }
    var file = selectedAttachmentFile();
    target.textContent = file
      ? file.name + " · " + attachmentSizeLabel(file.size)
      : "尚未选择现场图片";
  }

  async function uploadPendingAttachment() {
    var file = selectedAttachmentFile();
    if (!file) return null;
    if (state.pendingAttachment && state.pendingAttachment.file === file) {
      return state.pendingAttachment.attachment;
    }
    renderAttachmentSelection("正在上传并检查 " + file.name + "…");
    try {
      var attachment = await Client.assistant.uploadAttachment(file);
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
      state.pendingExternalMessageId = Client.ids.externalMessage("web");
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

  function optimisticAttachments(description, externalMessageId) {
    var file = selectedAttachmentFile();
    if (!file) return [];
    var attachmentId = "pending-" + externalMessageId;
    state.attachmentObjectUrls[attachmentId] = URL.createObjectURL(file);
    return [{
      attachment_id: attachmentId,
      name: file.name || "现场图片",
      description: description,
      uploaded_by_name: state.user && (state.user.display_name || state.user.username) || "企业员工",
      created_at: Date.now() / 1000,
      size_bytes: file.size
    }];
  }

  function showOptimisticMessage(content, attachmentNote, externalMessageId, sessionId) {
    var message = {
      role: "user",
      content: content,
      external_message_id: externalMessageId,
      session_id: sessionId || "",
      status: "SENDING",
      created_at: Date.now() / 1000,
      business_cards: [],
      attachments: optimisticAttachments(attachmentNote, externalMessageId),
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
    var input = byId("message-input");
    var content = input.value.trim();
    if (!content) return;
    var attachmentNote = byId("attachment-note").value.trim();
    var targetSessionId = state.activeSessionId;
    var targetExternalConversationId = state.activeSession && state.activeSession.external_conversation_id;
    var targetSourceEventId = latestOpenEventId();
    state.lastSubmittedContent = content;
    var externalMessageId = ensurePendingExternalMessageId();
    var optimisticMessage = showOptimisticMessage(
      content,
      attachmentNote,
      externalMessageId,
      targetSessionId
    );
    setSubmitting(true);
    clearError();
    setAssistantStatus("SENDING", "正在提交消息");
    try {
      var uploadedAttachment = await uploadPendingAttachment();
      var response = await Client.assistant.send({
        content: content,
        session_id: targetSessionId,
        channel: "WEB",
        external_message_id: externalMessageId,
        external_conversation_id: targetExternalConversationId,
        attachments: uploadedAttachment ? [{
          attachment_id: uploadedAttachment.attachment_id,
          description: attachmentNote
        }] : undefined,
        metadata: {
          source: "employee_assistant",
          attachment_note: attachmentNote || undefined,
          source_event_id: targetSourceEventId
        }
      });
      optimisticMessage.message_id = response.message_id;
      optimisticMessage.session_id = response.session_id;
      state.activeSessionId = response.session_id;
      saveLastSessionContext();
      updateSessionURL(response.session_id);
      setOptimisticMessageStatus(optimisticMessage, "SENT");
      if (state.pendingExternalMessageId === externalMessageId) state.pendingExternalMessageId = "";
      input.value = "";
      byId("attachment-note").value = "";
      byId("attachment-file").value = "";
      state.pendingAttachment = null;
      renderAttachmentSelection();
      updateCount();
      setAssistantStatus("SENT", "消息已由正式服务受理");
      await loadMessages(response.session_id, false);
      followRun(response.session_id, response.message_id);
      refreshSessionSummaries();
    } catch (error) {
      removeOptimisticMessage(optimisticMessage);
      renderMessages();
      renderError(error, "retry-message");
      setAssistantStatus("FAILED", "消息未成功提交");
    } finally {
      setSubmitting(false);
      input.focus();
    }
  }

  function retryMessage() {
    if (!state.lastSubmittedContent || state.submitting) return;
    byId("message-input").value = state.lastSubmittedContent;
    updateCount();
    byId("message-form").requestSubmit();
  }

  async function retryPersistedMessage(messageId) {
    if (!messageId || state.retryingMessageId) return;
    var retrySessionId = state.activeSessionId;
    var retryOwnerKey = signedUserContextKey(state.user);
    state.retryingMessageId = messageId;
    clearError();
    renderMessages();
    setAssistantStatus("RETRYING", "正在从原消息继续处理");
    try {
      var response = await Client.assistant.retry(messageId);
      if (state.activeSessionId !== retrySessionId) return;
      if (signedUserContextKey(state.user) !== retryOwnerKey) return;
      state.activeSessionId = response.session_id || state.activeSessionId;
      var retriedSessionId = state.activeSessionId;
      saveLastSessionContext();
      await loadMessages(state.activeSessionId, false);
      if (state.activeSessionId !== retriedSessionId || signedUserContextKey(state.user) !== retryOwnerKey) return;
      followRun(state.activeSessionId, messageId);
    } catch (error) {
      if (state.activeSessionId !== retrySessionId || signedUserContextKey(state.user) !== retryOwnerKey) return;
      renderError(error, "refresh-current");
      setPersistedAssistantStatus("原消息重试状态未确认，请刷新会话");
    } finally {
      state.retryingMessageId = "";
      renderMessages();
    }
  }

  async function refreshCurrent() {
    clearError();
    if (state.section === "work") {
      await loadWork();
      return;
    }
    if (state.section === "experience") {
      await loadExperience();
      return;
    }
    if (state.section === "me") {
      try {
        applyUser(await Client.auth.restore());
        notify("企业身份已刷新");
      } catch (error) {
        showLogin(error);
      }
      return;
    }
    if (state.activeSessionId) await loadMessages(state.activeSessionId, true);
    else await loadSessions();
  }

  function updateCount() {
    var input = byId("message-input");
    byId("message-count").textContent = input.value.length + " / 5000";
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  }

  function filterWork(event) {
    event.preventDefault();
    loadWork();
  }

  async function handleLogin(event) {
    event.preventDefault();
    var button = byId("login-submit");
    button.disabled = true;
    button.textContent = "正在验证";
    byId("login-error").textContent = "";
    try {
      var user = await Client.auth.login(byId("login-username").value, byId("login-password").value);
      byId("login-form").reset();
      await showApp(user);
    } catch (error) {
      byId("login-error").textContent = UI.errorView(error).message;
    } finally {
      button.disabled = false;
      button.textContent = "登录助手";
    }
  }

  async function logout() {
    if (state.submitting) {
      notify("消息正在发送，请稍候再退出。", "error");
      return;
    }
    if (state.followController) state.followController.abort();
    try {
      await Client.auth.logout();
    } catch (error) {
      Client.auth.clear();
    }
    state.sessions = [];
    state.messages = [];
    state.activeSessionId = null;
    resetPendingExternalMessageId(true);
    state.lastSubmittedContent = "";
    clearOptimisticMessages();
    state.pendingAttachment = null;
    clearAttachmentObjectUrls();
    state.user = null;
    showLogin();
  }

  function handleClick(event) {
    var sectionTarget = event.target.closest("[data-section]");
    if (sectionTarget) {
      navigate(sectionTarget.getAttribute("data-section"));
      return;
    }
    var experienceViewTarget = event.target.closest("[data-experience-view]");
    if (experienceViewTarget) {
      switchExperienceView(experienceViewTarget.getAttribute("data-experience-view"));
      return;
    }
    var prompt = event.target.closest("[data-prompt]");
    if (prompt) {
      var input = byId("message-input");
      resetPendingExternalMessageId();
      input.value = prompt.getAttribute("data-prompt");
      updateCount();
      input.focus();
      return;
    }
    var retryTarget = event.target.closest("[data-retry-message-id]");
    if (retryTarget) {
      retryPersistedMessage(retryTarget.getAttribute("data-retry-message-id"));
      return;
    }
    var sessionTarget = event.target.closest("[data-session-id]");
    if (sessionTarget) {
      selectSession(sessionTarget.getAttribute("data-session-id"));
      return;
    }
    var taskTarget = event.target.closest("[data-task-id]");
    if (taskTarget) {
      openTask(taskTarget.getAttribute("data-task-id"));
      return;
    }
    var eventTarget = event.target.closest("[data-event-id]");
    if (eventTarget) {
      openEvent(eventTarget.getAttribute("data-event-id"));
      return;
    }
    var interviewTarget = event.target.closest("[data-interview-id]");
    if (interviewTarget) {
      openInterview(interviewTarget.getAttribute("data-interview-id"));
      return;
    }
    var experienceCardTarget = event.target.closest("[data-experience-card-id]");
    if (experienceCardTarget) {
      openExperienceCard(experienceCardTarget.getAttribute("data-experience-card-id"));
      return;
    }
    var feedbackTarget = event.target.closest("[data-feedback-card-id]");
    if (feedbackTarget) {
      sendExperienceFeedback(
        feedbackTarget.getAttribute("data-feedback-card-id"),
        feedbackTarget.getAttribute("data-feedback-value")
      );
      return;
    }
    var actionTarget = event.target.closest("[data-action]");
    if (!actionTarget) return;
    var actions = {
      "new-session": newSession,
      "open-sessions": openSessions,
      "close-sessions": closeSessions,
      "refresh-sessions": loadSessions,
      "refresh-current": refreshCurrent,
      "retry-message": retryMessage,
      "close-task": closeTask,
      "close-event": closeEvent,
      "close-sop": closeSop,
      "start-task": startTask,
      "close-interview": closeInterview,
      "accept-interview": acceptInterview,
      "pause-interview": pauseInterview,
      "resume-interview": resumeInterview,
      "close-experience-card": closeExperienceCard,
      "confirm-card": confirmExperienceCard,
      logout: logout
    };
    var action = actions[actionTarget.getAttribute("data-action")];
    if (action) action();
  }

  async function init() {
    emptyChatTemplate = byId("chat-empty").outerHTML;
    byId("login-form").addEventListener("submit", handleLogin);
    byId("message-form").addEventListener("submit", submitMessage);
    byId("work-filter-form").addEventListener("submit", filterWork);
    byId("task-complete-form").addEventListener("submit", completeTask);
    byId("task-block-form").addEventListener("submit", blockTask);
    byId("interview-answer-form").addEventListener("submit", answerInterview);
    byId("interview-complete-form").addEventListener("submit", completeInterview);
    byId("experience-card-revise-form").addEventListener("submit", reviseExperienceCard);
    byId("experience-search-form").addEventListener("submit", searchExperience);
    byId("message-input").addEventListener("input", function () {
      resetPendingExternalMessageId();
      updateCount();
    });
    byId("attachment-note").addEventListener("input", resetPendingExternalMessageId);
    byId("attachment-file").addEventListener("change", function () {
      resetPendingExternalMessageId();
      state.pendingAttachment = null;
      renderAttachmentSelection();
    });
    document.addEventListener("click", handleClick);
    window.addEventListener("popstate", function () {
      var workResource = workResourceFromLocation();
      var sopResource = sopResourceFromLocation();
      navigate(workResource ? "work" : sectionFromLocation(), true);
      if (workResource && workResource.type === "event") openEvent(workResource.id, true);
      if (workResource && workResource.type === "task") openTask(workResource.id, true);
      if (sopResource) openSop(sopResource.id, sopResource.version, true);
    });
    renderAttachmentSelection();
    updateCount();
    if (!Client.auth.isAuthenticated()) {
      showLogin();
      return;
    }
    try {
      await showApp(await Client.auth.restore());
    } catch (error) {
      showLogin(error);
    }
  }

  init();
}());
