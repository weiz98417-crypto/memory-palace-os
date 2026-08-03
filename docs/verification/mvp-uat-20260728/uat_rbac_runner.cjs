const { execFileSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("C:/Users/Admin/.codex/skills/gstack/browse/node_modules/playwright");

const BASE_URL = process.env.MP_UAT_URL || "http://localhost:8082/admin/";
const APP_CONTAINER = process.env.MP_UAT_APP_CONTAINER || "memory-palace-uat-app-1";
const ADMIN_USERNAME = process.env.MP_UAT_USERNAME || "uat-admin";
const ROOT_DIR = __dirname;
const SCREENSHOT_DIR = path.join(ROOT_DIR, "screenshots");
const EVIDENCE_DIR = path.join(ROOT_DIR, "evidence");
const BROWSER_EXECUTABLE = [
  process.env.MP_UAT_BROWSER_EXECUTABLE,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
].find((candidate) => candidate && fs.existsSync(candidate));
const RUN_SUFFIX = `${Date.now().toString(36)}-${crypto.randomBytes(3).toString("hex")}`.toLowerCase();
const VENUE_ID = `uat-rbac-${RUN_SUFFIX}`;
const VENUE_NAME = `RBAC 验收场地 ${RUN_SUFFIX}`;
const MANAGER_USERNAME = `uat-mgr-${RUN_SUFFIX}`;
const OPERATOR_USERNAME = `uat-op-${RUN_SUFFIX}`;
const EXPECTED_NAVIGATION = {
  admin: ["dashboard", "events", "sessions", "tasks", "approvals", "actions", "knowledge", "persona", "watcher", "sops", "management", "settings", "diagnostics"],
  manager: ["dashboard", "events", "sessions", "tasks", "approvals", "actions", "knowledge", "persona", "watcher", "sops", "settings"],
  operator: ["dashboard", "events", "sessions", "tasks"],
};
const SENSITIVE_VALUES = new Set();

fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
fs.mkdirSync(EVIDENCE_DIR, { recursive: true });

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function randomPassword() {
  const password = `${crypto.randomBytes(24).toString("base64url")}Aa1!`;
  SENSITIVE_VALUES.add(password);
  return password;
}

function getAdminPassword() {
  const password = execFileSync(
    "docker",
    ["exec", APP_CONTAINER, "printenv", "ADMIN_PASSWORD"],
    { encoding: "utf8", windowsHide: true }
  ).trim();
  if (!password) throw new Error("UAT admin password is unavailable in the app container");
  SENSITIVE_VALUES.add(password);
  return password;
}

function redactString(value) {
  let redacted = String(value);
  for (const secret of SENSITIVE_VALUES) {
    if (secret && redacted.includes(secret)) return "[REDACTED]";
  }
  return redacted;
}

function isSensitiveKey(key) {
  return /(?:password(?:_hash)?|access_token|refresh_token|api_key|secret|authorization(?:_header)?)$/i.test(key);
}

function redact(value) {
  if (Array.isArray(value)) return value.map(redact);
  if (typeof value === "string") return redactString(value);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([key, item]) => {
    if (isSensitiveKey(key)) {
      return [key, "[REDACTED]"];
    }
    return [key, redact(item)];
  }));
}

function containsSensitiveValue(value) {
  if (Array.isArray(value)) return value.some(containsSensitiveValue);
  if (typeof value === "string") {
    return Array.from(SENSITIVE_VALUES).some((secret) => secret && value.includes(secret));
  }
  if (!value || typeof value !== "object") return false;
  return Object.values(value).some(containsSensitiveValue);
}

function validateEvidence(filename, value) {
  for (const [name, result] of Object.entries(value.assertions || {})) {
    assert(result === true, `${filename} assertion ${name} must remain boolean true after redaction`);
  }
  for (const [name, credential] of Object.entries(value.credentials || {})) {
    assert(credential === "[REDACTED]", `${filename} credential ${name} must be redacted`);
  }
  assert(!containsSensitiveValue(value), `${filename} contains an unredacted runtime credential`);
}

function writeJson(filename, value) {
  const redactedValue = redact(value);
  validateEvidence(filename, redactedValue);
  fs.writeFileSync(
    path.join(EVIDENCE_DIR, filename),
    `${JSON.stringify(redactedValue, null, 2)}\n`,
    "utf8"
  );
}

function resultCode(result) {
  return result.payload?.detail?.code || result.payload?.code || null;
}

function compactResult(result, extra = {}) {
  return {
    status: result.status,
    ok: result.ok,
    code: resultCode(result),
    trace_id: result.payload?.detail?.trace_id || result.payload?.trace_id || null,
    ...extra,
  };
}

function compactAudit(row) {
  return {
    venue_id: row.venue_id,
    user_id: row.user_id,
    action: row.action,
    resource_type: row.resource_type,
    resource_id: row.resource_id,
    outcome: row.outcome,
    trace_id: row.trace_id,
    metadata: row.metadata || {},
    created_at: row.created_at,
  };
}

function trackPage(page, role) {
  const telemetry = {
    role,
    console_errors: [],
    expected_console_rejections: [],
    expected_http_rejections: [],
    page_errors: [],
    failed_requests: [],
    server_errors: [],
  };
  Object.defineProperty(telemetry, "_expectedRejection", {
    value: null,
    writable: true,
    enumerable: false,
  });
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = redactString(message.text());
    const expected = telemetry._expectedRejection;
    if (expected && (text.includes("Failed to load resource") || expected.statuses.some((status) => text.includes(String(status))))) {
      telemetry.expected_console_rejections.push({ attempt: expected.attempt, message: text });
      return;
    }
    telemetry.console_errors.push(text);
  });
  page.on("pageerror", (error) => telemetry.page_errors.push(redactString(error.message)));
  page.on("requestfailed", (request) => {
    telemetry.failed_requests.push({
      method: request.method(),
      url: request.url(),
      error: redactString(request.failure()?.errorText || "request failed"),
    });
  });
  page.on("response", (response) => {
    const expected = telemetry._expectedRejection;
    if (
      expected
      && expected.statuses.includes(response.status())
      && response.url().includes(expected.urlIncludes)
    ) {
      telemetry.expected_http_rejections.push({
        attempt: expected.attempt,
        method: response.request().method(),
        url: response.url(),
        status: response.status(),
      });
    }
    if (response.status() >= 500) {
      telemetry.server_errors.push({
        method: response.request().method(),
        url: response.url(),
        status: response.status(),
      });
    }
  });
  return telemetry;
}

function responseMatches(response, method, pathname) {
  return response.request().method() === method && new URL(response.url()).pathname === pathname;
}

function beginExpectedRejection(telemetry, { attempt, statuses, urlIncludes }) {
  assert(!telemetry._expectedRejection, `${telemetry.role} already has an expected rejection window`);
  telemetry._expectedRejection = { attempt, statuses, urlIncludes };
}

function endExpectedRejection(telemetry) {
  telemetry._expectedRejection = null;
}

