const { execFileSync } = require("node:child_process");
const { randomUUID } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("C:/Users/Admin/.codex/skills/gstack/browse/node_modules/playwright");

const BASE_URL = process.env.MP_UAT_URL || "http://localhost:8082/admin/";
const APP_CONTAINER = process.env.MP_UAT_APP_CONTAINER || "memory-palace-uat-app-1";
const USERNAME = process.env.MP_UAT_USERNAME || "uat-admin";
const MODE = process.argv[2] || "inspect";
const TARGET = process.argv[3] || "";
const ROOT_DIR = __dirname;
const SCREENSHOT_DIR = path.join(ROOT_DIR, "screenshots");
const EVIDENCE_DIR = path.join(ROOT_DIR, "evidence");

fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
fs.mkdirSync(EVIDENCE_DIR, { recursive: true });

function getAdminPassword() {
  const password = execFileSync(
    "docker",
    ["exec", APP_CONTAINER, "printenv", "ADMIN_PASSWORD"],
    { encoding: "utf8", windowsHide: true }
  ).trim();
  if (!password) throw new Error("UAT admin password is unavailable in the app container");
  return password;
}

function writeJson(filename, value) {
  fs.writeFileSync(path.join(EVIDENCE_DIR, filename), `${JSON.stringify(redact(value), null, 2)}\n`, "utf8");
}

function redact(value) {
  if (Array.isArray(value)) return value.map(redact);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([key, item]) => {
    if (/password|access_token|refresh_token|api_key|secret/i.test(key)) return [key, "[REDACTED]"];
    return [key, redact(item)];
  }));
}

function sameId(left, right) {
  return left !== null && left !== undefined && right !== null && right !== undefined && String(left) === String(right);
}

async function apiFromPage(page, route) {
  return page.evaluate(async (url) => {
    const token = sessionStorage.getItem("mp_access_token");
    const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    const payload = await response.json();
    if (!response.ok) throw new Error(`GET ${url} returned HTTP ${response.status}`);
    return payload;
  }, route);
}

async function loginWithCredentials(page, username, password) {
  await page.goto(BASE_URL, { waitUntil: "networkidle" });
  await page.locator("#login-username").fill(username);
  await page.locator("#login-password").fill(password);
  const [response] = await Promise.all([
    page.waitForResponse((response) => response.url().includes("/api/v1/auth/login")),
    page.locator("#login-form button[type=submit]").click(),
  ]);
  if (!response.ok()) throw new Error(`UAT login returned HTTP ${response.status()}`);
  await page.waitForFunction(() => {
    return Boolean(sessionStorage.getItem("mp_access_token")) && document.querySelectorAll("[data-view]").length > 0;
  });
}

async function login(page) {
  await loginWithCredentials(page, USERNAME, getAdminPassword());
}

async function inspectClient(page, runtime) {
  const clientMap = await page.evaluate(() => ({
    title: document.title,
    visibleView: document.querySelector(".view.active")?.id || null,
    navigation: Array.from(document.querySelectorAll("[data-view]")).map((element) => ({
      view: element.getAttribute("data-view"),
      text: element.textContent.trim(),
      tag: element.tagName,
    })),
    dialogs: Array.from(document.querySelectorAll("dialog")).map((dialog) => ({
      id: dialog.id,
      title: dialog.querySelector("h1,h2,h3")?.textContent.trim() || "",
    })),
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "client-inspection-1440x900.png"), fullPage: true });
  writeJson("client-map.json", { ...clientMap, runtime });
  return clientMap;
}

async function inspectView(page, view, runtime) {
  if (!view) throw new Error("view-inspect requires a view name");
  await openView(page, view);
  const map = await page.locator(`#view-${view}`).evaluate((element) => ({
    heading: element.querySelector("h1,h2")?.textContent.trim() || "",
    text: element.innerText,
    buttons: Array.from(element.querySelectorAll("button")).map((button) => ({
      text: button.textContent.trim(),
      disabled: button.disabled,
      action: button.getAttribute("data-action"),
      onclick: button.getAttribute("onclick"),
    })),
    fields: Array.from(element.querySelectorAll("input,textarea,select")).map((field) => ({
      id: field.id,
      name: field.name,
      type: field.type,
      placeholder: field.placeholder,
      value: field.value,
      required: field.required,
      options: field.tagName === "SELECT" ? Array.from(field.options).map((option) => ({ value: option.value, text: option.textContent.trim() })) : [],
    })),
    rows: Array.from(element.querySelectorAll("tr")).map((row) => row.innerText.trim()).filter(Boolean),
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, `view-${view}-inspection-1440x900.png`), fullPage: true });
  writeJson(`view-${view}-map.json`, { ...map, runtime });
  return map;
}

async function openView(page, view) {
  await page.locator(`[data-view="${view}"]`).click();
  await page.locator(`#view-${view}`).waitFor({ state: "visible" });
  await page.waitForTimeout(500);
}

async function inspectTasks(page, runtime) {
  await openView(page, "tasks");
  await page.locator('[data-action="decompose-task"]').click();
  await page.locator("#task-decompose-dialog").waitFor({ state: "visible" });
  const taskMap = await page.evaluate(() => ({
    sessions: Array.from(document.querySelectorAll("#task-decompose-session option")).map((option) => ({
      value: option.value,
      text: option.textContent.trim(),
    })),
    assignees: Array.from(document.querySelectorAll("#task-decompose-assignee option")).map((option) => ({
      value: option.value,
      text: option.textContent.trim(),
    })),
    taskRows: Array.from(document.querySelectorAll("#tasks-table tr")).map((row) => row.innerText.trim()).filter(Boolean),
    taskButtons: Array.from(document.querySelectorAll("#view-tasks button")).map((button) => ({
      text: button.textContent.trim(),
      disabled: button.disabled,
    })),
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "tasks-decompose-dialog-1440x900.png"), fullPage: true });
  writeJson("tasks-client-map.json", { ...taskMap, runtime });
  return taskMap;
}

async function decomposeTodo(page, runtime) {
  await openView(page, "tasks");
  await page.locator('[data-action="decompose-task"]').click();
  await page.locator("#task-decompose-dialog").waitFor({ state: "visible" });

  const sessionOptions = await page.locator("#task-decompose-session option").evaluateAll((options) => {
    return options.map((option) => ({ value: option.value, text: option.textContent.trim() }));
  });
  const selectedSession = sessionOptions.find((option) => option.value.startsWith("uat-golden-")) ||
    sessionOptions.find((option) => option.text.endsWith("· active"));
  if (!selectedSession) throw new Error("No active UAT session is available for TodoWrite");

  const assigneeOptions = await page.locator("#task-decompose-assignee option").evaluateAll((options) => {
    return options.map((option) => ({ value: option.value, text: option.textContent.trim() }));
  });
  const selectedAssignee = assigneeOptions.find((option) => option.text.includes("值班经理")) ||
    assigneeOptions.find((option) => option.value);
  if (!selectedAssignee) throw new Error("No UAT assignee is available for TodoWrite");

  const goal = "完成景区暑期周末高峰前安全联合检查：核验北门急救通道、东区配电间、游客中心消防器材，记录问题、安排复核并形成闭环报告";
  await page.locator("#task-decompose-goal").fill(goal);
  await page.locator("#task-decompose-session").selectOption(selectedSession.value);
  await page.locator("#task-decompose-assignee").selectOption(selectedAssignee.value);
  await page.locator("#task-decompose-attempts").fill("3");
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "todo-01-before-submit-1440x900.png"), fullPage: true });

  const startedAt = Date.now();
  const [response] = await Promise.all([
    page.waitForResponse(
      (candidate) => candidate.url().includes("/api/v1/admin/tasks/decompose") && candidate.request().method() === "POST",
      { timeout: 120000 }
    ),
    page.locator("#task-decompose-submit").click(),
  ]);
  const responsePayload = await response.json();
  const elapsedMs = Date.now() - startedAt;
  if (!response.ok()) throw new Error(`TodoWrite returned HTTP ${response.status()}: ${responsePayload?.detail?.message || "request failed"}`);

  await page.locator("#task-decompose-dialog").waitFor({ state: "hidden", timeout: 30000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "todo-02-decomposed-1440x900.png"), fullPage: true });

  const traceId = responsePayload.trace_id;
  const [tasksPayload, llmPayload, auditPayload, tracePayload] = await Promise.all([
    apiFromPage(page, "/api/v1/admin/tasks?limit=200"),
    apiFromPage(page, "/api/v1/admin/llm-calls?limit=50"),
    apiFromPage(page, "/api/v1/admin/audit-logs?limit=200"),
    apiFromPage(page, `/api/v1/admin/traces/${encodeURIComponent(traceId)}`),
  ]);
  const createdIds = new Set((responsePayload.tasks || []).map((task) => task.id));
  const tasks = (tasksPayload.tasks || []).filter((task) => createdIds.has(task.id) || task.trace_id === traceId);
  const llmCalls = (llmPayload.calls || llmPayload.llm_calls || []).filter((call) => call.trace_id === traceId);
  const audits = (auditPayload.logs || auditPayload.audit_logs || []).filter((log) => log.trace_id === traceId);
  const evidence = {
    uat_id: "MVP-UAT-004",
    operation: "TodoWrite task decomposition",
    input: { goal, session_id: selectedSession.value, assignee: selectedAssignee.text, max_attempts: 3 },
    response_status: response.status(),
    elapsed_ms: elapsedMs,
    response: responsePayload,
    tasks,
    llm_calls: llmCalls,
    audits,
    trace: tracePayload,
    runtime,
  };
  writeJson("MVP-UAT-004-todo-decompose.json", evidence);
  return evidence;
}

function loadTodoDecompositionEvidence() {
  const filename = path.join(EVIDENCE_DIR, "MVP-UAT-004-todo-decompose.json");
  if (!fs.existsSync(filename)) throw new Error("TodoWrite decomposition evidence is missing");
  return JSON.parse(fs.readFileSync(filename, "utf8"));
}

async function getTasksByIds(page, taskIds) {
  const payload = await apiFromPage(page, "/api/v1/admin/tasks?limit=200");
  const idSet = new Set(taskIds);
  return (payload.tasks || []).filter((task) => idSet.has(task.id));
}

async function performTaskAction(page, taskId, action, value) {
  const labels = { start: "开始", complete: "完成", fail: "失败", retry: "恢复" };
  const label = labels[action];
  if (!label) throw new Error(`Unsupported task action: ${action}`);
  const row = page.locator("#tasks-table tr").filter({
    has: page.locator("td:first-child").filter({ hasText: taskId }),
  });
  await row.waitFor({ state: "visible" });
  const button = row.getByRole("button", { name: label, exact: true });
  await button.waitFor({ state: "visible" });
  const responseMatcher = (response) => {
    return response.url().includes(`/api/v1/admin/tasks/${taskId}/${action}`) && response.request().method() === "POST";
  };

  let response;
  if (action === "fail" || action === "complete") {
    await button.click();
    const dialog = page.locator("#action-dialog");
    await dialog.waitFor({ state: "visible" });
    const field = dialog.locator("textarea, input:not([type=hidden])").first();
    if (await field.count()) await field.fill(value || `${label}验收记录`);
    [response] = await Promise.all([
      page.waitForResponse(responseMatcher, { timeout: 30000 }),
      dialog.locator('button[type="submit"]').click(),
    ]);
    await dialog.waitFor({ state: "hidden", timeout: 10000 });
  } else {
    [response] = await Promise.all([
      page.waitForResponse(responseMatcher, { timeout: 30000 }),
      button.click(),
    ]);
  }
  const payload = await response.json();
  if (!response.ok()) throw new Error(`Task ${action} returned HTTP ${response.status()}`);
  await page.waitForTimeout(350);
  return { action, task_id: taskId, status: response.status(), response: payload };
}

async function runTodoLifecycle(page, runtime) {
  const decomposition = loadTodoDecompositionEvidence();
  const taskIds = (decomposition.response.tasks || []).map((task) => task.id);
  const traceId = decomposition.response.trace_id;
  if (!taskIds.length || !traceId) throw new Error("TodoWrite evidence does not contain task IDs and trace ID");
  await openView(page, "tasks");

  const actions = [];
  let tasks = await getTasksByIds(page, taskIds);
  let rootTask = tasks.find((task) => task.status === "PENDING" && !(task.dependencies || []).length);
  if (!rootTask) throw new Error("TodoWrite graph has no executable root task");

  actions.push(await performTaskAction(page, rootTask.id, "start"));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "todo-03-root-running-1440x900.png"), fullPage: true });
  actions.push(await performTaskAction(page, rootTask.id, "fail", "UAT 注入失败 1：现场检查照片缺失，系统自动重试"));
  actions.push(await performTaskAction(page, rootTask.id, "start"));
  actions.push(await performTaskAction(page, rootTask.id, "fail", "UAT 注入失败 2：检查记录未签字，系统自动重试"));
  actions.push(await performTaskAction(page, rootTask.id, "start"));
  actions.push(await performTaskAction(page, rootTask.id, "fail", "UAT 注入失败 3：达到最大尝试次数，等待经理恢复"));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "todo-04-root-failed-1440x900.png"), fullPage: true });

  tasks = await getTasksByIds(page, taskIds);
  rootTask = tasks.find((task) => task.id === rootTask.id);
  if (rootTask.status !== "FAILED") throw new Error(`Expected root task FAILED, got ${rootTask.status}`);
  actions.push(await performTaskAction(page, rootTask.id, "retry"));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "todo-05-root-recovered-1440x900.png"), fullPage: true });
  actions.push(await performTaskAction(page, rootTask.id, "start"));
  actions.push(await performTaskAction(page, rootTask.id, "complete", "现场复核完成：三处检查对象均已形成带时间戳记录"));

  for (let guard = 0; guard < taskIds.length * 2; guard += 1) {
    tasks = await getTasksByIds(page, taskIds);
    if (tasks.every((task) => task.status === "DONE")) break;
    const nextTask = tasks.find((task) => task.status === "PENDING");
    if (!nextTask) {
      const statusSummary = tasks.map((task) => `${task.id}:${task.status}`).join(", ");
      throw new Error(`TodoWrite graph cannot make progress: ${statusSummary}`);
    }
    actions.push(await performTaskAction(page, nextTask.id, "start"));
    actions.push(await performTaskAction(page, nextTask.id, "complete", `UAT 已完成：${nextTask.description}`));
  }

  tasks = await getTasksByIds(page, taskIds);
  if (!tasks.every((task) => task.status === "DONE")) throw new Error("TodoWrite graph did not reach DONE for every task");
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "todo-06-all-done-1440x900.png"), fullPage: true });

  await openView(page, "diagnostics");
  await page.locator("#trace-search-input").fill(traceId);
  const [traceResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().includes(`/api/v1/admin/traces/${traceId}`)),
    page.locator("#trace-search-form button[type=submit]").click(),
  ]);
  if (!traceResponse.ok()) throw new Error(`Trace lookup returned HTTP ${traceResponse.status()}`);
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "todo-07-trace-timeline-1440x900.png"), fullPage: true });

  const [llmPayload, auditPayload, tracePayload] = await Promise.all([
    apiFromPage(page, "/api/v1/admin/llm-calls?limit=100"),
    apiFromPage(page, "/api/v1/admin/audit-logs?limit=200"),
    apiFromPage(page, `/api/v1/admin/traces/${encodeURIComponent(traceId)}`),
  ]);
  const evidence = {
    uat_id: "MVP-UAT-004",
    operation: "TodoWrite task execution, failure exhaustion, recovery and completion",
    decomposition_trace_id: traceId,
    action_count: actions.length,
    actions,
    final_tasks: tasks,
    llm_calls: (llmPayload.calls || llmPayload.llm_calls || []).filter((call) => call.trace_id === traceId),
    decomposition_audits: (auditPayload.logs || auditPayload.audit_logs || []).filter((log) => log.trace_id === traceId),
    trace: tracePayload,
    runtime,
  };
  writeJson("MVP-UAT-004-todo-lifecycle.json", evidence);
  return evidence;
}

