const { execFileSync } = require("node:child_process");
const { createHash, randomUUID } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("C:/Users/Admin/.codex/skills/gstack/browse/node_modules/playwright");

const MODE = process.argv[2] || "";
const ROOT_DIR = __dirname;
const SCREENSHOT_DIR = path.join(ROOT_DIR, "screenshots");
const EVIDENCE_DIR = path.join(ROOT_DIR, "evidence");
const SOURCE_URL = process.env.MP_UAT_URL || "http://localhost:8082/admin/";
const SOURCE_PROJECT = process.env.MP_UAT_SOURCE_PROJECT || "memory-palace-uat";
const RESTORE_URL = process.env.MP_UAT_RESTORE_URL || "http://localhost:18082/admin/";
const RESTORE_PROJECT = process.env.MP_UAT_RESTORE_PROJECT || "memory-palace-uat-restore-01";
const USERNAME = process.env.MP_UAT_USERNAME || "uat-admin";
const CHROME_PATH = process.env.MP_UAT_CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const SOURCE_EGRESS_NETWORK = process.env.MP_UAT_EGRESS_NETWORK || `${SOURCE_PROJECT}_egress`;
const STREAM_KEY = "memory_palace:messages";
const DEAD_LETTER_KEY = "memory_palace:dead_letter";
const CONSUMER_GROUP = "mp_workers";
const SUPPORTED_MODES = new Set(["restore", "dead-letter", "runtime-reload", "integrations", "app-restart", "llm-failure"]);
const DEFAULT_COMPARE_TABLES = [
  "venues",
  "users",
  "sessions",
  "messages",
  "message_runs",
  "confirmed_events",
  "tasks",
  "approval_requests",
  "knowledge_documents",
  "sop_documents",
  "sop_versions",
  "system_settings",
  "watcher_policies",
  "watcher_findings",
  "watcher_runs",
  "push_logs",
  "audit_logs",
  "tool_invocation_logs",
  "personas",
  "persona_interviews",
];

fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
fs.mkdirSync(EVIDENCE_DIR, { recursive: true });

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function redactString(value) {
  return value
    .replace(/\u001b\[[0-9;]*m/g, "")
    .replace(/\bsk-[A-Za-z0-9_-]{16,}\b/g, "[REDACTED]")
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [REDACTED]")
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[REDACTED]")
    .replace(/([a-z][a-z0-9+.-]*:\/\/)[^\s/:@]+:[^\s/@]+@/gi, "$1[REDACTED]@");
}

function redact(value, seen = new WeakSet()) {
  if (typeof value === "string") return redactString(value);
  if (Array.isArray(value)) return value.map((item) => redact(item, seen));
  if (!value || typeof value !== "object") return value;
  if (seen.has(value)) return "[REDACTED:CIRCULAR]";
  seen.add(value);
  const result = {};
  for (const [key, item] of Object.entries(value)) {
    if (/(^|_)(password|passphrase|access_token|refresh_token|api_key|secret|authorization|cookie|credential|private_key)(_|$)/i.test(key)) {
      result[key] = "[REDACTED]";
    } else {
      result[key] = redact(item, seen);
    }
  }
  seen.delete(value);
  return result;
}

function writeJson(filename, value) {
  const target = path.join(EVIDENCE_DIR, filename);
  fs.writeFileSync(target, `${JSON.stringify(redact(value), null, 2)}\n`, "utf8");
  return target;
}

function docker(args, options = {}) {
  try {
    return execFileSync("docker", args, {
      encoding: "utf8",
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
      maxBuffer: options.maxBuffer || 16 * 1024 * 1024,
    }).trim();
  } catch (error) {
    const commandLabel = args.slice(0, 3).join(" ");
    throw new Error(`Docker command failed (${error.status ?? "unknown"}): ${commandLabel}`);
  }
}

function getAdminPassword(appContainer) {
  const password = docker(["exec", appContainer, "printenv", "ADMIN_PASSWORD"]);
  requireCondition(password, `ADMIN_PASSWORD is unavailable in App container ${appContainer}`);
  return password;
}

function parseDockerInspect(container) {
  const payload = JSON.parse(docker(["inspect", container]));
  requireCondition(Array.isArray(payload) && payload.length === 1, `Container inspect did not return one record for ${container}`);
  return payload[0];
}

function containerNetworkNames(container) {
  return Object.keys(parseDockerInspect(container).NetworkSettings?.Networks || {});
}

function isNetworkConnected(container, network) {
  return containerNetworkNames(container).includes(network);
}

function disconnectNetwork(container, network) {
  requireCondition(isNetworkConnected(container, network), `${container} is not connected to ${network}`);
  docker(["network", "disconnect", network, container]);
  requireCondition(!isNetworkConnected(container, network), `${container} remained connected to ${network}`);
}

function connectNetwork(container, network) {
  if (!isNetworkConnected(container, network)) {
    docker(["network", "connect", "--alias", "app", network, container]);
  }
  requireCondition(isNetworkConnected(container, network), `${container} was not reconnected to ${network}`);
}

async function waitForContainerHealthy(container, timeoutMs = 60000) {
  return waitForCondition(() => {
    const inspected = parseDockerInspect(container);
    const state = inspected.State || {};
    return state.Running === true && state.Health?.Status === "healthy" ? {
      container,
      started_at: state.StartedAt,
      status: state.Status,
      health: state.Health.Status,
      networks: Object.keys(inspected.NetworkSettings?.Networks || {}),
    } : null;
  }, `${container} healthy state`, timeoutMs, 500);
}

function resolveServiceContainer(project, service, explicitName = "") {
  if (explicitName) {
    const inspected = parseDockerInspect(explicitName);
    const labels = inspected.Config?.Labels || {};
    requireCondition(labels["com.docker.compose.project"] === project, `${explicitName} does not belong to Compose project ${project}`);
    requireCondition(labels["com.docker.compose.service"] === service, `${explicitName} is not the ${service} service`);
    return inspected.Name.replace(/^\//, "");
  }
  const output = docker([
    "ps",
    "-a",
    "--filter",
    `label=com.docker.compose.project=${project}`,
    "--filter",
    `label=com.docker.compose.service=${service}`,
    "--filter",
    "label=com.docker.compose.oneoff=False",
    "--format",
    "{{.Names}}",
  ]);
  const names = output.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  requireCondition(names.length === 1, `Expected exactly one ${service} container in ${project}, found ${names.length}`);
  return names[0];
}

function sourceContainer(service) {
  const envNames = {
    app: "MP_UAT_APP_CONTAINER",
    postgres: "MP_UAT_SOURCE_POSTGRES_CONTAINER",
    redis: "MP_UAT_REDIS_CONTAINER",
    chromadb: "MP_UAT_SOURCE_CHROMADB_CONTAINER",
    nginx: "MP_UAT_SOURCE_NGINX_CONTAINER",
  };
  return resolveServiceContainer(SOURCE_PROJECT, service, process.env[envNames[service]] || "");
}

function restoreContainer(service) {
  const envNames = {
    app: "MP_UAT_RESTORE_APP_CONTAINER",
    postgres: "MP_UAT_RESTORE_POSTGRES_CONTAINER",
    redis: "MP_UAT_RESTORE_REDIS_CONTAINER",
    chromadb: "MP_UAT_RESTORE_CHROMADB_CONTAINER",
    nginx: "MP_UAT_RESTORE_NGINX_CONTAINER",
  };
  return resolveServiceContainer(RESTORE_PROJECT, service, process.env[envNames[service]] || "");
}

function collectHealthyStack(project, resolver) {
  const services = ["app", "postgres", "redis", "chromadb", "nginx"];
  const records = services.map((service) => {
    const container = resolver(service);
    const inspected = parseDockerInspect(container);
    const state = inspected.State || {};
    const health = state.Health?.Status || "not-configured";
    requireCondition(state.Running === true, `${project}/${service} is not running`);
    requireCondition(health === "healthy", `${project}/${service} is not healthy (${health})`);
    return {
      service,
      container,
      project,
      image: inspected.Config?.Image || null,
      state: state.Status,
      health,
    };
  });
  return records;
}

function queryPostgres(container, sql) {
  return docker([
    "exec",
    container,
    "sh",
    "-c",
    'psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"',
    "uat-query",
    sql,
  ]);
}

function sqlLiteral(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

function queryPostgresRows(container, selectSql) {
  const raw = queryPostgres(
    container,
    `SELECT COALESCE(json_agg(row_to_json(uat_rows)), '[]'::json)::text FROM (${selectSql}) AS uat_rows;`,
  );
  const rows = JSON.parse(raw || "[]");
  requireCondition(Array.isArray(rows), "PostgreSQL JSON row query did not return an array");
  return rows;
}

function decompositionRows(container, principal, idempotencyKey) {
  return queryPostgresRows(
    container,
    `SELECT decomposition_id, venue_id, requested_by, idempotency_key, session_id, trace_id, status, task_ids, error, created_at, updated_at
     FROM task_decompositions
     WHERE venue_id = ${sqlLiteral(principal.venue_id)}
       AND requested_by = ${sqlLiteral(principal.id)}
       AND idempotency_key = ${sqlLiteral(idempotencyKey)}
     ORDER BY created_at`,
  );
}

function decompositionTaskRows(container, decompositionId) {
  return queryPostgresRows(
    container,
    `SELECT id, venue_id, session_id, description, status, dependencies, assigned_agent, assigned_user_id,
            decomposition_id, attempts, max_attempts, created_at, updated_at
     FROM tasks WHERE decomposition_id = ${sqlLiteral(decompositionId)} ORDER BY created_at`,
  );
}

function llmRowsForTraces(container, traceIds) {
  const uniqueTraceIds = [...new Set(traceIds.filter(Boolean))];
  if (!uniqueTraceIds.length) return [];
  return queryPostgresRows(
    container,
    `SELECT id, venue_id, trace_id, agent_id, agent_name, provider, model_name, status,
            attempt_count, latency_seconds, prompt_tokens, completion_tokens, total_tokens,
            request_id, error_type, is_mock, created_at
     FROM llm_call_logs
     WHERE trace_id IN (${uniqueTraceIds.map(sqlLiteral).join(",")})
     ORDER BY created_at`,
  );
}

function sideEffectRowsForTraces(container, traceIds) {
  const uniqueTraceIds = [...new Set(traceIds.filter(Boolean))];
  if (!uniqueTraceIds.length) return { approvals: [], pushes: [], tool_invocations: [], audits: [] };
  const inList = uniqueTraceIds.map(sqlLiteral).join(",");
  return {
    approvals: queryPostgresRows(
      container,
      `SELECT approval_id, venue_id, tool_name, session_id, user_id, status,
              correlation_trace_id, execution_trace_id, execution_status, requested_at
       FROM approval_requests
       WHERE correlation_trace_id IN (${inList}) OR execution_trace_id IN (${inList})
       ORDER BY requested_at`,
    ),
    pushes: queryPostgresRows(
      container,
      `SELECT push_id, venue_id, event_type, severity, trace_id, channel, recipient,
              delivery_status, adoption_status, pushed_at
       FROM push_logs WHERE trace_id IN (${inList}) ORDER BY pushed_at`,
    ),
    tool_invocations: queryPostgresRows(
      container,
      `SELECT id, venue_id, tool_name, session_id, user_id, agent_name, trace_id, approval_id, logged_at
       FROM tool_invocation_logs WHERE trace_id IN (${inList}) ORDER BY logged_at`,
    ),
    audits: queryPostgresRows(
      container,
      `SELECT id, venue_id, user_id, action, resource_type, resource_id, outcome, trace_id, created_at
       FROM audit_logs WHERE trace_id IN (${inList}) ORDER BY created_at`,
    ),
  };
}

function configuredCompareTables() {
  const configured = (process.env.MP_UAT_COMPARE_TABLES || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const tables = configured.length ? configured : DEFAULT_COMPARE_TABLES;
  for (const table of tables) {
    requireCondition(/^[a-z][a-z0-9_]*$/.test(table), `Invalid PostgreSQL table name: ${table}`);
  }
  return [...new Set(tables)];
}

function tableCount(container, table) {
  const exists = queryPostgres(container, `SELECT to_regclass(${sqlLiteral(`public.${table}`)}) IS NOT NULL;`);
  requireCondition(exists === "t", `Table public.${table} is missing from ${container}`);
  const count = Number(queryPostgres(container, `SELECT COUNT(*) FROM public.${table};`));
  requireCondition(Number.isSafeInteger(count) && count >= 0, `Invalid row count for public.${table} in ${container}`);
  return count;
}

function comparePostgresCounts(sourcePostgres, restorePostgres) {
  const policy = process.env.MP_UAT_TABLE_COUNT_POLICY || "source-at-least-restore";
  requireCondition(["exact", "source-at-least-restore"].includes(policy), `Unsupported MP_UAT_TABLE_COUNT_POLICY: ${policy}`);
  const counts = configuredCompareTables().map((table) => {
    const source = tableCount(sourcePostgres, table);
    const restored = tableCount(restorePostgres, table);
    const valid = policy === "exact" ? source === restored : source >= restored;
    requireCondition(valid, `PostgreSQL count check failed for ${table}: source=${source}, restore=${restored}, policy=${policy}`);
    return { table, source, restored, exact_match: source === restored, policy_valid: valid };
  });
  const restoredKnowledge = counts.find((item) => item.table === "knowledge_documents");
  requireCondition(restoredKnowledge && restoredKnowledge.restored > 0, "Restored PostgreSQL has no knowledge_documents rows");
  return { policy, counts };
}

function assertPlainFileInside(directory, filename) {
  requireCondition(path.basename(filename) === filename, `Manifest artifact must use a plain filename: ${filename}`);
  const target = path.join(directory, filename);
  const stats = fs.lstatSync(target);
  requireCondition(stats.isFile() && !stats.isSymbolicLink(), `Backup artifact is not a regular file: ${filename}`);
  const realDirectory = fs.realpathSync.native(directory);
  const realTarget = fs.realpathSync.native(target);
  const relative = path.relative(realDirectory, realTarget);
  requireCondition(relative && !relative.startsWith("..") && !path.isAbsolute(relative), `Backup artifact escapes its directory: ${filename}`);
  return { target: realTarget, bytes: stats.size };
}

function sha256File(filename) {
  return new Promise((resolve, reject) => {
    const hash = createHash("sha256");
    const stream = fs.createReadStream(filename);
    stream.on("error", reject);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("end", () => resolve(hash.digest("hex")));
  });
}

async function verifyBackupV2() {
  const configuredDirectory = process.env.MP_UAT_BACKUP_DIR;
  requireCondition(configuredDirectory, "MP_UAT_BACKUP_DIR is required for restore mode");
  const directory = path.resolve(configuredDirectory);
  const directoryStats = fs.lstatSync(directory);
  requireCondition(directoryStats.isDirectory() && !directoryStats.isSymbolicLink(), "MP_UAT_BACKUP_DIR must be a regular directory");
  const manifestFile = assertPlainFileInside(directory, "manifest.json").target;
  const manifest = JSON.parse(fs.readFileSync(manifestFile, "utf8").replace(/^\uFEFF/, ""));
  requireCondition(manifest.schema_version === "memory-palace-mvp-backup/v2", `Unsupported backup schema: ${manifest.schema_version}`);
  requireCondition(manifest.backup_id === path.basename(directory), "Manifest backup_id does not match MP_UAT_BACKUP_DIR");
  requireCondition(manifest.source?.compose_project === SOURCE_PROJECT, `Manifest source project is not ${SOURCE_PROJECT}`);

  const expectedArtifacts = {
    postgres: "postgres.dump",
    chroma: "chroma-data.tar.gz",
    embedding_cache: "embedding-cache.tar.gz",
  };
  const artifacts = [];
  for (const [name, expectedFile] of Object.entries(expectedArtifacts)) {
    const metadata = manifest.artifacts?.[name];
    requireCondition(metadata?.file === expectedFile, `Manifest ${name} artifact filename is invalid`);
    requireCondition(/^[a-f0-9]{64}$/i.test(String(metadata.sha256 || "")), `Manifest ${name} SHA256 is invalid`);
    const local = assertPlainFileInside(directory, expectedFile);
    const actualSha256 = await sha256File(local.target);
    requireCondition(actualSha256 === String(metadata.sha256).toLowerCase(), `${name} artifact SHA256 mismatch`);
    if (metadata.bytes !== undefined && metadata.bytes !== null) {
      requireCondition(Number(metadata.bytes) === local.bytes, `${name} artifact byte size mismatch`);
    }
    artifacts.push({ name, file: expectedFile, bytes: local.bytes, sha256: actualSha256, verified: true });
  }
  return {
    schema_version: manifest.schema_version,
    script_version: manifest.script_version,
    backup_id: manifest.backup_id,
    created_at_utc: manifest.created_at_utc,
    source: {
      compose_project: manifest.source.compose_project,
      compose_file_sha256: manifest.source.compose_file_sha256,
      git: manifest.source.git,
    },
    artifacts,
  };
}

function attachRuntime(page) {
  const runtime = {
    console_errors: [],
    page_errors: [],
    failed_requests: [],
    http_errors: [],
  };
  page.on("console", (message) => {
    if (message.type() === "error") runtime.console_errors.push(message.text());
  });
  page.on("pageerror", (error) => runtime.page_errors.push(error.message));
  page.on("requestfailed", (request) => {
    runtime.failed_requests.push({ url: request.url(), error: request.failure()?.errorText || "unknown" });
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      runtime.http_errors.push({ url: response.url(), method: response.request().method(), status: response.status() });
    }
  });
  return runtime;
}

function assertRuntimeClean(runtime, expectedHttpErrors = []) {
  requireCondition(runtime.console_errors.length === 0, `Browser emitted ${runtime.console_errors.length} console errors`);
  requireCondition(runtime.page_errors.length === 0, `Browser emitted ${runtime.page_errors.length} page errors`);
  requireCondition(runtime.failed_requests.length === 0, `Browser emitted ${runtime.failed_requests.length} failed requests`);
  const remaining = [...runtime.http_errors];
  for (const expected of expectedHttpErrors) {
    const matching = remaining.filter((item) => item.status === expected.status && item.url.includes(expected.url_includes));
    requireCondition(matching.length === expected.count, `Expected ${expected.count} HTTP ${expected.status} responses for ${expected.url_includes}, found ${matching.length}`);
    for (const match of matching) remaining.splice(remaining.indexOf(match), 1);
  }
  requireCondition(remaining.length === 0, `Browser received unexpected HTTP errors: ${JSON.stringify(remaining)}`);
}

function snapshotRuntime(runtime) {
  return JSON.parse(JSON.stringify(runtime));
}

function clearRuntime(runtime) {
  runtime.console_errors.length = 0;
  runtime.page_errors.length = 0;
  runtime.failed_requests.length = 0;
  runtime.http_errors.length = 0;
}

function assertExpectedDecompositionTransportFailure(runtime, label, allowCleanAbort = false) {
  requireCondition(runtime.page_errors.length === 0, `${label} emitted ${runtime.page_errors.length} page errors`);
  const failedPosts = runtime.failed_requests.filter((item) => item.url.includes("/api/v1/admin/tasks/decompose"));
  const errorResponses = runtime.http_errors.filter((item) => item.url.includes("/api/v1/admin/tasks/decompose"));
  requireCondition(allowCleanAbort || failedPosts.length + errorResponses.length >= 1, `${label} did not visibly interrupt or fail the in-flight decomposition request`);
  requireCondition(runtime.failed_requests.every((item) => item.url.includes("/api/v1/admin/tasks/decompose")), `${label} caused an unrelated failed browser request`);
  requireCondition(runtime.http_errors.every((item) => item.url.includes("/api/v1/admin/tasks/decompose") && [502, 503, 504].includes(item.status)), `${label} caused an unrelated HTTP error`);
  requireCondition(runtime.console_errors.every((message) => /failed to load resource|network|fetch|502|503|504/i.test(message)), `${label} caused an unrelated browser console error`);
}

async function responsePayload(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (_error) {
    return text;
  }
}

async function apiFromPage(page, route) {
  return page.evaluate(async (url) => {
    const token = sessionStorage.getItem("mp_access_token");
    const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(`GET ${url} returned HTTP ${response.status}`);
    return payload;
  }, route);
}

async function requestFromPage(page, route, method, body) {
  const token = await page.evaluate(() => sessionStorage.getItem("mp_access_token"));
  requireCondition(token, "Authenticated browser token is unavailable for direct API verification");
  const response = await page.request.fetch(new URL(route, page.url()).toString(), {
    method,
    headers: { Authorization: `Bearer ${token}` },
    data: body,
    failOnStatusCode: false,
  });
  const payload = await response.json().catch(() => ({}));
  return { status: response.status(), payload };
}

async function login(page, { baseUrl, appContainer, username = USERNAME }) {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator("#login-username").fill(username);
  await page.locator("#login-password").fill(getAdminPassword(appContainer));
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.url().includes("/api/v1/auth/login")),
    page.locator("#login-form button[type=submit]").click(),
  ]);
  requireCondition(response.status() === 200, `UAT login returned HTTP ${response.status()}`);
  await page.waitForFunction(() => Boolean(sessionStorage.getItem("mp_access_token")) && document.querySelectorAll("[data-view]").length > 0);
}