async function apiRequest(page, route, options = {}) {
  const token = await page.evaluate(() => sessionStorage.getItem("mp_access_token") || "");
  assert(token, "authenticated browser context does not contain an access token");
  SENSITIVE_VALUES.add(token);
  const headers = {
    ...(options.headers || {}),
    Authorization: `Bearer ${token}`,
  };
  const requestOptions = { method: options.method || "GET", headers };
  if (options.body !== undefined) requestOptions.data = options.body;
  const response = await page.context().request.fetch(new URL(route, BASE_URL).toString(), requestOptions);
  const contentType = response.headers()["content-type"] || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => ({}))
    : await response.text();
  return { status: response.status(), ok: response.ok(), payload };
}

async function loginThroughUi(page, username, password, expectedRole, expectedVenueId = null) {
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  await page.locator("#login-screen.active").waitFor({ state: "visible" });
  await page.locator("#login-username").fill(username);
  await page.locator("#login-password").fill(password);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      return candidate.request().method() === "POST" && candidate.url().includes("/api/v1/auth/login");
    }),
    page.locator("#login-submit").click(),
  ]);
  assert(response.status() === 200, `${expectedRole} UI login returned HTTP ${response.status()}`);
  await page.locator("#app-screen.active").waitFor({ state: "visible" });
  await page.waitForFunction(() => {
    const user = JSON.parse(sessionStorage.getItem("mp_user") || "null");
    return Boolean(user?.id && document.querySelector("#view-dashboard.active"));
  });
  await page.waitForFunction(() => document.querySelector("#dashboard-updated")?.textContent.includes("更新于"));
  const sessionCredentials = await page.evaluate(() => ({
    accessToken: sessionStorage.getItem("mp_access_token") || "",
    refreshToken: sessionStorage.getItem("mp_refresh_token") || "",
  }));
  if (sessionCredentials.accessToken) SENSITIVE_VALUES.add(sessionCredentials.accessToken);
  if (sessionCredentials.refreshToken) SENSITIVE_VALUES.add(sessionCredentials.refreshToken);
  const identity = await page.evaluate(() => JSON.parse(sessionStorage.getItem("mp_user") || "null"));
  assert(identity?.role === expectedRole, `${expectedRole} UI login restored unexpected role`);
  if (expectedVenueId) assert(identity.venue_id === expectedVenueId, `${expectedRole} UI login restored unexpected venue`);
  return identity;
}

async function rejectLoginThroughUi(page, telemetry, username, password, attempt) {
  await page.locator("#login-screen.active").waitFor({ state: "visible" });
  await page.locator("#login-username").fill(username);
  await page.locator("#login-password").fill(password);
  beginExpectedRejection(telemetry, {
    attempt,
    statuses: [401, 429],
    urlIncludes: "/api/v1/auth/login",
  });
  try {
    const [response] = await Promise.all([
      page.waitForResponse((candidate) => responseMatches(candidate, "POST", "/api/v1/auth/login")),
      page.locator("#login-submit").click(),
    ]);
    const payload = await response.json();
    await page.waitForFunction(() => {
      return Boolean(document.querySelector("#login-screen.active") && document.querySelector("#login-error")?.textContent.trim());
    });
    await page.waitForTimeout(150);
    const errorText = (await page.locator("#login-error").innerText()).trim();
    assert(response.status() === 401, `rejected login attempt ${attempt} returned HTTP ${response.status()} instead of 401`);
    assert(payload?.detail?.code === "AUTH_INVALID_CREDENTIALS", `rejected login attempt ${attempt} returned the wrong error code`);
    assert(errorText.includes("用户名或密码错误"), `rejected login attempt ${attempt} did not render the explicit credential error`);
    return {
      attempt,
      status: response.status(),
      ok: response.ok(),
      code: payload.detail.code,
      trace_id: payload.detail.trace_id,
      error_visible: true,
      error_text: errorText,
    };
  } finally {
    endExpectedRejection(telemetry);
  }
}

async function verifyDashboardConsistency(page, role) {
  await page.locator("#view-dashboard.active").waitFor({ state: "visible" });
  const endpoints = [
    { key: "dashboard", pathname: "/api/v1/admin/dashboard" },
    { key: "tasks", pathname: "/api/v1/admin/tasks" },
    { key: "skills", pathname: "/api/v1/skills" },
  ];
  if (role !== "operator") endpoints.push({ key: "approvals", pathname: "/api/v1/admin/approvals" });
  const responsePromises = endpoints.map((endpoint) => {
    return page.waitForResponse((candidate) => responseMatches(candidate, "GET", endpoint.pathname));
  });
  await page.locator('button[data-action="refresh"]').click();
  const responses = await Promise.all(responsePromises);
  const payloads = {};
  const responseStatuses = {};
  for (let index = 0; index < endpoints.length; index += 1) {
    const response = responses[index];
    assert(response.status() === 200, `${role} dashboard refresh ${endpoints[index].key} returned HTTP ${response.status()}`);
    payloads[endpoints[index].key] = await response.json();
    responseStatuses[endpoints[index].key] = response.status();
  }
  const apiCounts = {
    events: Number(payloads.dashboard.total_memory_count || 0),
    tasks: (payloads.tasks.tasks || []).filter((task) => String(task.status).toUpperCase() !== "DONE").length,
    approvals: role === "operator"
      ? 0
      : (payloads.approvals || []).filter((approval) => String(approval.status).toUpperCase() === "PENDING").length,
    agents: (payloads.skills || []).length,
  };
  await page.waitForFunction((counts) => {
    return Number(document.querySelector("#metric-events")?.textContent) === counts.events
      && Number(document.querySelector("#metric-tasks")?.textContent) === counts.tasks
      && Number(document.querySelector("#metric-approvals")?.textContent) === counts.approvals
      && Number(document.querySelector("#metric-agents")?.textContent) === counts.agents;
  }, apiCounts);
  const uiCounts = await page.evaluate(() => ({
    events: Number(document.querySelector("#metric-events")?.textContent),
    tasks: Number(document.querySelector("#metric-tasks")?.textContent),
    approvals: Number(document.querySelector("#metric-approvals")?.textContent),
    agents: Number(document.querySelector("#metric-agents")?.textContent),
    updated_label: document.querySelector("#dashboard-updated")?.textContent.trim() || "",
  }));
  for (const metric of ["events", "tasks", "approvals", "agents"]) {
    assert(uiCounts[metric] === apiCounts[metric], `${role} dashboard ${metric} metric differs from the same refresh response`);
  }
  assert(uiCounts.updated_label.startsWith("更新于 "), `${role} dashboard refresh did not update its timestamp label`);
  return {
    trigger: "formal client refresh button",
    captured_same_refresh_round: true,
    response_http_statuses: responseStatuses,
    api_counts: apiCounts,
    ui_counts: uiCounts,
  };
}

