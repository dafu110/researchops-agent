let lastRunId = null;

const $ = (selector) => document.querySelector(selector);

const labels = {
  status: {
    Ready: "就绪",
    Running: "运行中",
    Evaluating: "评测中",
    Error: "出错",
  },
  step: {
    planner: "任务规划",
    human_approval_requested: "请求人工审批",
    tool_agent: "工具调用",
    rag_research: "检索与回答",
    final_response: "生成最终回答",
  },
  state: {
    completed: "已完成",
    failed: "失败",
    pending: "待审批",
    approved: "已批准",
    rejected: "已拒绝",
  },
  risk: {
    high: "高风险",
    medium: "中风险",
    low: "低风险",
  },
  task: {
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
  },
  kind: {
    ingest_github_repo: "GitHub 仓库索引",
    ingest_text: "文本索引",
    ingest_url: "网页抓取",
    eval_run: "评测运行",
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

const getJson = async (url, options) => {
  const apiKey = localStorage.getItem("researchops-api-key") || "";
  const headers = new Headers(options?.headers || {});
  if (apiKey) headers.set("X-API-Key", apiKey);
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

const setStatus = (text) => {
  $("#status").textContent = labels.status[text] || text;
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

    $("#metric-docs").textContent = summary.document_count;
    $("#metric-chunks").textContent = summary.chunk_count;
    $("#metric-runs").textContent = summary.run_count;
    $("#metric-coverage").textContent = Number(summary.citation_coverage).toFixed(2);

    $("#documents").innerHTML = docs.length
      ? docs.map((doc) => item(doc.title, `${doc.source} · ${doc.chunk_count} 个分块 · ${doc.status}`)).join("")
      : "暂无文档";

    $("#approvals-list").innerHTML = approvals.length
      ? approvals.map(renderApproval).join("")
      : "暂无审批项";

    $("#tasks-list").innerHTML = tasks.length
      ? tasks.map(renderTask).join("")
      : "暂无任务";

    $("#audit-list").innerHTML = audit.length
      ? audit.map(renderAudit).join("")
      : "暂无审计记录";

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
  $("#trace-list").innerHTML = trace.steps.length
    ? trace.steps.map(renderTraceStep).join("")
    : "暂无轨迹";
}

function renderTraceStep(step) {
  const status = localize("state", step.status);
  const name = localize("step", step.name);
  const error = step.error ? `<div class="muted">${escapeHtml(step.error)}</div>` : "";
  return `
    <div class="step" data-state="${escapeHtml(step.status)}">
      <strong>${escapeHtml(name)}</strong>
      <div>${escapeHtml(status)} · ${step.latency_ms ?? 0}ms</div>
      ${error}
    </div>`;
}

function renderApproval(row) {
  const buttons = row.status === "pending"
    ? `<div class="actions">
        <button class="small" data-approve="${row.approval_id}">批准</button>
        <button class="small secondary" data-reject="${row.approval_id}">拒绝</button>
      </div>`
    : "";
  const status = localize("state", row.status);
  const risk = localize("risk", row.risk_level);
  return item(`${status} · ${risk}`, row.action, buttons);
}

function renderTask(row) {
  const status = localize("task", row.status);
  const kind = localize("kind", row.kind);
  const result = row.result?.chunks_indexed != null ? ` · ${row.result.chunks_indexed} 个分块` : "";
  const error = row.error ? ` · ${row.error}` : "";
  return item(`${status} · ${kind}`, `${row.title}${result}${error}`);
}

function renderAudit(row) {
  const risk = localize("risk", row.risk_level);
  const status = localize("state", row.status);
  return item(`${risk} · ${row.target}`, `${status} · ${row.detail || row.action}`);
}

function renderEvalSummary(summary) {
  const coverage = Math.max(0, Math.min(1, Number(summary.citation_coverage || 0)));
  return `
    <div class="item">
      <strong>引用覆盖率</strong>
      <div>${coverage.toFixed(2)}</div>
      <div class="bar"><span style="width:${coverage * 100}%"></span></div>
    </div>`;
}

function renderEvalResult(result) {
  const body = result.passed
    ? "通过"
    : `未通过 · 缺失关键词：${result.missing_terms.join("、") || "无"}`;
  return item(result.case_id, body);
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
    $("#run-id").textContent = `运行 ${response.run_id.slice(0, 8)}`;
    $("#answer").textContent = response.answer;
    $("#citations").innerHTML = response.citations.length
      ? response.citations.map((citation) => item(`${citation.title} · ${citation.locator}`, citation.excerpt)).join("")
      : "暂无引用";
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
  setStatus("Running");
  try {
    const body = new FormData();
    body.append("file", file);
    const response = await getJson("/api/ingest", { method: "POST", body });
    $("#answer").textContent = `文件已索引：${response.source}，生成 ${response.chunks_indexed} 个分块。`;
    $("#file-input").value = "";
    await refresh();
  } catch (error) {
    setStatus("Error");
    $("#answer").textContent = formatError(error);
  } finally {
    setBusy(false);
  }
});

$("#url-ingest").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = $("#url-input").value.trim();
  if (!url) return;
  setBusy(true);
  setStatus("Running");
  try {
    const response = await getJson("/api/ingest/url/async", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    $("#answer").textContent = `网页抓取任务已创建：${response.task_id.slice(0, 8)}。`;
    $("#url-input").value = "";
    await refresh();
  } catch (error) {
    setStatus("Error");
    $("#answer").textContent = formatError(error);
  } finally {
    setBusy(false);
  }
});

$("#repo-ingest").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = $("#repo-input").value.trim();
  const ref = $("#repo-ref").value.trim() || "main";
  if (!url) return;
  setBusy(true);
  setStatus("Running");
  try {
    const response = await getJson("/api/ingest/github/async", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, ref }),
    });
    $("#answer").textContent = `GitHub 仓库索引任务已创建：${response.task_id.slice(0, 8)}。`;
    $("#repo-input").value = "";
    $("#repo-ref").value = "";
    await refresh();
  } catch (error) {
    setStatus("Error");
    $("#answer").textContent = formatError(error);
  } finally {
    setBusy(false);
  }
});

$("#text-ingest").addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = $("#text-title").value.trim();
  const text = $("#text-body").value.trim();
  if (!title || !text) return;
  setBusy(true);
  setStatus("Running");
  try {
    const response = await getJson("/api/ingest/text/async", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, text, source: "manual" }),
    });
    $("#answer").textContent = `文本索引任务已创建：${response.task_id.slice(0, 8)}。`;
    $("#text-title").value = "";
    $("#text-body").value = "";
    await refresh();
  } catch (error) {
    setStatus("Error");
    $("#answer").textContent = formatError(error);
  } finally {
    setBusy(false);
  }
});

$("#run-eval").addEventListener("click", async () => {
  setBusy(true);
  setStatus("Evaluating");
  try {
    const response = await getJson("/api/eval/run/async", { method: "POST" });
    $("#eval-list").innerHTML = item("评测任务已创建", `任务 ${response.task_id.slice(0, 8)} 正在后台运行。`);
    await refresh();
    setStatus("Ready");
  } catch (error) {
    setStatus("Error");
    $("#eval-list").innerHTML = item("评测失败", formatError(error));
  } finally {
    setBusy(false);
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
  if (approve) await decideApproval(approve, true);
  if (reject) await decideApproval(reject, false);
});

$("#refresh").addEventListener("click", refresh);
$("#api-key").value = localStorage.getItem("researchops-api-key") || "";
$("#api-key").addEventListener("change", (event) => {
  localStorage.setItem("researchops-api-key", event.target.value);
  refresh();
});
refresh();