async function openView(page, view) {
  await page.locator(`[data-view="${view}"]`).click();
  await page.locator(`#view-${view}`).waitFor({ state: "visible" });
  await page.waitForTimeout(500);
}

async function principalFromPage(page) {
  const principal = await page.evaluate(() => JSON.parse(sessionStorage.getItem("mp_user") || "null"));
  requireCondition(principal && principal.id && principal.venue_id, "Authenticated client does not expose a venue-scoped principal");
  return principal;
}

async function openTaskDecompositionForm(page, goal) {
  await openView(page, "tasks");
  await page.locator('#view-tasks [data-action="decompose-task"]').click();
  const dialog = page.locator("#task-decompose-dialog");
  await dialog.waitFor({ state: "visible" });
  await page.locator("#task-decompose-goal").fill(goal);
  const sessionOptions = await page.locator("#task-decompose-session option").count();
  requireCondition(sessionOptions > 0, "Formal client has no session available for TodoWrite decomposition");
  const activeSessionId = await page.evaluate(() => {
    const session = (window.App?.state?.sessions || []).find((item) => String(item.stage || "").toUpperCase() !== "CLOSED");
    return session?.session_id || null;
  });
  requireCondition(activeSessionId, "Formal client has no active session available for TodoWrite decomposition");
  await page.locator("#task-decompose-session").selectOption(activeSessionId);
  await page.locator("#task-decompose-attempts").fill("3");
  return dialog;
}

async function readTodoOperation(page) {
  const operation = await page.evaluate(() => JSON.parse(sessionStorage.getItem("mp_todo_decomposition") || "null"));
  requireCondition(operation?.idempotency_key && operation?.trace_id, "Formal client did not persist the TodoWrite operation identity");
  return operation;
}

