const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");


const simulatorHtml = fs.readFileSync(
  path.resolve(__dirname, "../../static/simulator/wecom/index.html"),
  "utf8"
);
const simulatorScript = fs.readFileSync(
  path.resolve(__dirname, "../../static/simulator/wecom/app.js"),
  "utf8"
);


function memoryStorage(initial) {
  const values = new Map(Object.entries(initial || {}));
  return {
    getItem: function (key) { return values.has(key) ? values.get(key) : null; },
    setItem: function (key, value) { values.set(key, String(value)); },
    removeItem: function (key) { values.delete(key); },
    snapshot: function () { return Object.fromEntries(values.entries()); }
  };
}


class FakeElement {
  constructor(id) {
    this.id = id || "";
    this.attributes = {};
    this.children = [];
    this.className = "";
    this.disabled = false;
    this.files = [];
    this.hidden = false;
    this.innerHTML = "";
    this.listeners = {};
    this.open = false;
    this.parentElement = null;
    this.scrollHeight = 0;
    this.scrollTop = 0;
    this.textContent = "";
    this.value = "";
    this.classList = {
      add: function () {},
      remove: function () {},
      toggle: function () {}
    };
  }

  addEventListener(type, listener) {
    this.listeners[type] = listener;
  }

  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
    return child;
  }

  emit(type, event) {
    if (!this.listeners[type]) return undefined;
    return this.listeners[type](Object.assign({
      target: this,
      preventDefault: function () {}
    }, event || {}));
  }

  focus() {}

  getAttribute(name) {
    return this.attributes[name] || null;
  }

  querySelectorAll() {
    return [];
  }

  remove() {
    if (!this.parentElement) return;
    const index = this.parentElement.children.indexOf(this);
    if (index >= 0) this.parentElement.children.splice(index, 1);
    this.parentElement = null;
  }

  removeAttribute(name) {
    delete this.attributes[name];
  }

  close() {
    this.open = false;
  }

  requestSubmit() {}

  reset() {
    this.value = "";
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  showModal() {
    this.open = true;
  }

  get firstElementChild() {
    return this.children[0] || null;
  }
}


