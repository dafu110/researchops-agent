let lastRunId = null;

const $ = (selector) => document.querySelector(selector);
const tokenKey = "researchops-token";
const apiKeyKey = "researchops-api-key";

const labels = {
  step: {
    intake: "需求识别",
    planner: "规划器",
    tool_call: "工具调用",
    retrieve_evidence: "证据检索",
    compose_answer: "生成回答",
    synthesize_report: "报告生成",
    human_approval: "人工审批",
    human_approval_requested: "审批已创建",
    tool_agent: "工具执行",
    rag_research: "RAG 研究",
    final_response: "最终响应",
  },
  state: {
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    pending: "等待中",
    approved: "已批准",
    rejected: "已拒绝",
    canceled: "已取消",
  },
  task: {
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    canceled: "已取消",
  },
  kind: {
    ingest_github_repo: "GitHub 接入",
    ingest_text: "文本接入",
    ingest_url: "URL 接入",
    eval_run: "评测运行",
  },
  risk: {
    low: "低风险",
    medium: "中风险",
    high: "高风险",
    critical: "严重风险",
  },
  stage: {
    intake: "输入",
    execution: "执行",
    retrieval: "检索",
    response: "响应",
    artifact: "产物",
    approval: "审批",
  },
};

const escapeHtml = (value) =>
  String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);

const localize = (group, value) => labels[group]?.[value] || value || "-";

async function getJson(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = localStorage.getItem(tokenKey) || "";
  const apiKey = localStorage.getItem(apiKeyKey) || "";
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!token && apiKey) headers.set("X-API-Key", apiKey);
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

const setStatus = (text, state = "ready") => {
  $("#status").textContent = text;
  $("#status").dataset.state = state;
};

const setBusy = (busy) => {
  ["#ask-button", "#run-eval", "#refresh"].forEach((selector) => {
    const element = $(selector);
    if (element) element.disabled = busy;
  });
};

const item = (title, body, extra = "") =>
  `<div class="item"><strong>${escapeHtml(title)}</strong><div>${escapeHtml(body)}</div>${extra}</div>`;

async function refresh() {
  try {
    const [docs, approvals, summary, tasks, audit] = await Promise.all([
      getJson("/api/documents"),
      getJson("/api/approvals"),
      getJson("/api/eval/summary"),
      getJson("/api/tasks"),
      getJson(auditUrl()),
    ]);
    const [users, system] = await Promise.all([safeJson("/api/users", []), safeJson("/api/system/config", null)]);

    $("#metric-docs").textContent = summary.document_count;
    $("#metric-chunks").textContent = summary.chunk_count;
    $("#metric-runs").textContent = summary.run_count;
    $("#metric-coverage").textContent = Number(summary.citation_coverage).toFixed(2);
    $("#documents-list").innerHTML = docs.length
      ? docs.map((doc) => item(doc.title, `${doc.source} | ${doc.chunk_count} 分块 | ${doc.status}`)).join("")
      : emptyText("暂无资料");
    $("#approvals-list").innerHTML = approvals.length ? approvals.map(renderApproval).join("") : emptyText("暂无审批");
    $("#tasks-list").innerHTML = tasks.length ? tasks.map(renderTask).join("") : emptyText("暂无任务");
    $("#audit-list").innerHTML = audit.length ? audit.map(renderAudit).join("") : emptyText("暂无审计");
    $("#users-list").innerHTML = users.length ? users.map(renderUser).join("") : emptyText("暂无用户");
    $("#eval-list").innerHTML = renderEvalSummary(summary);
    $("#system-list").innerHTML = renderSystem(system);
    if (system) {
      $("#sidebar-runtime").textContent = `${system.task_backend} / ${system.agent_runtime}`;
      $("#sidebar-store").textContent = `存储：${system.active_store}`;
    }
    if (lastRunId) await refreshTrace();
    setStatus("就绪", "ready");
  } catch (error) {
    setStatus("错误", "error");
    $("#answer").textContent = formatError(error);
  }
}

async function safeJson(url, fallback) {
  try {
    return await getJson(url);
  } catch {
    return fallback;
  }
}