async function runTodoRecovery(page, runtime) {
  const source = loadTodoDecompositionEvidence();
  const completed = source.response;
  const originalTasks = completed.tasks || [];
  const currentUser = await page.evaluate(() => JSON.parse(sessionStorage.getItem("mp_user") || "null"));
  if (!currentUser?.id || !currentUser?.venue_id) throw new Error("Authenticated UAT user is unavailable");
  if (!completed?.idempotency_key || !completed?.trace_id || !originalTasks.length) {
    throw new Error("TodoWrite decomposition evidence is incomplete");
  }

  const operation = {
    status: "RUNNING",
    trace_id: completed.trace_id,
    idempotency_key: completed.idempotency_key,
    decomposition_id: completed.decomposition_id,
    owner_user_id: currentUser.id,
    venue_id: currentUser.venue_id,
    agent_id: completed.agent_id || "TodoWrite",
    tasks_created: null,
    note: "正在等待 DeepSeek 返回任务图。",
    payload: {
      goal: source.input.goal,
      session_id: source.input.session_id,
      assigned_user_id: originalTasks[0].assigned_user_id || null,
      max_attempts: source.input.max_attempts,
    },
  };
  const decompositionPosts = [];
  const recordRequest = (request) => {
    if (request.method() === "POST" && request.url().includes("/api/v1/admin/tasks/decompose")) {
      decompositionPosts.push(request.url());
    }
  };
  page.on("request", recordRequest);

  try {
    await page.evaluate((storedOperation) => {
      sessionStorage.setItem("mp_todo_decomposition", JSON.stringify(storedOperation));
    }, operation);
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForFunction(() => {
      return document.querySelector("#app-screen")?.classList.contains("active") && window.App?.todoDecomposition?.status === "CHECK_REQUIRED";
    });
    await openView(page, "tasks");

    const before = await page.evaluate(() => {
      const stored = JSON.parse(sessionStorage.getItem("mp_todo_decomposition") || "null");
      return {
        app_status: window.App?.todoDecomposition?.status,
        stored_status: stored?.status,
        idempotency_key: stored?.idempotency_key,
        trace_id: stored?.trace_id,
        submit_disabled: document.querySelector("#task-decompose-submit")?.disabled,
        recovery_visible: !document.querySelector("#task-decompose-recovery")?.classList.contains("hidden"),
        recovery_disabled: document.querySelector("#task-decompose-recover")?.disabled,
        recovery_text: document.querySelector("#task-decompose-recover")?.textContent.trim(),
        note: document.querySelector("#task-decompose-note")?.textContent.trim(),
      };
    });
    if (before.app_status !== "CHECK_REQUIRED" || before.stored_status !== "CHECK_REQUIRED") {
      throw new Error(`Refresh recovery expected CHECK_REQUIRED, got ${before.app_status}/${before.stored_status}`);
    }
    if (!before.submit_disabled || !before.recovery_visible || before.recovery_disabled || before.idempotency_key !== completed.idempotency_key) {
      throw new Error("Refresh recovery controls or idempotency key were not preserved");
    }
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, "todo-08-refresh-check-required-1440x900.png"), fullPage: true });

    const [statusResponse] = await Promise.all([
      page.waitForResponse((response) => {
        return response.request().method() === "GET" && response.url().includes("/api/v1/admin/tasks/decompositions/status");
      }, { timeout: 30000 }),
      page.locator("#task-decompose-recover").click(),
    ]);
    const statusPayload = await statusResponse.json();
    if (!statusResponse.ok()) throw new Error(`TodoWrite status recovery returned HTTP ${statusResponse.status()}`);
    await page.waitForFunction(() => window.App?.todoDecomposition?.status === "SUCCEEDED");
    await page.waitForTimeout(400);

    const after = await page.evaluate(() => {
      const stored = JSON.parse(sessionStorage.getItem("mp_todo_decomposition") || "null");
      return {
        app_status: window.App?.todoDecomposition?.status,
        stored_status: stored?.status,
        idempotency_key: stored?.idempotency_key,
        trace_id: stored?.trace_id,
        decomposition_id: stored?.decomposition_id,
        tasks_created: stored?.tasks_created,
        dialog_open: document.querySelector("#task-decompose-dialog")?.open,
      };
    });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, "todo-09-recovery-succeeded-1440x900.png"), fullPage: true });

    const [tasksPayload, llmPayload] = await Promise.all([
      apiFromPage(page, "/api/v1/admin/tasks?limit=200"),
      apiFromPage(page, "/api/v1/admin/llm-calls?limit=100"),
    ]);
    const originalIds = new Set(originalTasks.map((task) => String(task.id)));
    const recoveredTasks = (tasksPayload.tasks || []).filter((task) => originalIds.has(String(task.id)));
    const llmCalls = (llmPayload.calls || llmPayload.llm_calls || []).filter((call) => call.trace_id === completed.trace_id);
    const passed = statusResponse.status() === 200 &&
      statusPayload.status === "COMPLETED" &&
      after.app_status === "SUCCEEDED" &&
      after.stored_status === "SUCCEEDED" &&
      after.idempotency_key === completed.idempotency_key &&
      after.trace_id === completed.trace_id &&
      sameId(after.decomposition_id, completed.decomposition_id) &&
      after.tasks_created === originalTasks.length &&
      after.dialog_open === false &&
      decompositionPosts.length === 0 &&
      recoveredTasks.length === originalTasks.length &&
      llmCalls.length === 1;
    const evidence = {
      uat_id: "MVP-UAT-004",
      operation: "TodoWrite browser refresh and status-query recovery",
      before,
      status_http: statusResponse.status(),
      status: statusPayload,
      after,
      decomposition_post_count: decompositionPosts.length,
      recovered_task_count: recoveredTasks.length,
      llm_call_count: llmCalls.length,
      passed,
      runtime,
    };
    writeJson("MVP-UAT-004-todo-recovery.json", evidence);
    if (!passed) throw new Error("TodoWrite browser recovery assertions failed");
    return evidence;
  } finally {
    page.off("request", recordRequest);
  }
}

async function inspectApprovalActionViews(page, runtime) {
  await openView(page, "approvals");
  const approvals = await page.evaluate(() => ({
    buttons: Array.from(document.querySelectorAll("#view-approvals button")).map((button) => ({
      text: button.textContent.trim(),
      disabled: button.disabled,
    })),
    rows: Array.from(document.querySelectorAll("#view-approvals tr")).map((row) => row.innerText.trim()).filter(Boolean),
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "approval-01-center-1440x900.png"), fullPage: true });

  await openView(page, "actions");
  const actions = await page.evaluate(() => ({
    buttons: Array.from(document.querySelectorAll("#view-actions button")).map((button) => ({
      text: button.textContent.trim(),
      disabled: button.disabled,
    })),
    rows: Array.from(document.querySelectorAll("#view-actions tr")).map((row) => row.innerText.trim()).filter(Boolean),
    row_actions: Array.from(document.querySelectorAll("#view-actions tr")).map((row) => ({
      text: row.innerText.trim(),
      buttons: Array.from(row.querySelectorAll("button")).map((button) => ({
        text: button.textContent.trim(),
        onclick: button.getAttribute("onclick"),
      })),
    })).filter((row) => row.text),
    text: document.querySelector("#view-actions")?.innerText || "",
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "approval-02-actions-1440x900.png"), fullPage: true });

  await page.locator('#view-actions [data-action="new-action-request"]').click();
  const dialog = page.locator("#action-dialog");
  await dialog.waitFor({ state: "visible" });
  const requestDialog = await dialog.evaluate((element) => ({
    title: element.querySelector("h1,h2,h3")?.textContent.trim() || "",
    labels: Array.from(element.querySelectorAll("label")).map((label) => label.textContent.trim()),
    fields: Array.from(element.querySelectorAll("input,textarea,select")).map((field) => ({
      name: field.name,
      id: field.id,
      type: field.type,
      required: field.required,
      options: field.tagName === "SELECT" ? Array.from(field.options).map((option) => ({ value: option.value, text: option.textContent.trim() })) : [],
    })),
    buttons: Array.from(element.querySelectorAll("button")).map((button) => ({ text: button.textContent.trim(), type: button.type })),
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "approval-03-request-dialog-1440x900.png"), fullPage: true });
  await dialog.locator('button[type="button"]').filter({ hasText: "取消" }).click();
  await dialog.waitFor({ state: "hidden" });
  const evidence = { approvals, actions, request_dialog: requestDialog, runtime };
  writeJson("approval-action-client-map.json", evidence);
  return evidence;
}

async function inspectInAppAlertForm(page, runtime) {
  await openView(page, "actions");
  await page.locator('#view-actions [data-action="new-action-request"]').click();
  const dialog = page.locator("#action-dialog");
  await dialog.waitFor({ state: "visible" });
  await dialog.locator('select[name="tool_name"]').selectOption("send_in_app_alert");
  await dialog.locator('button[type="submit"]').click();
  await page.waitForTimeout(250);
  const form = await dialog.evaluate((element) => ({
    title: element.querySelector("h1,h2,h3")?.textContent.trim() || "",
    description: element.querySelector(".dialog-body")?.innerText || "",
    labels: Array.from(element.querySelectorAll("label")).map((label) => label.textContent.trim()),
    fields: Array.from(element.querySelectorAll("input,textarea,select")).map((field) => ({
      name: field.name,
      id: field.id,
      type: field.type,
      required: field.required,
      value: field.value,
      options: field.tagName === "SELECT" ? Array.from(field.options).map((option) => ({ value: option.value, text: option.textContent.trim() })) : [],
    })),
    buttons: Array.from(element.querySelectorAll("button")).map((button) => ({ text: button.textContent.trim(), type: button.type })),
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "approval-04-in-app-form-1440x900.png"), fullPage: true });
  const cancel = dialog.locator('button[type="button"]').filter({ hasText: "取消" });
  if (await cancel.count()) await cancel.click();
  else await dialog.locator('button[type="button"]').first().click();
  await dialog.waitFor({ state: "hidden" });
  writeJson("in-app-alert-form-map.json", { form, runtime });
  return form;
}

async function createInAppAlertRequest(page, message, priority, screenshotName) {
  await openView(page, "actions");
  await page.locator('#view-actions [data-action="new-action-request"]').click();
  const dialog = page.locator("#action-dialog");
  await dialog.waitFor({ state: "visible" });
  await dialog.locator('select[name="tool_name"]').selectOption("send_in_app_alert");
  await dialog.locator('button[type="submit"]').click();
  await page.waitForTimeout(150);
  const sessionSelect = dialog.locator('select[name="session_id"]');
  const sessionOptions = await sessionSelect.locator("option").evaluateAll((options) => {
    return options.map((option) => ({ value: option.value, text: option.textContent.trim() }));
  });
  const session = sessionOptions.find((option) => option.value.startsWith("uat-golden-")) || sessionOptions[0];
  if (!session) throw new Error("No session is available for in-app alert approval");
  await sessionSelect.selectOption(session.value);
  await dialog.locator('select[name="priority"]').selectOption(priority);
  await dialog.locator('textarea[name="message"]').fill(message);
  if (screenshotName) await page.screenshot({ path: path.join(SCREENSHOT_DIR, screenshotName), fullPage: true });
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      return candidate.request().method() === "POST" && candidate.url().includes("/api/v1/admin/");
    }, { timeout: 30000 }),
    dialog.locator('button[type="submit"]').click(),
  ]);
  const payload = await response.json();
  if (!response.ok()) throw new Error(`Controlled action request returned HTTP ${response.status()}`);
  await dialog.waitFor({ state: "hidden", timeout: 10000 });
  await page.waitForTimeout(400);
  return { url: response.url(), status: response.status(), payload, session_id: session.value, priority, message };
}

async function createApprovalRequests(page, runtime) {
  const runId = Date.now().toString(36);
  const approveRequest = await createInAppAlertRequest(
    page,
    `UAT 站内告警批准链 ${runId}：暑期高峰联合检查已完成，请值班经理确认闭环报告并采纳。`,
    "warning",
    "approval-05-submit-approved-path-1440x900.png"
  );
  const rejectRequest = await createInAppAlertRequest(
    page,
    `UAT 站内告警拒绝链 ${runId}：该通知缺少现场复核附件，应拒绝并退回补充。`,
    "info",
    "approval-06-submit-rejected-path-1440x900.png"
  );
  await openView(page, "approvals");
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "approval-07-two-pending-1440x900.png"), fullPage: true });
  const evidence = {
    uat_id: "MVP-UAT-004",
    operation: "Create controlled in-app alert requests",
    approve_request: approveRequest,
    reject_request: rejectRequest,
    runtime,
  };
  writeJson("MVP-UAT-004-approval-requests.json", evidence);
  return evidence;
}

async function performApprovalDecision(page, approvalId, decision, reason) {
  const labels = { approve: "批准", reject: "拒绝" };
  await openView(page, "approvals");
  const row = page.locator("#approvals-table tr").filter({
    has: page.locator("td:nth-child(2)").filter({ hasText: approvalId }),
  });
  await row.waitFor({ state: "visible" });
  await row.getByRole("button", { name: labels[decision], exact: true }).click();
  const dialog = page.locator("#action-dialog");
  await dialog.waitFor({ state: "visible" });
  const field = dialog.locator("textarea, input:not([type=hidden])").first();
  if (await field.count()) await field.fill(reason);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      return candidate.request().method() === "POST" && candidate.url().includes(approvalId);
    }, { timeout: 30000 }),
    dialog.locator('button[type="submit"]').click(),
  ]);
  const payload = await response.json();
  if (!response.ok()) throw new Error(`Approval ${decision} returned HTTP ${response.status()}`);
  await dialog.waitFor({ state: "hidden", timeout: 10000 });
  await page.waitForTimeout(500);
  return { decision, approval_id: approvalId, url: response.url(), status: response.status(), payload };
}

async function collectApprovalDecisionRecords(page, approveId, rejectId, approvedTraceId, rejectedTraceId) {
  const [approvalsPayload, pushesPayload, auditPayload] = await Promise.all([
    apiFromPage(page, "/api/v1/admin/approvals?limit=200&status=ALL"),
    apiFromPage(page, "/api/v1/admin/push_logs?limit=200"),
    apiFromPage(page, "/api/v1/admin/audit-logs?limit=200"),
  ]);
  const approvalIds = new Set([approveId, rejectId].map(String));
  const decisionTraceIds = new Set([approvedTraceId, rejectedTraceId].filter(Boolean));
  const approvalRows = Array.isArray(approvalsPayload) ? approvalsPayload : (approvalsPayload.approvals || []);
  const approvals = approvalRows.filter((item) => {
    return approvalIds.has(String(item.approval_id)) || approvalIds.has(String(item.id));
  });
  const pushes = (pushesPayload.pushes || pushesPayload.push_logs || pushesPayload.logs || []).filter((item) => {
    return approvalIds.has(String(item.approval_id || item.idempotency_key)) || decisionTraceIds.has(item.trace_id);
  });
  const audits = (auditPayload.logs || auditPayload.audit_logs || []).filter((item) => {
    return approvalIds.has(String(item.resource_id)) || decisionTraceIds.has(item.trace_id);
  });
  return { approvals, pushes, audits };
}

async function decideApprovalRequests(page, runtime) {
  const source = JSON.parse(fs.readFileSync(path.join(EVIDENCE_DIR, "MVP-UAT-004-approval-requests.json"), "utf8"));
  const approveId = source.approve_request.payload.approval_id;
  const rejectId = source.reject_request.payload.approval_id;
  const approved = await performApprovalDecision(
    page,
    approveId,
    "approve",
    "UAT 批准：联合检查记录齐全，同意投递站内告警"
  );
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "approval-08-approved-and-delivered-1440x900.png"), fullPage: true });
  const rejected = await performApprovalDecision(
    page,
    rejectId,
    "reject",
    "UAT 拒绝：缺少现场复核附件，退回补充"
  );
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "approval-09-rejected-1440x900.png"), fullPage: true });
  const { approvals, pushes, audits } = await collectApprovalDecisionRecords(
    page,
    approveId,
    rejectId,
    approved.payload.trace_id,
    rejected.payload.trace_id
  );
  const evidence = {
    uat_id: "MVP-UAT-004",
    operation: "Approve and reject controlled actions",
    approved,
    rejected,
    approvals,
    pushes,
    audits,
    runtime,
  };
  writeJson("MVP-UAT-004-approval-decisions.json", evidence);
  if (approvals.length !== 2 || pushes.length < 1) {
    throw new Error(`Approval decision evidence is incomplete: approvals=${approvals.length}, pushes=${pushes.length}`);
  }
  return evidence;
}

async function verifyApprovalDecisionEvidence(page, runtime) {
  const filename = path.join(EVIDENCE_DIR, "MVP-UAT-004-approval-decisions.json");
  if (!fs.existsSync(filename)) throw new Error("Approval decision evidence is missing");
  const existing = JSON.parse(fs.readFileSync(filename, "utf8"));
  const approveId = existing.approved?.approval_id;
  const rejectId = existing.rejected?.approval_id;
  if (!approveId || !rejectId) throw new Error("Approval decision evidence does not contain both approval IDs");
  const { approvals, pushes, audits } = await collectApprovalDecisionRecords(
    page,
    approveId,
    rejectId,
    existing.approved?.payload?.trace_id,
    existing.rejected?.payload?.trace_id
  );
  const evidence = { ...existing, approvals, pushes, audits, runtime };
  writeJson("MVP-UAT-004-approval-decisions.json", evidence);
  if (approvals.length !== 2 || pushes.length < 1) {
    throw new Error(`Approval evidence verification failed: approvals=${approvals.length}, pushes=${pushes.length}`);
  }
  return evidence;
}