async function todoUiState(page) {
  return page.evaluate(() => {
    const stored = JSON.parse(sessionStorage.getItem("mp_todo_decomposition") || "null");
    return {
      app_status: window.App?.todoDecomposition?.status || null,
      stored_status: stored?.status || null,
      idempotency_key: stored?.idempotency_key || null,
      trace_id: stored?.trace_id || null,
      decomposition_id: stored?.decomposition_id || null,
      tasks_created: stored?.tasks_created ?? null,
      note: document.querySelector("#task-decompose-note")?.textContent.trim() || "",
      status_text: document.querySelector("#task-decompose-status")?.textContent.trim() || "",
      recovery_visible: !document.querySelector("#task-decompose-recovery")?.classList.contains("hidden"),
      recovery_text: document.querySelector("#task-decompose-recover")?.textContent.trim() || "",
      submit_disabled: Boolean(document.querySelector("#task-decompose-submit")?.disabled),
    };
  });
}

async function waitForCondition(check, description, timeoutMs = 30000, intervalMs = 250) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const result = await check();
      if (result) return result;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(`${description} did not complete within ${timeoutMs}ms${lastError ? ` (${lastError.message})` : ""}`);
}

function redisCommand(container, args) {
  return docker(["exec", container, "redis-cli", "--raw", ...args]);
}

async function runRestore(page, runtime, restoreStack) {
  const manifest = await verifyBackupV2();
  const sourcePostgres = sourceContainer("postgres");
  const restorePostgres = restoreContainer("postgres");
  const postgres = comparePostgresCounts(sourcePostgres, restorePostgres);

  await openView(page, "knowledge");
  await page.locator("#knowledge-table tr").first().waitFor({ state: "visible" });
  const restoredRows = await page.locator("#knowledge-table tr").allInnerTexts();
  requireCondition(restoredRows.length > 0, "Restore client did not display restored knowledge rows");

  const query = "东区闸机断电";
  await page.locator("#knowledge-vector-query").fill(query);
  const [searchResponse] = await Promise.all([
    page.waitForResponse((candidate) => candidate.url().includes("/api/v1/admin/knowledge/search") && candidate.request().method() === "POST"),
    page.locator("#knowledge-search-form button[type=submit]").click(),
  ]);
  const searchPayload = await responsePayload(searchResponse);
  requireCondition(searchResponse.status() === 200, `Restore knowledge search returned HTTP ${searchResponse.status()}`);
  requireCondition(Array.isArray(searchPayload?.results) && searchPayload.results.length > 0, "Restore knowledge search returned no results");
  await page.locator("#knowledge-results .feed-item").first().waitFor({ state: "visible" });
  const renderedResults = await page.locator("#knowledge-results .feed-item").allInnerTexts();
  requireCondition(renderedResults.some((text) => /闸机|断电/.test(text)), "Restore client search results do not display the restored gate outage knowledge");

  const screenshot = "restore-01-knowledge-search-1440x900.png";
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, screenshot), fullPage: true });
  assertRuntimeClean(runtime);
  const evidence = {
    uat_id: "MVP-UAT-008",
    operation: "Backup v2 integrity and isolated restore client verification",
    manifest,
    postgres,
    restore_stack: restoreStack,
    client: {
      url: RESTORE_URL,
      displayed_knowledge_rows: restoredRows,
      query,
      search_status: searchResponse.status(),
      search_results: searchPayload.results,
      rendered_results: renderedResults,
    },
    screenshots: [screenshot],
    runtime,
  };
  writeJson("MVP-UAT-008-backup-restore.json", evidence);
  return {
    backup_id: manifest.backup_id,
    verified_artifacts: manifest.artifacts.length,
    compared_tables: postgres.counts.length,
    search_results: searchPayload.results.length,
  };
}

async function runDeadLetter(page, runtime, redisContainer, postgresContainer) {
  const principal = await principalFromPage(page);
  const probeId = randomUUID();
  const messageId = `uat-dead-letter-${probeId}`;
  const message = {
    msg_id: messageId,
    trace_id: randomUUID().replace(/-/g, ""),
    session_id: `uat-dl-${probeId}`,
    from_user: principal.id || principal.user_id || "uat-admin",
    venue_id: principal.venue_id,
    msg_type: "text",
    content: `收到。UAT dead-letter recovery probe ${probeId}`,
    timestamp: Date.now() / 1000,
    metadata: { source: "mvp-uat-dead-letter", synthetic: true, venue_id: principal.venue_id },
  };
  const errorMarker = `MVP UAT synthetic dead-letter ${probeId}`;
  const deadLetterId = redisCommand(redisContainer, [
    "XADD",
    DEAD_LETTER_KEY,
    "*",
    "data",
    JSON.stringify(message),
    "error",
    errorMarker,
    "retries",
    "3",
  ]);
  requireCondition(/^\d+-\d+$/.test(deadLetterId), `Redis returned an invalid dead-letter ID: ${deadLetterId}`);

  await openView(page, "diagnostics");
  const card = page.locator("#dead-letter-list .feed-item").filter({ hasText: deadLetterId });
  await card.waitFor({ state: "visible" });
  requireCondition(await card.count() === 1, `Expected one visible dead-letter card for ${deadLetterId}`);
  const responsePromise = page.waitForResponse((candidate) => candidate.url().includes(`/api/v1/admin/dead-letters/${deadLetterId}/retry`) && candidate.request().method() === "POST");
  await card.locator("button").click();
  const retryResponse = await responsePromise;
  const retryPayload = await responsePayload(retryResponse);
  requireCondition(retryResponse.status() === 200, `Dead-letter retry returned HTTP ${retryResponse.status()}`);
  requireCondition(retryPayload?.dead_letter_id === deadLetterId, "Dead-letter retry response does not identify the selected entry");
  requireCondition(retryPayload?.message_id === messageId, "Dead-letter retry response does not identify the synthetic message");
  await card.waitFor({ state: "detached" });

  await waitForCondition(() => {
    const count = Number(queryPostgres(postgresContainer, `SELECT COUNT(*) FROM messages WHERE message_id = ${sqlLiteral(messageId)};`));
    return count === 1;
  }, "Retried dead-letter queue consumption", 45000, 500);
  await waitForCondition(() => {
    const pending = redisCommand(redisContainer, ["XPENDING", STREAM_KEY, CONSUMER_GROUP, retryPayload.stream_message_id, retryPayload.stream_message_id, "10"]);
    return pending === "";
  }, "Retried stream message acknowledgement", 15000, 250);
  const remainingDeadLetter = redisCommand(redisContainer, ["XRANGE", DEAD_LETTER_KEY, deadLetterId, deadLetterId, "COUNT", "1"]);
  requireCondition(remainingDeadLetter === "", "Selected dead-letter entry still exists after retry");

  const deadLetters = await apiFromPage(page, "/api/v1/admin/dead-letters?limit=200");
  requireCondition(!(deadLetters.dead_letters || []).some((item) => item.id === deadLetterId), "Selected dead-letter entry remains visible through the API");
  const auditsPayload = await apiFromPage(page, "/api/v1/admin/audit-logs?limit=500");
  const audit = (auditsPayload.audit_logs || auditsPayload.logs || []).find((item) => (
    item.action === "DEAD_LETTER_RETRIED"
    && item.resource_id === deadLetterId
    && item.outcome === "SUCCEEDED"
    && item.trace_id === retryPayload.trace_id
  ));
  requireCondition(audit, "DEAD_LETTER_RETRIED audit evidence is missing");
  await page.waitForFunction((resourceId) => document.querySelector("#audit-table")?.innerText.includes(resourceId), deadLetterId);

  const screenshot = "dead-letter-01-retried-1440x900.png";
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, screenshot), fullPage: true });
  assertRuntimeClean(runtime);
  const evidence = {
    uat_id: "MVP-UAT-008",
    operation: "Tenant-scoped Redis dead-letter recovery through the formal diagnostics client",
    injected_entry: {
      id: deadLetterId,
      venue_id: message.venue_id,
      message_id: messageId,
      trace_id: message.trace_id,
      error: errorMarker,
      contains_credentials: false,
    },
    ui_selection: { exact_dead_letter_id: deadLetterId, retry_button_count: 1 },
    retry: { status: retryResponse.status(), response: retryPayload },
    consumption: {
      postgres_message_count: 1,
      dead_letter_deleted: true,
      stream_message_acknowledged: true,
    },
    audit,
    screenshots: [screenshot],
    runtime,
  };
  writeJson("MVP-UAT-008-dead-letter-recovery.json", evidence);
  return { dead_letter_id: deadLetterId, stream_message_id: retryPayload.stream_message_id, audit_trace_id: audit.trace_id };
}

