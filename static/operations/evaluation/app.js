(function () {
  "use strict";

  var state = { runs: [], selected: null, filter: "all" };

  var SCENARIO_LABELS = {
    DEVICE_ANOMALY: "设备异常",
    CROWD_ALERT: "客流告警",
    NO_KNOWLEDGE_HIT: "无知识命中",
    DEVICE: "设备安全",
    CROWD: "客流秩序",
    WEATHER: "天气防汛",
    EMERGENCY: "应急处置",
    KNOWLEDGE: "知识类",
    NO_KNOWLEDGE_BASE: "知识库外"
  };

  var STATUS_LABELS = {
    GROUNDED: "有依据",
    NO_EVIDENCE: "没有依据",
    RETRIEVAL_FAILED: "未获得模型建议",
    READY: "已就绪",
    DEGRADED: "已降级",
    FAILED: "失败",
    ERROR: "运行异常"
  };

  var TIER_LABELS = { contract: "契约门禁", deep: "深度评分" };

  function pct(value) { return (Number(value || 0) * 100).toFixed(1) + "%"; }
  function stamp(value) {
    if (!value) { return "—"; }
    return new Date(Number(value) * 1000).toLocaleString("zh-CN", { hour12: false });
  }
  function seconds(value) { return value == null ? "—" : Number(value).toFixed(1) + "s"; }
  function label(map, key, fallback) { return map[key] || fallback || key || "—"; }

  function token() {
    return sessionStorage.getItem("mp_access_token") || "";
  }

  function api(path) {
    var headers = { "Content-Type": "application/json" };
    if (token()) { headers.Authorization = "Bearer " + token(); }
    return fetch(path, { headers: headers }).then(function (response) {
      if (response.status === 401) { throw new Error("登录已过期，请重新登录运维账号"); }
      if (!response.ok) { throw new Error(response.status + " " + response.statusText); }
      return response.json();
    });
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function renderCards(runs) {
    var host = document.getElementById("summary-cards");
    if (!runs.length) {
      host.innerHTML = '<p class="empty">尚无评估记录。</p>';
      return;
    }
    var contract = runs.filter(function (r) { return r.tier === "contract"; });
    var deep = runs.filter(function (r) { return r.tier === "deep"; });
    var cards = [];
    if (contract.length) {
      var latestContract = contract[0];
      var tone = latestContract.pass_rate >= 1 ? "ok" : (latestContract.failed_count > 5 ? "bad" : "warn");
      cards.push('<article class="card ' + tone + '"><div class="label">契约门禁 · 最新</div>' +
        '<div class="value">' + latestContract.passed_count + " / " + latestContract.case_count + "</div>" +
        '<div class="sub">通过率 ' + pct(latestContract.pass_rate) + " · 耗时 " + seconds(latestContract.elapsed_seconds) + "</div></article>");
      var summary = latestContract.summary || {};
      if (summary.real_calls != null) {
        cards.push('<article class="card"><div class="label">真实模型调用</div>' +
          '<div class="value">' + summary.real_calls + "</div>" +
          '<div class="sub">Mock ' + (summary.mocked_calls || 0) + (summary.mocked_calls ? "  · 存在 Mock，请核对" : "  · 无伪造调用") + "</div></article>");
      }
    }
    if (deep.length) {
      var latestDeep = deep[0];
      cards.push('<article class="card ' + (latestDeep.pass_rate >= 1 ? "ok" : "warn") + '"><div class="label">深度评分 · 最新</div>' +
        '<div class="value">' + latestDeep.passed_count + " / " + latestDeep.case_count + "</div>" +
        '<div class="sub">判官 ' + esc(latestDeep.judge_model || "—") + " · 通过率 " + pct(latestDeep.pass_rate) + "</div></article>");
    }
    cards.push('<article class="card"><div class="label">评估运行总数</div><div class="value">' + runs.length +
      '</div><div class="sub">契约 ' + contract.length + " 次 · 深度 " + deep.length + " 次</div></article>");
    host.innerHTML = cards.join("");
  }

  function renderRuns(runs) {
    var tbody = document.querySelector("#runs-table tbody");
    document.getElementById("runs-empty").hidden = runs.length > 0;
    document.getElementById("run-count").textContent = runs.length ? "共 " + runs.length + " 次" : "";
    tbody.innerHTML = runs.map(function (run) {
      return "<tr>" +
        '<td class="mono">' + stamp(run.created_at) + "</td>" +
        "<td>" + label(TIER_LABELS, run.tier, run.tier) + "</td>" +
        "<td>" + esc(run.case_set) + "</td>" +
        "<td>" + run.passed_count + " / " + run.case_count + "</td>" +
        '<td><span class="pill ' + (run.pass_rate >= 1 ? "ok" : "warn") + '">' + pct(run.pass_rate) + "</span></td>" +
        "<td>" + esc(run.judge_model || "—") + "</td>" +
        "<td>" + seconds(run.elapsed_seconds) + "</td>" +
        '<td><button type="button" data-run="' + esc(run.run_id) + '">查看明细</button></td></tr>';
    }).join("");
  }

  function caseRow(item) {
    var expected = label(STATUS_LABELS, item.expected_status, item.expected_status);
    var actualKey = item.actual || item.evidence_status || item.expected_status;
    var passed = Boolean(item.passed || item.success);
    var citations = Array.isArray(item.citations) && item.citations.length ? item.citations.join(", ") : "—";
    var score = item.score == null ? "—" : Number(item.score).toFixed(3);
    var reason = item.reason ? '<div class="reason">' + esc(item.reason) + "</div>" : "";
    var advice = item.advice_text ? '<div class="reason">' + esc(item.advice_text) + "</div>" : "";
    return "<tr>" +
      '<td class="mono">' + esc(item.case_id) + "</td>" +
      "<td>" + label(SCENARIO_LABELS, item.scenario_type, item.scenario_type) + "</td>" +
      "<td>" + expected + "</td>" +
      '<td><span class="pill ' + (passed ? "ok" : "bad") + '">' + label(STATUS_LABELS, actualKey, actualKey) + "</span>" + reason + advice + "</td>" +
      '<td class="mono">' + esc(citations) + "</td>" +
      "<td>" + score + "</td>" +
      "<td>" + (item.latency == null ? "—" : seconds(item.latency)) + "</td></tr>";
  }

  function renderCases(run) {
    document.getElementById("detail-panel").hidden = false;
    document.getElementById("detail-title").textContent =
      run.case_set + " · " + stamp(run.created_at) + " · 通过 " + run.passed_count + "/" + run.case_count;
    var results = run.results || [];
    var filtered = results.filter(function (item) {
      if (state.filter === "all") { return true; }
      if (state.filter === "failed") { return !(item.passed || item.success); }
      return (item.expected_status || item.evidence_status) === state.filter;
    });
    document.querySelector("#cases-table tbody").innerHTML = filtered.length
      ? filtered.map(caseRow).join("")
      : '<tr><td colspan="7" class="empty">没有符合条件的用例。</td></tr>';
  }

  function reportError(error) {
    document.getElementById("summary-cards").innerHTML =
      '<p class="empty">加载失败：' + esc(error && error.message ? error.message : error) + "</p>";
  }

  function loadRuns() {
    var tier = document.getElementById("tier-filter").value;
    var query = tier ? "?tier=" + encodeURIComponent(tier) : "";
    return api("/api/v1/operations/scenic/evaluation-runs" + query)
      .then(function (payload) {
        state.runs = payload.runs || [];
        renderCards(state.runs);
        renderRuns(state.runs);
        document.getElementById("detail-panel").hidden = true;
      })
      .catch(reportError);
  }

  function openRun(runId) {
    return api("/api/v1/operations/scenic/evaluation-runs/" + encodeURIComponent(runId))
      .then(function (run) {
        state.selected = run;
        state.filter = "all";
        document.querySelectorAll(".chip").forEach(function (chip) {
          chip.classList.toggle("active", chip.dataset.filter === "all");
        });
        renderCases(run);
        document.getElementById("detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
      })
      .catch(reportError);
  }

  document.getElementById("refresh").addEventListener("click", loadRuns);
  document.getElementById("tier-filter").addEventListener("change", loadRuns);
  document.querySelector("#runs-table tbody").addEventListener("click", function (event) {
    var button = event.target.closest("button[data-run]");
    if (button) { openRun(button.dataset.run); }
  });
  document.querySelectorAll(".chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      state.filter = chip.dataset.filter;
      document.querySelectorAll(".chip").forEach(function (other) {
        other.classList.toggle("active", other === chip);
      });
      if (state.selected) { renderCases(state.selected); }
    });
  });

  loadRuns();
})();