async function requestFromPage(page, route, method, body) {
  return page.evaluate(async ({ url, requestMethod, requestBody }) => {
    const token = sessionStorage.getItem("mp_access_token");
    const response = await fetch(url, {
      method: requestMethod,
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: requestBody === undefined ? undefined : JSON.stringify(requestBody),
    });
    let payload;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    return { status: response.status, payload };
  }, { url: route, requestMethod: method, requestBody: body });
}

async function adoptPendingPush(page, runtime) {
  const pendingPayload = await apiFromPage(page, "/api/v1/admin/push_logs?limit=200&adoption_status=pending");
  const pendingPush = (pendingPayload.push_logs || [])[0];
  if (!pendingPush?.push_id) throw new Error("No pending push is available for adoption verification");
  const pushId = pendingPush.push_id;
  await openView(page, "actions");
  const row = page.locator("#push-table tr").filter({
    has: page.locator(`button[onclick*="${pushId}"]`),
  });
  await row.waitFor({ state: "visible" });
  await row.getByRole("button", { name: "采纳", exact: true }).click();
  const dialog = page.locator("#action-dialog");
  await dialog.waitFor({ state: "visible" });
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      return candidate.url().includes(`/api/v1/admin/push_logs/${encodeURIComponent(pushId)}/adoption`)
        && candidate.request().method() === "PATCH";
    }, { timeout: 30000 }),
    dialog.locator('button[type="submit"]').click(),
  ]);
  const payload = await response.json();
  if (!response.ok()) throw new Error(`Push adoption returned HTTP ${response.status()}`);
  if (payload.push_id !== pushId || payload.status !== "adopted") {
    throw new Error(`Push adoption updated an unexpected record: expected ${pushId}, got ${payload.push_id}`);
  }
  await dialog.waitFor({ state: "hidden", timeout: 10000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "approval-10-push-adopted-1440x900.png"), fullPage: true });

  const duplicate = await requestFromPage(page, response.url(), response.request().method(), { status: "rejected" });
  if (duplicate.status !== 409 || duplicate.payload?.detail?.code !== "PUSH_LOG_STATE_CHANGED") {
    throw new Error(`Expected duplicate terminal transition to return PUSH_LOG_STATE_CHANGED/409, got ${duplicate.status}`);
  }
  const pushesPayload = await apiFromPage(page, "/api/v1/admin/push_logs?limit=200");
  const evidence = {
    uat_id: "MVP-UAT-004",
    operation: "Adopt delivered in-app alert and reject duplicate terminal transition",
    adoption: {
      url: response.url(),
      method: response.request().method(),
      status: response.status(),
      payload,
    },
    duplicate_terminal_transition: duplicate,
    pushes: pushesPayload,
    runtime,
  };
  writeJson("MVP-UAT-004-push-adoption.json", evidence);
  return evidence;
}

async function runPushConcurrency(page, runtime) {
  const request = await createInAppAlertRequest(
    page,
    "UAT 并发采纳验证：同一条站内告警只能进入一个终态。",
    "warning",
    null
  );
  const approvalId = request.payload.approval_id;
  const approved = await performApprovalDecision(
    page,
    approvalId,
    "approve",
    "UAT 批准：用于验证并发终态保护"
  );
  const pushId = approved.payload?.execution_result?.result?.push_id;
  if (!pushId) throw new Error("Approved in-app alert did not return its push ID");
  await openView(page, "actions");
  const row = page.locator("#push-table tr").filter({
    has: page.locator(`button[onclick*="${pushId}"]`),
  });
  await row.waitFor({ state: "visible" });
  const route = `/api/v1/admin/push_logs/${encodeURIComponent(pushId)}/adoption`;
  const results = await page.evaluate(async ({ url }) => {
    const token = sessionStorage.getItem("mp_access_token");
    const submit = async (status) => {
      const response = await fetch(url, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      return { status: response.status, payload: await response.json() };
    };
    return Promise.all([submit("adopted"), submit("rejected")]);
  }, { url: route });
  const statuses = results.map((result) => result.status).sort((left, right) => left - right);
  if (statuses[0] !== 200 || statuses[1] !== 409) {
    throw new Error(`Expected one 200 and one 409 from concurrent adoption, got ${statuses.join(",")}`);
  }
  await openView(page, "actions");
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "approval-11-concurrent-adoption-terminal-1440x900.png"), fullPage: true });
  const pushes = await apiFromPage(page, "/api/v1/admin/push_logs?limit=200");
  const evidence = {
    uat_id: "MVP-UAT-004",
    operation: "Competing concurrent adoption transitions",
    request,
    approved,
    push_id: pushId,
    results,
    pushes,
    runtime,
  };
  writeJson("MVP-UAT-004-push-concurrency.json", evidence);
  return evidence;
}

async function prepareTodoDialog(page, goal) {
  await openView(page, "tasks");
  await page.locator('#view-tasks [data-action="decompose-task"]').click();
  const dialog = page.locator("#task-decompose-dialog");
  await dialog.waitFor({ state: "visible" });
  await dialog.locator("#task-decompose-goal").fill(goal);
  const sessionOptions = await dialog.locator("#task-decompose-session option").evaluateAll((options) => {
    return options.map((option) => option.value);
  });
  const session = sessionOptions.find((value) => value.startsWith("uat-golden-")) || sessionOptions[0];
  await dialog.locator("#task-decompose-session").selectOption(session);
  return dialog;
}

async function probeTodoPermanentLoading(page, runtime) {
  const dialog = await prepareTodoDialog(page, "UAT 前端超时保护探针，不应到达服务端");
  let requestIntercepted = false;
  let releaseRoute;
  await page.route("**/api/v1/admin/tasks/decompose", async (route) => {
    requestIntercepted = true;
    await new Promise((resolve) => { releaseRoute = resolve; });
    await route.abort("failed").catch(() => {});
  });
  await dialog.locator("#task-decompose-submit").click();
  await page.waitForFunction(() => window.App?.todoDecomposition?.status === "RUNNING" && !document.querySelector("#task-decompose-cancel")?.classList.contains("hidden"));
  const waiting = await page.evaluate(() => ({
    app_status: window.App?.todoDecomposition?.status,
    cancel_visible: !document.querySelector("#task-decompose-cancel")?.classList.contains("hidden"),
    submit_disabled: document.querySelector("#task-decompose-submit")?.disabled,
    status_text: document.querySelector("#task-decompose-status")?.textContent.trim(),
    dialog_open: document.querySelector("#task-decompose-dialog")?.open,
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "issue-001-todo-01-waiting-cancellable-1440x900.png"), fullPage: true });
  await dialog.locator("#task-decompose-cancel").click();
  if (releaseRoute) releaseRoute();
  await page.waitForFunction(() => window.App?.todoDecomposition?.status === "CHECK_REQUIRED");
  const cancelled = await page.evaluate(() => {
    const stored = JSON.parse(sessionStorage.getItem("mp_todo_decomposition") || "null");
    return {
      app_status: window.App?.todoDecomposition?.status,
      stored_status: stored?.status,
      idempotency_key: stored?.idempotency_key,
      trace_id: stored?.trace_id,
      note: stored?.note,
      recover_visible: !document.querySelector("#task-decompose-recovery")?.classList.contains("hidden"),
      dialog_open: document.querySelector("#task-decompose-dialog")?.open,
    };
  });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "issue-001-todo-02-cancelled-recoverable-1440x900.png"), fullPage: true });
  await page.unroute("**/api/v1/admin/tasks/decompose");

  await page.reload({ waitUntil: "networkidle" });
  await page.waitForFunction(() => Boolean(sessionStorage.getItem("mp_access_token")) && document.querySelector("#app-screen")?.classList.contains("active"));
  await openView(page, "tasks");
  await page.waitForFunction(() => window.App?.todoDecomposition?.status === "CHECK_REQUIRED");
  const restored = await page.evaluate(() => {
    const stored = JSON.parse(sessionStorage.getItem("mp_todo_decomposition") || "null");
    return {
      app_status: window.App?.todoDecomposition?.status,
      stored_status: stored?.status,
      idempotency_key: stored?.idempotency_key,
      trace_id: stored?.trace_id,
      recover_visible: !document.querySelector("#task-decompose-recovery")?.classList.contains("hidden"),
    };
  });
  const recoveryTraceId = cancelled.trace_id;
  let recoveryStatusRequest;
  await page.route("**/api/v1/admin/tasks/decompositions/status?**", async (route) => {
    recoveryStatusRequest = new URL(route.request().url()).searchParams.get("idempotency_key");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "COMPLETED",
        trace_id: recoveryTraceId,
        idempotency_key: recoveryStatusRequest,
        result: {
          status: "created",
          agent_id: "TodoWrite",
          tasks_created: 2,
          trace_id: recoveryTraceId,
          idempotency_key: recoveryStatusRequest,
        },
      }),
    });
  });
  await page.locator("#task-decompose-recover").click();
  await page.waitForFunction(() => window.App?.todoDecomposition?.status === "SUCCEEDED");
  const recovered = await page.evaluate(() => {
    const stored = JSON.parse(sessionStorage.getItem("mp_todo_decomposition") || "null");
    return {
      app_status: window.App?.todoDecomposition?.status,
      stored_status: stored?.status,
      idempotency_key: stored?.idempotency_key,
      trace_id: stored?.trace_id,
      tasks_created: stored?.tasks_created,
      status_text: document.querySelector("#task-decompose-status")?.textContent.trim(),
      result_visible: !document.querySelector("#task-decompose-result")?.classList.contains("hidden"),
    };
  });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "issue-001-todo-03-recovered-succeeded-1440x900.png"), fullPage: true });
  await page.unroute("**/api/v1/admin/tasks/decompositions/status?**");

  if (!requestIntercepted || waiting.app_status !== "RUNNING" || !waiting.cancel_visible || waiting.submit_disabled !== true) {
    throw new Error("Todo waiting state is not cancellable");
  }
  if (cancelled.app_status !== "CHECK_REQUIRED" || cancelled.stored_status !== "CHECK_REQUIRED" || !cancelled.recover_visible) {
    throw new Error("Cancelled Todo wait is not recoverable");
  }
  if (restored.app_status !== "CHECK_REQUIRED" || restored.idempotency_key !== cancelled.idempotency_key) {
    throw new Error("Todo recovery state did not survive refresh");
  }
  if (recoveryStatusRequest !== cancelled.idempotency_key || recovered.app_status !== "SUCCEEDED" || recovered.stored_status !== "SUCCEEDED") {
    throw new Error("Todo recovery did not preserve the original idempotency key and succeed");
  }
  const expectedTransportEvents = runtime.failedRequests.filter((item) => item.url.includes("/api/v1/admin/tasks/decompose"));
  const unexpectedRuntime = {
    consoleErrors: runtime.consoleErrors,
    pageErrors: runtime.pageErrors,
    failedRequests: runtime.failedRequests.filter((item) => !item.url.includes("/api/v1/admin/tasks/decompose")),
    serverErrors: runtime.serverErrors,
  };
  if (unexpectedRuntime.consoleErrors.length || unexpectedRuntime.pageErrors.length || unexpectedRuntime.failedRequests.length || unexpectedRuntime.serverErrors.length) {
    throw new Error("Todo cancellation probe contains unexpected browser errors");
  }
  const evidence = {
    operation: "Cancel a pending Todo wait, persist it across refresh and recover by the original idempotency key",
    waiting,
    cancelled,
    restored,
    recovered,
    expected_transport_events: expectedTransportEvents,
    unexpected_runtime: unexpectedRuntime,
    simulated_delayed_server_completion: true,
    application_server_decomposition_post_count: 0,
    runtime,
  };
  writeJson("issue-001-todo-permanent-loading.json", evidence);
  return evidence;
}

async function probeTodoRefreshMisreport(page, runtime) {
  let decompositionReturned = false;
  await page.route("**/api/v1/admin/tasks/decompose", async (route) => {
    decompositionReturned = true;
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        status: "created",
        agent_id: "TodoWrite",
        tasks_created: 2,
        trace_id: "uat-success-trace-refresh-probe",
        tasks: [],
      }),
    });
  });
  await page.route("**/api/v1/admin/tasks?limit=200", async (route) => {
    if (!decompositionReturned) return route.continue();
    return route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: { code: "QA_REFRESH_PROBE", message: "UAT 列表刷新故障探针" } }),
    });
  });
  const dialog = await prepareTodoDialog(page, "UAT 成功后列表刷新误报探针，不应到达服务端");
  await dialog.locator("#task-decompose-submit").click();
  await page.waitForFunction(() => window.App?.todoDecomposition?.status === "SUCCEEDED");
  const state = await page.evaluate(() => ({
    app_status: window.App?.todoDecomposition?.status,
    stored_status: JSON.parse(sessionStorage.getItem("mp_todo_decomposition") || "null")?.status,
    status_text: document.querySelector("#task-decompose-status")?.textContent.trim(),
    trace_text: document.querySelector("#task-decompose-trace")?.textContent.trim(),
    note_text: document.querySelector("#task-decompose-note")?.textContent.trim(),
    dialog_open: document.querySelector("#task-decompose-dialog")?.open,
    result_visible: !document.querySelector("#task-decompose-result")?.classList.contains("hidden"),
    toast_messages: Array.from(document.querySelectorAll("#toast-region .toast")).map((item) => item.textContent.trim()),
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "issue-002-todo-success-misreported-failed-1440x900.png"), fullPage: true });
  await page.unroute("**/api/v1/admin/tasks/decompose");
  await page.unroute("**/api/v1/admin/tasks?limit=200");
  if (state.app_status !== "SUCCEEDED" || state.stored_status !== "SUCCEEDED" || !state.result_visible || state.dialog_open) {
    throw new Error("Successful Todo decomposition was overwritten by the refresh failure");
  }
  if (!state.note_text.includes("拆解已成功，仅任务列表刷新失败") || state.toast_messages.some((message) => message.includes("拆解失败"))) {
    throw new Error("Todo refresh failure messaging misreports the successful decomposition");
  }
  const expectedHttpErrors = runtime.serverErrors.filter((item) => item.status === 503 && item.url.includes("/api/v1/admin/tasks?limit=200"));
  const expectedConsoleErrors = runtime.consoleErrors.filter((message) => message.includes("Failed to load resource") && message.includes("503"));
  const unexpectedRuntime = {
    consoleErrors: runtime.consoleErrors.filter((message) => !(message.includes("Failed to load resource") && message.includes("503"))),
    pageErrors: runtime.pageErrors,
    failedRequests: runtime.failedRequests,
    serverErrors: runtime.serverErrors.filter((item) => !(item.status === 503 && item.url.includes("/api/v1/admin/tasks?limit=200"))),
  };
  if (unexpectedRuntime.consoleErrors.length || unexpectedRuntime.pageErrors.length || unexpectedRuntime.failedRequests.length || unexpectedRuntime.serverErrors.length) {
    throw new Error(`Todo refresh probe contains unexpected browser errors: ${JSON.stringify(unexpectedRuntime)}`);
  }
  const evidence = {
    operation: "Keep successful Todo result when the subsequent task-list refresh fails",
    state,
    simulated_decomposition_status: 201,
    simulated_refresh_status: 503,
    application_server_decomposition_post_count: 0,
    expected_http_errors: expectedHttpErrors,
    expected_console_errors: expectedConsoleErrors,
    unexpected_runtime: unexpectedRuntime,
    runtime,
  };
  writeJson("issue-002-todo-success-misreported-failed.json", evidence);
  return evidence;
}

