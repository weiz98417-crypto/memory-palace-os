const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");


function jsonResponse(status, payload) {
  return {
    status: status,
    ok: status >= 200 && status < 300,
    headers: {
      get: function (name) {
        return String(name).toLowerCase() === "content-type"
          ? "application/json"
          : "";
      }
    },
    json: async function () { return payload; },
    text: async function () { return JSON.stringify(payload); },
    blob: async function () { return payload; }
  };
}


function storageWithSession() {
  const values = new Map([
    ["mp_access_token", "access-r0"],
    ["mp_refresh_token", "refresh-r0"],
    ["mp_user", JSON.stringify({ id: "employee-01" })]
  ]);
  return {
    getItem: function (key) { return values.has(key) ? values.get(key) : null; },
    setItem: function (key, value) { values.set(key, String(value)); },
    removeItem: function (key) { values.delete(key); }
  };
}


function loadClient(fetchMock, sessionStorage, authEvents) {
  class CustomEventStub {
    constructor(type, options) {
      this.type = type;
      this.detail = options && options.detail;
    }
  }

  const window = {
    crypto: { randomUUID: function () { return "fixed-uuid"; } },
    dispatchEvent: function (event) { authEvents.push(event); },
    setTimeout: setTimeout,
    clearTimeout: clearTimeout
  };
  const context = {
    AbortController: AbortController,
    CustomEvent: CustomEventStub,
    DOMException: DOMException,
    FormData: FormData,
    Headers: Headers,
    URLSearchParams: URLSearchParams,
    console: console,
    fetch: fetchMock,
    queueMicrotask: queueMicrotask,
    sessionStorage: sessionStorage,
    window: window
  };
  const source = fs.readFileSync(
    path.resolve(__dirname, "../../static/shared/client.js"),
    "utf8"
  );
  vm.runInNewContext(source, context, { filename: "static/shared/client.js" });
  return window.MemoryPalaceClient;
}


test("concurrent 401 responses share one rotating-token refresh", async function () {
  const sessionStorage = storageWithSession();
  const authEvents = [];
  const initialResponses = [];
  const requestTokens = [];
  let dataRequestCount = 0;
  let refreshRequestCount = 0;
  let releaseStaleRefresh;
  const staleRefreshBarrier = new Promise(function (resolve) {
    releaseStaleRefresh = resolve;
  });

  async function fetchMock(url, options) {
    if (String(url).endsWith("/auth/refresh")) {
      refreshRequestCount += 1;
      if (refreshRequestCount === 1) {
        return jsonResponse(200, {
          access_token: "access-r1",
          refresh_token: "refresh-r1",
          user: { id: "employee-01" }
        });
      }
      await staleRefreshBarrier;
      return jsonResponse(401, { detail: { code: "REFRESH_TOKEN_REUSED" } });
    }

    if (String(url).includes("/assistant/sessions")) {
      dataRequestCount += 1;
      requestTokens.push(options.headers.get("Authorization"));
      if (dataRequestCount <= 2) {
        return new Promise(function (resolve) {
          initialResponses.push(resolve);
          if (initialResponses.length === 2) {
            queueMicrotask(function () {
              initialResponses.forEach(function (release) {
                release(jsonResponse(401, { detail: { code: "ACCESS_TOKEN_EXPIRED" } }));
              });
            });
          }
        });
      }
      releaseStaleRefresh();
      return jsonResponse(200, { sessions: [] });
    }

    throw new Error("Unexpected URL: " + url);
  }

  const client = loadClient(fetchMock, sessionStorage, authEvents);

  await Promise.all([
    client.assistant.sessions({ limit: 20 }),
    client.assistant.sessions({ limit: 20 })
  ]);

  assert.equal(refreshRequestCount, 1);
  assert.equal(dataRequestCount, 4);
  assert.deepEqual(requestTokens.slice(2), ["Bearer access-r1", "Bearer access-r1"]);
  assert.equal(sessionStorage.getItem("mp_access_token"), "access-r1");
  assert.equal(sessionStorage.getItem("mp_refresh_token"), "refresh-r1");
  assert.equal(
    authEvents.some(function (event) {
      return event.type === "memory-palace-auth-changed" && !event.detail.authenticated;
    }),
    false
  );
});


