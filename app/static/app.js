let lastRunId = null;

const $ = (selector) => document.querySelector(selector);
const tokenKey = "researchops-token";
const apiKeyKey = "researchops-api-key";

const labels = {
  step: {
    planner: "Planner",
    human_approval_requested: "Approval requested",
    tool_agent: "Tool agent",
    rag_research: "RAG research",
    final_response: "Final response",
  },
  state: { completed: "Completed", failed: "Failed", pending: "Pending", approved: "Approved", rejected: "Rejected" },
  task: { queued: "Queued", running: "Running", completed: "Completed", failed: "Failed" },
  kind: {
    ingest_github_repo: "GitHub ingest",
    ingest_text: "Text ingest",
    ingest_url: "URL ingest",
    eval_run: "Eval run",
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

const localize = (group, value) => labels[group][value] || value || "-";

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

const setStatus = (text) => {
  $("#status").textContent = text;
  $("#status").dataset.state = text.toLowerCase();
};

const setBusy = (busy) => {
  $("#ask-button").disabled = busy;
  $("#run-eval").disabled = busy;
  $("#refresh").disabled = busy;
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
      getJson("/api/audit"),
    ]);
    let users = [];
    try {
      users = await getJson("/api/users");
    } catch {
      users = [];
    }

    $("#metric-docs").textContent = summary.document_count;
    $("#metric-chunks").textContent = summary.chunk_count;
    $("#metric-runs").textContent = summary.run_count;
    $("#metric-coverage").textContent = Number(summary.citation_coverage).toFixed(2);
    $("#documents").innerHTML = docs.length
      ? docs.map((doc) => item(doc.title, `${doc.source} | ${doc.chunk_count} chunks | ${doc.status}`)).join("")
      : "No documents";
    $("#approvals-list").innerHTML = approvals.length ? approvals.map(renderApproval).join("") : "No approvals";
    $("#tasks-list").innerHTML = tasks.length ? tasks.map(renderTask).join("") : "No tasks";
    $("#audit-list").innerHTML = audit.length ? audit.map(renderAudit).join("") : "No audit records";
    $("#users-list").innerHTML = users.length ? users.map(renderUser).join("") : "No users";
    $("#eval-list").innerHTML = renderEvalSummary(summary);
    if (lastRunId) await refreshTrace();
    setStatus("Ready");
  } catch (error) {
    setStatus("Error");
    $("#answer").textContent = formatError(error);
  }
}

async function refreshTrace() {
  const trace = await getJson(`/api/runs/${lastRunId}/trace`);
  $("#trace-list").innerHTML = trace.steps.length ? trace.steps.map(renderTraceStep).join("") : "No trace";
}

function renderTraceStep(step) {
  const error = step.error ? `<div class="muted">${escapeHtml(step.error)}</div>` : "";
  return `<div class="step" data-state="${escapeHtml(step.status)}">
    <strong>${escapeHtml(localize("step", step.name))}</strong>
    <div>${escapeHtml(localize("state", step.status))} | ${step.latency_ms ?? 0}ms</div>${error}</div>`;
}

function renderApproval(row) {
  const buttons = row.status === "pending"
    ? `<div class="actions"><button class="small" data-approve="${row.approval_id}">Approve</button>
       <button class="small secondary" data-reject="${row.approval_id}">Reject</button></div>`
    : "";
  return item(`${localize("state", row.status)} | ${row.risk_level}`, row.action, buttons);
}

function renderTask(row) {
  const chunks = row.result?.chunks_indexed != null ? ` | ${row.result.chunks_indexed} chunks` : "";
  const error = row.error ? ` | ${row.error}` : "";
  return item(`${localize("task", row.status)} | ${localize("kind", row.kind)}`, `${row.title}${chunks}${error}`);
}

function renderAudit(row) {
  return item(`${row.risk_level} | ${row.target}`, `${localize("state", row.status)} | ${row.detail || row.action}`);
}