async function runMemoryOpsAdvice(page, runtime) {
  await openView(page, "events");
  await page.getByRole("button", { name: "现场智能受理", exact: true }).click();
  const content = "这是历史经验咨询，不是正在发生的事件。请查询记忆库：以前东区配电间出现温控告警时怎么处理？请基于已有案例给出处置流程和避坑建议。";
  await page.locator("#event-content").fill(content);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "memory-ops-01-before-submit-1440x900.png"), fullPage: true });
  const startedAt = Date.now();
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => apiResponseMatches(candidate, "POST", "/api/v1/messages/"), { timeout: 30000 }),
    page.locator("#event-form button[type=submit]").click(),
  ]);
  const intake = await response.json();
  if (!response.ok()) throw new Error(`MemoryOps intake returned HTTP ${response.status()}`);
  await page.waitForFunction(() => {
    const status = (document.querySelector("#run-status")?.textContent.trim() || "").toUpperCase();
    const agent = (document.querySelector("#run-agent")?.textContent.trim() || "").toLowerCase();
    return ["COMPLETED", "FAILED"].includes(status) && agent !== "路由中";
  }, null, { timeout: 120000 });
  const run = await page.evaluate(() => ({
    status: document.querySelector("#run-status")?.textContent.trim(),
    message_id: document.querySelector("#run-message")?.textContent.trim(),
    trace_id: document.querySelector("#run-trace")?.textContent.trim(),
    session_id: document.querySelector("#run-session")?.textContent.trim(),
    agent: document.querySelector("#run-agent")?.textContent.trim(),
    result: document.querySelector("#run-result")?.textContent.trim(),
  }));
  if (run.status !== "COMPLETED") throw new Error(`MemoryOps message finished as ${run.status}`);
  if (String(run.agent).toLowerCase() !== "memory_ops") throw new Error(`Expected memory_ops, received ${run.agent}`);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "memory-ops-02-completed-1440x900.png"), fullPage: true });

  const traceId = run.trace_id || intake.trace_id;
  const [trace, llm, audits, events, sessions] = await Promise.all([
    apiFromPage(page, `/api/v1/admin/traces/${encodeURIComponent(traceId)}`),
    apiFromPage(page, "/api/v1/admin/llm-calls?limit=200"),
    apiFromPage(page, "/api/v1/admin/audit-logs?limit=300"),
    apiFromPage(page, "/api/v1/admin/events?limit=200"),
    apiFromPage(page, "/api/v1/sessions/?limit=200"),
  ]);
  const traceCalls = (llm.calls || llm.llm_calls || []).filter((item) => item.trace_id === traceId);
  const memoryOpsCalls = traceCalls.filter((item) => item.agent_id === "MemoryOps");
  const validMemoryOpsCalls = memoryOpsCalls.filter((item) => {
    return item.model_name === "deepseek-v4-flash" && item.status === "SUCCEEDED" && item.is_mock === false;
  });
  if (!validMemoryOpsCalls.length) throw new Error("MemoryOps has no successful non-mock deepseek-v4-flash call");
  const timelineAgentIds = [...new Set((trace.timeline || []).map((item) => item.agent_id).filter(Boolean))].sort();
  if (!timelineAgentIds.includes("MemoryOps")) throw new Error("MemoryOps is missing from the persisted trace timeline");
  const sessionRecords = (Array.isArray(sessions) ? sessions : (sessions.sessions || [])).filter((item) => {
    return item.session_id === run.session_id || item.id === run.session_id;
  });
  if (!sessionRecords.length) throw new Error(`MemoryOps session ${run.session_id} is missing from the formal client API`);

  await openView(page, "diagnostics");
  await page.locator("#trace-search-input").fill(traceId);
  const [traceResponse] = await Promise.all([
    page.waitForResponse((candidate) => apiResponseMatches(candidate, "GET", `/api/v1/admin/traces/${traceId}`), { timeout: 30000 }),
    page.locator("#trace-search-form button[type=submit]").click(),
  ]);
  if (!traceResponse.ok()) throw new Error(`Formal client trace lookup returned HTTP ${traceResponse.status()}`);
  await page.waitForFunction(() => {
    const text = document.querySelector("#trace-timeline")?.textContent || "";
    return text.includes("MemoryOps") && text.includes("deepseek-v4-flash");
  });
  const traceView = await page.evaluate(() => ({
    summary: document.querySelector("#trace-summary")?.innerText.trim(),
    timeline: document.querySelector("#trace-timeline")?.innerText.trim(),
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "memory-ops-03-trace-timeline-1440x900.png"), fullPage: true });
  if (runtime.consoleErrors.length || runtime.pageErrors.length || runtime.failedRequests.length || runtime.serverErrors.length) {
    throw new Error("MemoryOps browser runtime contains console, page, request or HTTP errors");
  }

  const evidence = {
    uat_id: "MVP-UAT-002",
    operation: "Formal client MemoryOps grounded advice and trace inspection",
    input: { content },
    intake_status: response.status(),
    intake,
    elapsed_ms: Date.now() - startedAt,
    run,
    trace,
    trace_view: traceView,
    timeline_agent_ids: timelineAgentIds,
    memory_ops_calls: validMemoryOpsCalls,
    llm_calls: traceCalls,
    audits: (audits.logs || audits.audit_logs || []).filter((item) => item.trace_id === traceId),
    events: (events.events || []).filter((item) => item.trace_id === traceId || item.raw_text === content),
    sessions: sessionRecords,
    runtime,
  };
  writeJson("MVP-UAT-002-memory-ops-live.json", evidence);
  return evidence;
}

async function runLiveEventIntake(page, runtime) {
  await openView(page, "events");
  await page.getByRole("button", { name: "现场智能受理", exact: true }).click();
  const content = "UAT 实时受理：北门游客突发低血糖并短暂晕厥，现场已呼叫医护、疏散围观游客并建立急救通道，请生成分阶段处置建议并记录链路。";
  if (await page.locator("#event-type").isVisible()) await page.locator("#event-type").selectOption({ label: "人员安全" });
  if (await page.locator("#event-severity").isVisible()) await page.locator("#event-severity").selectOption("P0");
  await page.locator("#event-content").fill(content);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "event-01-live-before-submit-1440x900.png"), fullPage: true });
  const startedAt = Date.now();
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      return candidate.request().method() === "POST" && candidate.url().includes("/api/v1/");
    }, { timeout: 30000 }),
    page.locator("#event-form button[type=submit]").click(),
  ]);
  const intake = await response.json();
  if (!response.ok()) throw new Error(`Live event intake returned HTTP ${response.status()}`);
  await page.waitForFunction(() => {
    const status = (document.querySelector("#run-status")?.textContent.trim() || "").toUpperCase();
    const agent = document.querySelector("#run-agent")?.textContent.trim() || "";
    return status && !["QUEUED", "PENDING", "RUNNING", "ACCEPTED", "PROCESSING"].includes(status) && agent !== "路由中";
  }, null, { timeout: 120000 });
  const elapsedMs = Date.now() - startedAt;
  const run = await page.evaluate(() => ({
    status: document.querySelector("#run-status")?.textContent.trim(),
    message_id: document.querySelector("#run-message")?.textContent.trim(),
    trace_id: document.querySelector("#run-trace")?.textContent.trim(),
    session_id: document.querySelector("#run-session")?.textContent.trim(),
    agent: document.querySelector("#run-agent")?.textContent.trim(),
    result: document.querySelector("#run-result")?.textContent.trim(),
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "event-02-live-processed-1440x900.png"), fullPage: true });
  const traceId = run.trace_id || intake.trace_id;
  const [trace, llm, audits, events, sessions] = await Promise.all([
    apiFromPage(page, `/api/v1/admin/traces/${encodeURIComponent(traceId)}`),
    apiFromPage(page, "/api/v1/admin/llm-calls?limit=100"),
    apiFromPage(page, "/api/v1/admin/audit-logs?limit=200"),
    apiFromPage(page, "/api/v1/admin/events?limit=200"),
    apiFromPage(page, "/api/v1/sessions/?limit=200"),
  ]);
  const sessionRecords = (Array.isArray(sessions) ? sessions : (sessions.sessions || [])).filter((item) => {
    return item.session_id === run.session_id || item.id === run.session_id;
  });
  if (!sessionRecords.length) throw new Error(`Live event session ${run.session_id} is missing from the formal client API`);
  if (runtime.consoleErrors.length || runtime.pageErrors.length || runtime.failedRequests.length || runtime.serverErrors.length) {
    throw new Error("Live event browser runtime contains console, page, request or HTTP errors");
  }
  const evidence = {
    uat_id: "MVP-UAT-002",
    operation: "Live event intelligent intake",
    input: { content },
    intake_status: response.status(),
    intake,
    elapsed_ms: elapsedMs,
    run,
    trace,
    llm_calls: (llm.calls || llm.llm_calls || []).filter((item) => item.trace_id === traceId),
    audits: (audits.logs || audits.audit_logs || []).filter((item) => item.trace_id === traceId),
    events: (events.events || []).filter((item) => item.trace_id === traceId || item.raw_text === content),
    sessions: sessionRecords,
    runtime,
  };
  writeJson("MVP-UAT-002-live-event.json", evidence);
  return evidence;
}

async function runSessionLifecycle(page, runtime) {
  const runSuffix = `${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`;
  const content = `UAT 会话生命周期 ${runSuffix}：请基于既有运营经验，给出闭馆前巡检交接应重点核对的三项内容。`;
  let boundaryPage = null;
  let boundaryFixture = null;
  let cleanup = null;
  let lifecycle = null;

  try {
    await openView(page, "events");
    await page.getByRole("button", { name: "现场智能受理", exact: true }).click();
    await page.locator("#event-content").fill(content);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, "session-01-before-create-1440x900.png"), fullPage: true });

    const [intakeResponse] = await Promise.all([
      page.waitForResponse((candidate) => apiResponseMatches(candidate, "POST", "/api/v1/messages/"), { timeout: 30000 }),
      page.locator("#event-form button[type=submit]").click(),
    ]);
    const intake = await intakeResponse.json();
    if (!intakeResponse.ok() || !intake.session_id || !intake.message_id) {
      throw new Error(`Session intake returned HTTP ${intakeResponse.status()} without a complete identity`);
    }

    await page.waitForFunction(() => {
      const status = (document.querySelector("#run-status")?.textContent.trim() || "").toUpperCase();
      return ["COMPLETED", "FAILED"].includes(status);
    }, null, { timeout: 120000 });
    const run = await page.evaluate(() => ({
      status: document.querySelector("#run-status")?.textContent.trim(),
      message_id: document.querySelector("#run-message")?.textContent.trim(),
      trace_id: document.querySelector("#run-trace")?.textContent.trim(),
      session_id: document.querySelector("#run-session")?.textContent.trim(),
      agent: document.querySelector("#run-agent")?.textContent.trim(),
      result: document.querySelector("#run-result")?.textContent.trim(),
    }));
    if (run.status !== "COMPLETED") throw new Error(`Session source message finished as ${run.status}`);
    if (!sameId(run.session_id, intake.session_id) || !sameId(run.message_id, intake.message_id)) {
      throw new Error("Formal client run identifiers do not match the accepted session message");
    }

    const primaryIdentity = await page.evaluate(() => JSON.parse(sessionStorage.getItem("mp_user") || "null"));
    if (!primaryIdentity?.id || !primaryIdentity?.venue_id) throw new Error("Primary client identity is unavailable");
    const messageBefore = await apiFromPage(page, `/api/v1/messages/${encodeURIComponent(intake.message_id)}`);

    await openView(page, "sessions");
    let sessionRow = page.locator("#sessions-table tr").filter({ hasText: intake.session_id });
    await sessionRow.waitFor({ state: "visible", timeout: 30000 });
    if (await sessionRow.count() !== 1) throw new Error(`Expected one formal client row for session ${intake.session_id}`);
    const [sessionsBefore, detailBefore] = await Promise.all([
      apiFromPage(page, "/api/v1/sessions/?limit=200"),
      apiFromPage(page, `/api/v1/sessions/${encodeURIComponent(intake.session_id)}`),
    ]);
    const listRecordBefore = sessionsBefore.find((item) => sameId(item.session_id, intake.session_id));
    if (!listRecordBefore || !sameId(detailBefore.session_id, intake.session_id)) {
      throw new Error("Created session is missing from the formal list or detail endpoint");
    }
    if (!sameId(detailBefore.user_id, primaryIdentity.id) || String(detailBefore.stage).toUpperCase() === "CLOSED") {
      throw new Error("Created session has an unexpected owner or initial stage");
    }
    const rowBeforeText = await sessionRow.innerText();
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, "session-02-list-and-detail-1440x900.png"), fullPage: true });

    const boundaryVenueId = `uat-session-boundary-${runSuffix}`;
    const boundaryUsername = `uat-session-manager-${runSuffix}`;
    const boundaryPassword = `Uat-${randomUUID().replace(/-/g, "")}!aA9`;
    const venueCreated = await requestFromPage(page, "/api/v1/admin/venues", "POST", {
      id: boundaryVenueId,
      name: `会话租户边界 ${runSuffix}`,
    });
    if (venueCreated.status !== 201 || !venueCreated.payload?.venue?.id) {
      throw new Error(`Boundary venue creation returned HTTP ${venueCreated.status}`);
    }
    boundaryFixture = { venue_id: boundaryVenueId, user_id: null };
    const userCreated = await requestFromPage(page, "/api/v1/admin/users", "POST", {
      username: boundaryUsername,
      password: boundaryPassword,
      display_name: `会话边界经理 ${runSuffix}`,
      role: "manager",
      venue_id: boundaryVenueId,
    });
    if (userCreated.status !== 201 || !userCreated.payload?.user?.id) {
      throw new Error(`Boundary manager creation returned HTTP ${userCreated.status}`);
    }
    boundaryFixture.user_id = userCreated.payload.user.id;

    boundaryPage = await page.context().newPage();
    await loginWithCredentials(boundaryPage, boundaryUsername, boundaryPassword);
    const boundaryIdentity = await boundaryPage.evaluate(() => JSON.parse(sessionStorage.getItem("mp_user") || "null"));
    if (!sameId(boundaryIdentity?.id, boundaryFixture.user_id) || boundaryIdentity?.venue_id !== boundaryVenueId) {
      throw new Error("Boundary client identity does not match the provisioned tenant manager");
    }
    const boundaryList = await apiFromPage(boundaryPage, "/api/v1/sessions/?limit=200");
    if (boundaryList.some((item) => sameId(item.session_id, intake.session_id))) {
      throw new Error("Foreign session leaked into the boundary tenant list");
    }
    await openView(boundaryPage, "sessions");
    if ((await boundaryPage.locator("#sessions-table").innerText()).includes(intake.session_id)) {
      throw new Error("Foreign session leaked into the boundary tenant workspace");
    }
    await boundaryPage.screenshot({ path: path.join(SCREENSHOT_DIR, "session-03-tenant-boundary-1440x900.png"), fullPage: true });

    const boundaryRead = await requestFromPage(
      boundaryPage,
      `/api/v1/sessions/${encodeURIComponent(intake.session_id)}`,
      "GET"
    );
    const boundaryClose = await requestFromPage(
      boundaryPage,
      `/api/v1/sessions/${encodeURIComponent(intake.session_id)}`,
      "DELETE"
    );
    if (boundaryRead.status !== 404) throw new Error(`Cross-tenant session read returned HTTP ${boundaryRead.status}`);
    if (boundaryClose.status !== 404 || boundaryClose.payload?.detail?.code !== "SESSION_NOT_FOUND") {
      throw new Error(`Cross-tenant session close returned an unexpected contract (${boundaryClose.status})`);
    }
    const boundaryTraceId = boundaryClose.payload?.detail?.trace_id;
    if (!boundaryTraceId) throw new Error("Cross-tenant session close did not return a trace ID");
    const boundaryAuditsPayload = await apiFromPage(
      boundaryPage,
      `/api/v1/admin/audit-logs?trace_id=${encodeURIComponent(boundaryTraceId)}&limit=50`
    );
    const boundaryAudit = (boundaryAuditsPayload.audit_logs || []).find((item) => {
      return item.action === "SESSION_CLOSE_DENIED"
        && item.outcome === "DENIED"
        && sameId(item.resource_id, intake.session_id);
    });
    if (!boundaryAudit || boundaryAudit.venue_id !== boundaryVenueId || !sameId(boundaryAudit.user_id, boundaryIdentity.id)) {
      throw new Error("Cross-tenant session denial audit is missing or attributed to the wrong tenant");
    }
    const detailAfterBoundary = await apiFromPage(page, `/api/v1/sessions/${encodeURIComponent(intake.session_id)}`);
    if (String(detailAfterBoundary.stage) !== String(detailBefore.stage)) {
      throw new Error("Cross-tenant denial changed the target session stage");
    }

    sessionRow = page.locator("#sessions-table tr").filter({ hasText: intake.session_id });
    await sessionRow.getByRole("button", { name: "关闭", exact: true }).click();
    const actionDialog = page.locator("#action-dialog");
    await actionDialog.waitFor({ state: "visible" });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, "session-04-close-confirmation-1440x900.png"), fullPage: true });
    const [closeResponse] = await Promise.all([
      page.waitForResponse((candidate) => {
        return apiResponseMatches(candidate, "DELETE", `/api/v1/sessions/${encodeURIComponent(intake.session_id)}`);
      }, { timeout: 30000 }),
      actionDialog.locator('button[type="submit"]').click(),
    ]);
    const closed = await closeResponse.json();
    if (!closeResponse.ok() || !sameId(closed.session_id, intake.session_id) || !closed.trace_id) {
      throw new Error(`Formal client session close returned HTTP ${closeResponse.status()} without complete evidence`);
    }
    await actionDialog.waitFor({ state: "hidden" });
    await page.waitForFunction((sessionId) => {
      const row = Array.from(document.querySelectorAll("#sessions-table tr")).find((item) => item.textContent.includes(sessionId));
      const stage = row?.querySelector("td:nth-child(4)")?.textContent.trim().toUpperCase() || "";
      return Boolean(row) && stage.includes("CLOSED") && !row.querySelector("button");
    }, intake.session_id);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, "session-05-closed-1440x900.png"), fullPage: true });

    await page.reload({ waitUntil: "networkidle" });
    await page.waitForFunction(() => {
      return Boolean(sessionStorage.getItem("mp_access_token"))
        && document.querySelector("#app-screen")?.classList.contains("active")
        && document.querySelectorAll("[data-view]").length > 0;
    });
    await openView(page, "sessions");
    const persistedRow = page.locator("#sessions-table tr").filter({ hasText: intake.session_id });
    await persistedRow.waitFor({ state: "visible", timeout: 30000 });
    const [sessionsAfter, detailAfter, messageAfter, closeAuditsPayload] = await Promise.all([
      apiFromPage(page, "/api/v1/sessions/?limit=200"),
      apiFromPage(page, `/api/v1/sessions/${encodeURIComponent(intake.session_id)}`),
      apiFromPage(page, `/api/v1/messages/${encodeURIComponent(intake.message_id)}`),
      apiFromPage(page, `/api/v1/admin/audit-logs?trace_id=${encodeURIComponent(closed.trace_id)}&limit=50`),
    ]);
    const listRecordAfter = sessionsAfter.find((item) => sameId(item.session_id, intake.session_id));
    const closeAudit = (closeAuditsPayload.audit_logs || []).find((item) => {
      return item.action === "SESSION_CLOSED"
        && item.outcome === "SUCCEEDED"
        && sameId(item.resource_id, intake.session_id);
    });
    if (!listRecordAfter || String(listRecordAfter.stage).toUpperCase() !== "CLOSED") {
      throw new Error("Closed session did not persist in the formal client list after refresh");
    }
    if (String(detailAfter.stage).toUpperCase() !== "CLOSED" || !sameId(messageAfter.session_id, intake.session_id)) {
      throw new Error("Closed session detail or message history did not persist after refresh");
    }
    if (await persistedRow.getByRole("button", { name: "关闭", exact: true }).count()) {
      throw new Error("Formal client still offers the close action for a persisted closed session");
    }
    if (!closeAudit || closeAudit.venue_id !== primaryIdentity.venue_id || !sameId(closeAudit.user_id, primaryIdentity.id)) {
      throw new Error("Session close audit is missing or attributed to the wrong actor");
    }
    const rowAfterText = await persistedRow.innerText();
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, "session-06-closed-after-refresh-1440x900.png"), fullPage: true });

    lifecycle = {
      input: { content },
      intake: { response_status: intakeResponse.status(), response: intake },
      run,
      identity: primaryIdentity,
      message: { before: messageBefore, after_refresh: messageAfter },
      session: {
        id: intake.session_id,
        list_before: listRecordBefore,
        detail_before: detailBefore,
        row_before: rowBeforeText,
        detail_after_boundary_denial: detailAfterBoundary,
        close: { response_status: closeResponse.status(), response: closed },
        list_after_refresh: listRecordAfter,
        detail_after_refresh: detailAfter,
        row_after_refresh: rowAfterText,
      },
      audits: { closed: closeAudit, cross_tenant_denied: boundaryAudit },
      tenant_boundary: {
        fixture: {
          venue: venueCreated.payload.venue,
          user: userCreated.payload.user,
        },
        identity: boundaryIdentity,
        list_excludes_target: true,
        client_excludes_target: true,
        read: boundaryRead,
        close: boundaryClose,
        target_stage_unchanged: String(detailAfterBoundary.stage) === String(detailBefore.stage),
      },
      screenshots: [
        "session-01-before-create-1440x900.png",
        "session-02-list-and-detail-1440x900.png",
        "session-03-tenant-boundary-1440x900.png",
        "session-04-close-confirmation-1440x900.png",
        "session-05-closed-1440x900.png",
        "session-06-closed-after-refresh-1440x900.png",
      ],
    };
  } finally {
    if (boundaryPage && !boundaryPage.isClosed()) await boundaryPage.close();
    if (boundaryFixture?.venue_id) {
      try {
        let userDisabled = null;
        if (boundaryFixture.user_id) {
          userDisabled = await requestFromPage(
            page,
            `/api/v1/admin/users/${encodeURIComponent(boundaryFixture.user_id)}`,
            "PATCH",
            { status: "DISABLED" }
          );
        }
        const venueDisabled = await requestFromPage(
          page,
          `/api/v1/admin/venues/${encodeURIComponent(boundaryFixture.venue_id)}`,
          "PATCH",
          { status: "DISABLED" }
        );
        cleanup = {
          passed: (!userDisabled || userDisabled.status === 200) && venueDisabled.status === 200,
          user_status: userDisabled?.status || null,
          venue_status: venueDisabled.status,
          user: userDisabled?.payload?.user || null,
          venue: venueDisabled.payload?.venue || null,
        };
      } catch (error) {
        cleanup = { passed: false, error: error.message };
      }
    }
  }

  if (!lifecycle) throw new Error("Session lifecycle did not produce evidence");
  if (!cleanup?.passed) throw new Error("Boundary fixture was not safely disabled after verification");
  if (runtime.consoleErrors.length || runtime.pageErrors.length || runtime.failedRequests.length || runtime.serverErrors.length) {
    throw new Error("Session lifecycle browser runtime contains console, page, request or HTTP errors");
  }
  const evidence = {
    uat_id: "MVP-UAT-002",
    operation: "Formal client session create, list, detail, close, persistence, audit and tenant boundary",
    ...lifecycle,
    tenant_boundary: { ...lifecycle.tenant_boundary, cleanup },
    runtime,
  };
  writeJson("MVP-UAT-002-session-lifecycle.json", evidence);
  return evidence;
}