async function confirmUiAction(page, trigger, responsePredicate) {
  await trigger.click();
  await page.locator("#action-dialog").waitFor({ state: "visible" });
  const responsePromise = page.waitForResponse(responsePredicate);
  await page.locator("#action-dialog-submit").click();
  const response = await responsePromise;
  return { response, payload: await responsePayload(response) };
}

async function runRuntimeReload(page, runtime) {
  await openView(page, "diagnostics");
  const config = await confirmUiAction(
    page,
    page.locator('[data-action="reload-config"]'),
    (candidate) => candidate.url().includes("/api/v1/admin/config/reload") && candidate.request().method() === "POST",
  );
  requireCondition(config.response.status() === 200 && config.payload?.status === "ok", `Runtime configuration reload returned HTTP ${config.response.status()}`);

  const watcherCard = page.locator("#skills-list .feed-item").filter({ hasText: "watcher" });
  await watcherCard.waitFor({ state: "visible" });
  requireCondition(await watcherCard.count() === 1, "Watcher Agent card is not uniquely visible in diagnostics");
  const watcher = await confirmUiAction(
    page,
    watcherCard.locator("button"),
    (candidate) => candidate.url().includes("/api/v1/skills/watcher/reload") && candidate.request().method() === "POST",
  );
  requireCondition(watcher.response.status() === 200 && watcher.payload?.status === "ok" && watcher.payload?.skill_name === "watcher", `Watcher Agent reload returned HTTP ${watcher.response.status()}`);

  const auditsPayload = await apiFromPage(page, "/api/v1/admin/audit-logs?limit=500");
  const audits = auditsPayload.audit_logs || auditsPayload.logs || [];
  const configAudit = audits.find((item) => item.action === "CONFIG_RELOADED" && item.resource_id === "runtime" && item.outcome === "SUCCEEDED" && item.trace_id === config.payload.trace_id);
  const watcherAudit = audits.find((item) => item.action === "SKILL_RELOADED" && item.resource_id === "watcher" && item.outcome === "SUCCEEDED" && item.trace_id === watcher.payload.trace_id);
  requireCondition(configAudit, "CONFIG_RELOADED audit evidence is missing");
  requireCondition(watcherAudit, "SKILL_RELOADED watcher audit evidence is missing");
  await page.waitForFunction((traceIds) => traceIds.every((traceId) => document.querySelector("#audit-table")?.innerText.includes(traceId)), [config.payload.trace_id, watcher.payload.trace_id]);

  const screenshot = "runtime-reload-01-config-watcher-1440x900.png";
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, screenshot), fullPage: true });
  assertRuntimeClean(runtime);
  const evidence = {
    uat_id: "MVP-UAT-008",
    operation: "Audited runtime configuration and Watcher Agent reload through the formal diagnostics client",
    config_reload: { status: config.response.status(), response: config.payload, audit: configAudit },
    watcher_reload: { status: watcher.response.status(), response: watcher.payload, audit: watcherAudit },
    screenshots: [screenshot],
    runtime,
  };
  writeJson("MVP-UAT-008-runtime-reload.json", evidence);
  return { config_status: config.response.status(), watcher_status: watcher.response.status(), audit_count: 2 };
}