function createSimulatorHarness(options) {
  const elements = new Map();
  const documentListeners = {};
  const windowListeners = {};
  const sessionCalls = [];
  const messageCalls = [];
  const outboxCalls = [];
  const sendCalls = [];
  const experienceCalls = [];
  const storage = memoryStorage(options.storage);

  function element(id) {
    if (!elements.has(id)) elements.set(id, new FakeElement(id));
    return elements.get(id);
  }

  element("simulator-message-stream").innerHTML = "<div>empty</div>";

  const document = {
    addEventListener: function (type, listener) { documentListeners[type] = listener; },
    createElement: function () { return new FakeElement(); },
    getElementById: element
  };
  const ui = {
    arrayFrom: function (payload, keys) {
      for (const key of keys) {
        if (payload && Array.isArray(payload[key])) return payload[key];
      }
      return [];
    },
    dateLabel: function (value) { return "time-" + String(value || 0); },
    errorView: function (error) {
      return {
        title: "请求失败",
        message: error && error.message || "请求失败",
        action: "请重试",
        retryable: true
      };
    },
    escapeHTML: function (value) { return String(value === undefined || value === null ? "" : value); },
    statusCode: function (value) { return String(value || "").toUpperCase(); },
    statusLabel: function (value) { return String(value || "").toUpperCase(); }
  };
  const client = {
    assistant: {
      follow: function () { return Promise.resolve({ messages: [] }); },
      messages: async function (sessionId, requestOptions) {
        messageCalls.push({ sessionId: sessionId, options: requestOptions });
        const session = options.sessions.find(function (item) { return item.session_id === sessionId; });
        return {
          identity: options.identities.find(function (item) { return item.user_id === requestOptions.acting_user_id; }),
          messages: [],
          session: session
        };
      },
      retry: async function () { throw new Error("not used"); },
      sessions: async function (requestOptions) {
        sessionCalls.push(requestOptions);
        return { sessions: options.sessions.slice() };
      }
    },
    attachments: {
      content: async function () { throw new Error("not used"); }
    },
    auth: {
      clear: function () {},
      isAuthenticated: function () { return true; },
      login: async function () { return options.signedUser; },
      logout: async function () {},
      restore: async function () { return options.signedUser; }
    },
    ids: {
      externalMessage: function () { return "message-fixed"; }
    },
    experience: {
      home: async function (requestOptions) {
        experienceCalls.push({ action: "home", options: requestOptions });
        const handler = options.experienceHandlers && options.experienceHandlers.home;
        if (handler) return handler(requestOptions);
        return options.experienceHomeByUser && options.experienceHomeByUser[requestOptions.acting_user_id] || {
          expert: null,
          interviews: [],
          cards: []
        };
      },
      interview: async function (interviewId, requestOptions) {
        experienceCalls.push({ action: "interview", interviewId: interviewId, options: requestOptions });
        const handler = options.experienceHandlers && options.experienceHandlers.interview;
        if (handler) return handler(interviewId, requestOptions);
        return { interview: options.experienceInterviews && options.experienceInterviews[interviewId] };
      },
      acceptInterview: async function (interviewId, requestOptions) {
        experienceCalls.push({ action: "accept", interviewId: interviewId, options: requestOptions });
        const handler = options.experienceHandlers && options.experienceHandlers.accept;
        return handler ? handler(interviewId, requestOptions) : {};
      },
      answerInterview: async function (interviewId, input, requestOptions) {
        experienceCalls.push({ action: "answer", interviewId: interviewId, input: input, options: requestOptions });
        const handler = options.experienceHandlers && options.experienceHandlers.answer;
        return handler ? handler(interviewId, input, requestOptions) : {};
      },
      pauseInterview: async function (interviewId, requestOptions) {
        experienceCalls.push({ action: "pause", interviewId: interviewId, options: requestOptions });
        const handler = options.experienceHandlers && options.experienceHandlers.pause;
        return handler ? handler(interviewId, requestOptions) : {};
      },
      resumeInterview: async function (interviewId, requestOptions) {
        experienceCalls.push({ action: "resume", interviewId: interviewId, options: requestOptions });
        const handler = options.experienceHandlers && options.experienceHandlers.resume;
        return handler ? handler(interviewId, requestOptions) : {};
      },
      completeInterview: async function (interviewId, requestOptions) {
        experienceCalls.push({ action: "complete", interviewId: interviewId, options: requestOptions });
        const handler = options.experienceHandlers && options.experienceHandlers.complete;
        if (handler) return handler(interviewId, requestOptions);
        return { card: options.experienceCards && options.experienceCards[0] };
      },
      reviseCard: async function (cardId, input, requestOptions) {
        experienceCalls.push({ action: "revise", cardId: cardId, input: input, options: requestOptions });
        const handler = options.experienceHandlers && options.experienceHandlers.revise;
        return handler ? handler(cardId, input, requestOptions) : { card: Object.assign({ id: cardId }, input) };
      },
      confirmCard: async function (cardId, requestOptions) {
        experienceCalls.push({ action: "confirm", cardId: cardId, options: requestOptions });
        const handler = options.experienceHandlers && options.experienceHandlers.confirm;
        return handler ? handler(cardId, requestOptions) : { card: { id: cardId, status: "EXPERT_CONFIRMED" } };
      }
    },
    recovery: {
      isTransient: function () { return false; },
      run: async function (operation) {
        return operation(new AbortController().signal);
      }
    },
    simulator: {
      identities: async function () { return { identities: options.identities.slice() }; },
      outbox: async function (sessionId, userId) {
        outboxCalls.push({ sessionId: sessionId, userId: userId });
        return { items: [], session_id: sessionId, user_id: userId };
      },
      send: async function (request) {
        sendCalls.push(request);
        if (!options.sendResponse) throw new Error("not used");
        if (options.sessionAfterSend && !options.sessions.some(function (item) {
          return item.session_id === options.sessionAfterSend.session_id;
        })) {
          options.sessions.push(options.sessionAfterSend);
        }
        return options.sendResponse;
      },
      uploadAttachment: async function () { throw new Error("not used"); }
    },
    ui: ui
  };
  const window = {
    MemoryPalaceClient: client,
    addEventListener: function (type, listener) { windowListeners[type] = listener; },
    history: { replaceState: function () {} },
    location: {
      href: "http://test/simulator/wecom/",
      origin: "http://test"
    },
    requestAnimationFrame: function (callback) { callback(); },
    setTimeout: function () { return 0; }
  };
  vm.runInNewContext(simulatorScript, {
    AbortController: AbortController,
    URL: URL,
    console: console,
    document: document,
    sessionStorage: storage,
    window: window
  }, { filename: "static/simulator/wecom/app.js" });

  return {
    documentListeners: documentListeners,
    element: element,
    experienceCalls: experienceCalls,
    messageCalls: messageCalls,
    outboxCalls: outboxCalls,
    sendCalls: sendCalls,
    sessionCalls: sessionCalls,
    storage: storage,
    windowListeners: windowListeners
  };
}