test("a stale refresh failure cannot clear a newer login", async function () {
  const sessionStorage = storageWithSession();
  const authEvents = [];
  let releaseRefresh;
  let markRefreshStarted;
  const refreshResponse = new Promise(function (resolve) {
    releaseRefresh = resolve;
  });
  const refreshStarted = new Promise(function (resolve) {
    markRefreshStarted = resolve;
  });

  async function fetchMock(url) {
    if (String(url).includes("/assistant/sessions")) {
      return jsonResponse(401, { detail: { code: "ACCESS_TOKEN_EXPIRED" } });
    }
    if (String(url).endsWith("/auth/refresh")) {
      markRefreshStarted();
      return refreshResponse;
    }
    if (String(url).endsWith("/auth/login")) {
      return jsonResponse(200, {
        access_token: "access-new-login",
        refresh_token: "refresh-new-login",
        user: { id: "employee-02" }
      });
    }
    throw new Error("Unexpected URL: " + url);
  }

  const client = loadClient(fetchMock, sessionStorage, authEvents);
  const staleRequest = client.assistant.sessions({ limit: 20 }).catch(function (error) {
    return error;
  });
  await refreshStarted;
  await client.auth.login("employee-02", "password");
  releaseRefresh(jsonResponse(401, { detail: { code: "REFRESH_TOKEN_REUSED" } }));
  const staleError = await staleRequest;

  assert.equal(staleError.status, 401);
  assert.equal(sessionStorage.getItem("mp_access_token"), "access-new-login");
  assert.equal(sessionStorage.getItem("mp_refresh_token"), "refresh-new-login");
  assert.equal(JSON.parse(sessionStorage.getItem("mp_user")).id, "employee-02");
  assert.equal(authEvents.at(-1).detail.authenticated, true);
});


test("every governed experience request carries the simulated employee identity", async function () {
  const requests = [];
  async function fetchMock(url, options) {
    requests.push({ url: String(url), options: options || {} });
    return jsonResponse(200, { ok: true, card: { id: "card-1" }, interview: { id: "interview-1" } });
  }

  const client = loadClient(fetchMock, storageWithSession(), []);
  const acting = { acting_user_id: "employee-expert-1" };
  await client.experience.home(acting);
  await client.experience.interview("interview-1", acting);
  await client.experience.acceptInterview("interview-1", acting);
  await client.experience.answerInterview("interview-1", {
    answer: "先隔离风险区域",
    source_excerpt: "先把人和设备分开",
    idempotency_key: "answer-fixed"
  }, acting);
  await client.experience.pauseInterview("interview-1", acting);
  await client.experience.resumeInterview("interview-1", acting);
  await client.experience.completeInterview("interview-1", acting);
  await client.experience.reviseCard("card-1", {
    title: "现场风险隔离经验",
    change_note: "补充隔离边界"
  }, acting);
  await client.experience.confirmCard("card-1", acting);
  await client.experience.search({ query: "设备异响", top_k: 3 }, acting);
  await client.experience.feedback("card-1", { feedback: "HELPFUL", note: "现场有效" }, acting);

  assert.equal(requests.length, 11);
  for (const request of requests) {
    const url = new URL(request.url, "http://test");
    assert.equal(url.searchParams.get("acting_user_id"), "employee-expert-1", request.url);
    assert.equal(request.options.headers.get("Authorization"), "Bearer access-r0");
  }
  assert.equal(requests[0].options.method, "GET");
  assert.equal(requests[2].options.method, "POST");
  assert.equal(requests[3].options.headers.get("Idempotency-Key"), "answer-fixed");
  assert.equal(requests[7].options.method, "PUT");
  assert.equal(requests[10].options.method, "POST");
});