function renderUser(row) {
  return item(
    `${row.user_id} | ${row.role}`,
    `tenant=${row.tenant_id} | sources=${row.allowed_sources.join(", ") || "*"}`,
    `<div class="actions"><button class="small secondary" data-delete-user="${row.user_id}">Delete</button></div>`
  );
}

function renderEvalSummary(summary) {
  const coverage = Math.max(0, Math.min(1, Number(summary.citation_coverage || 0)));
  return `<div class="item metric-item"><strong>Citation coverage</strong><div>${coverage.toFixed(2)}</div>
    <div class="bar"><span style="width:${coverage * 100}%"></span></div></div>`;
}

function renderEvalResult(result) {
  const body = result.passed ? "Passed" : `Missing: ${result.missing_terms.join(", ") || "none"}`;
  return item(result.case_id, body);
}

function formatError(error) {
  try {
    const parsed = JSON.parse(String(error.message || error));
    return parsed.detail ? `Request failed: ${parsed.detail}` : `Request failed: ${JSON.stringify(parsed)}`;
  } catch {
    return `Request failed: ${String(error.message || error)}`;
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
    setStatus("Ready");
    await refresh();
    return;
  }
  const response = await getJson("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey || null, user_id: userId || null, password: password || null }),
  });
  localStorage.setItem(tokenKey, response.access_token);
  setStatus(`Signed in as ${response.user_id}`);
  await refresh();
});

$("#ask-button").addEventListener("click", async () => {
  const question = $("#question").value.trim();
  if (!question) return;
  setBusy(true);
  setStatus("Running");
  try {
    const response = await getJson("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, corpus_ids: [] }),
    });
    lastRunId = response.run_id;
    $("#run-id").textContent = `Run ${response.run_id.slice(0, 8)}`;
    $("#answer").textContent = response.answer;
    $("#citations").innerHTML = response.citations.length
      ? response.citations.map((citation) => item(`${citation.title} | ${citation.locator}`, citation.excerpt)).join("")
      : "No citations";
    await refresh();
  } catch (error) {
    setStatus("Error");
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
    $("#answer").textContent = `Indexed ${response.source} with ${response.chunks_indexed} chunks.`;
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
  $("#answer").textContent = `URL ingest task created: ${response.task_id.slice(0, 8)}.`;
  $("#url-input").value = "";
  await refresh();
});

$("#repo-ingest").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = $("#repo-input").value.trim();
  const ref = $("#repo-ref").value.trim() || "main";
  if (!url) return;
  const response = await createJsonTask("/api/ingest/github/async", { url, ref });
  $("#answer").textContent = `GitHub ingest task created: ${response.task_id.slice(0, 8)}.`;
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
  $("#answer").textContent = `Text ingest task created: ${response.task_id.slice(0, 8)}.`;
  $("#text-title").value = "";
  $("#text-body").value = "";
  await refresh();
});

async function createJsonTask(url, payload) {
  setBusy(true);
  setStatus("Running");
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
  setStatus("Evaluating");
  try {
    const response = await getJson("/api/eval/run", { method: "POST" });
    $("#eval-list").innerHTML =
      `<div class="item"><strong>Pass rate</strong><div>${response.pass_rate.toFixed(2)}</div>
      <div class="bar"><span style="width:${response.pass_rate * 100}%"></span></div></div>` +
      response.results.map(renderEvalResult).join("");
    setStatus("Ready");
  } catch (error) {
    setStatus("Error");
    $("#eval-list").innerHTML = item("Eval failed", formatError(error));
  } finally {
    setBusy(false);
  }
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
  if (approve) await decideApproval(approve, true);
  if (reject) await decideApproval(reject, false);
  if (deleteUser) {
    await getJson(`/api/users/${encodeURIComponent(deleteUser)}`, { method: "DELETE" });
    await refresh();
  }
});

$("#refresh").addEventListener("click", refresh);
$("#api-key").value = localStorage.getItem(apiKeyKey) || localStorage.getItem(tokenKey) || "";
refresh();