async function captureWorkspace(page, role, screenshotName) {
  await page.locator("#view-dashboard.active").waitFor({ state: "visible" });
  const workspace = await page.evaluate(() => ({
    identity: JSON.parse(sessionStorage.getItem("mp_user") || "null"),
    account_name: document.querySelector("#account-name")?.textContent.trim() || "",
    account_role: document.querySelector("#account-role")?.textContent.trim() || "",
    tenant_chip: document.querySelector("#tenant-chip")?.textContent.trim() || "",
    active_view: document.querySelector(".view.active")?.id || null,
    dashboard_health_label: document.querySelector("#dashboard-health-label")?.textContent.trim() || "",
    visible_navigation: Array.from(document.querySelectorAll(".nav-item[data-view]:not(.hidden)")).map((item) => ({
      view: item.getAttribute("data-view"),
      label: item.textContent.trim(),
    })),
    hidden_navigation: Array.from(document.querySelectorAll(".nav-item[data-view].hidden")).map((item) => item.getAttribute("data-view")),
  }));
  const actualViews = workspace.visible_navigation.map((item) => item.view);
  assert(JSON.stringify(actualViews) === JSON.stringify(EXPECTED_NAVIGATION[role]), `${role} visible navigation does not match the role contract`);
  assert(workspace.identity?.role === role, `${role} workspace identity mismatch`);
  assert(workspace.active_view === "view-dashboard", `${role} did not land on the dashboard workspace`);
  if (role === "admin") {
    assert(workspace.dashboard_health_label && workspace.dashboard_health_label !== "业务视图", "admin dashboard did not expose health status");
  } else {
    assert(workspace.dashboard_health_label === "业务视图", `${role} dashboard should expose the business workspace instead of admin health`);
  }
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, screenshotName), fullPage: true });
  return workspace;
}

async function openView(page, view) {
  const navigation = page.locator(`.nav-item[data-view="${view}"]`);
  assert(await navigation.isVisible(), `${view} navigation is not visible to the current role`);
  await navigation.click();
  await page.locator(`#view-${view}.active`).waitFor({ state: "visible" });
  await page.waitForTimeout(300);
}

async function createVenueThroughUi(page) {
  await page.locator('[data-action="new-venue"]').click();
  await page.locator("#venue-dialog").waitFor({ state: "visible" });
  await page.locator("#venue-id").fill(VENUE_ID);
  await page.locator("#venue-name").fill(VENUE_NAME);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      return candidate.request().method() === "POST" && candidate.url().endsWith("/api/v1/admin/venues");
    }),
    page.locator('#venue-form button[type="submit"]').click(),
  ]);
  const payload = await response.json();
  assert(response.status() === 201, `UI venue creation returned HTTP ${response.status()}`);
  assert(payload.venue?.id === VENUE_ID, "UI venue creation returned the wrong venue");
  await page.locator("#venue-dialog").waitFor({ state: "hidden" });
  await page.waitForFunction((venueId) => {
    return Array.from(document.querySelectorAll("#venues-table tr")).some((row) => row.textContent.includes(venueId));
  }, VENUE_ID);
  return payload;
}

async function createUserThroughUi(page, { username, displayName, role, password }) {
  await page.locator('[data-action="new-user"]').click();
  await page.locator("#user-dialog").waitFor({ state: "visible" });
  await page.locator("#user-username").fill(username);
  await page.locator("#user-display-name").fill(displayName);
  await page.locator("#user-role").selectOption(role);
  await page.locator("#user-venue").selectOption(VENUE_ID);
  await page.locator("#user-password").fill(password);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      return candidate.request().method() === "POST" && candidate.url().endsWith("/api/v1/admin/users");
    }),
    page.locator('#user-form button[type="submit"]').click(),
  ]);
  const payload = await response.json();
  assert(response.status() === 201, `UI ${role} creation returned HTTP ${response.status()}`);
  assert(payload.user?.username === username, `UI ${role} creation returned the wrong username`);
  assert(payload.user?.role === role, `UI ${role} creation returned the wrong role`);
  assert(payload.user?.venue_id === VENUE_ID, `UI ${role} creation returned the wrong venue`);
  await page.locator("#user-dialog").waitFor({ state: "hidden" });
  await page.waitForFunction((createdUsername) => {
    return Array.from(document.querySelectorAll("#users-table tr")).some((row) => row.textContent.includes(createdUsername));
  }, username);
  return payload;
}

async function fetchAuditByTrace(page, traceId, { action, resourceId, outcome = "SUCCEEDED" }) {
  const result = await apiRequest(
    page,
    `/api/v1/admin/audit-logs?trace_id=${encodeURIComponent(traceId)}&limit=50`
  );
  assert(result.status === 200, `audit lookup for ${traceId} returned HTTP ${result.status}`);
  const audit = (result.payload.audit_logs || []).find((row) => {
    return row.trace_id === traceId
      && row.action === action
      && row.resource_id === resourceId
      && row.outcome === outcome;
  });
  assert(audit, `${action} audit for ${resourceId} and trace ${traceId} was not persisted`);
  return audit;
}

function settingRow(page, settingKey) {
  return page.locator("#settings-list .feed-item").filter({ hasText: settingKey });
}

async function readSetting(page, settingKey) {
  const result = await apiRequest(page, "/api/v1/admin/settings");
  assert(result.status === 200, `settings GET returned HTTP ${result.status}`);
  const setting = (result.payload.settings || []).find((item) => item.key === settingKey);
  assert(setting, `settings GET did not return ${settingKey}`);
  return { result, setting };
}

async function updateSettingThroughUi(page, settingKey, expectedValue) {
  const row = settingRow(page, settingKey);
  assert(await row.isVisible(), `${settingKey} is not visible in the formal settings client`);
  await row.getByRole("button", { name: "修改", exact: true }).click();
  await page.locator("#action-dialog").waitFor({ state: "visible" });
  await page.locator("#action-field-value").fill(String(expectedValue));
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      return responseMatches(candidate, "PUT", `/api/v1/admin/settings/${settingKey}`);
    }),
    page.locator("#action-dialog-submit").click(),
  ]);
  const payload = await response.json();
  assert(response.status() === 200, `UI setting update returned HTTP ${response.status()}`);
  assert(payload.key === settingKey && payload.value === expectedValue, "UI setting update returned an unexpected payload");
  await page.waitForFunction(({ key, value }) => {
    return Array.from(document.querySelectorAll("#settings-list .feed-item")).some((item) => {
      return item.textContent.includes(key) && item.textContent.includes(String(value));
    });
  }, { key: settingKey, value: expectedValue });
  return payload;
}