async function flushAsyncWork() {
  for (let index = 0; index < 12; index += 1) {
    await new Promise(function (resolve) { setImmediate(resolve); });
  }
}


function clickAction(harness, action, attributes) {
  attributes = attributes || {};
  return harness.documentListeners.click({
    target: {
      closest: function (selector) {
        if (selector !== "[data-action]") return null;
        return {
          getAttribute: function (name) {
            if (name === "data-action") return action;
            return attributes[name] || null;
          }
        };
      }
    }
  });
}


test("simulator exposes an explicit employee conversation selector", function () {
  assert.match(simulatorHtml, /id="session-select"/);
  assert.match(simulatorHtml, /id="session-status"[^>]*aria-live="polite"/);
  assert.match(simulatorHtml, /data-action="new-session"/);
});


test("selecting an employee restores the newest isolated WeCom simulator conversation", async function () {
  const harness = createSimulatorHarness({
    signedUser: { id: "manager-1", venue_id: "venue-1", display_name: "值班经理" },
    identities: [
      { user_id: "employee-a", venue_id: "venue-1", display_name: "李明", role: "operator", wecom_binding_status: "ACTIVE" }
    ],
    sessions: [
      { session_id: "a-old", user_id: "employee-a", venue_id: "venue-1", channel: "WECOM_SIMULATOR", external_conversation_id: "conv-a-old", updated_at: 100, created_at: 10, last_message: "较早消息" },
      { session_id: "a-web", user_id: "employee-a", venue_id: "venue-1", channel: "WEB", external_conversation_id: "conv-a-web", updated_at: 400, created_at: 40, last_message: "网页消息" },
      { session_id: "a-new", user_id: "employee-a", venue_id: "venue-1", channel: "WECOM_SIMULATOR", external_conversation_id: "conv-a-new", updated_at: 300, created_at: 30, last_message: "最新企微消息" },
      { session_id: "other-user", user_id: "employee-b", venue_id: "venue-1", channel: "WECOM_SIMULATOR", external_conversation_id: "conv-b", updated_at: 500, created_at: 50, last_message: "其他员工" },
      { session_id: "other-venue", user_id: "employee-a", venue_id: "venue-2", channel: "WECOM_SIMULATOR", external_conversation_id: "conv-v2", updated_at: 600, created_at: 60, last_message: "其他租户" }
    ]
  });
  await flushAsyncWork();

  const identitySelect = harness.element("identity-select");
  identitySelect.value = "employee-a";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();

  assert.equal(harness.sessionCalls.length, 1);
  assert.equal(harness.sessionCalls[0].acting_user_id, "employee-a");
  assert.equal(harness.element("session-select").value, "a-new");
  assert.match(harness.element("session-select").innerHTML, /a-new/);
  assert.match(harness.element("session-select").innerHTML, /a-old/);
  assert.doesNotMatch(harness.element("session-select").innerHTML, /a-web|other-user|other-venue/);
  assert.equal(harness.messageCalls.at(-1).sessionId, "a-new");
  assert.equal(harness.messageCalls.at(-1).options.acting_user_id, "employee-a");
  assert.deepEqual(harness.outboxCalls.at(-1), { sessionId: "a-new", userId: "employee-a" });
});