async function runAppRestart(page, runtime, appContainer, postgresContainer) {
  const principal = await principalFromPage(page);
  const probeId = randomUUID();
  const goal = `UAT App restart recovery ${probeId}: 制定景区闭园前设备巡检、异常升级与复核任务图。`;
  const decompositionPosts = [];
  const recordPost = (request) => {
    if (request.method() === "POST" && request.url().includes("/api/v1/admin/tasks/decompose")) {
      decompositionPosts.push({ url: request.url(), timestamp: Date.now() });
    }
  };
  page.on("request", recordPost);
  let egressDisconnected = false;

  try {
    await openTaskDecompositionForm(page, goal);
    await page.locator("#task-decompose-submit").click();
    await page.waitForFunction(() => Boolean(JSON.parse(sessionStorage.getItem("mp_todo_decomposition") || "null")?.idempotency_key));
    const operation = await readTodoOperation(page);

    const processingRow = await waitForCondition(() => {
      const rows = decompositionRows(postgresContainer, principal, operation.idempotency_key);
      return rows.length === 1 && rows[0].status === "PROCESSING" ? rows[0] : null;
    }, "persisted PROCESSING task decomposition", 30000, 100);
    requireCondition(processingRow.trace_id === operation.trace_id, "PROCESSING decomposition trace does not match the formal client");
    requireCondition(decompositionTaskRows(postgresContainer, processingRow.decomposition_id).length === 0, "PROCESSING decomposition already exposed tasks before restart");
    requireCondition(llmRowsForTraces(postgresContainer, [operation.trace_id]).length === 0, "PROCESSING decomposition already completed an LLM call before restart injection");

    const beforeInspect = parseDockerInspect(appContainer);
    disconnectNetwork(appContainer, SOURCE_EGRESS_NETWORK);
    egressDisconnected = true;
    const heldRows = decompositionRows(postgresContainer, principal, operation.idempotency_key);
    requireCondition(heldRows.length === 1 && heldRows[0].status === "PROCESSING", "Decomposition left PROCESSING before App restart");

    docker(["restart", "--time", "1", appContainer]);
    connectNetwork(appContainer, SOURCE_EGRESS_NETWORK);
    egressDisconnected = false;
    const restartedApp = await waitForContainerHealthy(appContainer, 90000);
    requireCondition(restartedApp.started_at !== beforeInspect.State?.StartedAt, "App container start timestamp did not change after restart");

    const recoveredRow = await waitForCondition(() => {
      const rows = decompositionRows(postgresContainer, principal, operation.idempotency_key);
      return rows.length === 1 && rows[0].status === "FAILED" ? rows[0] : null;
    }, "restart recovery state", 30000, 250);
    requireCondition(recoveredRow.error === "processing_interrupted_by_restart", `Unexpected restart recovery error: ${recoveredRow.error}`);

    await page.waitForTimeout(500);
    const interruptionRuntime = snapshotRuntime(runtime);
    assertExpectedDecompositionTransportFailure(interruptionRuntime, "App restart", true);
    clearRuntime(runtime);

    await page.reload({ waitUntil: "networkidle" });
    await page.waitForFunction(() => document.querySelector("#app-screen")?.classList.contains("active"));
    await page.waitForFunction(() => window.App?.todoDecomposition?.status === "CHECK_REQUIRED");
    await openView(page, "tasks");
    const beforeStatusQuery = await todoUiState(page);
    requireCondition(beforeStatusQuery.idempotency_key === operation.idempotency_key, "Restarted client lost the original Idempotency-Key");
    requireCondition(beforeStatusQuery.trace_id === operation.trace_id, "Restarted client lost the original trace before recovery query");
    requireCondition(beforeStatusQuery.recovery_visible && beforeStatusQuery.submit_disabled, "Restarted client did not lock duplicate submission before status recovery");
    const checkScreenshot = "app-restart-01-check-required-1440x900.png";
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, checkScreenshot), fullPage: true });

    const [statusResponse] = await Promise.all([
      page.waitForResponse((response) => response.request().method() === "GET" && response.url().includes("/api/v1/admin/tasks/decompositions/status")),
      page.locator("#task-decompose-recover").click(),
    ]);
    const statusPayload = await responsePayload(statusResponse);
    requireCondition(statusResponse.status() === 200, `Restart status query returned HTTP ${statusResponse.status()}`);
    requireCondition(statusPayload?.status === "FAILED" && statusPayload?.retryable === true, "Restart status query did not return a retryable FAILED state");
    await page.waitForFunction(() => window.App?.todoDecomposition?.status === "RETRYABLE");
    const afterStatusQuery = await todoUiState(page);
    requireCondition(afterStatusQuery.idempotency_key === operation.idempotency_key, "Recovery query changed the original Idempotency-Key");
    requireCondition(afterStatusQuery.decomposition_id === processingRow.decomposition_id, "Recovery query changed the decomposition identity");
    const retryableScreenshot = "app-restart-02-retryable-1440x900.png";
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, retryableScreenshot), fullPage: true });

    const finalRows = decompositionRows(postgresContainer, principal, operation.idempotency_key);
    const finalTasks = decompositionTaskRows(postgresContainer, processingRow.decomposition_id);
    const traceLineage = [operation.trace_id, recoveredRow.trace_id];
    const llmCalls = llmRowsForTraces(postgresContainer, traceLineage);
    const sideEffects = sideEffectRowsForTraces(postgresContainer, traceLineage);
    requireCondition(decompositionPosts.length === 1, `Restart recovery emitted ${decompositionPosts.length} decomposition POST requests`);
    requireCondition(finalRows.length === 1, `Restart recovery persisted ${finalRows.length} decomposition rows`);
    requireCondition(finalTasks.length === 0, `Restart recovery left ${finalTasks.length} partial or duplicate tasks`);
    requireCondition(llmCalls.length === 0, `Restart recovery produced ${llmCalls.length} completed or duplicate LLM call records`);
    requireCondition(sideEffects.approvals.length === 0 && sideEffects.pushes.length === 0 && sideEffects.tool_invocations.length === 0, "Restart recovery produced an external business side effect");
    requireCondition(!sideEffects.audits.some((item) => ["TASK_CREATED", "TASK_DECOMPOSED"].includes(item.action)), "Restart recovery retained a false successful task audit");
    assertRuntimeClean(runtime);

    const evidence = {
      uat_id: "MVP-UAT-008",
      operation: "Persistent TodoWrite PROCESSING operation interrupted by a real App restart and recovered through the formal client",
      fault_injection: {
        app_container: appContainer,
        egress_network: SOURCE_EGRESS_NETWORK,
        reason: "Hold the persisted PROCESSING window deterministically before restarting App",
        started_at_before: beforeInspect.State?.StartedAt,
        restarted_app: restartedApp,
        egress_restored: isNetworkConnected(appContainer, SOURCE_EGRESS_NETWORK),
      },
      client_operation: {
        goal,
        original_trace_id: operation.trace_id,
        recovery_trace_id: recoveredRow.trace_id,
        idempotency_key: operation.idempotency_key,
        decomposition_id: processingRow.decomposition_id,
      },
      before_restart: processingRow,
      after_restart: recoveredRow,
      status_http: statusResponse.status(),
      status_payload: statusPayload,
      client_before_query: beforeStatusQuery,
      client_after_query: afterStatusQuery,
      duplicate_guards: {
        decomposition_post_count: decompositionPosts.length,
        decomposition_row_count: finalRows.length,
        task_row_count: finalTasks.length,
        llm_call_count: llmCalls.length,
        status_recovery_method: "GET",
      },
      llm_calls: llmCalls,
      side_effects: sideEffects,
      screenshots: [checkScreenshot, retryableScreenshot],
      interruption_runtime: interruptionRuntime,
      recovery_runtime: snapshotRuntime(runtime),
    };
    writeJson("MVP-UAT-008-app-restart-recovery.json", evidence);
    return {
      decomposition_id: processingRow.decomposition_id,
      recovery_status: recoveredRow.status,
      error: recoveredRow.error,
      duplicate_posts: decompositionPosts.length - 1,
      duplicate_tasks: finalTasks.length,
      duplicate_llm_calls: llmCalls.length,
      egress_restored: isNetworkConnected(appContainer, SOURCE_EGRESS_NETWORK),
    };
  } finally {
    if (egressDisconnected || !isNetworkConnected(appContainer, SOURCE_EGRESS_NETWORK)) {
      connectNetwork(appContainer, SOURCE_EGRESS_NETWORK);
    }
    page.off("request", recordPost);
  }
}

function approvalContainsMarker(item, marker) {
  return JSON.stringify(item.args || {}).includes(marker) || JSON.stringify(item).includes(marker);
}

function pushContainsMarker(item, marker) {
  return [item.raw_text, item.event_type, item.delivery_error, item.confirmed_notes].some((value) => String(value || "").includes(marker));
}