function auditUrl() {
  const params = new URLSearchParams();
  const risk = $("#audit-risk")?.value || "";
  const status = $("#audit-status")?.value || "";
  const target = $("#audit-target")?.value.trim() || "";
  if (risk) params.set("risk_level", risk);
  if (status) params.set("status", status);
  if (target) params.set("target", target);
  const query = params.toString();
  return query ? `/api/audit?${query}` : "/api/audit";
}

async function refreshTrace() {
  const trace = await getJson(`/api/runs/${lastRunId}/trace`);
  $("#trace-list").innerHTML = trace.steps.length ? trace.steps.map(renderTraceStep).join("") : emptyText("暂无追踪");
}

function renderTraceStep(step) {
  const error = step.error ? `<div class="muted">${escapeHtml(step.error)}</div>` : "";
  return `<div class="step" data-state="${escapeHtml(step.status)}">
    <strong>${escapeHtml(localize("step", step.name))}</strong>
    <div>${escapeHtml(localize("state", step.status))} | ${step.latency_ms ?? 0}ms</div>${error}</div>`;
}

function renderPlan(steps) {
  $("#plan-list").innerHTML = steps.length ? steps.map(renderPlanStep).join("") : emptyText("暂无计划");
}

function renderPlanStep(step) {
  const tool = step.tool_hint ? ` | 工具：${step.tool_hint}` : "";
  const approval = step.needs_approval ? " | 需要审批" : "";
  return `<div class="step plan-step" data-state="${escapeHtml(step.risk_level)}">
    <strong>${escapeHtml(localize("step", step.name))}</strong>
    <div>${escapeHtml(localize("stage", step.stage))} | ${escapeHtml(localize("risk", step.risk_level))}${escapeHtml(tool)}${escapeHtml(approval)}</div>
    <div class="muted">${escapeHtml(step.goal)} | 置信度 ${Math.round(Number(step.confidence || 0) * 100)}%</div>
  </div>`;
}

function renderApproval(row) {
  const buttons = row.status === "pending"
    ? `<div class="actions"><button class="small" data-approve="${row.approval_id}">批准</button>
       <button class="small secondary" data-reject="${row.approval_id}">拒绝</button></div>`
    : "";
  return item(`${localize("state", row.status)} | ${localize("risk", row.risk_level)}`, row.action, buttons);
}

function renderTask(row) {
  const chunks = row.result?.chunks_indexed != null ? ` | ${row.result.chunks_indexed} 分块` : "";
  const attempts = ` | 尝试 ${row.attempts}/${row.max_attempts}`;
  const error = row.error ? ` | ${row.error}` : "";
  const canCancel = ["queued", "running"].includes(row.status);
  const canRetry = ["failed", "canceled"].includes(row.status) && row.attempts < row.max_attempts;
  const actions = canCancel || canRetry
    ? `<div class="actions">
        ${canCancel ? `<button class="small secondary" data-cancel-task="${row.task_id}">取消</button>` : ""}
        ${canRetry ? `<button class="small" data-retry-task="${row.task_id}">重试</button>` : ""}
      </div>`
    : "";
  return item(
    `${localize("task", row.status)} | ${localize("kind", row.kind)}`,
    `${row.title}${chunks}${attempts}${error}`,
    actions,
  );
}

function renderAudit(row) {
  const replay = row.run_id
    ? `<div class="actions"><button class="small secondary" data-replay="${row.run_id}">回放</button></div>`
    : "";
  return item(
    `${localize("risk", row.risk_level)} | ${row.target}`,
    `${localize("state", row.status)} | ${row.detail || row.action}`,
    replay,
  );
}

function renderUser(row) {
  return item(
    `${row.user_id} | ${row.role}`,
    `tenant=${row.tenant_id} | sources=${row.allowed_sources.join(", ") || "*"}`,
    `<div class="actions"><button class="small secondary" data-delete-user="${row.user_id}">删除</button></div>`,
  );
}