test("switching employees restores each employee's explicitly selected conversation", async function () {
  const harness = createSimulatorHarness({
    signedUser: { id: "manager-1", venue_id: "venue-1", display_name: "值班经理" },
    identities: [
      { user_id: "employee-a", venue_id: "venue-1", display_name: "李明", role: "operator", wecom_binding_status: "ACTIVE" },
      { user_id: "employee-b", venue_id: "venue-1", display_name: "陈雨", role: "operator", wecom_binding_status: "ACTIVE" }
    ],
    sessions: [
      { session_id: "a-old", user_id: "employee-a", venue_id: "venue-1", channel: "WECOM_SIMULATOR", external_conversation_id: "conv-a-old", updated_at: 100, created_at: 10, last_message: "较早消息" },
      { session_id: "a-new", user_id: "employee-a", venue_id: "venue-1", channel: "WECOM_SIMULATOR", external_conversation_id: "conv-a-new", updated_at: 300, created_at: 30, last_message: "最新消息" },
      { session_id: "b-only", user_id: "employee-b", venue_id: "venue-1", channel: "WECOM_SIMULATOR", external_conversation_id: "conv-b", updated_at: 200, created_at: 20, last_message: "陈雨会话" }
    ]
  });
  await flushAsyncWork();

  const identitySelect = harness.element("identity-select");
  const sessionSelect = harness.element("session-select");
  identitySelect.value = "employee-a";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();

  sessionSelect.value = "a-old";
  sessionSelect.emit("change", { target: sessionSelect });
  await flushAsyncWork();
  assert.equal(harness.messageCalls.at(-1).sessionId, "a-old");

  identitySelect.value = "employee-b";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();
  assert.equal(harness.element("session-select").value, "b-only");

  identitySelect.value = "employee-a";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();
  assert.equal(harness.element("session-select").value, "a-old");
  assert.equal(harness.messageCalls.at(-1).sessionId, "a-old");
  assert.deepEqual(harness.outboxCalls.at(-1), { sessionId: "a-old", userId: "employee-a" });
});


test("refresh reloads the selected employee's simulator conversation list", async function () {
  const options = {
    signedUser: { id: "manager-1", venue_id: "venue-1", display_name: "值班经理" },
    identities: [
      { user_id: "employee-a", venue_id: "venue-1", display_name: "李明", role: "operator", wecom_binding_status: "ACTIVE" }
    ],
    sessions: [
      { session_id: "a-old", user_id: "employee-a", venue_id: "venue-1", channel: "WECOM_SIMULATOR", external_conversation_id: "conv-a-old", updated_at: 100, created_at: 10, last_message: "较早消息" }
    ]
  };
  const harness = createSimulatorHarness(options);
  await flushAsyncWork();

  const identitySelect = harness.element("identity-select");
  identitySelect.value = "employee-a";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();
  assert.equal(harness.sessionCalls.length, 1);

  options.sessions.push({
    session_id: "a-new",
    user_id: "employee-a",
    venue_id: "venue-1",
    channel: "WECOM_SIMULATOR",
    external_conversation_id: "conv-a-new",
    updated_at: 300,
    created_at: 30,
    last_message: "最新消息"
  });
  harness.documentListeners.click({
    target: {
      closest: function (selector) {
        if (selector === "[data-action]") {
          return { getAttribute: function () { return "refresh"; } };
        }
        return null;
      }
    }
  });
  await flushAsyncWork();

  assert.equal(harness.sessionCalls.length, 2);
  assert.match(harness.element("session-select").innerHTML, /a-new/);
  assert.equal(harness.element("session-select").value, "a-old");
});


test("an explicit new-session choice is preserved separately for each employee", async function () {
  const harness = createSimulatorHarness({
    signedUser: { id: "manager-1", venue_id: "venue-1", display_name: "值班经理" },
    identities: [
      { user_id: "employee-a", venue_id: "venue-1", display_name: "李明", role: "operator", wecom_binding_status: "ACTIVE" },
      { user_id: "employee-b", venue_id: "venue-1", display_name: "陈雨", role: "operator", wecom_binding_status: "ACTIVE" }
    ],
    sessions: [
      { session_id: "a-new", user_id: "employee-a", venue_id: "venue-1", channel: "WECOM_SIMULATOR", external_conversation_id: "conv-a-new", updated_at: 300, created_at: 30, last_message: "李明消息" },
      { session_id: "b-only", user_id: "employee-b", venue_id: "venue-1", channel: "WECOM_SIMULATOR", external_conversation_id: "conv-b", updated_at: 200, created_at: 20, last_message: "陈雨消息" }
    ]
  });
  await flushAsyncWork();

  const identitySelect = harness.element("identity-select");
  const sessionSelect = harness.element("session-select");
  identitySelect.value = "employee-a";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();

  sessionSelect.value = "";
  sessionSelect.emit("change", { target: sessionSelect });
  await flushAsyncWork();
  assert.equal(sessionSelect.value, "");

  identitySelect.value = "employee-b";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();
  assert.equal(sessionSelect.value, "b-only");

  identitySelect.value = "employee-a";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();
  assert.equal(sessionSelect.value, "");
  assert.equal(harness.messageCalls.at(-1).sessionId, "b-only");

  const stored = JSON.parse(harness.storage.snapshot().mp_wecom_simulator_context);
  const owner = stored["venue-1:manager-1"];
  assert.equal(owner.selectedUserId, "employee-a");
  assert.equal(owner.employees["employee-a"].newSession, true);
  assert.equal(owner.employees["employee-b"].sessionId, "b-only");
});