async function runLlmFailure(page, runtime, appContainer, postgresContainer) {
  const principal = await principalFromPage(page);
  const probeId = randomUUID();
  const goal = `UAT DeepSeek outage ${probeId}: 生成景区强降雨期间巡检、升级、游客疏导和恢复复核任务图。`;
  const decompositionPosts = [];
  const recordPost = (request) => {
    if (request.method() === "POST" && request.url().includes("/api/v1/admin/tasks/decompose")) {
      decompositionPosts.push({ url: request.url(), timestamp: Date.now() });
    }
  };
  page.on("request", recordPost);
  let egressDisconnected = false;

  try {
    await openTaskDecompositionForm(page, goal);

    let operation;
    let failureRow;
    let failureCalls;
    let failureTasks;
    let failureSideEffects;
    let failureRuntime;
    let retryableUi;
    let statusPayload;
    let retryableScreenshot;
    let localWaitCancelled = false;
    try {
      await page.locator("#task-decompose-submit").click();
      await page.waitForFunction(() => Boolean(JSON.parse(sessionStorage.getItem("mp_todo_decomposition") || "null")?.idempotency_key));
      operation = await readTodoOperation(page);
      const processingRow = await waitForCondition(() => {
        const rows = decompositionRows(postgresContainer, principal, operation.idempotency_key);
        return rows.length === 1 && rows[0].status === "PROCESSING" ? rows[0] : null;
      }, "DeepSeek outage PROCESSING state", 30000, 100);
      requireCondition(processingRow.trace_id === operation.trace_id, "DeepSeek outage PROCESSING trace does not match the formal client");

      disconnectNetwork(appContainer, SOURCE_EGRESS_NETWORK);
      egressDisconnected = true;

      failureRow = await waitForCondition(() => {
        const rows = decompositionRows(postgresContainer, principal, operation.idempotency_key);
        return rows.length === 1 && rows[0].status === "FAILED" ? rows[0] : null;
      }, "DeepSeek outage FAILED state", 90000, 250);
      const browserStatus = await page.evaluate(() => window.App?.todoDecomposition?.status || null);
      if (browserStatus === "RUNNING") {
        await page.locator("#task-decompose-cancel").click();
        localWaitCancelled = true;
      }
      await page.waitForFunction(() => window.App?.todoDecomposition?.status === "CHECK_REQUIRED", null, { timeout: 30000 });
      await page.waitForTimeout(300);
      failureCalls = llmRowsForTraces(postgresContainer, [operation.trace_id]);
      failureTasks = decompositionTaskRows(postgresContainer, failureRow.decomposition_id);
      failureSideEffects = sideEffectRowsForTraces(postgresContainer, [operation.trace_id]);
      const expectedAttempts = Number(docker(["exec", appContainer, "sh", "-c", 'printf "%s" "${LLM_MAX_RETRIES:-3}"']));
      requireCondition(Number.isSafeInteger(expectedAttempts) && expectedAttempts > 0, "App exposes an invalid LLM_MAX_RETRIES value");
      requireCondition(failureCalls.length === 1, `DeepSeek outage produced ${failureCalls.length} LLM evidence rows instead of one aggregated failure`);
      requireCondition(failureCalls[0].status === "FAILED", "DeepSeek outage LLM evidence is not FAILED");
      requireCondition(failureCalls[0].attempt_count === expectedAttempts, `DeepSeek outage recorded ${failureCalls[0].attempt_count} attempts instead of ${expectedAttempts}`);
      requireCondition(failureCalls[0].model_name === "deepseek-v4-flash" && failureCalls[0].is_mock === false, "DeepSeek outage evidence is not a real deepseek-v4-flash call");
      requireCondition(failureTasks.length === 0, "DeepSeek outage created partial tasks");
      requireCondition(failureSideEffects.approvals.length === 0 && failureSideEffects.pushes.length === 0 && failureSideEffects.tool_invocations.length === 0, "DeepSeek outage produced an external business side effect");
      requireCondition(failureSideEffects.audits.some((item) => item.action === "TASK_DECOMPOSITION_FAILED" && item.outcome === "FAILED"), "DeepSeek outage lacks a failure audit");
      requireCondition(!failureSideEffects.audits.some((item) => ["TASK_CREATED", "TASK_DECOMPOSED"].includes(item.action)), "DeepSeek outage produced a false successful task audit");

      failureRuntime = snapshotRuntime(runtime);
      assertExpectedDecompositionTransportFailure(failureRuntime, "DeepSeek outage", localWaitCancelled);
      clearRuntime(runtime);
    } finally {
      if (egressDisconnected || !isNetworkConnected(appContainer, SOURCE_EGRESS_NETWORK)) {
        connectNetwork(appContainer, SOURCE_EGRESS_NETWORK);
      }
      egressDisconnected = false;
    }

    requireCondition(isNetworkConnected(appContainer, SOURCE_EGRESS_NETWORK), "App egress was not restored before the recovery probe");
    await waitForContainerHealthy(appContainer, 30000);
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForFunction(() => document.querySelector("#app-screen")?.classList.contains("active"));
    await page.waitForFunction(() => window.App?.todoDecomposition?.status === "CHECK_REQUIRED");
    await openView(page, "tasks");
    const [statusResponse] = await Promise.all([
      page.waitForResponse((response) => response.request().method() === "GET" && response.url().includes("/api/v1/admin/tasks/decompositions/status")),
      page.locator("#task-decompose-recover").click(),
    ]);
    statusPayload = await responsePayload(statusResponse);
    requireCondition(statusResponse.status() === 200, `DeepSeek failure status query returned HTTP ${statusResponse.status()}`);
    requireCondition(statusPayload?.status === "FAILED" && statusPayload?.retryable === true, "DeepSeek failure status query did not offer manual recovery");
    await page.waitForFunction(() => window.App?.todoDecomposition?.status === "RETRYABLE");
    retryableUi = await todoUiState(page);
    requireCondition(retryableUi.idempotency_key === operation.idempotency_key, "Manual recovery lost the original Idempotency-Key");
    requireCondition(retryableUi.recovery_visible && retryableUi.recovery_text.includes("继续"), "Formal client did not expose an explicit manual retry action");
    retryableScreenshot = "llm-failure-01-retryable-1440x900.png";
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, retryableScreenshot), fullPage: true });

    const recoveryResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/v1/admin/tasks/decompose"),
      { timeout: 180000 },
    );
    await page.locator("#task-decompose-recover").click();
    const recoveryResponse = await recoveryResponsePromise;
    const recoveryPayload = await responsePayload(recoveryResponse);
    requireCondition(recoveryResponse.status() === 201, `DeepSeek recovery returned HTTP ${recoveryResponse.status()}`);
    await page.waitForFunction(() => window.App?.todoDecomposition?.status === "SUCCEEDED", null, { timeout: 30000 });
    await page.waitForTimeout(500);
    const recoveredUi = await todoUiState(page);
    requireCondition(recoveredUi.idempotency_key === operation.idempotency_key, "Successful recovery changed the Idempotency-Key");
    requireCondition(recoveredUi.trace_id === operation.trace_id, "Successful recovery changed the original trace");
    requireCondition(recoveredUi.tasks_created > 0, "Successful recovery did not report created tasks");
    const recoveredScreenshot = "llm-failure-02-recovered-1440x900.png";
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, recoveredScreenshot), fullPage: true });

    const finalRows = decompositionRows(postgresContainer, principal, operation.idempotency_key);
    requireCondition(finalRows.length === 1 && finalRows[0].status === "COMPLETED", "DeepSeek recovery did not complete the original decomposition row");
    const finalTasks = decompositionTaskRows(postgresContainer, finalRows[0].decomposition_id);
    const finalCalls = llmRowsForTraces(postgresContainer, [operation.trace_id]);
    const finalSideEffects = sideEffectRowsForTraces(postgresContainer, [operation.trace_id]);
    const successfulCalls = finalCalls.filter((item) => item.status === "SUCCEEDED");
    requireCondition(decompositionPosts.length === 2, `DeepSeek failure and manual recovery emitted ${decompositionPosts.length} POST requests`);
    requireCondition(finalTasks.length === recoveredUi.tasks_created, "DeepSeek recovery task count does not match the formal client");
    requireCondition(successfulCalls.length === 1, `DeepSeek network recovery produced ${successfulCalls.length} successful LLM calls`);
    requireCondition(successfulCalls[0].model_name === "deepseek-v4-flash" && successfulCalls[0].is_mock === false && successfulCalls[0].request_id, "DeepSeek recovery lacks Live deepseek-v4-flash evidence");
    requireCondition(finalSideEffects.approvals.length === 0 && finalSideEffects.pushes.length === 0 && finalSideEffects.tool_invocations.length === 0, "DeepSeek failure/recovery emitted an unrelated external business action");
    assertRuntimeClean(runtime);

    const evidence = {
      uat_id: "MVP-UAT-010",
      operation: "DeepSeek network outage, bounded retry, explicit manual recovery, and verified Live restoration",
      fault_injection: {
        app_container: appContainer,
        egress_network: SOURCE_EGRESS_NETWORK,
        method: "Persist through the formal client first, then disconnect App egress; PostgreSQL remained available and the client preserved the operation for status recovery",
        egress_restored: isNetworkConnected(appContainer, SOURCE_EGRESS_NETWORK),
      },
      client_operation: {
        goal,
        trace_id: operation.trace_id,
        idempotency_key: operation.idempotency_key,
        decomposition_id: failureRow.decomposition_id,
      },
      failure: {
        transport_status: failureRuntime.http_errors[0]?.status || "REQUEST_INTERRUPTED",
        local_wait_cancelled: localWaitCancelled,
        decomposition: failureRow,
        llm_calls: failureCalls,
        tasks: failureTasks,
        side_effects: failureSideEffects,
        client: retryableUi,
        status: statusPayload,
        runtime: failureRuntime,
      },
      recovery: {
        http_status: recoveryResponse.status(),
        response: recoveryPayload,
        decomposition: finalRows[0],
        llm_calls: finalCalls,
        tasks: finalTasks,
        side_effects: finalSideEffects,
        client: recoveredUi,
        runtime: snapshotRuntime(runtime),
      },
      duplicate_guards: {
        decomposition_post_count: decompositionPosts.length,
        decomposition_row_count: finalRows.length,
        failed_phase_task_count: failureTasks.length,
        final_task_count: finalTasks.length,
        successful_llm_call_count: successfulCalls.length,
      },
      screenshots: [retryableScreenshot, recoveredScreenshot],
    };
    writeJson("MVP-UAT-010-llm-failure-recovery.json", evidence);
    return {
      failure_status: failureRuntime.http_errors[0]?.status || "REQUEST_INTERRUPTED",
      failed_attempts: failureCalls[0].attempt_count,
      manual_state: retryableUi.app_status,
      recovery_status: recoveryResponse.status(),
      recovery_model: successfulCalls[0].model_name,
      tasks_created: finalTasks.length,
      egress_restored: isNetworkConnected(appContainer, SOURCE_EGRESS_NETWORK),
    };
  } finally {
    if (egressDisconnected || !isNetworkConnected(appContainer, SOURCE_EGRESS_NETWORK)) {
      connectNetwork(appContainer, SOURCE_EGRESS_NETWORK);
    }
    page.off("request", recordPost);
  }
}