async function exerciseSettingLifecycle(page) {
  const settingKey = "organization_name";
  await openView(page, "settings");
  const original = await readSetting(page, settingKey);
  assert(original.setting.type === "string", "organization_name is no longer a string setting");
  const modifiedValue = `MVP 联合验收中心 ${RUN_SUFFIX}`;
  let modification = null;
  let modifiedRead = null;
  let modifiedAudit = null;
  let restoration = null;
  let restoredRead = null;
  let restoredAudit = null;
  let restoreRequired = false;
  try {
    restoreRequired = true;
    modification = await updateSettingThroughUi(page, settingKey, modifiedValue);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "MVP-UAT-001-setting-modified-1440x900.png"),
      fullPage: true,
    });
    modifiedRead = await readSetting(page, settingKey);
    assert(modifiedRead.setting.value === modifiedValue, "organization_name GET did not reflect the UI modification");
    modifiedAudit = await fetchAuditByTrace(page, modification.trace_id, {
      action: "SETTING_UPDATED",
      resourceId: settingKey,
    });
  } finally {
    if (restoreRequired) {
      const actionDialog = page.locator("#action-dialog");
      if (await actionDialog.isVisible()) {
        await page.locator('#action-dialog [data-close="action-dialog"]').click();
        await actionDialog.waitFor({ state: "hidden" });
      }
      if (!(await page.locator("#view-settings.active").isVisible())) await openView(page, "settings");
      restoration = await updateSettingThroughUi(page, settingKey, original.setting.value);
      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, "MVP-UAT-001-setting-restored-1440x900.png"),
        fullPage: true,
      });
      restoredRead = await readSetting(page, settingKey);
      assert(restoredRead.setting.value === original.setting.value, "organization_name was not restored through the UI");
      restoredAudit = await fetchAuditByTrace(page, restoration.trace_id, {
        action: "SETTING_UPDATED",
        resourceId: settingKey,
      });
    }
  }
  assert(modification && modifiedRead && modifiedAudit, "setting modification evidence is incomplete");
  assert(restoration && restoredRead && restoredAudit, "setting restoration evidence is incomplete");
  return {
    key: settingKey,
    original_value: original.setting.value,
    modified_value: modifiedValue,
    modification: {
      status: 200,
      trace_id: modification.trace_id,
      get_verified: true,
      audit: compactAudit(modifiedAudit),
    },
    restoration: {
      status: 200,
      trace_id: restoration.trace_id,
      get_verified: true,
      audit: compactAudit(restoredAudit),
    },
  };
}

function userRow(page, username) {
  return page.locator("#users-table tr").filter({ hasText: username });
}

async function toggleUserThroughUi(page, user, targetStatus) {
  const actionLabel = targetStatus === "ACTIVE" ? "启用" : "停用";
  const row = userRow(page, user.username);
  assert(await row.isVisible(), `${user.username} is not visible in the formal user table`);
  await row.getByRole("button", { name: actionLabel, exact: true }).click();
  await page.locator("#action-dialog").waitFor({ state: "visible" });
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      return responseMatches(candidate, "PATCH", `/api/v1/admin/users/${user.id}`);
    }),
    page.locator("#action-dialog-submit").click(),
  ]);
  const payload = await response.json();
  assert(response.status() === 200, `UI user ${actionLabel} returned HTTP ${response.status()}`);
  assert(payload.user?.id === user.id && payload.user?.status === targetStatus, `UI user ${actionLabel} returned the wrong state`);
  await page.waitForFunction(({ userId, status }) => {
    return Boolean(window.App?.state?.users?.some((item) => item.id === userId && item.status === status));
  }, { userId: user.id, status: targetStatus });
  return payload;
}

async function resetPasswordThroughUi(page, user, newPassword) {
  const row = userRow(page, user.username);
  assert(await row.isVisible(), `${user.username} is not visible before password reset`);
  await row.getByRole("button", { name: "重置密码", exact: true }).click();
  await page.locator("#action-dialog").waitFor({ state: "visible" });
  await page.locator("#action-field-password").fill(newPassword);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      return responseMatches(candidate, "POST", `/api/v1/admin/users/${user.id}/reset-password`);
    }),
    page.locator("#action-dialog-submit").click(),
  ]);
  const payload = await response.json();
  assert(response.status() === 200, `UI password reset returned HTTP ${response.status()}`);
  assert(payload.reset === true && payload.trace_id, "UI password reset returned the wrong contract");
  return payload;
}

async function exerciseUserLifecycle(page, user, newPassword) {
  await openView(page, "management");
  const disabled = await toggleUserThroughUi(page, user, "DISABLED");
  const enabled = await toggleUserThroughUi(page, user, "ACTIVE");
  const passwordReset = await resetPasswordThroughUi(page, user, newPassword);
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, "MVP-UAT-001-user-lifecycle-1440x900.png"),
    fullPage: true,
  });
  const listed = await apiRequest(page, `/api/v1/admin/users?venue_id=${encodeURIComponent(user.venue_id)}`);
  assert(listed.status === 200, "user lifecycle verification listing failed");
  const current = (listed.payload.users || []).find((item) => item.id === user.id);
  assert(current?.status === "ACTIVE", "operator was not ACTIVE after the UI lifecycle");
  const disabledAudit = await fetchAuditByTrace(page, disabled.trace_id, {
    action: "USER_UPDATED",
    resourceId: user.id,
  });
  const enabledAudit = await fetchAuditByTrace(page, enabled.trace_id, {
    action: "USER_UPDATED",
    resourceId: user.id,
  });
  const passwordResetAudit = await fetchAuditByTrace(page, passwordReset.trace_id, {
    action: "USER_PASSWORD_RESET",
    resourceId: user.id,
  });
  return {
    user_id: user.id,
    username: user.username,
    final_status: current.status,
    transitions: [
      { target_status: "DISABLED", trace_id: disabled.trace_id, audit: compactAudit(disabledAudit) },
      { target_status: "ACTIVE", trace_id: enabled.trace_id, audit: compactAudit(enabledAudit) },
    ],
    password_reset: {
      status: 200,
      trace_id: passwordReset.trace_id,
      audit: compactAudit(passwordResetAudit),
    },
  };
}

async function ensureTenantResource(page, tenantLabel) {
  const listed = await apiRequest(page, "/api/v1/sessions/?limit=200");
  assert(listed.status === 200 && Array.isArray(listed.payload), `${tenantLabel} session listing failed`);
  if (listed.payload.length) {
    const session = listed.payload.find((item) => item.session_id) || listed.payload[0];
    const detail = await apiRequest(page, `/api/v1/sessions/${encodeURIComponent(session.session_id)}`);
    assert(detail.status === 200, `${tenantLabel} could not read the selected session`);
    return { source: "existing", session: detail.payload };
  }

  const accepted = await apiRequest(page, "/api/v1/messages/", {
    method: "POST",
    body: {
      content: `MVP UAT ${tenantLabel} session boundary probe ${RUN_SUFFIX}`,
      metadata: { uat_id: "MVP-UAT-009", purpose: "tenant-boundary", tenant_label: tenantLabel },
    },
  });
  assert(accepted.status === 202 && accepted.payload?.session_id, `could not create the ${tenantLabel} session fallback`);
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    const detail = await apiRequest(page, `/api/v1/sessions/${encodeURIComponent(accepted.payload.session_id)}`);
    if (detail.status === 200) return { source: "generated", session: detail.payload, message: accepted.payload };
    await page.waitForTimeout(500);
  }
  throw new Error(`${tenantLabel} session fallback was not materialized by the queue worker`);
}