test("the first successful message immediately adds its server session to the selector", async function () {
  const createdSession = {
    session_id: "created-session",
    user_id: "employee-a",
    venue_id: "venue-1",
    channel: "WECOM_SIMULATOR",
    external_conversation_id: "created-conversation",
    updated_at: 500,
    created_at: 500,
    last_message: "上报现场问题"
  };
  const harness = createSimulatorHarness({
    signedUser: { id: "manager-1", venue_id: "venue-1", display_name: "值班经理" },
    identities: [
      { user_id: "employee-a", venue_id: "venue-1", display_name: "李明", role: "operator", wecom_binding_status: "ACTIVE" }
    ],
    sessions: [],
    sessionAfterSend: createdSession,
    sendResponse: {
      channel: "WECOM_SIMULATOR",
      status: "QUEUED",
      message_id: "message-1",
      session_id: "created-session",
      external_conversation_id: "created-conversation",
      trace_id: "trace-1",
      created_at: 500
    }
  });
  await flushAsyncWork();

  const identitySelect = harness.element("identity-select");
  identitySelect.value = "employee-a";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();
  assert.equal(harness.sessionCalls.length, 1);

  harness.element("simulator-message-input").value = "上报现场问题";
  await harness.element("simulator-message-form").emit("submit");
  await flushAsyncWork();

  assert.equal(harness.sendCalls.length, 1);
  assert.equal(harness.sessionCalls.length, 2);
  assert.match(harness.element("session-select").innerHTML, /created-session/);
  assert.equal(harness.element("session-select").value, "created-session");
});


test("a restored employee also restores paused interview rounds and refreshes their progress", async function () {
  const interview = {
    id: "interview-1",
    business_id: "INT-001",
    title: "夜间设备异响处置经验",
    status: "PAUSED",
    progress: { answered: 2, total: 4 },
    turns: [
      { turn_number: 1, question_text: "先看什么？", answer_text: "先看告警灯。" },
      { turn_number: 2, question_text: "再听什么？", answer_text: "再听异响位置。" }
    ],
    next_question: "什么情况下必须停机？",
    updated_at: 200,
    created_at: 100
  };
  const harness = createSimulatorHarness({
    signedUser: { id: "manager-1", venue_id: "venue-1", display_name: "值班经理" },
    identities: [
      { user_id: "employee-a", venue_id: "venue-1", display_name: "李明", role: "operator", wecom_binding_status: "ACTIVE" }
    ],
    sessions: [],
    storage: {
      mp_wecom_simulator_context: JSON.stringify({
        "venue-1:manager-1": {
          owner_key: "venue-1:manager-1",
          selectedUserId: "employee-a",
          employees: {
            "employee-a": { sessionId: null, externalConversationId: null, newSession: true }
          }
        }
      })
    },
    experienceHomeByUser: {
      "employee-a": { expert: { user_id: "employee-a" }, interviews: [interview], cards: [] }
    },
    experienceInterviews: { "interview-1": interview }
  });
  await flushAsyncWork();

  assert.equal(harness.sessionCalls.length, 1);
  assert.deepEqual(
    harness.experienceCalls.filter(function (call) { return call.action === "home"; }).map(function (call) {
      return call.options.acting_user_id;
    }),
    ["employee-a"]
  );
  assert.match(harness.element("simulator-message-stream").innerHTML, /2 \/ 4 轮/);

  clickAction(harness, "open-interview", { "data-interview-id": "interview-1" });
  await flushAsyncWork();
  assert.equal(harness.element("interview-dialog").open, true);
  assert.match(harness.element("interview-turns").innerHTML, /先看告警灯/);
  assert.match(harness.element("interview-turns").innerHTML, /再听异响位置/);
  assert.match(harness.element("interview-progress").innerHTML, /已回答 2 \/ 4/);

  interview.progress = { answered: 3, total: 4 };
  interview.turns.push({ turn_number: 3, question_text: "何时停机？", answer_text: "出现焦糊味立即停机。" });
  clickAction(harness, "refresh");
  await flushAsyncWork();
  clickAction(harness, "open-interview", { "data-interview-id": "interview-1" });
  await flushAsyncWork();

  assert.match(harness.element("simulator-message-stream").innerHTML, /3 \/ 4 轮/);
  assert.match(harness.element("interview-turns").innerHTML, /出现焦糊味立即停机/);
  assert.match(harness.element("interview-progress").innerHTML, /已回答 3 \/ 4/);
  for (const call of harness.experienceCalls) {
    assert.equal(call.options.acting_user_id, "employee-a");
  }
});