function renderSystem(system) {
  if (!system) return emptyText("需要管理员权限查看系统配置");
  const roleRows = Object.entries(system.roles)
    .map(([role, permissions]) => `<div class="permission-row"><strong>${escapeHtml(role)}</strong><span>${escapeHtml(permissions.join(" / "))}</span></div>`)
    .join("");
  return `
    <div class="system-grid">
      ${item("运行环境", `${system.app_env} | auth=${system.auth_required}`)}
      ${item("存储", `${system.active_store} | 配置=${system.store_backend}`)}
      ${item("队列", system.task_backend)}
      ${item("Agent", `${system.agent_runtime} | embedding=${system.embedding_provider}`)}
      ${item("沙箱", system.sandbox_mode)}
      ${item("限制", Object.entries(system.limits).map(([key, value]) => `${key}=${value}`).join(" | "))}
    </div>
    <div class="permissions">${roleRows}</div>`;
}

function renderEvalSummary(summary) {
  const coverage = Math.max(0, Math.min(1, Number(summary.citation_coverage || 0)));
  return `<div class="item metric-item"><strong>引用覆盖</strong><div>${coverage.toFixed(2)}</div>
    <div class="bar"><span style="width:${coverage * 100}%"></span></div></div>`;
}

function renderEvalResult(result) {
  const body = result.passed ? "通过" : `缺少：${result.missing_terms.join(", ") || "无"}`;
  return item(result.case_id, body);
}

function emptyText(text) {
  return `<span class="empty">${escapeHtml(text)}</span>`;
}

function formatError(error) {
  try {
    const parsed = JSON.parse(String(error.message || error));
    return parsed.detail ? `请求失败：${parsed.detail}` : `请求失败：${JSON.stringify(parsed)}`;
  } catch {
    return `请求失败：${String(error.message || error)}`;
  }
}