async function runHistoricalEventImport(page, runtime) {
  await openView(page, "events");
  await page.getByRole("button", { name: "历史事件补录", exact: true }).click();
  const content = "UAT 历史补录：2026 年 7 月 12 日东区配电间温控告警，值班员更换散热风扇并连续观察三十分钟，设备温度恢复正常。";
  if (await page.locator("#event-type").isVisible()) await page.locator("#event-type").selectOption({ label: "设施故障" });
  if (await page.locator("#event-severity").isVisible()) await page.locator("#event-severity").selectOption("P2");
  await page.locator("#event-content").fill(content);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "event-03-history-before-submit-1440x900.png"), fullPage: true });
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      return candidate.request().method() === "POST" && candidate.url().includes("/api/v1/admin/events");
    }, { timeout: 30000 }),
    page.locator("#event-form button[type=submit]").click(),
  ]);
  const imported = await response.json();
  if (!response.ok()) throw new Error(`Historical event import returned HTTP ${response.status()}`);
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "event-04-history-imported-1440x900.png"), fullPage: true });
  const traceId = imported.trace_id;
  const [events, llm, audits] = await Promise.all([
    apiFromPage(page, "/api/v1/admin/events?limit=200"),
    apiFromPage(page, "/api/v1/admin/llm-calls?limit=100"),
    apiFromPage(page, "/api/v1/admin/audit-logs?limit=200"),
  ]);
  await openView(page, "knowledge");
  await page.locator("#knowledge-vector-query").fill("东区配电间温控告警更换散热风扇");
  const [searchResponse] = await Promise.all([
    page.waitForResponse((candidate) => candidate.url().includes("/api/v1/admin/knowledge/search")),
    page.locator("#view-knowledge form").filter({ has: page.locator("#knowledge-vector-query") }).locator('button[type="submit"]').click(),
  ]);
  const search = await searchResponse.json();
  if (!searchResponse.ok()) throw new Error(`Historical vector search returned HTTP ${searchResponse.status()}`);
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "event-05-history-vector-search-1440x900.png"), fullPage: true });
  const evidence = {
    uat_id: "MVP-UAT-003",
    operation: "Historical event import and semantic retrieval",
    input: { content, event_type: "设施故障", severity: "P2" },
    import_status: response.status(),
    imported,
    events: (events.events || []).filter((item) => item.trace_id === traceId || item.raw_text === content),
    llm_calls: (llm.calls || llm.llm_calls || []).filter((item) => item.trace_id === traceId),
    audits: (audits.logs || audits.audit_logs || []).filter((item) => item.trace_id === traceId),
    search_status: searchResponse.status(),
    search,
    runtime,
  };
  writeJson("MVP-UAT-003-history-event.json", evidence);
  return evidence;
}

async function inspectLatestLiveEventDetails(page, runtime) {
  const source = JSON.parse(fs.readFileSync(path.join(EVIDENCE_DIR, "MVP-UAT-002-live-event.json"), "utf8"));
  const traceId = source.run.trace_id;
  const event = (source.events || []).find((item) => item.trace_id === traceId) || source.events?.[0];
  if (!event) throw new Error("Live event evidence has no event record");
  await openView(page, "events");
  const row = page.locator("#events-table tr").filter({
    has: page.locator("td:nth-child(2)").filter({ hasText: event.event_id }),
  });
  await row.getByRole("button", { name: "详情", exact: true }).click();
  await page.waitForTimeout(250);
  const details = await page.evaluate(() => ({
    visible_candidates: Array.from(document.querySelectorAll('[id*="detail"], dialog[open]')).filter((element) => {
      const style = getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
    }).map((element) => ({
      id: element.id,
      tag: element.tagName,
      text: element.innerText,
      buttons: Array.from(element.querySelectorAll("button")).map((button) => ({
        text: button.textContent.trim(),
        onclick: button.getAttribute("onclick"),
        action: button.getAttribute("data-action"),
      })),
    })),
  }));
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "event-06-live-details-1440x900.png"), fullPage: true });
  writeJson("live-event-details-map.json", { event, details, runtime });
  return { event, details };
}

async function closeLatestLiveEvent(page, runtime) {
  const source = JSON.parse(fs.readFileSync(path.join(EVIDENCE_DIR, "MVP-UAT-002-live-event.json"), "utf8"));
  const traceId = source.run.trace_id;
  const event = (source.events || []).find((item) => item.trace_id === traceId) || source.events?.[0];
  if (!event) throw new Error("Live event evidence has no event record");
  await openView(page, "events");
  const row = page.locator("#events-table tr").filter({
    has: page.locator("td:nth-child(2)").filter({ hasText: event.event_id }),
  });
  await row.getByRole("button", { name: "详情", exact: true }).click();
  await page.locator("#details").waitFor({ state: "visible" });
  await page.locator("#details").getByRole("button", { name: "闭环事件", exact: true }).click();
  const dialog = page.locator("#action-dialog");
  await dialog.waitFor({ state: "visible" });
  const resolution = "现场医护到达后完成血糖检测与补糖处置，游客意识恢复并由家属陪同离场；急救通道恢复，值班经理复核记录与时间戳齐全。";
  await dialog.locator("textarea, input:not([type=hidden])").first().fill(resolution);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "POST" && candidate.url().includes(`/api/v1/admin/events/${event.event_id}/close`)),
    dialog.locator('button[type="submit"]').click(),
  ]);
  const payload = await response.json();
  if (!response.ok()) throw new Error(`Event close returned HTTP ${response.status()}`);
  await dialog.waitFor({ state: "hidden" });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "event-07-live-closed-1440x900.png"), fullPage: true });
  const [events, audits] = await Promise.all([
    apiFromPage(page, "/api/v1/admin/events?limit=200"),
    apiFromPage(page, "/api/v1/admin/audit-logs?limit=200"),
  ]);
  const evidence = {
    uat_id: "MVP-UAT-005",
    operation: "Close live event with resolution",
    event_id: event.event_id,
    resolution,
    response_status: response.status(),
    response: payload,
    event: (events.events || []).find((item) => item.event_id === event.event_id),
    audits: (audits.logs || audits.audit_logs || []).filter((item) => item.resource_id === event.event_id || item.trace_id === payload.trace_id),
    runtime,
  };
  writeJson("MVP-UAT-005-event-close.json", evidence);
  return evidence;
}