test("the simulator wires the complete expert interview and draft confirmation controls", async function () {
  const interview = {
    id: "interview-journey",
    title: "高峰期排队处置经验",
    status: "IN_PROGRESS",
    progress: { answered: 3, total: 4 },
    turns: [],
    next_question: "最后确认哪条边界？",
    updated_at: 300
  };
  const card = {
    id: "card-1",
    business_id: "EXP-001",
    title: "高峰期排队处置",
    status: "DRAFT",
    applicable_context: "入口连续排队超过十分钟",
    signals: ["等待人数持续增加"],
    decision_rule: "先分流再增援",
    recommended_actions: ["开放备用入口"],
    rationale: "降低主入口拥堵",
    prohibitions: ["不得跳过安全检查"],
    exceptions: ["消防通道不可占用"],
    source_excerpts: ["先把人流分开"],
    authorization_scopes: [],
    source: { expert_name: "李明", interview_id: "interview-journey" },
    updated_at: 400
  };
  const harness = createSimulatorHarness({
    signedUser: { id: "manager-1", venue_id: "venue-1", display_name: "值班经理" },
    identities: [
      { user_id: "employee-a", venue_id: "venue-1", display_name: "李明", role: "operator", wecom_binding_status: "ACTIVE" }
    ],
    sessions: [],
    experienceHomeByUser: {
      "employee-a": { expert: { user_id: "employee-a" }, interviews: [interview], cards: [card] }
    },
    experienceInterviews: { "interview-journey": interview },
    experienceCards: [card],
    experienceHandlers: {
      complete: function () { return { card: card, extraction: { model: "deepseek-v4-flash" } }; },
      revise: function (cardId, input) { return { card: Object.assign({}, card, input, { id: cardId }) }; },
      confirm: function (cardId) { return { card: Object.assign({}, card, { id: cardId, status: "EXPERT_CONFIRMED" }) }; }
    }
  });
  await flushAsyncWork();

  const identitySelect = harness.element("identity-select");
  identitySelect.value = "employee-a";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();

  clickAction(harness, "open-interview", { "data-interview-id": "interview-journey" });
  await flushAsyncWork();
  clickAction(harness, "accept-interview");
  await flushAsyncWork();
  clickAction(harness, "pause-interview");
  await flushAsyncWork();
  clickAction(harness, "resume-interview");
  await flushAsyncWork();

  harness.element("interview-answer").value = "先分流，再请值班经理增援。";
  harness.element("interview-source-excerpt").value = "先把人流分开";
  await harness.element("interview-answer-form").emit("submit");
  await flushAsyncWork();
  await harness.element("interview-complete-form").emit("submit");
  await flushAsyncWork();

  assert.equal(harness.element("experience-card-dialog").open, true);
  harness.element("experience-card-change-note").value = "补充分流边界";
  await harness.element("experience-card-revise-form").emit("submit");
  await flushAsyncWork();
  clickAction(harness, "confirm-card");
  await flushAsyncWork();
  clickAction(harness, "close-experience-card");
  clickAction(harness, "reload-experience");
  await flushAsyncWork();

  const expectedActions = ["home", "interview", "accept", "pause", "resume", "answer", "complete", "revise", "confirm"];
  for (const action of expectedActions) {
    assert.ok(harness.experienceCalls.some(function (call) { return call.action === action; }), action + " was not called");
  }
  for (const call of harness.experienceCalls) {
    assert.equal(call.options.acting_user_id, "employee-a", call.action + " used the wrong employee identity");
  }
  const answerCall = harness.experienceCalls.find(function (call) { return call.action === "answer"; });
  assert.equal(answerCall.input.answer, "先分流，再请值班经理增援。");
  assert.equal(answerCall.input.source_excerpt, "先把人流分开");
  assert.equal(harness.element("experience-card-dialog").open, false);
});


