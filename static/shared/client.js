(function () {
  "use strict";

  var API_BASE = "/api/v1";
  var STORAGE_KEYS = {
    accessToken: "mp_access_token",
    refreshToken: "mp_refresh_token",
    user: "mp_user"
  };
  var sequence = 0;
  var session = readSession();
  var refreshPromise = null;

  function readSession() {
    var user = null;
    try {
      user = JSON.parse(sessionStorage.getItem(STORAGE_KEYS.user) || "null");
    } catch (error) {
      user = null;
    }
    return {
      accessToken: sessionStorage.getItem(STORAGE_KEYS.accessToken) || "",
      refreshToken: sessionStorage.getItem(STORAGE_KEYS.refreshToken) || "",
      user: user
    };
  }

  function emitAuthChange() {
    window.dispatchEvent(new CustomEvent("memory-palace-auth-changed", {
      detail: { authenticated: Boolean(session.accessToken), user: session.user }
    }));
  }

  function saveSession(payload) {
    session.accessToken = payload.access_token || "";
    session.refreshToken = payload.refresh_token || "";
    session.user = payload.user || null;
    sessionStorage.setItem(STORAGE_KEYS.accessToken, session.accessToken);
    sessionStorage.setItem(STORAGE_KEYS.refreshToken, session.refreshToken);
    sessionStorage.setItem(STORAGE_KEYS.user, JSON.stringify(session.user));
    emitAuthChange();
    return session.user;
  }

  function clearSession() {
    session.accessToken = "";
    session.refreshToken = "";
    session.user = null;
    Object.keys(STORAGE_KEYS).forEach(function (key) {
      sessionStorage.removeItem(STORAGE_KEYS[key]);
    });
    emitAuthChange();
  }

  function externalId(prefix) {
    sequence += 1;
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return prefix + "-" + window.crypto.randomUUID();
    }
    return prefix + "-" + Date.now().toString(36) + "-" + sequence.toString(36);
  }

  async function parseResponse(response, responseType) {
    var contentType = response.headers.get("content-type") || "";
    if (response.status === 204) return null;
    if (responseType === "blob") return response.blob();
    if (contentType.indexOf("application/json") >= 0) {
      return response.json().catch(function () { return {}; });
    }
    return response.text();
  }

  function errorDetails(status, payload) {
    var detail = payload && payload.detail !== undefined ? payload.detail : payload;
    var serverMessage = typeof detail === "string"
      ? detail
      : (detail && detail.message) || (payload && payload.message) || "";
    var messages = {
      400: "提交内容未通过校验，请检查后重试。",
      401: "登录状态已失效，请重新登录。",
      403: "当前账号没有执行此操作的权限。",
      404: "当前服务版本尚未启用这项能力，请联系管理员确认统一助手接口已部署。",
      409: "这条消息已被系统受理，请刷新会话查看最新状态。",
      422: "提交内容不完整，请检查必填信息。",
      429: "请求较多，系统正在保护服务，请稍后重试。",
      500: "服务处理失败，系统没有生成替代结果。请稍后重试或联系管理员查看运行记录。",
      502: "智能服务暂时无法连接，请稍后重试。",
      503: "企业运营助手暂时不可用，请稍后重试。",
      504: "本次处理等待超时，消息可能仍在后台执行，请从会话历史确认结果。"
    };
    var error = new Error(serverMessage || messages[status] || ("请求失败（" + status + "）"));
    error.status = status;
    error.code = detail && detail.code;
    error.traceId = detail && detail.trace_id;
    error.retryable = Boolean(detail && detail.retryable) || status >= 500 || status === 429;
    error.action = detail && detail.action;
    error.userMessage = serverMessage || messages[status] || error.message;
    return error;
  }

  function refresh() {
    if (!session.refreshToken) return Promise.resolve(false);
    if (refreshPromise) return refreshPromise;
    var refreshToken = session.refreshToken;
    refreshPromise = (async function () {
      var response;
      try {
        response = await fetch(API_BASE + "/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken })
        });
      } catch (error) {
        return false;
      }
      if (!response.ok) {
        if (session.refreshToken === refreshToken) clearSession();
        return false;
      }
      var payload = await parseResponse(response);
      if (session.refreshToken !== refreshToken) return Boolean(session.accessToken);
      saveSession(payload);
      return true;
    }()).finally(function () {
      refreshPromise = null;
    });
    return refreshPromise;
  }

  async function request(path, options, retry) {
    options = options || {};
    if (retry === undefined) retry = true;
    var requestAccessToken = session.accessToken;
    var headers = new Headers(options.headers || {});
    var isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
    if (session.accessToken) headers.set("Authorization", "Bearer " + session.accessToken);
    if (options.body !== undefined && !isFormData && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    var response;
    try {
      response = await fetch(path.indexOf("http") === 0 ? path : API_BASE + path, {
        method: options.method || "GET",
        headers: headers,
        body: options.body === undefined
          ? undefined
          : ((isFormData || typeof options.body === "string") ? options.body : JSON.stringify(options.body)),
        signal: options.signal
      });
    } catch (cause) {
      var networkError = new Error("无法连接企业服务，请检查网络或确认服务已启动。");
      networkError.cause = cause;
      networkError.status = 0;
      networkError.retryable = true;
      networkError.userMessage = networkError.message;
      throw networkError;
    }
    if (response.status === 401 && retry && await refresh()) {
      return request(path, options, false);
    }
    var payload = await parseResponse(response, options.responseType);
    if (!response.ok) {
      if (response.status === 401 && session.accessToken === requestAccessToken) clearSession();
      throw errorDetails(response.status, payload);
    }
    return payload;
  }

  async function login(username, password) {
    clearSession();
    var payload = await request("/auth/login", {
      method: "POST",
      body: { username: String(username || "").trim(), password: String(password || "") }
    }, false);
    saveSession(payload);
    return session.user;
  }

  async function restore() {
    if (!session.accessToken) return null;
    session.user = await request("/auth/me");
    sessionStorage.setItem(STORAGE_KEYS.user, JSON.stringify(session.user));
    return session.user;
  }

  async function logout() {
    try {
      if (session.accessToken && session.refreshToken) {
        await request("/auth/logout", {
          method: "POST",
          body: { refresh_token: session.refreshToken }
        }, false);
      }
    } finally {
      clearSession();
    }
  }

  function compactBody(source, fields) {
    var body = {};
    fields.forEach(function (field) {
      var value = source[field];
      if (value !== undefined && value !== null && value !== "") body[field] = value;
    });
    return body;
  }

  async function sendAssistantMessage(input) {
    input = input || {};
    var content = String(input.content || "").trim();
    if (!content) throw new Error("请输入要发送的内容。");
    var body = compactBody({
      content: content,
      session_id: input.session_id,
      channel: input.channel || "WEB",
      external_message_id: input.external_message_id || externalId("web"),
      external_conversation_id: input.external_conversation_id,
      acting_user_id: input.acting_user_id,
      attachments: Array.isArray(input.attachments) && input.attachments.length ? input.attachments : undefined,
      metadata: input.metadata
    }, [
      "content", "session_id", "channel", "external_message_id",
      "external_conversation_id", "acting_user_id", "attachments", "metadata"
    ]);
    return request("/assistant/messages", { method: "POST", body: body });
  }

  function attachmentForm(file) {
    if (!file) throw new Error("请选择需要上传的现场图片。");
    var form = new FormData();
    form.append("file", file, file.name || "attachment");
    return form;
  }

  async function uploadAssistantAttachment(file) {
    var payload = await request("/assistant/attachments", {
      method: "POST",
      body: attachmentForm(file)
    });
    return payload && payload.attachment;
  }

  async function uploadSimulatorAttachment(userId, file) {
    userId = String(userId || "").trim();
    if (!userId) throw new Error("请先选择员工身份。");
    var form = attachmentForm(file);
    form.append("user_id", userId);
    var payload = await request("/channels/simulator/attachments", {
      method: "POST",
      body: form
    });
    return payload && payload.attachment;
  }

  async function getAttachmentContent(attachmentId) {
    attachmentId = String(attachmentId || "").trim();
    if (!attachmentId) throw new Error("附件编号无效，无法读取缩略图。");
    return request(
      "/assistant/attachments/" + encodeURIComponent(attachmentId) + "/content",
      { responseType: "blob" }
    );
  }

  async function sendSimulatorMessage(input) {
    input = input || {};
    var content = String(input.content || "").trim();
    if (!content) throw new Error("请输入要发送的内容。");
    return request("/channels/simulator/messages", {
      method: "POST",
      body: compactBody({
        user_id: input.user_id,
        content: content,
        external_message_id: input.external_message_id || externalId("wecom-sim"),
        external_conversation_id: input.external_conversation_id,
        attachments: Array.isArray(input.attachments) && input.attachments.length ? input.attachments : undefined,
        metadata: input.metadata
      }, ["user_id", "content", "external_message_id", "external_conversation_id", "attachments", "metadata"])
    });
  }

  function queryString(options, allowed) {
    var params = new URLSearchParams();
    options = options || {};
    allowed.forEach(function (key) {
      if (options[key] !== undefined && options[key] !== null && options[key] !== "") {
        params.set(key, options[key]);
      }
    });
    var value = params.toString();
    return value ? "?" + value : "";
  }

  async function listSessions(options) {
    options = options || {};
    return request(
      "/assistant/sessions" + queryString(options, ["channel", "acting_user_id", "limit", "cursor"]),
      { signal: options.signal }
    );
  }

  async function listMessages(sessionId, options) {
    if (!sessionId) throw new Error("请选择会话后再查看消息。");
    options = options || {};
    return request(
      "/assistant/sessions/" + encodeURIComponent(sessionId) + "/messages" +
      queryString(options, ["acting_user_id", "limit", "cursor"]),
      { signal: options.signal }
    );
  }

  async function retryAssistantMessage(messageId, input) {
    messageId = String(messageId || "").trim();
    if (!messageId) throw new Error("原消息编号无效，无法发起人工重试。");
    return request(
      "/assistant/messages/" + encodeURIComponent(messageId) + "/retry" +
      queryString(input, ["acting_user_id"]),
      { method: "POST" }
    );
  }

  async function listSimulatorIdentities(options) {
    return request("/channels/simulator-identities", { signal: options && options.signal });
  }

  async function getSimulatorOutbox(sessionId, userId, options) {
    sessionId = String(sessionId || "").trim();
    userId = String(userId || "").trim();
    if (!sessionId || !userId) throw new Error("请选择员工会话后再查看审批与出站回执。");
    return request(
      "/channels/simulator/sessions/" + encodeURIComponent(sessionId) + "/outbox" +
      queryString({ user_id: userId }, ["user_id"]),
      { signal: options && options.signal }
    );
  }

  function employeeTaskPath(taskId) {
    if (!taskId) throw new Error("请选择任务后再执行操作。");
    return "/assistant/work/tasks/" + encodeURIComponent(taskId);
  }

  async function listWork(options) {
    return request(
      "/assistant/work" + queryString(options, ["task_status", "event_status", "limit", "offset"])
    );
  }

  async function getWorkTask(taskId) {
    return request(employeeTaskPath(taskId));
  }

  async function getWorkEvent(eventId) {
    if (!eventId) throw new Error("请选择事件后再查看详情。");
    return request("/assistant/work/events/" + encodeURIComponent(eventId));
  }

  async function getKnowledgeSop(sopId, version) {
    if (!sopId) throw new Error("请选择 SOP 后再查看详情。");
    return request(
      "/assistant/knowledge/sops/" + encodeURIComponent(sopId) +
      queryString({ version: version }, ["version"])
    );
  }

  async function startWorkTask(taskId) {
    return request(employeeTaskPath(taskId) + "/start", { method: "POST" });
  }

  async function completeWorkTask(taskId, summary) {
    summary = String(summary || "").trim();
    if (!summary) throw new Error("请填写完成结果后再提交。");
    return request(employeeTaskPath(taskId) + "/complete", {
      method: "POST",
      body: { summary: summary }
    });
  }

  async function blockWorkTask(taskId, reason) {
    reason = String(reason || "").trim();
    if (!reason) throw new Error("请填写阻塞原因后再提交。");
    return request(employeeTaskPath(taskId) + "/block", {
      method: "POST",
      body: { reason: reason }
    });
  }

  function experiencePath(path, options) {
    return path + queryString(options, ["acting_user_id"]);
  }

  function experienceRequestOptions(options, method) {
    return {
      method: method || "GET",
      signal: options && options.signal
    };
  }

  function experienceInterviewPath(interviewId, options, action) {
    if (!interviewId) throw new Error("请选择访谈后再执行操作。");
    return experiencePath(
      "/assistant/experience/interviews/" + encodeURIComponent(interviewId) +
        (action ? "/" + action : ""),
      options
    );
  }

  function experienceCardPath(cardId, options, action) {
    if (!cardId) throw new Error("请选择经验卡后再执行操作。");
    return experiencePath(
      "/assistant/experience/cards/" + encodeURIComponent(cardId) +
        (action ? "/" + action : ""),
      options
    );
  }

  async function getExperienceHome(options) {
    return request(
      experiencePath("/assistant/experience", options),
      experienceRequestOptions(options)
    );
  }

  async function getExperienceInterview(interviewId, options) {
    return request(
      experienceInterviewPath(interviewId, options),
      experienceRequestOptions(options)
    );
  }

  async function acceptExperienceInterview(interviewId, options) {
    return request(
      experienceInterviewPath(interviewId, options, "accept"),
      experienceRequestOptions(options, "POST")
    );
  }

  async function answerExperienceInterview(interviewId, input, options) {
    input = input || {};
    var answer = String(input.answer || "").trim();
    if (!answer) throw new Error("请填写本题回答后再提交。");
    return request(experienceInterviewPath(interviewId, options, "answers"), {
      method: "POST",
      signal: options && options.signal,
      headers: { "Idempotency-Key": input.idempotency_key || externalId("interview-answer") },
      body: compactBody({
        answer: answer,
        source_excerpt: String(input.source_excerpt || "").trim()
      }, ["answer", "source_excerpt"])
    });
  }

  async function pauseExperienceInterview(interviewId, options) {
    return request(
      experienceInterviewPath(interviewId, options, "pause"),
      experienceRequestOptions(options, "POST")
    );
  }

  async function resumeExperienceInterview(interviewId, options) {
    return request(
      experienceInterviewPath(interviewId, options, "resume"),
      experienceRequestOptions(options, "POST")
    );
  }

  async function completeExperienceInterview(interviewId, options) {
    return request(
      experienceInterviewPath(interviewId, options, "complete"),
      experienceRequestOptions(options, "POST")
    );
  }

  async function reviseExperienceCard(cardId, input, options) {
    return request(experienceCardPath(cardId, options), {
      method: "PUT",
      signal: options && options.signal,
      body: input || {}
    });
  }

  async function confirmExperienceCard(cardId, options) {
    return request(
      experienceCardPath(cardId, options, "confirm"),
      experienceRequestOptions(options, "POST")
    );
  }

  async function searchExperience(input, options) {
    input = input || {};
    var query = String(input.query || "").trim();
    if (!query) throw new Error("请输入需要查找的现场问题。");
    return request(experiencePath("/assistant/experience/search", options), {
      method: "POST",
      signal: options && options.signal,
      body: compactBody({
        query: query,
        top_k: input.top_k,
        threshold: input.threshold,
        session_id: input.session_id
      }, ["query", "top_k", "threshold", "session_id"])
    });
  }

  async function sendExperienceFeedback(cardId, input, options) {
    input = input || {};
    if (["HELPFUL", "NOT_APPLICABLE", "NEEDS_EXPERT"].indexOf(input.feedback) < 0) {
      throw new Error("请选择经验是否有效。");
    }
    return request(experienceCardPath(cardId, options, "feedback"), {
      method: "POST",
      signal: options && options.signal,
      body: compactBody({
        feedback: input.feedback,
        session_id: input.session_id,
        note: String(input.note || "").trim()
      }, ["feedback", "session_id", "note"])
    });
  }

  function arrayFrom(payload, keys) {
    if (Array.isArray(payload)) return payload;
    payload = payload || {};
    for (var index = 0; index < keys.length; index += 1) {
      if (Array.isArray(payload[keys[index]])) return payload[keys[index]];
    }
    return [];
  }

  function statusCode(value) {
    return String(value || "UNKNOWN").trim().toUpperCase();
  }

  function statusLabel(value) {
    var code = statusCode(value);
    var labels = {
      SENDING: "发送中",
      SENT: "已受理",
      QUEUED: "已受理，等待处理",
      PENDING: "等待处理",
      PROCESSING: "处理中",
      RUNNING: "正在执行",
      RETRYING: "正在重新处理",
      RETRY_REQUIRED: "需要人工重试",
      DEAD_LETTERED: "需要人工重试",
      BLOCKED: "已阻塞",
      COMPLETED: "已完成",
      SUCCEEDED: "已完成",
      DONE: "已完成",
      FAILED: "处理失败",
      ERROR: "处理失败",
      CANCELLED: "已取消",
      OPEN: "处理中",
      CLOSED: "已闭环",
      INVITED: "待接受邀请",
      ACCEPTED: "已接受，待开始",
      IN_PROGRESS: "访谈进行中",
      PAUSED: "已暂停",
      DRAFT: "待专家确认",
      EXPERT_CONFIRMED: "专家已确认",
      IN_REVIEW: "审核中",
      PUBLISHED: "已发布",
      DEPRECATED: "已停用",
      ACTIVE: "使用中",
      INACTIVE: "已停用",
      WAITING_APPROVAL: "等待审批",
      EXECUTING: "执行中",
      REJECTED: "审批已拒绝",
      UNKNOWN: "状态待确认"
    };
    return labels[code] || "状态待确认";
  }

  function dateLabel(value) {
    if (value === undefined || value === null || value === "") return "时间待确认";
    var numeric = Number(value);
    var date = Number.isFinite(numeric)
      ? new Date(numeric < 100000000000 ? numeric * 1000 : numeric)
      : new Date(value);
    if (Number.isNaN(date.getTime())) return "时间待确认";
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false
    }).format(date);
  }

  function escapeHTML(value) {
    return String(value === undefined || value === null ? "" : value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[character];
    });
  }

  function errorView(error) {
    return {
      title: error && error.status === 403 ? "权限不足" : "暂时无法完成",
      message: (error && (error.userMessage || error.message)) || "发生未知错误，请稍后重试。",
      action: error && error.action,
      traceId: error && error.traceId,
      retryable: Boolean(error && error.retryable)
    };
  }

  function isTerminal(value) {
    return [
      "COMPLETED", "SUCCEEDED", "DONE", "FAILED", "ERROR", "CANCELLED", "RETRY_REQUIRED", "DEAD_LETTERED"
    ].indexOf(statusCode(value)) >= 0;
  }

  function wait(milliseconds, signal) {
    return new Promise(function (resolve, reject) {
      function cleanup() {
        window.clearTimeout(timer);
        if (signal) signal.removeEventListener("abort", abort);
      }
      function finish() {
        cleanup();
        resolve();
      }
      function abort() {
        cleanup();
        reject(new DOMException("操作已取消", "AbortError"));
      }
      var timer = window.setTimeout(finish, milliseconds);
      if (!signal) return;
      if (signal && signal.aborted) {
        abort();
        return;
      }
      signal.addEventListener("abort", abort, { once: true });
    });
  }

  function isTransientRecoveryError(error) {
    var status = Number(error && error.status);
    return status === 0 || status === 408 || status === 425 || status === 429 || status >= 500;
  }

  function recoveryDelay(attempt, options) {
    options = options || {};
    var baseDelayMs = Math.max(250, Number(options.baseDelayMs) || 1000);
    var maxDelayMs = Math.max(baseDelayMs, Number(options.maxDelayMs) || 15000);
    return Math.min(maxDelayMs, baseDelayMs * Math.pow(2, attempt));
  }

  async function recoveryAttempt(operation, timeoutMs, signal) {
    if (signal && signal.aborted) throw new DOMException("操作已取消", "AbortError");
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    var attemptSignal = controller ? controller.signal : signal;
    var guardReject;
    var timer;
    var timedOut = false;
    var guard = new Promise(function (resolve, reject) {
      guardReject = reject;
      timer = window.setTimeout(function () {
        timedOut = true;
        var error = new Error("服务请求等待超时，正在继续恢复原任务。");
        error.status = 504;
        error.retryable = true;
        error.userMessage = error.message;
        reject(error);
        if (controller) controller.abort();
      }, timeoutMs);
    });
    function forwardAbort() {
      guardReject(new DOMException("操作已取消", "AbortError"));
      if (controller) controller.abort();
    }
    if (signal) signal.addEventListener("abort", forwardAbort, { once: true });
    try {
      return await Promise.race([
        Promise.resolve().then(function () { return operation(attemptSignal); }),
        guard
      ]);
    } catch (error) {
      if (signal && signal.aborted) throw new DOMException("操作已取消", "AbortError");
      if (timedOut) {
        error.status = 504;
        error.retryable = true;
      }
      throw error;
    } finally {
      window.clearTimeout(timer);
      if (signal) signal.removeEventListener("abort", forwardAbort);
    }
  }

  async function withRecovery(operation, options) {
    options = options || {};
    var timeoutMs = Math.max(1, Number(options.timeoutMs) || 60000);
    var startedAt = Date.now();
    var attempt = 0;
    var recovering = false;
    while (Date.now() - startedAt < timeoutMs) {
      try {
        var remainingBeforeAttempt = timeoutMs - (Date.now() - startedAt);
        var attemptTimeoutMs = Math.min(
          remainingBeforeAttempt,
          Math.max(1000, Number(options.attemptTimeoutMs) || 15000)
        );
        var result = await recoveryAttempt(operation, attemptTimeoutMs, options.signal);
        if (recovering && typeof options.onRecovered === "function") {
          options.onRecovered({ attempts: attempt });
        }
        return result;
      } catch (error) {
        if (options.signal && options.signal.aborted) throw new DOMException("操作已取消", "AbortError");
        var remainingMs = timeoutMs - (Date.now() - startedAt);
        if (!isTransientRecoveryError(error) || remainingMs <= 0) throw error;
        var delayMs = Math.min(recoveryDelay(attempt, options), remainingMs);
        attempt += 1;
        recovering = true;
        if (typeof options.onRecovering === "function") {
          options.onRecovering({ attempt: attempt, delay_ms: delayMs, error: error });
        }
        await wait(delayMs, options.signal);
      }
    }
    var timeoutError = new Error("服务恢复等待超时，任务仍可能在后台处理中。");
    timeoutError.status = 504;
    timeoutError.retryable = true;
    timeoutError.userMessage = timeoutError.message;
    throw timeoutError;
  }

  async function followMessage(sessionId, messageId, options) {
    options = options || {};
    var timeoutMs = options.timeoutMs || 120000;
    var finalReadTimeoutMs = Math.min(
      timeoutMs,
      Math.max(1000, Number(options.finalReadTimeoutMs) || 15000)
    );
    var pollingTimeoutMs = Math.max(0, timeoutMs - finalReadTimeoutMs);
    var startedAt = Date.now();
    var latest;
    while (Date.now() - startedAt < pollingTimeoutMs) {
      try {
        latest = await withRecovery(function (signal) {
          var query = Object.assign({}, options.query || {}, { signal: signal });
          return listMessages(sessionId, query);
        }, {
          timeoutMs: pollingTimeoutMs - (Date.now() - startedAt),
          baseDelayMs: options.recoveryBaseDelayMs,
          maxDelayMs: options.recoveryMaxDelayMs,
          attemptTimeoutMs: options.recoveryAttemptTimeoutMs,
          signal: options.signal,
          onRecovering: options.onRecovering,
          onRecovered: options.onRecovered
        });
      } catch (error) {
        if (error && error.name === "AbortError") throw error;
        if (!isTransientRecoveryError(error)) throw error;
        break;
      }
      if (typeof options.onUpdate === "function") options.onUpdate(latest);
      var messages = arrayFrom(latest, ["messages", "items", "history"]);
      var assistant = messages.filter(function (item) {
        return item && item.role === "assistant" && (!messageId || item.message_id === messageId);
      }).pop();
      if (assistant && isTerminal(assistant.status)) return latest;
      var remainingPollingMs = pollingTimeoutMs - (Date.now() - startedAt);
      if (remainingPollingMs <= 0) break;
      await wait(Math.min(options.intervalMs || 1500, remainingPollingMs), options.signal);
    }
    try {
      latest = await withRecovery(function (signal) {
        return listMessages(sessionId, Object.assign({}, options.query || {}, { signal: signal }));
      }, {
        timeoutMs: finalReadTimeoutMs,
        attemptTimeoutMs: options.recoveryAttemptTimeoutMs,
        signal: options.signal,
        onRecovering: options.onRecovering,
        onRecovered: options.onRecovered
      });
      if (typeof options.onUpdate === "function") options.onUpdate(latest);
      var finalMessages = arrayFrom(latest, ["messages", "items", "history"]);
      var finalAssistant = finalMessages.filter(function (item) {
        return item && item.role === "assistant" && (!messageId || item.message_id === messageId);
      }).pop();
      if (finalAssistant && isTerminal(finalAssistant.status)) return latest;
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      if (!isTransientRecoveryError(error)) throw error;
    }
    var timeoutError = new Error("处理仍在后台继续，可稍后从会话历史查看结果。");
    timeoutError.status = 504;
    timeoutError.retryable = true;
    timeoutError.userMessage = timeoutError.message;
    throw timeoutError;
  }

  window.MemoryPalaceClient = {
    ids: {
      externalMessage: externalId
    },
    auth: {
      login: login,
      restore: restore,
      logout: logout,
      clear: clearSession,
      current: function () { return session.user; },
      isAuthenticated: function () { return Boolean(session.accessToken); }
    },
    assistant: {
      send: sendAssistantMessage,
      uploadAttachment: uploadAssistantAttachment,
      sessions: listSessions,
      messages: listMessages,
      retry: retryAssistantMessage,
      follow: followMessage
    },
    work: {
      list: listWork,
      task: getWorkTask,
      event: getWorkEvent,
      start: startWorkTask,
      complete: completeWorkTask,
      block: blockWorkTask
    },
    knowledge: {
      sop: getKnowledgeSop
    },
    experience: {
      home: getExperienceHome,
      interview: getExperienceInterview,
      acceptInterview: acceptExperienceInterview,
      answerInterview: answerExperienceInterview,
      pauseInterview: pauseExperienceInterview,
      resumeInterview: resumeExperienceInterview,
      completeInterview: completeExperienceInterview,
      reviseCard: reviseExperienceCard,
      confirmCard: confirmExperienceCard,
      search: searchExperience,
      feedback: sendExperienceFeedback
    },
    simulator: {
      identities: listSimulatorIdentities,
      uploadAttachment: uploadSimulatorAttachment,
      send: sendSimulatorMessage,
      outbox: getSimulatorOutbox
    },
    attachments: {
      content: getAttachmentContent
    },
    recovery: {
      run: withRecovery,
      isTransient: isTransientRecoveryError
    },
    ui: {
      arrayFrom: arrayFrom,
      statusCode: statusCode,
      statusLabel: statusLabel,
      dateLabel: dateLabel,
      escapeHTML: escapeHTML,
      errorView: errorView
    }
  };
}());