async function runKnowledgeSopLifecycle(page, runtime) {
  const closed = JSON.parse(fs.readFileSync(path.join(EVIDENCE_DIR, "MVP-UAT-005-event-close.json"), "utf8"));
  const eventId = closed.event_id;
  const runId = Date.now().toString(36);
  const knowledgeTitle = `北门低血糖应急处置基线（UAT ${runId}）`;
  const knowledgeContentV1 = "发现游客疑似低血糖并出现意识障碍时，现场人员应保持患者平卧、立即呼叫医护并疏散围观人员，确保急救通道持续畅通，同时记录处置时间线。";
  const knowledgeContentV2 = `${knowledgeContentV1} 医护到场后补充记录血糖检测、补糖处置、意识恢复时间和离场交接人，由值班经理复核。`;

  await openView(page, "knowledge");
  await page.locator('#view-knowledge [data-action="new-knowledge"]').click();
  let dialog = page.locator("#knowledge-dialog");
  await dialog.waitFor({ state: "visible" });
  await dialog.locator("#knowledge-title").fill(knowledgeTitle);
  await dialog.locator("#knowledge-category").fill("人员安全");
  await dialog.locator("#knowledge-tags").fill("低血糖,急救通道,UAT");
  await dialog.locator("#knowledge-content").fill(knowledgeContentV1);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "knowledge-01-create-1440x900.png"), fullPage: true });
  let response;
  [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "POST" && /\/api\/v1\/admin\/knowledge$/.test(candidate.url())),
    dialog.locator('button[type="submit"]').click(),
  ]);
  const knowledgeCreated = await response.json();
  if (!response.ok()) throw new Error(`Knowledge create returned HTTP ${response.status()}`);
  await dialog.waitFor({ state: "hidden" });
  await page.waitForTimeout(400);

  let knowledgeRow = page.locator("#knowledge-table tr").filter({ hasText: knowledgeTitle });
  await knowledgeRow.getByRole("button", { name: "编辑", exact: true }).click();
  await dialog.waitFor({ state: "visible" });
  const knowledgeId = await dialog.locator("#knowledge-id").inputValue();
  await dialog.locator("#knowledge-content").fill(knowledgeContentV2);
  [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "PUT" && candidate.url().includes(`/api/v1/admin/knowledge/${knowledgeId}`)),
    dialog.locator('button[type="submit"]').click(),
  ]);
  const knowledgeUpdated = await response.json();
  if (!response.ok()) throw new Error(`Knowledge update returned HTTP ${response.status()}`);
  await dialog.waitFor({ state: "hidden" });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "knowledge-02-version-2-1440x900.png"), fullPage: true });

  await page.locator('#view-knowledge [data-action="knowledge-rebuild"]').click();
  const rebuildDialog = page.locator("#action-dialog");
  await rebuildDialog.waitFor({ state: "visible" });
  [response] = await Promise.all([
    page.waitForResponse((candidate) => apiResponseMatches(candidate, "POST", "/api/v1/admin/knowledge/rebuild-index"), { timeout: 60000 }),
    rebuildDialog.locator('button[type="submit"]').click(),
  ]);
  const knowledgeRebuilt = await response.json();
  if (!response.ok()) throw new Error(`Knowledge index rebuild returned HTTP ${response.status()}`);
  if (!Number.isInteger(knowledgeRebuilt.rebuilt) || knowledgeRebuilt.rebuilt < 1) throw new Error("Knowledge index rebuild returned no persisted documents");
  await rebuildDialog.waitFor({ state: "hidden" });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "knowledge-03-index-rebuilt-1440x900.png"), fullPage: true });

  await page.locator("#knowledge-vector-query").fill("北门低血糖游客意识恢复和值班经理复核");
  let searchResponse;
  [searchResponse] = await Promise.all([
    page.waitForResponse((candidate) => candidate.url().includes("/api/v1/admin/knowledge/search")),
    page.locator("#view-knowledge form").filter({ has: page.locator("#knowledge-vector-query") }).locator('button[type="submit"]').click(),
  ]);
  const knowledgeSearch = await searchResponse.json();
  if (!searchResponse.ok()) throw new Error(`Knowledge search returned HTTP ${searchResponse.status()}`);
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "knowledge-04-semantic-search-1440x900.png"), fullPage: true });

  const sopTitle = `北门低血糖游客应急处置 SOP（UAT ${runId}）`;
  const sopContentV1 = "1. 识别疑似低血糖与意识状态；2. 保持患者平卧并呼叫医护；3. 疏散围观并保持急救通道；4. 连续记录处置时间线；5. 医护到场后完成交接。";
  const sopContentV2 = `${sopContentV1}\n6. 记录血糖检测、补糖、意识恢复与离场信息；7. 值班经理复核并关闭事件。`;
  const sopContentV3 = `${sopContentV2}\n8. 发布前由值班经理核对来源事件、责任人和时间戳，驳回意见必须逐项关闭。`;
  await openView(page, "sops");
  await page.locator('#view-sops [data-action="new-sop"]').click();
  dialog = page.locator("#sop-dialog");
  await dialog.waitFor({ state: "visible" });
  await dialog.locator("#sop-title").fill(sopTitle);
  await dialog.locator("#sop-category").fill("人员安全");
  await dialog.locator("#sop-priority").fill("1");
  await dialog.locator("#sop-source-event").fill(eventId);
  await dialog.locator("#sop-content").fill(sopContentV1);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "sop-01-create-draft-1440x900.png"), fullPage: true });
  [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "POST" && /\/api\/v1\/admin\/sops$/.test(candidate.url())),
    dialog.locator('button[type="submit"]').click(),
  ]);
  const sopCreated = await response.json();
  if (!response.ok()) throw new Error(`SOP create returned HTTP ${response.status()}`);
  await dialog.waitFor({ state: "hidden" });
  await page.waitForTimeout(400);

  let sopRow = page.locator("#sops-table tr").filter({ hasText: sopTitle });
  await sopRow.getByRole("button", { name: "编辑", exact: true }).click();
  await dialog.waitFor({ state: "visible" });
  const sopId = await dialog.locator("#sop-id").inputValue();
  await dialog.locator("#sop-content").fill(sopContentV2);
  await dialog.locator("#sop-change-note").fill("UAT v1.1：补充医护处置记录和值班经理复核步骤");
  [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "PUT" && candidate.url().includes(`/api/v1/admin/sops/${sopId}`)),
    dialog.locator('button[type="submit"]').click(),
  ]);
  const sopUpdated = await response.json();
  if (!response.ok()) throw new Error(`SOP update returned HTTP ${response.status()}`);
  await dialog.waitFor({ state: "hidden" });
  await page.waitForTimeout(400);

  sopRow = page.locator("#sops-table tr").filter({ hasText: sopTitle });
  [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "POST" && candidate.url().includes(`/api/v1/admin/sops/${sopId}/submit`)),
    sopRow.getByRole("button", { name: "提交审核", exact: true }).click(),
  ]);
  const sopSubmitted = await response.json();
  if (!response.ok()) throw new Error(`SOP submit returned HTTP ${response.status()}`);
  await page.waitForTimeout(400);

  sopRow = page.locator("#sops-table tr").filter({ hasText: sopTitle });
  await sopRow.getByRole("button", { name: "驳回", exact: true }).click();
  const actionDialog = page.locator("#action-dialog");
  await actionDialog.waitFor({ state: "visible" });
  const comment = actionDialog.locator("textarea, input:not([type=hidden])").first();
  await comment.fill("UAT 驳回：补充发布前的来源事件、责任人和时间戳复核步骤");
  [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "POST" && candidate.url().includes(`/api/v1/admin/sops/${sopId}/reject`)),
    actionDialog.locator('button[type="submit"]').click(),
  ]);
  const sopRejected = await response.json();
  if (!response.ok()) throw new Error(`SOP reject returned HTTP ${response.status()}`);
  if (sopRejected.sop?.status !== "REJECTED") throw new Error("SOP did not persist the REJECTED state");
  await actionDialog.waitFor({ state: "hidden" });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "sop-02-rejected-1440x900.png"), fullPage: true });

  sopRow = page.locator("#sops-table tr").filter({ hasText: sopTitle });
  await sopRow.getByRole("button", { name: "编辑", exact: true }).click();
  await dialog.waitFor({ state: "visible" });
  await dialog.locator("#sop-content").fill(sopContentV3);
  await dialog.locator("#sop-change-note").fill("UAT v1.2：落实驳回意见，补充发布前复核步骤");
  [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "PUT" && candidate.url().includes(`/api/v1/admin/sops/${sopId}`)),
    dialog.locator('button[type="submit"]').click(),
  ]);
  const sopRevised = await response.json();
  if (!response.ok()) throw new Error(`Rejected SOP revision returned HTTP ${response.status()}`);
  if (sopRevised.sop?.status !== "DRAFT") throw new Error("Rejected SOP revision did not return to DRAFT");
  await dialog.waitFor({ state: "hidden" });
  await page.waitForTimeout(400);

  sopRow = page.locator("#sops-table tr").filter({ hasText: sopTitle });
  [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "POST" && candidate.url().includes(`/api/v1/admin/sops/${sopId}/submit`)),
    sopRow.getByRole("button", { name: "提交审核", exact: true }).click(),
  ]);
  const sopResubmitted = await response.json();
  if (!response.ok()) throw new Error(`Revised SOP submit returned HTTP ${response.status()}`);
  if (sopResubmitted.sop?.status !== "IN_REVIEW") throw new Error("Revised SOP did not return to IN_REVIEW");
  await page.waitForTimeout(400);

  sopRow = page.locator("#sops-table tr").filter({ hasText: sopTitle });
  await sopRow.getByRole("button", { name: "发布", exact: true }).click();
  await actionDialog.waitFor({ state: "visible" });
  const publishComment = actionDialog.locator("textarea, input:not([type=hidden])").first();
  if (await publishComment.count()) await publishComment.fill("UAT 复审通过：驳回意见已关闭，步骤、来源事件和版本记录齐全");
  [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "POST" && candidate.url().includes(`/api/v1/admin/sops/${sopId}/publish`)),
    actionDialog.locator('button[type="submit"]').click(),
  ]);
  const sopPublished = await response.json();
  if (!response.ok()) throw new Error(`SOP publish returned HTTP ${response.status()}`);
  if (sopPublished.sop?.status !== "PUBLISHED") throw new Error("Revised SOP was not published");
  await actionDialog.waitFor({ state: "hidden" });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "sop-03-revised-published-1440x900.png"), fullPage: true });

  await openView(page, "knowledge");
  await page.locator("#knowledge-vector-query").fill("低血糖游客急救通道和值班经理复核 SOP");
  [searchResponse] = await Promise.all([
    page.waitForResponse((candidate) => candidate.url().includes("/api/v1/admin/knowledge/search")),
    page.locator("#view-knowledge form").filter({ has: page.locator("#knowledge-vector-query") }).locator('button[type="submit"]').click(),
  ]);
  const sopSearch = await searchResponse.json();
  if (!searchResponse.ok()) throw new Error(`Published SOP search returned HTTP ${searchResponse.status()}`);
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "sop-04-published-search-1440x900.png"), fullPage: true });

  const [knowledgePayload, sopsPayload, auditsPayload] = await Promise.all([
    apiFromPage(page, "/api/v1/admin/knowledge?limit=200"),
    apiFromPage(page, "/api/v1/admin/sops"),
    apiFromPage(page, "/api/v1/admin/audit-logs?limit=500"),
  ]);
  const knowledgeRecords = (knowledgePayload.knowledge || []).filter((item) => sameId(item.id, knowledgeId) || item.title === sopTitle);
  const sopRecords = (sopsPayload.sops || []).filter((item) => sameId(item.id, sopId));
  const operationTraceIds = new Set([
    knowledgeCreated.trace_id,
    knowledgeUpdated.trace_id,
    knowledgeRebuilt.trace_id,
    sopCreated.trace_id,
    sopUpdated.trace_id,
    sopSubmitted.trace_id,
    sopRejected.trace_id,
    sopRevised.trace_id,
    sopResubmitted.trace_id,
    sopPublished.trace_id,
  ].filter(Boolean));
  const operationAudits = (auditsPayload.logs || auditsPayload.audit_logs || []).filter((item) => {
    return sameId(item.resource_id, knowledgeId) || sameId(item.resource_id, sopId) || operationTraceIds.has(item.trace_id);
  });
  const requiredAuditActions = ["KNOWLEDGE_CREATED", "KNOWLEDGE_UPDATED", "KNOWLEDGE_INDEX_REBUILT", "SOP_CREATED", "SOP_UPDATED", "SOP_SUBMITTED", "SOP_REJECTED", "SOP_PUBLISHED"];
  const auditActions = new Set(operationAudits.filter((item) => item.outcome === "SUCCEEDED").map((item) => item.action));
  const missingAuditActions = requiredAuditActions.filter((action) => !auditActions.has(action));
  if (missingAuditActions.length) throw new Error(`Knowledge/SOP audits are missing: ${missingAuditActions.join(", ")}`);
  const persistedKnowledge = knowledgeRecords.find((item) => sameId(item.id, knowledgeId));
  const persistedSop = sopRecords.find((item) => sameId(item.id, sopId));
  if (!persistedKnowledge || persistedKnowledge.content !== knowledgeContentV2 || Number(persistedKnowledge.version) < 2) {
    throw new Error("Updated knowledge content/version is not persisted");
  }
  if (!persistedSop || persistedSop.status !== "PUBLISHED" || persistedSop.content !== sopContentV3) {
    throw new Error("Revised SOP is not persisted as PUBLISHED");
  }
  if (runtime.consoleErrors.length || runtime.pageErrors.length || runtime.failedRequests.length || runtime.serverErrors.length) {
    throw new Error("Knowledge/SOP browser runtime contains console, page, request or HTTP errors");
  }
  const evidence = {
    uat_id: "MVP-UAT-005",
    operation: "Knowledge and SOP version, review, publish and reuse",
    event_id: eventId,
    knowledge: { id: knowledgeId, created: knowledgeCreated, updated: knowledgeUpdated, rebuilt: knowledgeRebuilt, search: knowledgeSearch },
    sop: {
      id: sopId,
      created: sopCreated,
      updated: sopUpdated,
      submitted: sopSubmitted,
      rejected: sopRejected,
      revised: sopRevised,
      resubmitted: sopResubmitted,
      published: sopPublished,
      search: sopSearch,
    },
    knowledge_records: knowledgeRecords,
    sop_records: sopRecords,
    audits: operationAudits,
    runtime,
  };
  writeJson("MVP-UAT-005-knowledge-sop.json", evidence);
  return evidence;
}

async function probeExactKnowledgeSearch(page, runtime) {
  const query = "北门低血糖游客应急处置 SOP UAT 记录血糖检测 补糖 意识恢复 值班经理复核";
  const result = await requestFromPage(page, "/api/v1/admin/knowledge/search", "POST", {
    query,
    top_k: 20,
    threshold: 0.1,
  });
  if (result.status !== 200) throw new Error(`Exact knowledge search returned HTTP ${result.status}`);
  const matches = (result.payload.results || []).filter((item) => {
    return item.metadata?.title?.includes("北门低血糖") || item.id?.includes("sop:venue-uat:2") || item.id?.includes("bf8da10bf36b4272806c12cb6060bc25");
  });
  writeJson("MVP-UAT-005-exact-search-probe.json", { query, result, matches, runtime });
  return { result, matches };
}

async function runPersonaLifecycle(page, runtime) {
  const runId = Date.now().toString(36);
  const jobTitle = `景区北门应急值班专家（UAT ${runId}）`;
  const description = "沉淀游客突发低血糖、急救通道组织、医护交接和事件闭环经验。";
  await openView(page, "persona");
  await page.locator('#view-persona [data-action="new-persona"]').click();
  const createDialog = page.locator("#persona-dialog");
  await createDialog.waitFor({ state: "visible" });
  await createDialog.locator("#persona-title").fill(jobTitle);
  await createDialog.locator("#persona-description").fill(description);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "persona-01-create-1440x900.png"), fullPage: true });
  const startPromise = page.waitForResponse((candidate) => candidate.request().method() === "POST" && candidate.url().includes("/interview/start"), { timeout: 30000 });
  const [createResponse] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "POST" && /\/api\/v1\/admin\/personas$/.test(candidate.url())),
    createDialog.locator('button[type="submit"]').click(),
  ]);
  const created = await createResponse.json();
  if (!createResponse.ok()) throw new Error(`Persona create returned HTTP ${createResponse.status()}`);
  const startResponse = await startPromise;
  const started = await startResponse.json();
  if (!startResponse.ok()) throw new Error(`Persona interview start returned HTTP ${startResponse.status()}`);
  const personaId = created.persona_id || created.persona?.id;
  const interviewId = started.interview_id;
  const chatDialog = page.locator("#persona-chat-dialog");
  await chatDialog.waitFor({ state: "visible" });

  const answers = [
    "先确认游客意识、呼吸和是否能够安全吞咽，同时让同事呼叫医护并清理急救通道，避免围观影响处置。",
    "游客意识不清、抽搐或呼吸异常就是必须升级的信号，我会立即呼叫120和上级；只有意识清醒且能够吞咽时才提供含糖饮料。",
    "我刚值班时只口头通知医护，没有记录发现和呼叫时间，导致事后交接无法还原。现在固定安排一人记录时间线和现场负责人。",
    "常规思路是马上把晕倒游客搬走，但只要现场没有继续危险，我会先原地隔离、评估并等待医护，避免错误搬动造成二次伤害。",
  ];
  const responses = [];

  const submitAnswer = async (answer) => {
    await chatDialog.locator("#persona-chat-input").fill(answer);
    const [response] = await Promise.all([
      page.waitForResponse((candidate) => candidate.request().method() === "POST" && candidate.url().includes("/interview/continue"), { timeout: 60000 }),
      chatDialog.locator("#persona-chat-form button[type=submit]").click(),
    ]);
    const payload = await response.json();
    if (!response.ok()) throw new Error(`Persona interview continue returned HTTP ${response.status()}`);
    responses.push(payload);
    return payload;
  };

  let latest = await submitAnswer(answers[0]);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "persona-02-after-first-answer-1440x900.png"), fullPage: true });
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForFunction(() => Boolean(sessionStorage.getItem("mp_access_token")) && document.querySelectorAll("[data-view]").length > 0);
  await openView(page, "persona");
  await page.locator(`#persona-cards button[onclick^="App.openPersona"][onclick*="${personaId}"]`).click();
  await chatDialog.waitFor({ state: "visible" });
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "persona-03-resumed-after-refresh-1440x900.png"), fullPage: true });

  for (let index = 1; index < answers.length && !(latest.prompt_finalize || latest.stage === "summary"); index += 1) {
    latest = await submitAnswer(answers[index]);
  }
  if (!(latest.prompt_finalize || latest.stage === "summary")) throw new Error("Persona interview did not reach finalize stage");
  await page.locator("#persona-finalize").waitFor({ state: "visible" });
  const [finalizeResponse] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "POST" && candidate.url().includes("/interview/finalize"), { timeout: 60000 }),
    page.locator("#persona-finalize").click(),
  ]);
  const finalized = await finalizeResponse.json();
  if (!finalizeResponse.ok()) throw new Error(`Persona finalize returned HTTP ${finalizeResponse.status()}`);

  const question = "北门游客疑似低血糖且意识不清时，现场人员最重要的前三步是什么？";
  await chatDialog.locator("#persona-chat-input").fill(question);
  const [chatResponse] = await Promise.all([
    page.waitForResponse((candidate) => candidate.request().method() === "POST" && candidate.url().includes(`/personas/${personaId}/chat`), { timeout: 60000 }),
    chatDialog.locator("#persona-chat-form button[type=submit]").click(),
  ]);
  const answer = await chatResponse.json();
  if (!chatResponse.ok()) throw new Error(`Persona chat returned HTTP ${chatResponse.status()}`);
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "persona-04-authorized-answer-1440x900.png"), fullPage: true });

  await chatDialog.locator('button[type="button"]').filter({ hasText: "关闭" }).click();
  await page.waitForTimeout(250);
  await page.locator("#persona-search").fill(jobTitle);
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "persona-05-search-1440x900.png"), fullPage: true });

  const [personasPayload, llmPayload] = await Promise.all([
    apiFromPage(page, "/api/v1/admin/personas"),
    apiFromPage(page, "/api/v1/admin/llm-calls?limit=200"),
  ]);
  const personaBeforeDelete = (personasPayload.personas || []).find((item) => item.id === personaId);
  if (!personaBeforeDelete) throw new Error("Persona is missing before deletion");
  const personaCard = page.locator("#persona-cards article.record").filter({ hasText: jobTitle });
  if (await personaCard.count() !== 1) throw new Error("Formal client search did not isolate the created persona");
  await personaCard.getByRole("button", { name: "删除", exact: true }).click();
  const actionDialog = page.locator("#action-dialog");
  await actionDialog.waitFor({ state: "visible" });
  const [deleteResponse] = await Promise.all([
    page.waitForResponse((candidate) => apiResponseMatches(candidate, "DELETE", `/api/v1/admin/personas/${personaId}`), { timeout: 30000 }),
    actionDialog.locator('button[type="submit"]').click(),
  ]);
  const deleted = await deleteResponse.json();
  if (!deleteResponse.ok()) throw new Error(`Persona delete returned HTTP ${deleteResponse.status()}`);
  if (deleted.deleted !== true || deleted.persona_id !== personaId) throw new Error("Persona delete response is incomplete");
  await actionDialog.waitFor({ state: "hidden" });
  await personaCard.waitFor({ state: "detached" });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "persona-06-deleted-1440x900.png"), fullPage: true });

  const [postDeletePersonasPayload, auditsPayload] = await Promise.all([
    apiFromPage(page, "/api/v1/admin/personas"),
    apiFromPage(page, "/api/v1/admin/audit-logs?limit=300"),
  ]);
  const postDeletePersona = (postDeletePersonasPayload.personas || []).find((item) => item.id === personaId);
  if (postDeletePersona) throw new Error("Deleted persona still exists in the formal client API");
  const traceIds = new Set([started.trace_id, ...responses.map((item) => item.trace_id), finalized.trace_id, answer.trace_id].filter(Boolean));
  const personaAudits = (auditsPayload.logs || auditsPayload.audit_logs || []).filter((item) => item.resource_id === personaId || traceIds.has(item.trace_id));
  if (!personaAudits.some((item) => item.action === "PERSONA_DELETED" && item.outcome === "SUCCEEDED")) {
    throw new Error("Persona deletion audit is missing");
  }
  if (runtime.consoleErrors.length || runtime.pageErrors.length || runtime.failedRequests.length || runtime.serverErrors.length) {
    throw new Error("Persona lifecycle browser runtime contains console, page, request or HTTP errors");
  }
  const evidence = {
    uat_id: "MVP-UAT-006",
    operation: "Persona create, interview persistence, extraction, authorized Q&A, search and deletion",
    persona_id: personaId,
    interview_id: interviewId,
    created,
    started,
    responses,
    resumed_after_refresh: true,
    finalized,
    question,
    answer,
    persona: personaBeforeDelete,
    deletion: { response_status: deleteResponse.status(), response: deleted },
    deleted_from_client: await personaCard.count() === 0,
    post_delete_persona: postDeletePersona || null,
    llm_calls: (llmPayload.calls || llmPayload.llm_calls || []).filter((item) => traceIds.has(item.trace_id)),
    audits: personaAudits,
    runtime,
  };
  writeJson("MVP-UAT-006-persona-lifecycle.json", evidence);
  return evidence;
}