test("experience submission locks employee identity and restores the selected employee", async function () {
  let resolveComplete;
  const pendingComplete = new Promise(function (resolve) { resolveComplete = resolve; });
  const interview = {
    id: "interview-pending",
    title: "夜间异响处置经验",
    status: "IN_PROGRESS",
    progress: { answered: 4, total: 4 },
    turns: [],
    next_question: null,
    updated_at: 300
  };
  const card = {
    id: "card-pending",
    title: "夜间异响处置",
    status: "DRAFT",
    applicable_context: "夜间巡检",
    signals: ["持续异响"],
    decision_rule: "先停车再检查",
    recommended_actions: ["隔离车辆"],
    rationale: "避免带病运行",
    prohibitions: ["禁止载客试车"],
    exceptions: ["紧急救援除外"],
    source_excerpts: ["先停车再检查"],
    authorization_scopes: [],
    source: { expert_name: "李明", interview_id: "interview-pending" }
  };
  const harness = createSimulatorHarness({
    signedUser: { id: "manager-1", venue_id: "venue-1", display_name: "值班经理" },
    identities: [
      { user_id: "employee-a", venue_id: "venue-1", display_name: "李明", role: "operator", wecom_binding_status: "ACTIVE" },
      { user_id: "employee-b", venue_id: "venue-1", display_name: "陈雨", role: "operator", wecom_binding_status: "ACTIVE" }
    ],
    sessions: [],
    experienceHomeByUser: {
      "employee-a": { expert: { user_id: "employee-a" }, interviews: [interview], cards: [] },
      "employee-b": { expert: { user_id: "employee-b" }, interviews: [], cards: [] }
    },
    experienceInterviews: { "interview-pending": interview },
    experienceHandlers: {
      complete: function () { return pendingComplete; }
    }
  });
  await flushAsyncWork();

  const identitySelect = harness.element("identity-select");
  identitySelect.value = "employee-a";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();
  clickAction(harness, "open-interview", { "data-interview-id": "interview-pending" });
  await flushAsyncWork();

  const submitting = harness.element("interview-complete-form").emit("submit");
  assert.equal(identitySelect.disabled, true);
  identitySelect.value = "employee-b";

  resolveComplete({ card: card, extraction: { model: "deepseek-v4-flash" } });
  await submitting;
  await flushAsyncWork();

  assert.equal(identitySelect.disabled, false);
  assert.equal(identitySelect.value, "employee-a");
});


test("switching employees closes dialogs and ignores stale interview detail", async function () {
  let resolveInterview;
  const pendingInterview = new Promise(function (resolve) { resolveInterview = resolve; });
  const harness = createSimulatorHarness({
    signedUser: { id: "manager-1", venue_id: "venue-1", display_name: "值班经理" },
    identities: [
      { user_id: "employee-a", venue_id: "venue-1", display_name: "李明", role: "operator", wecom_binding_status: "ACTIVE" },
      { user_id: "employee-b", venue_id: "venue-1", display_name: "陈雨", role: "operator", wecom_binding_status: "ACTIVE" }
    ],
    sessions: [],
    experienceHomeByUser: {
      "employee-a": { expert: null, interviews: [], cards: [] },
      "employee-b": { expert: null, interviews: [], cards: [] }
    },
    experienceHandlers: {
      interview: function () { return pendingInterview; }
    }
  });
  await flushAsyncWork();

  const identitySelect = harness.element("identity-select");
  identitySelect.value = "employee-a";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();
  clickAction(harness, "open-interview", { "data-interview-id": "interview-stale" });
  await flushAsyncWork();
  assert.equal(harness.element("interview-dialog").open, true);

  identitySelect.value = "employee-b";
  identitySelect.emit("change", { target: identitySelect });
  await flushAsyncWork();
  resolveInterview({
    interview: {
      id: "interview-stale",
      title: "不应显示的旧访谈",
      status: "PAUSED",
      progress: { answered: 1, total: 4 },
      turns: [{ turn_number: 1, question_text: "旧问题", answer_text: "旧回答" }]
    }
  });
  await flushAsyncWork();

  assert.equal(harness.element("interview-dialog").open, false);
  assert.doesNotMatch(harness.element("interview-turns").innerHTML, /旧回答/);
  clickAction(harness, "accept-interview");
  await flushAsyncWork();
  assert.equal(harness.experienceCalls.filter(function (call) { return call.action === "accept"; }).length, 0);
});