function assertNoRuntimeErrors(telemetry) {
  for (const record of telemetry) {
    assert(record._expectedRejection === null, `${record.role} expected rejection window was not closed`);
    assert(record.console_errors.length === 0, `${record.role} browser recorded console errors: ${JSON.stringify(record.console_errors)}`);
    assert(record.page_errors.length === 0, `${record.role} browser recorded page errors: ${JSON.stringify(record.page_errors)}`);
    assert(record.failed_requests.length === 0, `${record.role} browser recorded failed requests: ${JSON.stringify(record.failed_requests)}`);
    assert(record.server_errors.length === 0, `${record.role} browser recorded HTTP 5xx responses: ${JSON.stringify(record.server_errors)}`);
  }
}

async function main() {
  assert(BROWSER_EXECUTABLE, "No supported local Chromium browser executable is available");
  const adminPassword = getAdminPassword();
  const managerPassword = randomPassword();
  const operatorPassword = randomPassword();
  const operatorNewPassword = randomPassword();
  const browser = await chromium.launch({ headless: true, executablePath: BROWSER_EXECUTABLE });
  const contexts = [];
  const telemetry = [];

  try {
    const adminContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    contexts.push(adminContext);
    const adminPage = await adminContext.newPage();
    const adminTelemetry = trackPage(adminPage, "admin");
    telemetry.push(adminTelemetry);
    const adminIdentity = await loginThroughUi(adminPage, ADMIN_USERNAME, adminPassword, "admin");
    const adminDashboard = await verifyDashboardConsistency(adminPage, "admin");
    const adminWorkspace = await captureWorkspace(
      adminPage,
      "admin",
      "MVP-UAT-001-admin-workspace-1440x900.png"
    );
    const settingLifecycle = await exerciseSettingLifecycle(adminPage);

    await openView(adminPage, "management");
    const venueCreation = await createVenueThroughUi(adminPage);
    const managerCreation = await createUserThroughUi(adminPage, {
      username: MANAGER_USERNAME,
      displayName: `验收经理 ${RUN_SUFFIX}`,
      role: "manager",
      password: managerPassword,
    });
    const operatorCreation = await createUserThroughUi(adminPage, {
      username: OPERATOR_USERNAME,
      displayName: `验收操作员 ${RUN_SUFFIX}`,
      role: "operator",
      password: operatorPassword,
    });
    await adminPage.screenshot({
      path: path.join(SCREENSHOT_DIR, "MVP-UAT-001-admin-management-1440x900.png"),
      fullPage: true,
    });

    const adminVenues = await apiRequest(adminPage, "/api/v1/admin/venues");
    const adminUsers = await apiRequest(
      adminPage,
      `/api/v1/admin/users?venue_id=${encodeURIComponent(VENUE_ID)}`
    );
    assert(adminVenues.status === 200, "admin-only venue API rejected admin");
    assert(adminUsers.status === 200, "admin-only user API rejected admin");
    assert(
      (adminUsers.payload.users || []).some((user) => user.id === managerCreation.user.id),
      "admin user API did not return the UI-created manager"
    );
    assert(
      (adminUsers.payload.users || []).some((user) => user.id === operatorCreation.user.id),
      "admin user API did not return the UI-created operator"
    );

    const tenantAResource = await ensureTenantResource(adminPage, "tenant A");
    const tenantASessionId = tenantAResource.session.session_id;
    const tenantASessionStage = tenantAResource.session.stage;

    const managerContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    contexts.push(managerContext);
    const managerPage = await managerContext.newPage();
    const managerTelemetry = trackPage(managerPage, "manager");
    telemetry.push(managerTelemetry);
    const managerIdentity = await loginThroughUi(
      managerPage,
      MANAGER_USERNAME,
      managerPassword,
      "manager",
      VENUE_ID
    );
    const managerDashboard = await verifyDashboardConsistency(managerPage, "manager");
    const managerWorkspace = await captureWorkspace(
      managerPage,
      "manager",
      "MVP-UAT-001-manager-workspace-1440x900.png"
    );
    assert(
      managerWorkspace.hidden_navigation.includes("management"),
      "manager unexpectedly sees user and venue management"
    );
    assert(
      managerWorkspace.hidden_navigation.includes("diagnostics"),
      "manager unexpectedly sees admin diagnostics"
    );

    const managerVenues = await apiRequest(managerPage, "/api/v1/admin/venues");
    const managerUsers = await apiRequest(managerPage, "/api/v1/admin/users");
    const managerAssignees = await apiRequest(managerPage, "/api/v1/admin/assignees");
    const managerSettings = await apiRequest(managerPage, "/api/v1/admin/settings");
    assert(
      managerVenues.status === 403 && resultCode(managerVenues) === "AUTH_FORBIDDEN",
      "admin-only venue API did not reject manager"
    );
    assert(
      managerUsers.status === 403 && resultCode(managerUsers) === "AUTH_FORBIDDEN",
      "admin-only user API did not reject manager"
    );
    assert(managerAssignees.status === 200, "manager-allowed assignee API rejected manager");
    assert(managerSettings.status === 200, "manager-allowed settings API rejected manager");
    const managerAssigneeIds = new Set(
      (managerAssignees.payload.assignees || []).map((user) => user.id)
    );
    assert(
      managerAssigneeIds.has(managerCreation.user.id)
        && managerAssigneeIds.has(operatorCreation.user.id),
      "manager assignee API did not expose tenant B teammates"
    );
    assert(
      (managerAssignees.payload.assignees || []).every((user) => user.venue_id === VENUE_ID),
      "manager assignee API leaked another venue"
    );

    const tenantBResource = await ensureTenantResource(managerPage, "tenant B");
    const tenantBSessionId = tenantBResource.session.session_id;
    const tenantBSessionStage = tenantBResource.session.stage;

    const tenantBReadA = await apiRequest(
      managerPage,
      `/api/v1/sessions/${encodeURIComponent(tenantASessionId)}`
    );
    assert(tenantBReadA.status === 404, "tenant B manager could read tenant A session");
    const tenantBDeleteATraceId = `mvp-uat-009-b-to-a-${RUN_SUFFIX}`;
    const tenantBDeleteA = await apiRequest(
      managerPage,
      `/api/v1/sessions/${encodeURIComponent(tenantASessionId)}`,
      {
        method: "DELETE",
        headers: { "X-Trace-ID": tenantBDeleteATraceId },
      }
    );
    assert(tenantBDeleteA.status === 404, "tenant B manager could modify tenant A session");
    assert(
      resultCode(tenantBDeleteA) === "SESSION_NOT_FOUND",
      "tenant B to A modification returned the wrong denial contract"
    );
    assert(
      tenantBDeleteA.payload?.detail?.trace_id === tenantBDeleteATraceId,
      "tenant B to A denial did not preserve the requested trace ID"
    );
    const tenantBDeleteAAudit = await fetchAuditByTrace(managerPage, tenantBDeleteATraceId, {
      action: "SESSION_CLOSE_DENIED",
      resourceId: tenantASessionId,
      outcome: "DENIED",
    });
    assert(
      tenantBDeleteAAudit.venue_id === VENUE_ID
        && tenantBDeleteAAudit.user_id === managerIdentity.id,
      "tenant B to A denial audit has the wrong tenant or actor"
    );

    const invalidTraceInput = "..\\..\\session-id";
    const invalidTrace = await apiRequest(
      managerPage,
      `/api/v1/admin/traces/${encodeURIComponent(invalidTraceInput)}`
    );
    assert(invalidTrace.status === 422, "invalid trace path did not return HTTP 422");
    assert(
      resultCode(invalidTrace) === "REQUEST_VALIDATION_FAILED",
      "invalid trace path did not return the validation error contract"
    );

    const invalidSessionInput = `..\\..\\${tenantASessionId}`;
    const invalidSessionRead = await apiRequest(
      managerPage,
      `/api/v1/sessions/${encodeURIComponent(invalidSessionInput)}`
    );
    assert(invalidSessionRead.status === 404, "invalid session read did not return HTTP 404");
    const invalidSessionDeleteTraceId = `mvp-uat-009-invalid-session-${RUN_SUFFIX}`;
    const invalidSessionDelete = await apiRequest(
      managerPage,
      `/api/v1/sessions/${encodeURIComponent(invalidSessionInput)}`,
      {
        method: "DELETE",
        headers: { "X-Trace-ID": invalidSessionDeleteTraceId },
      }
    );
    assert(invalidSessionDelete.status === 404, "invalid session delete did not return HTTP 404");
    assert(
      resultCode(invalidSessionDelete) === "SESSION_NOT_FOUND",
      "invalid session delete returned the wrong denial contract"
    );
    const invalidSessionDeleteAudit = await fetchAuditByTrace(
      managerPage,
      invalidSessionDeleteTraceId,
      {
        action: "SESSION_CLOSE_DENIED",
        resourceId: invalidSessionInput,
        outcome: "DENIED",
      }
    );
    assert(
      invalidSessionDeleteAudit.venue_id === VENUE_ID
        && invalidSessionDeleteAudit.user_id === managerIdentity.id,
      "invalid session denial audit has the wrong tenant or actor"
    );

    const tenantAReadB = await apiRequest(
      adminPage,
      `/api/v1/sessions/${encodeURIComponent(tenantBSessionId)}`
    );
    assert(tenantAReadB.status === 404, "tenant A admin could read tenant B session");
    const tenantADeleteBTraceId = `mvp-uat-009-a-to-b-${RUN_SUFFIX}`;
    const tenantADeleteB = await apiRequest(
      adminPage,
      `/api/v1/sessions/${encodeURIComponent(tenantBSessionId)}`,
      {
        method: "DELETE",
        headers: { "X-Trace-ID": tenantADeleteBTraceId },
      }
    );
    assert(tenantADeleteB.status === 404, "tenant A admin could modify tenant B session");
    assert(
      resultCode(tenantADeleteB) === "SESSION_NOT_FOUND",
      "tenant A to B modification returned the wrong denial contract"
    );
    assert(
      tenantADeleteB.payload?.detail?.trace_id === tenantADeleteBTraceId,
      "tenant A to B denial did not preserve the requested trace ID"
    );
    const tenantADeleteBAudit = await fetchAuditByTrace(adminPage, tenantADeleteBTraceId, {
      action: "SESSION_CLOSE_DENIED",
      resourceId: tenantBSessionId,
      outcome: "DENIED",
    });
    assert(
      tenantADeleteBAudit.venue_id === adminIdentity.venue_id
        && tenantADeleteBAudit.user_id === adminIdentity.id,
      "tenant A to B denial audit was not persisted in the formal admin tenant"
    );

    const tenantAResourceAfter = await apiRequest(
      adminPage,
      `/api/v1/sessions/${encodeURIComponent(tenantASessionId)}`
    );
    assert(tenantAResourceAfter.status === 200, "tenant A session disappeared after denials");
    assert(
      tenantAResourceAfter.payload.stage === tenantASessionStage,
      "tenant A session changed after cross-tenant or invalid-path denials"
    );
    const tenantBResourceAfter = await apiRequest(
      managerPage,
      `/api/v1/sessions/${encodeURIComponent(tenantBSessionId)}`
    );
    assert(tenantBResourceAfter.status === 200, "tenant B session disappeared after tenant A denial");
    assert(
      tenantBResourceAfter.payload.stage === tenantBSessionStage,
      "tenant B session changed after tenant A denial"
    );

    const tenantBSessionList = await apiRequest(managerPage, "/api/v1/sessions/?limit=200");
    assert(tenantBSessionList.status === 200, "tenant B session listing failed");
    assert(
      !(tenantBSessionList.payload || []).some(
        (session) => session.session_id === tenantASessionId
      ),
      "tenant B session listing leaked tenant A resource"
    );
    assert(
      (tenantBSessionList.payload || []).some(
        (session) => session.session_id === tenantBSessionId
      ),
      "tenant B session listing omitted its own resource"
    );
    await openView(managerPage, "sessions");
    const tenantBSessionTable = await managerPage.locator("#sessions-table").innerText();
    assert(
      !tenantBSessionTable.includes(tenantASessionId),
      "tenant B session workspace rendered tenant A resource"
    );
    assert(
      tenantBSessionTable.includes(tenantBSessionId),
      "tenant B session workspace omitted its own resource"
    );
    await managerPage.screenshot({
      path: path.join(
        SCREENSHOT_DIR,
        "MVP-UAT-009-tenant-b-session-boundary-1440x900.png"
      ),
      fullPage: true,
    });

    const operatorContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    contexts.push(operatorContext);
    const operatorPage = await operatorContext.newPage();
    const operatorTelemetry = trackPage(operatorPage, "operator");
    telemetry.push(operatorTelemetry);
    const operatorIdentity = await loginThroughUi(
      operatorPage,
      OPERATOR_USERNAME,
      operatorPassword,
      "operator",
      VENUE_ID
    );
    const operatorDashboard = await verifyDashboardConsistency(operatorPage, "operator");
    const operatorWorkspace = await captureWorkspace(
      operatorPage,
      "operator",
      "MVP-UAT-001-operator-workspace-1440x900.png"
    );
    assert(
      operatorWorkspace.hidden_navigation.includes("approvals"),
      "operator unexpectedly sees approvals"
    );
    assert(
      operatorWorkspace.hidden_navigation.includes("settings"),
      "operator unexpectedly sees settings"
    );

    const operatorVenues = await apiRequest(operatorPage, "/api/v1/admin/venues");
    const operatorAssignees = await apiRequest(operatorPage, "/api/v1/admin/assignees");
    const operatorSettings = await apiRequest(operatorPage, "/api/v1/admin/settings");
    const operatorAudits = await apiRequest(
      operatorPage,
      "/api/v1/admin/audit-logs?limit=10"
    );
    assert(
      operatorVenues.status === 403 && resultCode(operatorVenues) === "AUTH_FORBIDDEN",
      "admin-only venue API did not reject operator"
    );
    assert(
      operatorAssignees.status === 403 && resultCode(operatorAssignees) === "AUTH_FORBIDDEN",
      "manager-allowed assignee API did not reject operator"
    );
    assert(
      operatorSettings.status === 403 && resultCode(operatorSettings) === "AUTH_FORBIDDEN",
      "manager-allowed settings API did not reject operator"
    );
    assert(
      operatorAudits.status === 403 && resultCode(operatorAudits) === "AUTH_FORBIDDEN",
      "manager-only audit API did not reject operator"
    );

    const userLifecycle = await exerciseUserLifecycle(
      adminPage,
      operatorCreation.user,
      operatorNewPassword
    );

    const rejectedLoginContext = await browser.newContext({
      viewport: { width: 1440, height: 900 },
    });
    contexts.push(rejectedLoginContext);
    const rejectedLoginPage = await rejectedLoginContext.newPage();
    const rejectedLoginTelemetry = trackPage(
      rejectedLoginPage,
      "operator-old-password-rejections"
    );
    telemetry.push(rejectedLoginTelemetry);
    await rejectedLoginPage.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    const rejectedLogins = [];
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      rejectedLogins.push(
        await rejectLoginThroughUi(
          rejectedLoginPage,
          rejectedLoginTelemetry,
          OPERATOR_USERNAME,
          operatorPassword,
          attempt
        )
      );
    }
    await rejectedLoginPage.screenshot({
      path: path.join(
        SCREENSHOT_DIR,
        "MVP-UAT-009-login-rejected-1440x900.png"
      ),
      fullPage: true,
    });
    assert(
      rejectedLogins.every(
        (attempt) => attempt.status === 401
          && attempt.code === "AUTH_INVALID_CREDENTIALS"
          && attempt.error_visible === true
      ),
      "three rejected formal-client logins did not preserve the explicit 401 contract"
    );
    assert(
      rejectedLoginTelemetry.expected_http_rejections.length === 3,
      "browser telemetry did not classify all three login 401 responses as expected"
    );
    assert(
      rejectedLoginTelemetry.expected_http_rejections.every(
        (entry) => entry.status === 401
      ),
      "login rejection telemetry observed an unexpected HTTP status"
    );

    const operatorNewPasswordContext = await browser.newContext({
      viewport: { width: 1440, height: 900 },
    });
    contexts.push(operatorNewPasswordContext);
    const operatorNewPasswordPage = await operatorNewPasswordContext.newPage();
    const operatorNewPasswordTelemetry = trackPage(
      operatorNewPasswordPage,
      "operator-new-password"
    );
    telemetry.push(operatorNewPasswordTelemetry);
    const operatorNewPasswordIdentity = await loginThroughUi(
      operatorNewPasswordPage,
      OPERATOR_USERNAME,
      operatorNewPassword,
      "operator",
      VENUE_ID
    );
    assert(
      operatorNewPasswordIdentity.id === operatorIdentity.id,
      "new operator password authenticated a different account"
    );

    const venueAudit = await fetchAuditByTrace(adminPage, venueCreation.trace_id, {
      action: "VENUE_CREATED",
      resourceId: VENUE_ID,
    });
    const managerAudit = await fetchAuditByTrace(adminPage, managerCreation.trace_id, {
      action: "USER_CREATED",
      resourceId: managerCreation.user.id,
    });
    const operatorAudit = await fetchAuditByTrace(adminPage, operatorCreation.trace_id, {
      action: "USER_CREATED",
      resourceId: operatorCreation.user.id,
    });

    const authenticationAudits = await apiRequest(
      managerPage,
      "/api/v1/admin/audit-logs?action=AUTH_LOGIN&limit=500"
    );
    assert(authenticationAudits.status === 200, "manager could not read tenant B login audits");
    const authenticationRows = authenticationAudits.payload.audit_logs || [];
    const managerLoginAudit = authenticationRows.find(
      (row) => row.user_id === managerIdentity.id && row.outcome === "SUCCEEDED"
    );
    const operatorLoginAudits = authenticationRows.filter(
      (row) => row.user_id === operatorIdentity.id && row.outcome === "SUCCEEDED"
    );
    const rejectedTraceIds = new Set(rejectedLogins.map((attempt) => attempt.trace_id));
    const rejectedLoginAudits = authenticationRows.filter(
      (row) => row.user_id === operatorIdentity.id
        && row.action === "AUTH_LOGIN"
        && row.outcome === "DENIED"
        && rejectedTraceIds.has(row.trace_id)
    );
    assert(managerLoginAudit, "manager UI login is missing its persisted audit record");
    assert(
      operatorLoginAudits.length >= 2,
      "operator old-password and new-password UI logins are not both audited"
    );
    assert(
      rejectedLoginAudits.length === 3
        && new Set(rejectedLoginAudits.map((row) => row.trace_id)).size === 3,
      "manager did not observe three distinct denied login audits"
    );

    assertNoRuntimeErrors(telemetry);

    const generatedAt = new Date().toISOString();
    const credentials = {
      admin_password: "[REDACTED]",
      manager_password: "[REDACTED]",
      operator_old_password: "[REDACTED]",
      operator_new_password: "[REDACTED]",
    };
    const roleEvidence = {
      uat_id: "MVP-UAT-001",
      name: "登录、角色与工作台",
      result: "PASS",
      generated_at: generatedAt,
      run_suffix: RUN_SUFFIX,
      base_url: BASE_URL,
      credentials,
      fixture: {
        venue: venueCreation.venue,
        users: [managerCreation.user, operatorCreation.user],
        creation_http_statuses: { venue: 201, manager: 201, operator: 201 },
      },
      role_workspaces: {
        admin: adminWorkspace,
        manager: managerWorkspace,
        operator: operatorWorkspace,
      },
      dashboard_consistency: {
        admin: adminDashboard,
        manager: managerDashboard,
        operator: operatorDashboard,
      },
      settings_lifecycle: settingLifecycle,
      user_management_lifecycle: userLifecycle,
      password_login_gate: {
        old_password_rejected_attempts: rejectedLogins.map((attempt) => ({
          attempt: attempt.attempt,
          status: attempt.status,
          code: attempt.code,
          trace_id: attempt.trace_id,
          error_visible: attempt.error_visible,
        })),
        new_password_login: {
          status: 200,
          identity: operatorNewPasswordIdentity,
          login_verified: true,
        },
      },
      api_matrix: [
        {
          capability: "admin-only venue administration",
          endpoint: "GET /api/v1/admin/venues",
          admin: compactResult(adminVenues, {
            venue_present: (adminVenues.payload.venues || []).some(
              (venue) => venue.id === VENUE_ID
            ),
          }),
          manager: compactResult(managerVenues),
          operator: compactResult(operatorVenues),
        },
        {
          capability: "manager-allowed assignee lookup",
          endpoint: "GET /api/v1/admin/assignees",
          manager: compactResult(managerAssignees, {
            tenant_only: true,
            assignee_count: (managerAssignees.payload.assignees || []).length,
          }),
          operator: compactResult(operatorAssignees),
        },
        {
          capability: "manager-readable settings",
          endpoint: "GET /api/v1/admin/settings",
          manager: compactResult(managerSettings, {
            setting_count: (managerSettings.payload.settings || []).length,
          }),
          operator: compactResult(operatorSettings),
        },
        {
          capability: "manager-readable audit logs",
          endpoint: "GET /api/v1/admin/audit-logs",
          operator: compactResult(operatorAudits),
        },
      ],
      audits: {
        ui_fixture_creation: [venueAudit, managerAudit, operatorAudit].map(compactAudit),
        successful_role_logins: [
          managerLoginAudit,
          ...operatorLoginAudits.slice(0, 2),
        ].map(compactAudit),
        denied_old_password_logins: rejectedLoginAudits.map(compactAudit),
      },
      screenshots: [
        "screenshots/MVP-UAT-001-admin-workspace-1440x900.png",
        "screenshots/MVP-UAT-001-admin-management-1440x900.png",
        "screenshots/MVP-UAT-001-manager-workspace-1440x900.png",
        "screenshots/MVP-UAT-001-operator-workspace-1440x900.png",
        "screenshots/MVP-UAT-001-setting-modified-1440x900.png",
        "screenshots/MVP-UAT-001-setting-restored-1440x900.png",
        "screenshots/MVP-UAT-001-user-lifecycle-1440x900.png",
      ],
      runtime: { telemetry },
      assertions: {
        admin_created_unique_venue_through_ui: true,
        admin_created_manager_and_operator_through_ui: true,
        all_passwords_runtime_random_and_redacted: true,
        all_three_roles_logged_in_through_formal_ui: true,
        all_three_dashboards_match_same_round_api_responses: true,
        role_navigation_and_dashboard_differences_verified: true,
        organization_setting_modified_verified_audited_and_restored_through_ui: true,
        operator_disabled_enabled_and_password_reset_through_ui: true,
        user_updates_and_password_reset_audited: true,
        old_password_rejected_and_new_password_login_succeeded: true,
        admin_only_api_enforced: true,
        manager_allowed_operator_denied_api_enforced: true,
        creation_and_login_audits_persisted: true,
        browser_console_page_request_and_5xx_errors_zero: true,
      },
    };

    const tenantEvidence = {
      uat_id: "MVP-UAT-009",
      name: "多租户与安全边界",
      result: "PASS",
      generated_at: generatedAt,
      run_suffix: RUN_SUFFIX,
      base_url: BASE_URL,
      credentials,
      login_rejections: {
        attempts: rejectedLogins,
        denied_audits: rejectedLoginAudits.map(compactAudit),
        explicit_rejection_observed: true,
        rate_limit_observed: false,
        expected_http_rejection_count:
          rejectedLoginTelemetry.expected_http_rejections.length,
        expected_console_rejection_count:
          rejectedLoginTelemetry.expected_console_rejections.length,
      },
      tenant_a: {
        venue_id: adminIdentity.venue_id,
        resource: {
          type: "session",
          id: tenantASessionId,
          source: tenantAResource.source,
          stage_before: tenantASessionStage,
          stage_after: tenantAResourceAfter.payload.stage,
        },
      },
      tenant_b: {
        venue_id: VENUE_ID,
        actor: {
          id: managerIdentity.id,
          username: managerIdentity.username,
          role: managerIdentity.role,
        },
        resource: {
          type: "session",
          id: tenantBSessionId,
          source: tenantBResource.source,
          stage_before: tenantBSessionStage,
          stage_after: tenantBResourceAfter.payload.stage,
        },
      },
      boundary_checks: {
        tenant_b_list_excludes_tenant_a_resource: true,
        tenant_b_list_includes_own_resource: true,
        tenant_b_to_tenant_a: {
          read: compactResult(tenantBReadA),
          modify: compactResult(tenantBDeleteA),
          denial_audit: compactAudit(tenantBDeleteAAudit),
        },
        tenant_a_to_tenant_b: {
          read: compactResult(tenantAReadB),
          modify: compactResult(tenantADeleteB),
          denial_audit: compactAudit(tenantADeleteBAudit),
        },
        tenant_a_resource_unchanged: true,
        tenant_b_resource_unchanged: true,
      },
      invalid_paths: {
        trace: {
          input: invalidTraceInput,
          result: compactResult(invalidTrace),
        },
        session: {
          input: invalidSessionInput,
          read: compactResult(invalidSessionRead),
          modify: compactResult(invalidSessionDelete),
          denial_audit: compactAudit(invalidSessionDeleteAudit),
        },
      },
      screenshots: [
        "screenshots/MVP-UAT-009-tenant-b-session-boundary-1440x900.png",
        "screenshots/MVP-UAT-009-login-rejected-1440x900.png",
      ],
      runtime: { telemetry },
      assertions: {
        three_consecutive_old_password_logins_explicitly_rejected: true,
        rejected_logins_have_three_denied_audits: true,
        login_specific_rate_limit_not_claimed: true,
        tenant_b_cannot_list_read_or_modify_tenant_a_resource: true,
        tenant_a_cannot_read_or_modify_tenant_b_resource: true,
        both_cross_tenant_denials_have_matching_trace_and_tenant_audits: true,
        formal_admin_tenant_contains_release_gate_denial_audit: true,
        invalid_trace_path_rejected_by_validation: true,
        invalid_session_path_read_and_modify_rejected: true,
        invalid_session_modify_has_matching_denial_audit: true,
        tenant_a_and_tenant_b_resources_remain_unchanged: true,
        browser_console_page_request_and_5xx_errors_zero: true,
      },
    };

    writeJson("MVP-UAT-001-role-workspaces.json", roleEvidence);
    writeJson("MVP-UAT-009-tenant-authz.json", tenantEvidence);
    process.stdout.write(`${JSON.stringify({
      result: "PASS",
      run_suffix: RUN_SUFFIX,
      venue_id: VENUE_ID,
      roles: ["admin", "manager", "operator"],
      role_evidence: "evidence/MVP-UAT-001-role-workspaces.json",
      tenant_evidence: "evidence/MVP-UAT-009-tenant-authz.json",
      screenshot_count: 9,
      expected_login_rejection_count: 3,
      runtime_error_count: 0,
    }, null, 2)}\n`);
  } finally {
    for (const context of contexts.reverse()) await context.close();
    await browser.close();
  }
}
main().catch((error) => {
  process.stderr.write(`${error.name}: ${redactString(error.message)}\n`);
  process.exitCode = 1;
});