function apiResponseMatches(response, method, pathname) {
  try {
    return response.request().method() === method && new URL(response.url()).pathname === pathname;
  } catch {
    return false;
  }
}

async function getExactPolicyCard(page, policyId, policyName) {
  const card = page.locator("#policy-cards article.record").filter({
    has: page.locator(`button[onclick*="${policyId}"]`),
  }).filter({
    has: page.getByRole("heading", { name: policyName, exact: true }),
  });
  await card.waitFor({ state: "visible", timeout: 30000 });
  const count = await card.count();
  if (count !== 1) throw new Error(`Expected one policy card for ${policyId}/${policyName}, found ${count}`);
  return card;
}

async function getExactFindingRow(page, findingId) {
  const finding = await page.evaluate((targetId) => {
    const items = window.App?.state?.findings || [];
    const index = items.findIndex((item) => String(item.id) === String(targetId));
    return index < 0 ? null : { index, item: items[index] };
  }, findingId);
  if (!finding) throw new Error(`Finding ${findingId} is not present in the Watcher client state`);
  const row = page.locator("#findings-table tr").nth(finding.index);
  await row.waitFor({ state: "visible", timeout: 30000 });
  return { row, item: finding.item };
}

async function captureWatcherScreenshot(page, locator, filename) {
  await locator.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, filename), fullPage: false });
  return filename;
}

async function runWatcherLifecycle(page, runtime) {
  const suffix = `${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`;
  const policyName = `UAT 鹰眼闭环 ${suffix}`;
  const updatedPolicyName = `${policyName} 已复核`;
  const description = "验证正式客户端的 Watcher 策略、真实模型巡检、发现分配与关闭闭环。";
  const updatedDescription = `${description} 已完成责任人和处理结果复核。`;
  const resolution = `UAT ${suffix}：值班人员已核对来源记录、补充处理结果并完成闭环复核。`;
  const screenshots = [];

  await openView(page, "watcher");
  await page.locator('#view-watcher [data-action="new-policy"]').click();
  const policyDialog = page.locator("#policy-dialog");
  await policyDialog.waitFor({ state: "visible" });
  await policyDialog.locator("#policy-name").fill(policyName);
  await policyDialog.locator("#policy-description").fill(description);
  await policyDialog.locator("#policy-cron").fill("*/15 * * * *");
  await policyDialog.locator("#policy-types").fill("SLA,TASK,SOP");
  await policyDialog.locator("#policy-enabled").selectOption("true");
  screenshots.push(await captureWatcherScreenshot(page, policyDialog, "watcher-01-policy-create-1440x900.png"));

  const createPath = "/api/v1/admin/watcher/policies";
  const [createResponse] = await Promise.all([
    page.waitForResponse((candidate) => apiResponseMatches(candidate, "POST", createPath), { timeout: 30000 }),
    policyDialog.locator('button[type="submit"]').click(),
  ]);
  const created = await createResponse.json();
  if (!createResponse.ok()) throw new Error(`Watcher policy create returned HTTP ${createResponse.status()}`);
  const policyId = created.policy?.id;
  if (!policyId || created.policy?.name !== policyName || created.policy?.enabled !== true) {
    throw new Error("Watcher policy create response does not match the submitted policy");
  }
  await policyDialog.waitFor({ state: "hidden", timeout: 10000 });
  const createdCard = await getExactPolicyCard(page, policyId, policyName);
  screenshots.push(await captureWatcherScreenshot(page, createdCard, "watcher-02-policy-created-1440x900.png"));

  const runPath = `/api/v1/admin/watcher/policies/${policyId}/run`;
  const [runResponse] = await Promise.all([
    page.waitForResponse((candidate) => apiResponseMatches(candidate, "POST", runPath), { timeout: 180000 }),
    createdCard.getByRole("button", { name: "立即运行", exact: true }).click(),
  ]);
  const run = await runResponse.json();
  if (!runResponse.ok()) throw new Error(`Watcher manual run returned HTTP ${runResponse.status()}`);
  if (run.status !== "SUCCEEDED" || !(run.target_count > 0) || !(run.finding_count > 0) || run.model !== "deepseek-v4-flash") {
    throw new Error(`Watcher run evidence is incomplete: status=${run.status}, targets=${run.target_count}, findings=${run.finding_count}, model=${run.model}`);
  }
  if (!run.run_id || !run.trace_id || !Array.isArray(run.findings) || !run.findings.length) {
    throw new Error("Watcher run did not return run, trace, and finding identifiers");
  }
  await page.waitForFunction(({ runId, policyId: targetPolicyId }) => {
    const runs = window.App?.state?.runs || [];
    return runs.some((item) => String(item.id) === String(runId) && String(item.policy_id) === String(targetPolicyId));
  }, { runId: run.run_id, policyId }, { timeout: 30000 });
  const runRowIndex = await page.evaluate((runId) => {
    return (window.App?.state?.runs || []).findIndex((item) => String(item.id) === String(runId));
  }, run.run_id);
  if (runRowIndex < 0) throw new Error(`Watcher run ${run.run_id} is not present in the client`);
  const runRow = page.locator("#watcher-runs-table tr").nth(runRowIndex);
  screenshots.push(await captureWatcherScreenshot(page, runRow, "watcher-03-run-completed-1440x900.png"));

  const findingId = run.findings[0].id;
  await page.waitForFunction((targetId) => {
    return (window.App?.state?.findings || []).some((item) => String(item.id) === String(targetId));
  }, findingId, { timeout: 30000 });
  let exactFinding = await getExactFindingRow(page, findingId);
  if (String(exactFinding.item.run_id) !== String(run.run_id) || String(exactFinding.item.policy_id) !== String(policyId)) {
    throw new Error(`Finding ${findingId} does not belong to run ${run.run_id} and policy ${policyId}`);
  }
  screenshots.push(await captureWatcherScreenshot(page, exactFinding.row, "watcher-04-finding-created-1440x900.png"));

  const assigneesPayload = await apiFromPage(page, "/api/v1/admin/assignees");
  const assignee = (assigneesPayload.assignees || [])[0];
  if (!assignee?.id || !assignee?.venue_id) throw new Error("No active current-venue assignee is available for Watcher UAT");

  const openFindingRow = page.locator("#findings-table tr").filter({
    has: page.locator(`button[onclick*="${findingId}"]`),
  });
  await openFindingRow.waitFor({ state: "visible" });
  if (await openFindingRow.count() !== 1) throw new Error(`Expected one actionable finding row for ${findingId}`);
  await openFindingRow.getByRole("button", { name: "处理", exact: true }).click();
  const actionDialog = page.locator("#action-dialog");
  await actionDialog.waitFor({ state: "visible" });
  await actionDialog.locator("#action-field-assigned_to").selectOption(assignee.id);
  const assignPath = `/api/v1/admin/watcher/findings/${findingId}`;
  const [assignResponse] = await Promise.all([
    page.waitForResponse((candidate) => apiResponseMatches(candidate, "PATCH", assignPath), { timeout: 30000 }),
    actionDialog.locator("#action-dialog-submit").click(),
  ]);
  const assigned = await assignResponse.json();
  if (!assignResponse.ok()) throw new Error(`Watcher finding assignment returned HTTP ${assignResponse.status()}`);
  if (String(assigned.finding?.id) !== String(findingId) || String(assigned.finding?.assigned_to) !== String(assignee.id) || assigned.finding?.status !== "IN_PROGRESS") {
    throw new Error(`Watcher finding ${findingId} was not assigned to ${assignee.id}`);
  }
  await actionDialog.waitFor({ state: "hidden", timeout: 10000 });
  await page.waitForFunction(({ findingId: targetId, assigneeId }) => {
    return (window.App?.state?.findings || []).some((item) => {
      return String(item.id) === String(targetId) && String(item.assigned_to) === String(assigneeId) && item.status === "IN_PROGRESS";
    });
  }, { findingId, assigneeId: assignee.id }, { timeout: 30000 });
  exactFinding = await getExactFindingRow(page, findingId);
  screenshots.push(await captureWatcherScreenshot(page, exactFinding.row, "watcher-05-finding-assigned-1440x900.png"));

  const assignedFindingRow = page.locator("#findings-table tr").filter({
    has: page.locator(`button[onclick*="${findingId}"]`),
  });
  await assignedFindingRow.getByRole("button", { name: "关闭", exact: true }).click();
  await actionDialog.waitFor({ state: "visible" });
  await actionDialog.locator("#action-field-resolution").fill(resolution);
  const closePath = `/api/v1/admin/watcher/findings/${findingId}/close`;
  const [closeResponse] = await Promise.all([
    page.waitForResponse((candidate) => apiResponseMatches(candidate, "POST", closePath), { timeout: 30000 }),
    actionDialog.locator("#action-dialog-submit").click(),
  ]);
  const closed = await closeResponse.json();
  if (!closeResponse.ok()) throw new Error(`Watcher finding close returned HTTP ${closeResponse.status()}`);
  if (String(closed.finding_id) !== String(findingId) || closed.closed !== true) {
    throw new Error(`Watcher finding close response does not match ${findingId}`);
  }
  await actionDialog.waitFor({ state: "hidden", timeout: 10000 });
  await page.waitForFunction((targetId) => {
    return (window.App?.state?.findings || []).some((item) => String(item.id) === String(targetId) && item.status === "CLOSED");
  }, findingId, { timeout: 30000 });
  exactFinding = await getExactFindingRow(page, findingId);
  screenshots.push(await captureWatcherScreenshot(page, exactFinding.row, "watcher-06-finding-closed-1440x900.png"));

  let policyCard = await getExactPolicyCard(page, policyId, policyName);
  await policyCard.getByRole("button", { name: "编辑", exact: true }).click();
  await policyDialog.waitFor({ state: "visible" });
  if (await policyDialog.locator("#policy-id").inputValue() !== policyId) {
    throw new Error(`Policy edit dialog opened an unexpected policy instead of ${policyId}`);
  }
  await policyDialog.locator("#policy-name").fill(updatedPolicyName);
  await policyDialog.locator("#policy-description").fill(updatedDescription);
  await policyDialog.locator("#policy-cron").fill("* * * * *");
  await policyDialog.locator("#policy-types").fill("SLA,TASK");
  await policyDialog.locator("#policy-enabled").selectOption("true");
  const updatePath = `/api/v1/admin/watcher/policies/${policyId}`;
  const [updateResponse] = await Promise.all([
    page.waitForResponse((candidate) => apiResponseMatches(candidate, "PUT", updatePath), { timeout: 30000 }),
    policyDialog.locator('button[type="submit"]').click(),
  ]);
  const updated = await updateResponse.json();
  if (!updateResponse.ok()) throw new Error(`Watcher policy update returned HTTP ${updateResponse.status()}`);
  if (updated.policy?.name !== updatedPolicyName || updated.policy?.schedule_cron !== "* * * * *" || updated.policy?.enabled !== true || !(updated.policy?.version > created.policy.version)) {
    throw new Error(`Watcher policy ${policyId} did not persist the edited fields and version`);
  }
  await policyDialog.waitFor({ state: "hidden", timeout: 10000 });
  policyCard = await getExactPolicyCard(page, policyId, updatedPolicyName);
  screenshots.push(await captureWatcherScreenshot(page, policyCard, "watcher-07-policy-edited-1440x900.png"));

  const refreshButton = page.locator('header [data-action="refresh"]');
  const scheduledDeadline = Date.now() + 150000;
  let scheduledRun = null;
  while (Date.now() < scheduledDeadline) {
    const [runsResponse] = await Promise.all([
      page.waitForResponse(
        (candidate) => apiResponseMatches(candidate, "GET", "/api/v1/admin/watcher/runs"),
        { timeout: 30000 }
      ),
      refreshButton.click(),
    ]);
    const runs = await runsResponse.json();
    scheduledRun = (runs.runs || []).find((item) => {
      return sameId(item.policy_id, policyId)
        && item.trigger_source === "SCHEDULED"
        && item.status === "SUCCEEDED"
        && Number(item.started_at) >= Number(updated.policy.updated_at)
        && !sameId(item.id, run.run_id);
    }) || null;
    if (scheduledRun) break;
    await page.waitForTimeout(5000);
  }
  if (!scheduledRun || !(scheduledRun.target_count > 0) || !(scheduledRun.finding_count > 0) || !scheduledRun.trace_id) {
    throw new Error(`Watcher Scheduler did not produce a successful persisted run for policy ${policyId}`);
  }
  await page.waitForFunction((scheduledRunId) => {
    return (window.App?.state?.runs || []).some((item) => {
      return String(item.id) === String(scheduledRunId) && item.trigger_source === "SCHEDULED" && item.status === "SUCCEEDED";
    });
  }, scheduledRun.id, { timeout: 30000 });
  const scheduledRunIndex = await page.evaluate((scheduledRunId) => {
    return (window.App?.state?.runs || []).findIndex((item) => String(item.id) === String(scheduledRunId));
  }, scheduledRun.id);
  if (scheduledRunIndex < 0) throw new Error(`Scheduled Watcher run ${scheduledRun.id} is not visible in client history`);
  const scheduledRunRow = page.locator("#watcher-runs-table tr").nth(scheduledRunIndex);
  screenshots.push(await captureWatcherScreenshot(page, scheduledRunRow, "watcher-08-scheduled-run-1440x900.png"));

  const [disableResponse] = await Promise.all([
    page.waitForResponse((candidate) => apiResponseMatches(candidate, "PUT", updatePath), { timeout: 30000 }),
    policyCard.getByRole("button", { name: "停用", exact: true }).click(),
  ]);
  const disabled = await disableResponse.json();
  if (!disableResponse.ok()) throw new Error(`Watcher policy disable returned HTTP ${disableResponse.status()}`);
  if (String(disabled.policy?.id) !== String(policyId) || disabled.policy?.enabled !== false || !(disabled.policy?.version > updated.policy.version)) {
    throw new Error(`Watcher policy ${policyId} did not reach a versioned disabled state`);
  }
  await page.waitForFunction((targetId) => {
    return (window.App?.state?.policies || []).some((item) => String(item.id) === String(targetId) && item.enabled === false);
  }, policyId, { timeout: 30000 });
  policyCard = await getExactPolicyCard(page, policyId, updatedPolicyName);
  if (!(await policyCard.getByRole("button", { name: "立即运行", exact: true }).isDisabled())) {
    throw new Error(`Disabled Watcher policy ${policyId} still has an enabled run control`);
  }
  screenshots.push(await captureWatcherScreenshot(page, policyCard, "watcher-09-policy-disabled-1440x900.png"));

  const [policiesPayload, runsPayload, findingsPayload, llmPayload, auditsPayload] = await Promise.all([
    apiFromPage(page, "/api/v1/admin/watcher/policies"),
    apiFromPage(page, "/api/v1/admin/watcher/runs?limit=200"),
    apiFromPage(page, "/api/v1/admin/watcher/findings?limit=500"),
    apiFromPage(page, "/api/v1/admin/llm-calls?limit=200"),
    apiFromPage(page, "/api/v1/admin/audit-logs?limit=500"),
  ]);
  const policyRecord = (policiesPayload.policies || []).find((item) => sameId(item.id, policyId));
  const runRecord = (runsPayload.runs || []).find((item) => sameId(item.id, run.run_id));
  const scheduledRunRecord = (runsPayload.runs || []).find((item) => sameId(item.id, scheduledRun.id));
  const findingRecord = (findingsPayload.findings || []).find((item) => sameId(item.id, findingId));
  const manualFindings = (findingsPayload.findings || []).filter((item) => sameId(item.run_id, run.run_id));
  const scheduledFindings = (findingsPayload.findings || []).filter((item) => sameId(item.run_id, scheduledRun.id));
  const allLlmCalls = llmPayload.calls || llmPayload.llm_calls || [];
  const manualLlmCalls = allLlmCalls.filter((item) => item.trace_id === run.trace_id);
  const scheduledLlmCalls = allLlmCalls.filter((item) => item.trace_id === scheduledRun.trace_id);
  const llmCalls = [...manualLlmCalls, ...scheduledLlmCalls];
  const traceIds = new Set([
    created.trace_id,
    run.trace_id,
    scheduledRun.trace_id,
    assigned.trace_id,
    closed.trace_id,
    updated.trace_id,
    disabled.trace_id,
  ].filter(Boolean));
  const resourceIds = new Set([policyId, run.run_id, scheduledRun.id, findingId]);
  const audits = (auditsPayload.logs || auditsPayload.audit_logs || []).filter((item) => {
    return resourceIds.has(item.resource_id) || traceIds.has(item.trace_id);
  });
  if (!policyRecord || policyRecord.enabled !== false || !runRecord || !scheduledRunRecord || scheduledRunRecord.trigger_source !== "SCHEDULED" || scheduledRunRecord.status !== "SUCCEEDED" || !findingRecord || findingRecord.status !== "CLOSED" || findingRecord.resolution !== resolution) {
    throw new Error("Watcher persisted policy, run, or finding evidence does not match the completed UI lifecycle");
  }
  if (manualFindings.length !== run.finding_count || scheduledFindings.length !== scheduledRunRecord.finding_count) {
    throw new Error("Watcher manual or scheduled finding persistence count does not match its run record");
  }

  const validateModelFieldMapping = (record, findings, label) => {
    const escalations = record.result?.escalated_cases || [];
    if (!escalations.length) throw new Error(`${label} Watcher run has no model escalations to validate`);
    return escalations.map((escalation) => {
      if (!escalation.violation_reason || !escalation.severity_level) {
        throw new Error(`${label} Watcher model output is missing violation_reason or severity_level`);
      }
      const persisted = findings.find((item) => sameId(item.source_id, escalation.case_id));
      if (!persisted) throw new Error(`${label} Watcher escalation ${escalation.case_id} has no persisted finding`);
      if (persisted.description !== escalation.violation_reason || persisted.severity !== String(escalation.severity_level).toUpperCase()) {
        throw new Error(`${label} Watcher escalation ${escalation.case_id} was degraded during persistence`);
      }
      return {
        case_id: escalation.case_id,
        violation_reason: escalation.violation_reason,
        severity_level: String(escalation.severity_level).toUpperCase(),
        finding_id: persisted.id,
        persisted_description: persisted.description,
        persisted_severity: persisted.severity,
      };
    });
  };
  const manualMapping = validateModelFieldMapping(runRecord, manualFindings, "Manual");
  const scheduledMapping = validateModelFieldMapping(scheduledRunRecord, scheduledFindings, "Scheduled");
  const persistedSeverities = new Set([...manualMapping, ...scheduledMapping].map((item) => item.persisted_severity));
  for (const severity of ["P0", "P1", "P2"]) {
    if (!persistedSeverities.has(severity)) throw new Error(`Watcher UAT evidence is missing preserved ${severity} findings`);
  }
  if (!manualLlmCalls.length || !scheduledLlmCalls.length || llmCalls.some((item) => {
    return (item.model_name || item.model) !== "deepseek-v4-flash" || item.status !== "SUCCEEDED" || item.is_mock !== false;
  })) {
    throw new Error("Watcher manual or scheduled run lacks a successful non-mock deepseek-v4-flash LLM record");
  }
  const auditActions = new Set(audits.map((item) => item.action));
  for (const action of ["WATCHER_POLICY_CREATED", "WATCHER_RUN", "WATCHER_FINDING_UPDATED", "WATCHER_FINDING_CLOSED", "WATCHER_POLICY_UPDATED"]) {
    if (!auditActions.has(action)) throw new Error(`Watcher lifecycle audit is missing ${action}`);
  }
  if (runtime.consoleErrors.length || runtime.pageErrors.length || runtime.failedRequests.length || runtime.serverErrors.length) {
    throw new Error("Watcher lifecycle produced browser runtime errors");
  }

  const evidence = {
    uat_id: "MVP-UAT-007",
    operation: "Watcher policy, manual and scheduled DeepSeek runs, finding assignment/closure, edit and disable lifecycle",
    policy_id: policyId,
    run_id: run.run_id,
    scheduled_run_id: scheduledRun.id,
    finding_id: findingId,
    policy: { created, updated, disabled, record: policyRecord },
    run: {
      response: run,
      record: runRecord,
      scheduled: { record: scheduledRunRecord },
      field_mapping: { manual: manualMapping, scheduled: scheduledMapping },
    },
    run_findings: { manual: manualFindings, scheduled: scheduledFindings },
    finding: { assigned, closed, record: findingRecord },
    assignee: { ...assignee, eligibility: "active current-venue user returned by the formal assignee API" },
    llm_calls: llmCalls,
    audits,
    screenshots,
    runtime,
  };
  writeJson("MVP-UAT-007-watcher-lifecycle.json", evidence);
  return evidence;
}