async function runIntegrations(page, runtime) {
  await openView(page, "settings");
  await page.locator("#settings-integrations .feed-item").first().waitFor({ state: "visible" });
  const integrationsPayload = await apiFromPage(page, "/api/v1/admin/integrations");
  const integrations = integrationsPayload.integrations || [];
  const byId = Object.fromEntries(integrations.map((item) => [item.id, item]));
  requireCondition(byId.deepseek?.status === "READY" && byId.deepseek?.model === "deepseek-v4-flash" && byId.deepseek?.live_verified === true, "DeepSeek integration is not READY with deepseek-v4-flash Live evidence");
  requireCondition(byId.in_app?.status === "READY" && byId.in_app?.live_verified === true, "In-app integration is not READY with delivery evidence");
  for (const integrationId of ["wechat", "sms", "voice"]) {
    requireCondition(byId[integrationId]?.status === "DISABLED_REQUIRES_CONFIG", `${integrationId} integration is not safely disabled`);
    requireCondition(byId[integrationId]?.configured === false, `${integrationId} unexpectedly reports configured`);
  }
  const settingsCards = await page.locator("#settings-integrations .feed-item").allInnerTexts();
  const settingsScreenshot = "integrations-01-settings-1440x900.png";
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, settingsScreenshot), fullPage: true });

  await openView(page, "actions");
  await page.locator('#view-actions [data-action="new-action-request"]').click();
  await page.locator("#action-dialog").waitFor({ state: "visible" });
  const actionOptions = await page.locator("#action-field-tool_name option").evaluateAll((options) => options.map((option) => ({
    value: option.value,
    text: option.textContent.trim(),
    disabled: option.disabled,
  })));
  for (const toolName of ["send_sms", "send_alert"]) {
    const option = actionOptions.find((item) => item.value === toolName);
    requireCondition(option?.disabled === true, `${toolName} remains selectable in the formal client`);
  }
  const actionsScreenshot = "integrations-02-disabled-actions-1440x900.png";
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, actionsScreenshot), fullPage: true });
  await page.locator('#action-dialog [data-close="action-dialog"]').first().click();

  const sessionsPayload = await apiFromPage(page, "/api/v1/sessions/?limit=200");
  const session = (sessionsPayload.sessions || sessionsPayload || [])[0];
  requireCondition(session?.session_id, "No current-venue session is available for disabled integration probes");
  const beforeApprovalsPayload = await apiFromPage(page, "/api/v1/admin/approvals?status=ALL");
  const beforePushesPayload = await apiFromPage(page, "/api/v1/admin/push_logs?limit=200");
  const beforeApprovals = Array.isArray(beforeApprovalsPayload) ? beforeApprovalsPayload : beforeApprovalsPayload.approvals || [];
  const beforePushes = beforePushesPayload.push_logs || [];
  const marker = `uat-integration-disabled-${randomUUID()}`;
  const sms = await requestFromPage(page, "/api/v1/admin/action-requests", "POST", {
    tool_name: "send_sms",
    session_id: session.session_id,
    recipient: "13800138000",
    message: `${marker}-sms`,
    priority: "high",
  });
  const alert = await requestFromPage(page, "/api/v1/admin/action-requests", "POST", {
    tool_name: "send_alert",
    session_id: session.session_id,
    message: `${marker}-alert`,
    priority: "warning",
  });
  for (const [toolName, result] of [["send_sms", sms], ["send_alert", alert]]) {
    requireCondition(result.status === 409, `${toolName} did not return HTTP 409`);
    requireCondition(result.payload?.detail?.code === "INTEGRATION_DISABLED", `${toolName} did not return INTEGRATION_DISABLED`);
  }

  const afterApprovalsPayload = await apiFromPage(page, "/api/v1/admin/approvals?status=ALL");
  const afterPushesPayload = await apiFromPage(page, "/api/v1/admin/push_logs?limit=200");
  const afterApprovals = Array.isArray(afterApprovalsPayload) ? afterApprovalsPayload : afterApprovalsPayload.approvals || [];
  const afterPushes = afterPushesPayload.push_logs || [];
  requireCondition(!afterApprovals.some((item) => approvalContainsMarker(item, marker)), "Disabled integration probe created a fake approval");
  requireCondition(!afterPushes.some((item) => pushContainsMarker(item, marker)), "Disabled integration probe created a fake push");
  requireCondition(afterApprovals.length === beforeApprovals.length, "Disabled integration probes changed the approval count");
  requireCondition(afterPushes.length === beforePushes.length, "Disabled integration probes changed the push count");

  assertRuntimeClean(runtime);
  const evidence = {
    uat_id: "MVP-UAT-010",
    operation: "Evidence-backed integration status and safe-disabled external actions",
    integrations,
    ui: { settings_cards: settingsCards, controlled_action_options: actionOptions },
    disabled_action_probes: {
      marker,
      send_sms: sms,
      send_alert: alert,
      approval_count_before: beforeApprovals.length,
      approval_count_after: afterApprovals.length,
      push_count_before: beforePushes.length,
      push_count_after: afterPushes.length,
      fake_approval_created: false,
      fake_push_created: false,
    },
    screenshots: [settingsScreenshot, actionsScreenshot],
    runtime,
  };
  writeJson("MVP-UAT-010-integrations.json", evidence);
  return {
    deepseek: `${byId.deepseek.status}/${byId.deepseek.model}`,
    in_app: byId.in_app.status,
    external_channels: ["wechat", "sms", "voice"].map((id) => `${id}:${byId[id].status}`),
    disabled_probe_statuses: [sms.status, alert.status],
  };
}

async function main() {
  requireCondition(SUPPORTED_MODES.has(MODE), `Usage: node uat_operations_runner.cjs ${[...SUPPORTED_MODES].join("|")}`);
  const browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const runtime = attachRuntime(page);
  try {
    let result;
    if (MODE === "restore") {
      const restoreStack = collectHealthyStack(RESTORE_PROJECT, restoreContainer);
      const appContainer = restoreStack.find((item) => item.service === "app").container;
      await login(page, { baseUrl: RESTORE_URL, appContainer });
      result = await runRestore(page, runtime, restoreStack);
    } else {
      const appContainer = sourceContainer("app");
      await login(page, { baseUrl: SOURCE_URL, appContainer });
      if (MODE === "dead-letter") {
        result = await runDeadLetter(page, runtime, sourceContainer("redis"), sourceContainer("postgres"));
      } else if (MODE === "runtime-reload") {
        result = await runRuntimeReload(page, runtime);
      } else if (MODE === "app-restart") {
        result = await runAppRestart(page, runtime, appContainer, sourceContainer("postgres"));
      } else if (MODE === "llm-failure") {
        result = await runLlmFailure(page, runtime, appContainer, sourceContainer("postgres"));
      } else {
        result = await runIntegrations(page, runtime);
      }
    }
    process.stdout.write(`${JSON.stringify(redact({ mode: MODE, status: "PASSED", ...result }), null, 2)}\n`);
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.name}: ${redactString(error.message)}\n`);
  process.exitCode = 1;
});