async function decideApproval(approvalId, approved) {
  await getJson(`/api/approvals/${approvalId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, reviewer: "dashboard" }),
  });
  await refresh();
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const apiKey = $("#api-key").value.trim();
  const userId = $("#login-user").value.trim();
  const password = $("#login-password").value;
  localStorage.setItem(apiKeyKey, apiKey);
  if (!userId && !password) {
    setStatus("就绪", "ready");
    await refresh();
    return;
  }
  const response = await getJson("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey || null, user_id: userId || null, password: password || null }),
  });
  localStorage.setItem(tokenKey, response.access_token);
  setStatus(`已登录：${response.user_id}`, "ready");
  await refresh();
});

$("#ask-button").addEventListener("click", async () => {
  const question = $("#question").value.trim();
  if (!question) return;
  setBusy(true);
  setStatus("运行中", "running");
  try {
    const response = await getJson("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, corpus_ids: [] }),
    });
    lastRunId = response.run_id;
    $("#run-id").textContent = `运行 ${response.run_id.slice(0, 8)}`;
    $("#answer").textContent = response.answer;
    renderPlan(response.plan_details || []);
    $("#citations").innerHTML = response.citations.length
      ? response.citations.map((citation) => item(`${citation.title} | ${citation.locator}`, citation.excerpt)).join("")
      : emptyText("暂无引用");
    await refresh();
  } catch (error) {
    setStatus("错误", "error");
    $("#answer").textContent = formatError(error);
  } finally {
    setBusy(false);
  }
});

$("#file-ingest").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("#file-input").files[0];
  if (!file) return;
  setBusy(true);
  try {
    const body = new FormData();
    body.append("file", file);
    const response = await getJson("/api/ingest", { method: "POST", body });
    $("#answer").textContent = `已索引 ${response.source}，共 ${response.chunks_indexed} 个分块。`;
    $("#file-input").value = "";
    await refresh();
  } catch (error) {
    $("#answer").textContent = formatError(error);
  } finally {
    setBusy(false);
  }
});

$("#url-ingest").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = $("#url-input").value.trim();
  if (!url) return;
  const response = await createJsonTask("/api/ingest/url/async", { url });
  $("#answer").textContent = `URL 接入任务已创建：${response.task_id.slice(0, 8)}。`;
  $("#url-input").value = "";
  await refresh();
});

$("#repo-ingest").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = $("#repo-input").value.trim();
  const ref = $("#repo-ref").value.trim() || "main";
  if (!url) return;
  const response = await createJsonTask("/api/ingest/github/async", { url, ref });
  $("#answer").textContent = `GitHub 接入任务已创建：${response.task_id.slice(0, 8)}。`;
  $("#repo-input").value = "";
  $("#repo-ref").value = "";
  await refresh();
});

$("#text-ingest").addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = $("#text-title").value.trim();
  const text = $("#text-body").value.trim();
  if (!title || !text) return;
  const response = await createJsonTask("/api/ingest/text/async", { title, text, source: "manual" });
  $("#answer").textContent = `文本接入任务已创建：${response.task_id.slice(0, 8)}。`;
  $("#text-title").value = "";
  $("#text-body").value = "";
  await refresh();
});

async function createJsonTask(url, payload) {
  setBusy(true);
  setStatus("运行中", "running");
  try {
    return await getJson(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } finally {
    setBusy(false);
  }
}

$("#run-eval").addEventListener("click", async () => {
  setBusy(true);
  setStatus("评测中", "running");
  try {
    const response = await getJson("/api/eval/run", { method: "POST" });
    $("#eval-list").innerHTML =
      `<div class="item"><strong>通过率</strong><div>${response.pass_rate.toFixed(2)}</div>
      <div class="bar"><span style="width:${response.pass_rate * 100}%"></span></div></div>` +
      response.results.map(renderEvalResult).join("");
    setStatus("就绪", "ready");
  } catch (error) {
    setStatus("错误", "error");
    $("#eval-list").innerHTML = item("评测失败", formatError(error));
  } finally {
    setBusy(false);
  }
});

$("#recover-tasks").addEventListener("click", async () => {
  try {
    const response = await getJson("/api/system/tasks/recover", { method: "POST" });
    $("#answer").textContent = `已恢复 ${response.recovered} 个卡住任务。`;
    await refresh();
  } catch (error) {
    $("#answer").textContent = formatError(error);
  }
});

$("#audit-filter").addEventListener("submit", async (event) => {
  event.preventDefault();
  await refresh();
});

$("#user-create").addEventListener("submit", async (event) => {
  event.preventDefault();
  const userId = $("#new-user-id").value.trim();
  const password = $("#new-user-password").value;
  const role = $("#new-user-role").value;
  if (!userId || !password) return;
  try {
    await getJson("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, password, role }),
    });
    $("#new-user-id").value = "";
    $("#new-user-password").value = "";
    await refresh();
  } catch (error) {
    $("#answer").textContent = formatError(error);
  }
});

document.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const prompt = target.getAttribute("data-prompt");
  if (prompt) {
    $("#question").value = prompt;
    $("#question").focus();
    return;
  }
  const approve = target.getAttribute("data-approve");
  const reject = target.getAttribute("data-reject");
  const deleteUser = target.getAttribute("data-delete-user");
  const cancelTask = target.getAttribute("data-cancel-task");
  const retryTask = target.getAttribute("data-retry-task");
  const replay = target.getAttribute("data-replay");
  if (approve) await decideApproval(approve, true);
  if (reject) await decideApproval(reject, false);
  if (deleteUser) {
    await getJson(`/api/users/${encodeURIComponent(deleteUser)}`, { method: "DELETE" });
    await refresh();
  }
  if (cancelTask) {
    await getJson(`/api/tasks/${encodeURIComponent(cancelTask)}/cancel`, { method: "POST" });
    await refresh();
  }
  if (retryTask) {
    await getJson(`/api/tasks/${encodeURIComponent(retryTask)}/retry`, { method: "POST" });
    await refresh();
  }
  if (replay) {
    const response = await getJson(`/api/audit/replay/${encodeURIComponent(replay)}`);
    $("#answer").textContent = JSON.stringify(response, null, 2);
  }
});

$("#refresh").addEventListener("click", refresh);
$("#api-key").value = localStorage.getItem(apiKeyKey) || "";
refresh();