async function main() {
  const browser = await chromium.launch({
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const runtime = { consoleErrors: [], pageErrors: [], failedRequests: [], serverErrors: [] };

  page.on("console", (message) => {
    if (message.type() === "error") runtime.consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => runtime.pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    runtime.failedRequests.push({ url: request.url(), error: request.failure()?.errorText || "unknown" });
  });
  page.on("response", (response) => {
    if (response.status() >= 400) runtime.serverErrors.push({ url: response.url(), status: response.status() });
  });

  try {
    await login(page);
    if (MODE === "inspect") {
      const clientMap = await inspectClient(page, runtime);
      process.stdout.write(`${JSON.stringify({ mode: MODE, navigationCount: clientMap.navigation.length, dialogCount: clientMap.dialogs.length, runtime }, null, 2)}\n`);
      return;
    }
    if (MODE === "view-inspect") {
      const map = await inspectView(page, TARGET, runtime);
      process.stdout.write(`${JSON.stringify({ mode: MODE, view: TARGET, buttonCount: map.buttons.length, fieldCount: map.fields.length, rowCount: map.rows.length, runtime }, null, 2)}\n`);
      return;
    }
    if (MODE === "todo-inspect") {
      const taskMap = await inspectTasks(page, runtime);
      process.stdout.write(`${JSON.stringify({ mode: MODE, sessionCount: taskMap.sessions.length, assigneeCount: taskMap.assignees.length, taskRowCount: taskMap.taskRows.length, runtime }, null, 2)}\n`);
      return;
    }
    if (MODE === "todo-decompose") {
      const evidence = await decomposeTodo(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        status: evidence.response_status,
        elapsedMs: evidence.elapsed_ms,
        traceId: evidence.response.trace_id,
        tasksCreated: evidence.response.tasks_created,
        llmCallCount: evidence.llm_calls.length,
        auditCount: evidence.audits.length,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "todo-lifecycle") {
      const evidence = await runTodoLifecycle(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        actionCount: evidence.action_count,
        finalTaskCount: evidence.final_tasks.length,
        finalStatuses: [...new Set(evidence.final_tasks.map((task) => task.status))],
        traceStatus: evidence.trace.status,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "todo-recovery") {
      const evidence = await runTodoRecovery(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        beforeStatus: evidence.before.app_status,
        recoveredStatus: evidence.after.app_status,
        statusHttp: evidence.status_http,
        decompositionPostCount: evidence.decomposition_post_count,
        recoveredTaskCount: evidence.recovered_task_count,
        llmCallCount: evidence.llm_call_count,
        passed: evidence.passed,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "approval-inspect") {
      const evidence = await inspectApprovalActionViews(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        approvalRows: evidence.approvals.rows.length,
        actionRows: evidence.actions.rows.length,
        requestFields: evidence.request_dialog.fields,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "approval-form-inspect") {
      const form = await inspectInAppAlertForm(page, runtime);
      process.stdout.write(`${JSON.stringify({ mode: MODE, form, runtime }, null, 2)}\n`);
      return;
    }
    if (MODE === "approval-create") {
      const evidence = await createApprovalRequests(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        approveStatus: evidence.approve_request.status,
        approveUrl: evidence.approve_request.url,
        approvePayload: evidence.approve_request.payload,
        rejectStatus: evidence.reject_request.status,
        rejectUrl: evidence.reject_request.url,
        rejectPayload: evidence.reject_request.payload,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "approval-decide") {
      const evidence = await decideApprovalRequests(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        approved: evidence.approved,
        rejected: evidence.rejected,
        pushCount: evidence.pushes.length,
        auditCount: evidence.audits.length,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "approval-verify") {
      const evidence = await verifyApprovalDecisionEvidence(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        approvalCount: evidence.approvals.length,
        pushCount: evidence.pushes.length,
        auditCount: evidence.audits.length,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "push-adopt") {
      const evidence = await adoptPendingPush(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        adoption: evidence.adoption,
        duplicate: evidence.duplicate_terminal_transition,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "push-concurrency") {
      const evidence = await runPushConcurrency(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        approvalId: evidence.request.payload.approval_id,
        pushId: evidence.push_id,
        statuses: evidence.results.map((result) => result.status),
        terminalStates: evidence.results.map((result) => result.payload.status || result.payload.detail?.code),
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "probe-todo-loading") {
      const evidence = await probeTodoPermanentLoading(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        waitingStatus: evidence.waiting.app_status,
        cancelledStatus: evidence.cancelled.app_status,
        restoredStatus: evidence.restored.app_status,
        recoveredStatus: evidence.recovered.app_status,
        idempotencyKeyPreserved: evidence.cancelled.idempotency_key === evidence.recovered.idempotency_key,
        unexpectedRuntime: evidence.unexpected_runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "probe-todo-refresh") {
      const evidence = await probeTodoRefreshMisreport(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        status: evidence.state.app_status,
        storedStatus: evidence.state.stored_status,
        note: evidence.state.note_text,
        expectedRefreshErrors: evidence.expected_http_errors.length,
        unexpectedRuntime: evidence.unexpected_runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "memory-ops-live") {
      const evidence = await runMemoryOpsAdvice(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        run: evidence.run,
        traceStatus: evidence.trace.status,
        memoryOpsCallCount: evidence.memory_ops_calls.length,
        timelineAgentIds: evidence.timeline_agent_ids,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "event-live") {
      const evidence = await runLiveEventIntake(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        intakeStatus: evidence.intake_status,
        elapsedMs: evidence.elapsed_ms,
        run: evidence.run,
        traceStatus: evidence.trace.status,
        llmCallCount: evidence.llm_calls.length,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "session-lifecycle") {
      const evidence = await runSessionLifecycle(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        sessionId: evidence.session.id,
        initialStage: evidence.session.detail_before.stage,
        finalStage: evidence.session.detail_after_refresh.stage,
        messageStatus: evidence.run.status,
        closeAudit: evidence.audits.closed.action,
        tenantReadStatus: evidence.tenant_boundary.read.status,
        tenantCloseStatus: evidence.tenant_boundary.close.status,
        tenantDenialAudit: evidence.audits.cross_tenant_denied.action,
        persistedAfterRefresh: true,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "event-history") {
      const evidence = await runHistoricalEventImport(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        importStatus: evidence.import_status,
        eventCount: evidence.events.length,
        llmCallCount: evidence.llm_calls.length,
        searchStatus: evidence.search_status,
        searchResultCount: (evidence.search.results || []).length,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "event-detail-inspect") {
      const evidence = await inspectLatestLiveEventDetails(page, runtime);
      process.stdout.write(`${JSON.stringify({ mode: MODE, eventId: evidence.event.event_id, details: evidence.details, runtime }, null, 2)}\n`);
      return;
    }
    if (MODE === "event-close") {
      const evidence = await closeLatestLiveEvent(page, runtime);
      process.stdout.write(`${JSON.stringify({ mode: MODE, eventId: evidence.event_id, status: evidence.event?.status, responseStatus: evidence.response_status, auditCount: evidence.audits.length, runtime }, null, 2)}\n`);
      return;
    }
    if (MODE === "knowledge-sop") {
      const evidence = await runKnowledgeSopLifecycle(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        knowledgeId: evidence.knowledge.id,
        rebuiltKnowledgeCount: evidence.knowledge.rebuilt.rebuilt,
        knowledgeSearchResults: (evidence.knowledge.search.results || []).length,
        sopId: evidence.sop.id,
        rejectedStatus: evidence.sop.rejected.sop.status,
        revisedStatus: evidence.sop.revised.sop.status,
        publishedStatus: evidence.sop.published.sop.status,
        sopSearchResults: (evidence.sop.search.results || []).length,
        knowledgeRecordCount: evidence.knowledge_records.length,
        sopRecordCount: evidence.sop_records.length,
        auditCount: evidence.audits.length,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "knowledge-search-exact") {
      const evidence = await probeExactKnowledgeSearch(page, runtime);
      process.stdout.write(`${JSON.stringify({ mode: MODE, resultCount: (evidence.result.payload.results || []).length, matches: evidence.matches.map((item) => ({ id: item.id, title: item.metadata?.title, score: item.score })), runtime }, null, 2)}\n`);
      return;
    }
    if (MODE === "persona-lifecycle") {
      const evidence = await runPersonaLifecycle(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        personaId: evidence.persona_id,
        interviewId: evidence.interview_id,
        responseCount: evidence.responses.length,
        resumedAfterRefresh: evidence.resumed_after_refresh,
        totalEntries: evidence.finalized.total_entries,
        entriesUsed: evidence.answer.entries_used,
        sourceNote: evidence.answer.source_note,
        deleted: evidence.deletion.response.deleted,
        deletedFromClient: evidence.deleted_from_client,
        postDeletePersona: evidence.post_delete_persona,
        llmCallCount: evidence.llm_calls.length,
        auditCount: evidence.audits.length,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    if (MODE === "watcher-lifecycle") {
      const evidence = await runWatcherLifecycle(page, runtime);
      process.stdout.write(`${JSON.stringify({
        mode: MODE,
        policyId: evidence.policy_id,
        manualRunId: evidence.run_id,
        scheduledRunId: evidence.scheduled_run_id,
        findingId: evidence.finding_id,
        manualTargetCount: evidence.run.response.target_count,
        manualFindingCount: evidence.run.response.finding_count,
        scheduledTargetCount: evidence.run.scheduled.record.target_count,
        scheduledFindingCount: evidence.run.scheduled.record.finding_count,
        model: evidence.run.response.model,
        preservedSeverities: [...new Set([
          ...evidence.run.field_mapping.manual,
          ...evidence.run.field_mapping.scheduled,
        ].map((item) => item.persisted_severity))].sort(),
        finalFindingStatus: evidence.finding.record.status,
        finalPolicyEnabled: evidence.policy.record.enabled,
        llmCallCount: evidence.llm_calls.length,
        auditCount: evidence.audits.length,
        runtime,
      }, null, 2)}\n`);
      return;
    }
    throw new Error(`Unsupported UAT mode: ${MODE}`);
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.name}: ${error.message}\n`);
  process.exitCode = 1;
});
