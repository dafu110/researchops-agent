let lastRunId = null;
let allDocuments = [];
let allRuns = [];
let selectedDocumentIds = new Set();
let activeAnswer = null;
let currentUser = null;
let agentMetrics = null;
let researchMode = "evidence";

const $ = (selector) => document.querySelector(selector);
const tokenKey = "researchops-token";
const apiKeyKey = "researchops-api-key";
const sidebarKey = "researchops-sidebar-collapsed";
const scopeKey = "researchops-last-scope";
const historyMetaKey = "researchops-history-meta";
const consoleSectionIds = ["operations", "tasks", "trace", "metrics", "approvals", "audit", "eval", "admin", "users"];
const researchModes = {
  evidence: { label: "证据研究" },
  quick: { label: "快速回答" },
  report: { label: "研究摘要" },
};
const progressStages = ["正在规划研究问题", "正在检索已选资料", "正在整理证据与结论"];

const labels = {
  step: { intake: "识别需求", planner: "规划", tool_call: "调用工具", retrieve_evidence: "检索证据", compose_answer: "生成回答", synthesize_report: "生成报告", human_approval: "人工审批", human_approval_requested: "已请求审批", tool_agent: "工具执行", rag_research: "资料研究", final_response: "最终响应" },
  state: { queued: "排队中", running: "运行中", completed: "已完成", failed: "失败", pending: "等待中", approved: "已批准", rejected: "已拒绝", canceled: "已取消" },
  task: { queued: "排队中", running: "运行中", completed: "已完成", failed: "失败", canceled: "已取消" },
  kind: { ingest_github_repo: "GitHub 接入", ingest_text: "文本接入", ingest_url: "URL 接入", eval_run: "评测运行" },
  risk: { low: "低风险", medium: "中风险", high: "高风险", critical: "严重风险" },
  stage: { intake: "输入", execution: "执行", retrieval: "检索", response: "响应", artifact: "产物", approval: "审批" },
};

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[char]);
const localize = (group, value) => labels[group]?.[value] || value || "-";
const emptyText = (text) => `<span class="empty">${escapeHtml(text)}</span>`;
const item = (title, body, extra = "") => `<div class="item"><strong>${escapeHtml(title)}</strong><div>${escapeHtml(body)}</div>${extra}</div>`;

function notify(message, state = "success") {
  const toast = $("#toast");
  toast.textContent = message;
  toast.dataset.state = state;
  toast.hidden = false;
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => { toast.hidden = true; }, 3600);
}

function showModal(kicker, title, body) {
  $("#detail-modal-kicker").textContent = kicker;
  $("#detail-modal-title").textContent = title;
  $("#detail-modal-body").innerHTML = body;
  $("#detail-modal").hidden = false;
}

function closeModal() { $("#detail-modal").hidden = true; }

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

function setStatus(text, state = "ready") {
  const status = $("#status");
  status.textContent = text;
  status.dataset.state = state;
}

function setBusy(busy) {
  ["#ask-button", "#run-eval", "#refresh", "#attach-button", "#mode-button", "#scope-button", "#scope-clear", "#scope-restore", "#scope-select-all", "#scope-search"].forEach((selector) => {
    const control = $(selector);
    if (control) control.disabled = busy;
  });
  document.querySelectorAll("[data-mode], #scope-list input").forEach((control) => { control.disabled = busy; });
  $("#question").disabled = busy;
  if (busy) { $("#mode-panel").hidden = true; $("#scope-panel").hidden = true; $("#mode-button").setAttribute("aria-expanded", "false"); }
  $(".composer")?.classList.toggle("is-busy", busy);
  const note = $("#composer-note");
  note.classList.toggle("is-busy", busy);
  note.textContent = busy ? "正在规划问题、检索资料并生成可追溯结论。" : "ResearchOps 可能出错，请核验关键结论与引用。";
  if (busy) startProgress(); else stopProgress();
}

function startProgress() {
  const panel = $("#run-progress");
  const label = $("#run-progress-text");
  panel.hidden = false;
  let stage = 0;
  label.textContent = progressStages[stage];
  window.clearInterval(startProgress.timer);
  startProgress.timer = window.setInterval(() => {
    stage = Math.min(stage + 1, progressStages.length - 1);
    label.textContent = progressStages[stage];
  }, 1400);
}

function stopProgress() {
  window.clearInterval(startProgress.timer);
  $("#run-progress").hidden = true;
}

function formatError(error) {
  try {
    const parsed = JSON.parse(String(error.message || error));
    return parsed.detail || JSON.stringify(parsed);
  } catch {
    return String(error.message || error);
  }
}

async function safeJson(url, fallback) {
  try { return await getJson(url); } catch { return fallback; }
}

function auditUrl() {
  const params = new URLSearchParams();
  const risk = $("#audit-risk")?.value || "";
  const status = $("#audit-status")?.value || "";
  const target = $("#audit-target")?.value.trim() || "";
  if (risk) params.set("risk_level", risk);
  if (status) params.set("status", status);
  if (target) params.set("target", target);
  return params.size ? `/api/audit?${params}` : "/api/audit";
}

function renderTraceStep(step) {
  const error = step.error ? `<div>${escapeHtml(step.error)}</div>` : "";
  return `<div class="step" data-state="${escapeHtml(step.status)}"><strong>${escapeHtml(localize("step", step.name))}</strong><div>${escapeHtml(localize("state", step.status))} | ${step.latency_ms ?? 0}ms</div>${error}</div>`;
}

function renderTraceDetails(step) {
  const token = step.token_usage || {};
  const meta = [
    step.model && `model=${step.model}`,
    token.input_tokens != null && `in=${token.input_tokens}`,
    token.output_tokens != null && `out=${token.output_tokens}`,
    step.cost_usd != null && `cost=$${Number(step.cost_usd).toFixed(4)}`,
  ].filter(Boolean).join(" | ");
  const payload = JSON.stringify({ input: step.input_payload || {}, output: step.output_payload || {} }, null, 2);
  return `<div class="step" data-state="${escapeHtml(step.status)}"><strong>${escapeHtml(localize("step", step.name))}</strong><div>${escapeHtml(localize("state", step.status))} | ${step.latency_ms ?? 0}ms</div>${meta ? `<div class="trace-meta">${escapeHtml(meta)}</div>` : ""}${step.error ? `<div class="trace-meta">${escapeHtml(step.error)}</div>` : ""}<details class="trace-detail"><summary>查看输入与输出</summary><pre>${escapeHtml(payload)}</pre></details></div>`;
}

function renderToolCall(call) {
  const output = call.output?.text || call.error || "暂无输出";
  const attempts = `${call.attempt}/${call.max_attempts}`;
  return `<div class="tool-call" data-state="${escapeHtml(call.status)}"><div class="tool-call-head"><strong>${escapeHtml(call.tool?.tool_name || "tool")}</strong><small>${escapeHtml(localize("state", call.status))} | ${call.latency_ms ?? 0}ms</small></div><div class="trace-meta">风险 ${escapeHtml(localize("risk", call.risk_level))} | 超时 ${call.timeout_ms}ms | 尝试 ${attempts}</div><details class="trace-detail"><summary>查看参数、输出与幂等键</summary><pre>${escapeHtml(JSON.stringify({ arguments: call.tool?.arguments || {}, output, error: call.error || null, idempotency_key: call.idempotency_key }, null, 2))}</pre></details></div>`;
}

function renderMetrics(metrics) {
  if (!metrics) return emptyText("暂无法读取运行指标");
  const percent = (value) => `${(Number(value || 0) * 100).toFixed(1)}%`;
  const cost = metrics.average_task_cost_usd == null ? "未采集" : `$${Number(metrics.average_task_cost_usd).toFixed(4)}`;
  const rows = [
    [percent(metrics.success_rate), "运行成功率"],
    [metrics.p95_latency_ms == null ? "—" : `${metrics.p95_latency_ms}ms`, "P95 运行时延"],
    [percent(metrics.tool_failure_rate), `工具失败率 · ${metrics.total_tool_calls} 次调用`],
    [percent(metrics.approval_rate), "人工审批率"],
    [cost, `单任务成本 · ${metrics.cost_sample_count} 个样本`],
    [`${metrics.terminal_runs}/${metrics.total_runs}`, "已完成 / 总运行"],
  ];
  return rows.map(([value, label]) => `<div class="metric-item"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("");
}

function renderPlan(steps) {
  $("#plan-list").innerHTML = steps.length ? steps.map((step) => {
    const tool = step.tool_hint ? ` | 工具：${step.tool_hint}` : "";
    const approval = step.needs_approval ? " | 需要审批" : "";
    return `<div class="step" data-state="${escapeHtml(step.risk_level)}"><strong>${escapeHtml(localize("step", step.name))}</strong><div>${escapeHtml(localize("stage", step.stage))} | ${escapeHtml(localize("risk", step.risk_level))}${escapeHtml(tool)}${approval}</div><div>${escapeHtml(step.goal)} | 置信度 ${Math.round(Number(step.confidence || 0) * 100)}%</div></div>`;
  }).join("") : emptyText("暂无执行计划");
  $("#plan-section").hidden = !steps.length;
}

function renderAgentLoop(run, approval = null) {
  const loop = $("#agent-loop");
  if (!run?.run_id) { loop.hidden = true; return; }
  const status = run.status || "created";
  const citations = run.citations || [];
  const plan = run.plan_details || [];
  const isWaiting = status === "awaiting_approval";
  const evidenceText = citations.length ? `${citations.length} 条可追溯引用` : "尚无可用引用";
  const approvalText = approval ? localize("state", approval.status) : "无需审批";
  const next = status === "rejected"
    ? "审批已拒绝，运行已停止"
    : isWaiting
    ? approval?.status === "approved" && currentUser?.role === "admin"
      ? `<button class="text-button loop-action" type="button" data-resume-run="${escapeHtml(run.run_id)}">继续运行</button>`
      : approval?.status === "approved" ? "等待管理员继续运行" : "等待人工决策"
    : status === "completed" ? "闭环已完成" : "等待运行状态更新";
  loop.innerHTML = `
    <div><span>计划</span><strong>${plan.length ? `已生成 ${plan.length} 个步骤` : "计划未保存"}</strong><small>${plan.some((step) => step.needs_approval) ? "包含受控步骤" : "自动执行范围"}</small></div>
    <div><span>证据</span><strong class="${citations.length ? "" : "loop-warning"}">${evidenceText}</strong><small>${citations.length ? "回答可回看来源" : "建议补充资料或重试"}</small></div>
    <div><span>审批</span><strong class="${approval?.status === "rejected" ? "loop-danger" : ""}">${escapeHtml(approvalText)}</strong><small>${approval ? `风险等级：${localize("risk", approval.risk_level)}` : "无授权阻塞"}</small></div>
    <div><span>下一步</span><strong class="${isWaiting ? "loop-action" : ""}">${next}</strong><small>运行：${escapeHtml(localize("state", status))}</small></div>`;
  loop.hidden = false;
}

function renderApproval(row) {
  const reason = row.reason ? `<div class="approval-reason">原因：${escapeHtml(row.reason)}</div>` : "";
  const linkedRun = allRuns.find((run) => run.run_id === row.run_id);
  const resume = row.status === "approved" && linkedRun?.status === "awaiting_approval" ? `<button class="primary" data-resume-run="${escapeHtml(row.run_id)}">继续运行</button>` : "";
  const canApprove = currentUser?.role === "admin";
  const decisionActions = row.status === "pending" && canApprove ? `<button class="primary" data-approve="${escapeHtml(row.approval_id)}">批准</button><button class="secondary" data-reject="${escapeHtml(row.approval_id)}">拒绝</button>` : resume && canApprove ? resume : "";
  const actions = `<div class="actions">${decisionActions}<button class="text-button" data-view-approval="${escapeHtml(row.approval_id)}">查看影响</button></div>`;
  return `<div class="item approval-item" data-risk="${escapeHtml(row.risk_level)}"><strong>${escapeHtml(localize("risk", row.risk_level))} | ${escapeHtml(localize("state", row.status))}</strong><div>${escapeHtml(row.action)}</div>${reason}${actions}</div>`;
}

function renderTask(row) {
  const chunks = row.result?.chunks_indexed != null ? ` | ${row.result.chunks_indexed} 个片段` : "";
  const error = row.error ? ` | ${row.error}` : "";
  const canCancel = ["queued", "running"].includes(row.status);
  const canRetry = ["failed", "canceled"].includes(row.status) && row.attempts < row.max_attempts;
  const canManageTasks = ["admin", "editor"].includes(currentUser?.role);
  const actions = canManageTasks && (canCancel || canRetry) ? `<div class="actions">${canCancel ? `<button class="secondary" data-cancel-task="${escapeHtml(row.task_id)}">取消</button>` : ""}${canRetry ? `<button class="primary" data-retry-task="${escapeHtml(row.task_id)}">重试</button>` : ""}</div>` : "";
  return item(`${localize("task", row.status)} | ${localize("kind", row.kind)}`, `${row.title}${chunks} | 尝试 ${row.attempts}/${row.max_attempts}${error}`, actions);
}

function renderAudit(row) {
  const replay = row.run_id ? `<div class="actions"><button class="secondary" data-replay="${escapeHtml(row.run_id)}">回放</button></div>` : "";
  return item(`${localize("risk", row.risk_level)} | ${row.target}`, `${localize("state", row.status)} | ${row.detail || row.action}`, replay);
}

function renderUser(row) {
  const actions = currentUser?.role === "admin" ? `<div class="actions"><button class="secondary" data-delete-user="${escapeHtml(row.user_id)}">删除</button></div>` : "";
  return item(`${row.user_id} | ${row.role}`, `tenant=${row.tenant_id} | sources=${row.allowed_sources.join(", ") || "*"}`, actions);
}

function renderSystem(system) {
  if (!system) return emptyText("需要管理员权限查看系统配置");
  const rows = [["运行环境", `${system.app_env} | auth=${system.auth_required}`], ["存储", `${system.active_store} | 配置=${system.store_backend}`], ["队列", system.task_backend], ["Agent", `${system.agent_runtime} | embedding=${system.embedding_provider}`], ["沙箱", system.sandbox_mode]];
  return `<div class="system-grid">${rows.map(([title, value]) => item(title, value)).join("")}</div>`;
}

function applyPermissions() {
  const role = currentUser?.role || "viewer";
  const canIngest = ["admin", "editor"].includes(role);
  const canEval = canIngest;
  const isAdmin = role === "admin";
  const canGovern = true;
  $("#ingest").hidden = !canIngest;
  $("#operations").hidden = !canGovern;
  $("#run-eval").hidden = !canEval;
  $("#recover-tasks").hidden = !isAdmin;
  $("#user-create").hidden = !isAdmin;
  $("#admin").hidden = !isAdmin;
  $("#users").hidden = !isAdmin;
  const ingestNav = document.querySelector('.nav a[href="#ingest"]');
  if (ingestNav) ingestNav.hidden = !canIngest;
  $("#governance-nav").hidden = !canGovern;
  const avatar = $(".avatar");
  if (avatar) avatar.textContent = (currentUser?.user_id || "A").slice(0, 1).toUpperCase();
  $("#sidebar-user").textContent = currentUser?.user_id || "本地工作区";
  $("#sidebar-runtime").textContent = `${currentUser?.user_id || "local-dev"} · ${role}`;
}

function renderEvalSummary(summary) {
  const coverage = Math.max(0, Math.min(1, Number(summary.citation_coverage || 0)));
  return `<div class="item"><strong>引用覆盖</strong><div>${coverage.toFixed(2)}</div><progress class="meter" max="1" value="${coverage}">${Math.round(coverage * 100)}%</progress></div>`;
}

function renderAttention(approvals, tasks) {
  const riskOrder = { critical: 0, high: 1, medium: 2, low: 3 };
  const pendingApprovals = approvals
    .filter((row) => row.status === "pending")
    .sort((left, right) => (riskOrder[left.risk_level] ?? 9) - (riskOrder[right.risk_level] ?? 9));
  const failedTasks = tasks.filter((row) => row.status === "failed");
  const runningTasks = tasks.filter((row) => ["queued", "running"].includes(row.status));
  const items = [
    ...pendingApprovals.map((row) => ({
      level: row.risk_level,
      title: `${localize("risk", row.risk_level)}审批等待决策`,
      detail: row.action,
      target: "approvals",
    })),
    ...failedTasks.map((row) => ({
      level: "failed",
      title: "任务执行失败",
      detail: row.title,
      target: "tasks",
    })),
    ...runningTasks.map((row) => ({
      level: "medium",
      title: row.status === "running" ? "任务正在运行" : "任务正在排队",
      detail: row.title,
      target: "tasks",
    })),
  ].slice(0, 3);
  $("#attention-list").innerHTML = items.length
    ? items.map((row) => `<div class="attention-item" data-level="${escapeHtml(row.level)}"><strong>${escapeHtml(row.title)}</strong><div>${escapeHtml(row.detail)}</div><button class="text-button" type="button" data-scroll-to="${escapeHtml(row.target)}">查看详情</button></div>`).join("")
    : emptyText("当前没有需要处理的事项");
  const governanceNav = $("#governance-nav");
  if (governanceNav && ["admin", "editor"].includes(currentUser?.role)) {
    governanceNav.classList.toggle("needs-attention", pendingApprovals.length + failedTasks.length > 0);
  }
}

function renderDocuments() {
  const search = $("#document-search")?.value.trim().toLowerCase() || "";
  const source = $("#document-source")?.value || "";
  const matchingDocs = allDocuments.filter((doc) => {
    const haystack = `${doc.title} ${doc.source} ${doc.status}`.toLowerCase();
    return (!search || haystack.includes(search)) && (!source || doc.source === source);
  });
  const recentDocs = matchingDocs.slice(0, 4);
  const moreDocs = matchingDocs.length > recentDocs.length ? `<button class="text-button more-items" type="button" data-open-ingest="true">查看全部 ${matchingDocs.length} 份资料</button>` : "";
  const canManageDocuments = ["admin", "editor"].includes(currentUser?.role);
  $("#documents-list").innerHTML = matchingDocs.length
    ? recentDocs.map((doc) => `<div class="item document-item"><strong>${escapeHtml(doc.title)}</strong><div>${escapeHtml(`${doc.source} | ${doc.chunk_count} 片段 | ${doc.status}`)}</div><div class="actions"><button class="text-button" data-view-document="${escapeHtml(doc.document_id)}">详情</button>${canManageDocuments ? `<button class="text-button danger-text" data-delete-document="${escapeHtml(doc.document_id)}">删除</button>` : ""}</div></div>`).join("") + moreDocs
    : emptyText(search || source ? "未找到匹配资料" : "暂无资料");
}

function renderScope() {
  const panel = $("#scope-list");
  const search = $("#scope-search")?.value.trim().toLowerCase() || "";
  const matchingDocuments = allDocuments.filter((doc) => `${doc.title} ${doc.source}`.toLowerCase().includes(search));
  const selectedCount = selectedDocumentIds.size;
  $("#scope-label").textContent = selectedCount ? `已限 ${selectedCount} 份` : "限定资料";
  $("#scope-count").textContent = selectedCount ? `已选择 ${selectedCount} / ${allDocuments.length} 份资料` : `默认检索全部 ${allDocuments.length} 份资料`;
  $("#context-scope").textContent = selectedCount ? `已限定 ${selectedCount} / ${allDocuments.length} 份资料` : `默认检索全部 ${allDocuments.length} 份资料`;
  const savedIds = savedScopeIds();
  $("#scope-restore").hidden = !savedIds.length;
  panel.innerHTML = matchingDocuments.length
    ? matchingDocuments.map((doc) => `<label class="scope-item"><input type="checkbox" value="${escapeHtml(doc.document_id)}" ${selectedDocumentIds.has(doc.document_id) ? "checked" : ""} /><span><strong>${escapeHtml(doc.title)}</strong><small>${escapeHtml(doc.source)} · ${doc.chunk_count} 片段</small></span></label>`).join("")
    : emptyText(search ? "未找到匹配资料" : "暂无可选资料");
}

function savedScopeIds() {
  try { return JSON.parse(localStorage.getItem(scopeKey) || "[]"); } catch { return []; }
}

function saveScope() {
  localStorage.setItem(scopeKey, JSON.stringify([...selectedDocumentIds]));
}

function historyMetadata() {
  try { return JSON.parse(localStorage.getItem(historyMetaKey) || "{}"); } catch { return {}; }
}

function saveHistoryMetadata(runId, metadata) {
  const records = historyMetadata();
  records[runId] = metadata;
  localStorage.setItem(historyMetaKey, JSON.stringify(records));
}

function setResearchMode(mode) {
  if (!researchModes[mode]) return;
  researchMode = mode;
  $("#mode-label").textContent = "更多";
  $("#mode-status").textContent = researchModes[mode].label.replace("研究", "");
  document.querySelectorAll("[data-mode]").forEach((option) => option.classList.toggle("active", option.dataset.mode === mode));
  $("#mode-panel").hidden = true;
  $("#mode-button").setAttribute("aria-expanded", "false");
  notify(`已切换为${researchModes[mode].label}。`);
}

function renderHistory() {
  const metadata = historyMetadata();
  const historyItem = (run) => { const meta = metadata[run.run_id]; const scope = meta?.scopeCount ? `${meta.scopeCount} 份资料` : run.corpus_ids?.length ? `${run.corpus_ids.length} 份资料` : "全部资料"; const time = meta?.createdAt ? new Date(meta.createdAt).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" }) : "历史记录"; const mode = meta?.mode ? researchModes[meta.mode]?.label || "研究" : "研究"; return `<button class="history-item ${run.run_id === lastRunId ? "active" : ""}" type="button" data-open-run="${escapeHtml(run.run_id)}"><span>${escapeHtml(run.question)}</span><small>${escapeHtml(`${mode} · ${scope} · ${time} · ${localize("state", run.status)}`)}</small></button>`; };
  const recentRuns = allRuns.slice(0, 6);
  const today = new Date().toDateString();
  const todayRuns = recentRuns.filter((run) => metadata[run.run_id]?.createdAt && new Date(metadata[run.run_id].createdAt).toDateString() === today);
  const earlierRuns = recentRuns.filter((run) => !todayRuns.includes(run));
  $("#history-list").innerHTML = allRuns.length
    ? `${todayRuns.length ? `<span class="history-group">今天</span>${todayRuns.map(historyItem).join("")}` : ""}${earlierRuns.length ? `<span class="history-group">更早</span>${earlierRuns.map(historyItem).join("")}` : ""}`
    : emptyText("暂无研究记录");
  renderSuggestions();
  $("#welcome-eyebrow").textContent = allRuns.length ? "RECENT RESEARCH" : "RESEARCHOPS";
  $("#welcome-title").textContent = allRuns.length ? "从已有研究继续" : "今天想研究什么？";
  $("#welcome-copy").textContent = allRuns.length ? "选择左侧记录回看结论、证据与审批，或基于当前资料库发起新的研究。" : "从已接入的资料中检索证据，生成可追溯的研究结论。";
}

function renderSuggestions() {
  const suggestions = $("#suggestions");
  if (!allRuns.length) {
    suggestions.innerHTML = `
      <button class="suggestion" type="button" data-prompt="请基于资料库说明研究结论如何做到可追溯，并给出引用。"><span>总结已接入资料</span><small>给出结论与证据</small></button>
      <button class="suggestion" type="button" data-prompt="请比较已接入资料中的主要观点，并说明存在分歧的地方。"><span>比较资料观点</span><small>识别共识与分歧</small></button>
      <button class="suggestion" type="button" data-prompt="请基于资料库生成研究摘要，列出下一步需要补充验证的信息。"><span>生成研究摘要</span><small>给出待验证事项</small></button>`;
    return;
  }
  const recentRun = allRuns[0];
  suggestions.innerHTML = `
    <button class="suggestion" type="button" data-open-run="${escapeHtml(recentRun.run_id)}"><span>继续最近研究</span><small>回看结论、证据与下一步</small></button>
    <button class="suggestion" type="button" data-restore-scope="true"><span>复用上次资料范围</span><small>将已选资料带入下一次研究</small></button>
    <button class="suggestion" type="button" data-scroll-to="approvals"><span>查看待处理事项</span><small>处理审批或失败任务</small></button>`;
}

function syncDocumentSources() {
  const select = $("#document-source");
  if (!select) return;
  const activeValue = select.value;
  const sources = [...new Set(allDocuments.map((doc) => doc.source).filter(Boolean))].sort();
  select.innerHTML = `<option value="">全部来源</option>${sources.map((source) => `<option value="${escapeHtml(source)}">${escapeHtml(source)}</option>`).join("")}`;
  select.value = sources.includes(activeValue) ? activeValue : "";
}

async function refreshTrace() {
  if (!lastRunId) return;
  try {
    const trace = await getJson(`/api/runs/${lastRunId}/trace`);
    $("#trace-list").innerHTML = trace.steps.length ? trace.steps.map(renderTraceStep).join("") : emptyText("暂无追踪");
  } catch (error) {
    if (formatError(error).includes("Trace not found")) {
      lastRunId = null;
      activeAnswer = null;
      $("#answer-area").hidden = true;
      $("#welcome").hidden = false;
      $("#agent-loop").hidden = true;
      $("#plan-section").hidden = true;
      $("#trace-list").innerHTML = emptyText("当前运行已删除或不可访问");
      return;
    }
    throw error;
  }
}

async function openRun(runId) {
  const run = allRuns.find((item) => item.run_id === runId);
  const [trace, replay, approvals] = await Promise.all([
    getJson(`/api/runs/${encodeURIComponent(runId)}/trace`),
    getJson(`/api/audit/replay/${encodeURIComponent(runId)}`),
    getJson("/api/approvals"),
  ]);
  lastRunId = runId;
  $("#trace-list").innerHTML = trace.steps.length ? trace.steps.map(renderTraceStep).join("") : emptyText("暂无追踪");
  const linkedApprovals = approvals.filter((item) => item.run_id === runId);
  const currentApproval = linkedApprovals.find((item) => item.approval_id === run?.approval_id) || linkedApprovals.at(-1) || null;
  if (run?.answer) showAnswer(run.question, run.answer, run.citations || [], run.plan_details || [], runId, { ...run, approval: currentApproval });
  const canControlRun = currentUser?.role === "admin";
  const canCancelRun = canControlRun && !["completed", "failed", "canceled", "rejected", "cancel_requested"].includes(run?.status);
  const canRecoverRun = canControlRun && (run?.status === "failed" || (trace.tool_calls || []).some((call) => ["failed", "timeout", "canceled"].includes(call.status)));
  showModal("研究运行", run?.question || `运行 ${runId.slice(0, 8)}`, `
    <div class="detail-summary"><span>状态</span><strong>${escapeHtml(localize("state", run?.status))}</strong><span>运行 ID</span><code>${escapeHtml(runId)}</code></div>
    <section class="detail-section"><h3>执行步骤</h3><div class="timeline">${trace.steps.length ? trace.steps.map(renderTraceDetails).join("") : emptyText("暂无步骤")}</div></section>
    <section class="detail-section"><h3>工具调用</h3><div class="list">${trace.tool_calls?.length ? trace.tool_calls.map(renderToolCall).join("") : emptyText("本次运行未调用工具")}</div></section>
    <section class="detail-section"><h3>工具审计</h3><div class="list">${replay.audit.length ? replay.audit.map(renderAudit).join("") : emptyText("本次运行未记录工具审计")}</div></section>
    <section class="detail-section"><h3>审批记录</h3><div class="list">${linkedApprovals.length ? linkedApprovals.map(renderApproval).join("") : emptyText("本次运行无需审批")}</div></section>
    ${canControlRun ? `<section class="detail-section"><div class="actions">${canCancelRun ? `<button class="secondary" type="button" data-cancel-run="${escapeHtml(runId)}">请求取消</button>` : ""}${canRecoverRun ? `<button class="primary" type="button" data-recover-run="${escapeHtml(runId)}">从失败恢复</button>` : ""}<button class="text-button danger-text" type="button" data-delete-run="${escapeHtml(runId)}">删除研究记录</button></div></section>` : ""}
  `);
  renderHistory();
}

async function refresh() {
  try {
    const results = await Promise.all(["/api/documents", "/api/approvals", "/api/eval/summary", "/api/tasks", auditUrl(), "/api/runs"].map((url) => safeJson(url, null)));
    const [docs, approvals, summary, tasks, audit, runs] = results;
    const [users, system, profile, metrics] = await Promise.all([safeJson("/api/users", []), safeJson("/api/system/config", null), safeJson("/api/auth/me", null), safeJson("/api/metrics", null)]);
    const unavailable = results.filter((result) => result === null).length;
    currentUser = profile;
    applyPermissions();
    const summaryValue = summary || { document_count: allDocuments.length, chunk_count: 0, run_count: allRuns.length, citation_coverage: 0 };
    if (docs) allDocuments = docs;
    if (runs) allRuns = runs;
    syncDocumentSources();
    renderDocuments();
    renderScope();
    renderHistory();
    const approvalRows = approvals || [];
    const taskRows = tasks || [];
    $("#approvals-list").innerHTML = approvalRows.length ? approvalRows.map(renderApproval).join("") : emptyText(approvals === null ? "审批数据暂不可用" : "暂无审批");
    $("#tasks-list").innerHTML = taskRows.length ? taskRows.map(renderTask).join("") : emptyText(tasks === null ? "任务数据暂不可用" : "暂无任务");
    $("#audit-list").innerHTML = audit?.length ? audit.map(renderAudit).join("") : emptyText(audit === null ? "审计数据暂不可用" : "暂无审计");
    $("#users-list").innerHTML = users.length ? users.map(renderUser).join("") : emptyText("暂无用户");
    $("#eval-list").innerHTML = summary ? renderEvalSummary(summary) : emptyText("评测数据暂不可用");
    agentMetrics = metrics;
    $("#metrics-list").innerHTML = renderMetrics(agentMetrics);
    $("#system-list").innerHTML = renderSystem(system);
    renderAttention(approvalRows, taskRows);
    const activeRun = allRuns.find((run) => run.run_id === lastRunId);
    if (activeRun) renderAgentLoop(activeRun, approvalRows.find((row) => row.approval_id === activeRun.approval_id) || approvalRows.filter((row) => row.run_id === activeRun.run_id).at(-1) || null);
    const pendingApprovals = approvalRows.filter((row) => row.status === "pending");
    const urgentApprovals = pendingApprovals.filter((row) => ["high", "critical"].includes(row.risk_level));
    const badge = $("#approval-count");
    badge.hidden = !pendingApprovals.length;
    badge.textContent = pendingApprovals.length;
    badge.classList.toggle("is-urgent", urgentApprovals.length > 0);
    const mobileBadge = $("#mobile-approval-count");
    mobileBadge.hidden = !pendingApprovals.length;
    mobileBadge.textContent = pendingApprovals.length;
    if (system) { $("#sidebar-runtime").textContent = `${system.task_backend} / ${system.agent_runtime}`; $("#sidebar-store").textContent = `存储：${system.active_store}`; }
    await refreshTrace();
    setStatus(unavailable ? "部分数据暂不可用" : "就绪", unavailable ? "error" : "ready");
  } catch (error) {
    setStatus("连接错误", "error");
  }
}

function showAnswer(question, answer, citations, planDetails, runId, loopState = {}) {
  $("#welcome").hidden = true;
  $("#answer-area").hidden = false;
  $("#question-preview").textContent = question;
  $("#answer").textContent = answer;
  const answerContext = $("#answer-context");
  const scope = selectedDocumentIds.size ? `已锁定 ${selectedDocumentIds.size} 份资料` : "全部资料";
  answerContext.textContent = `${researchModes[researchMode].label} · ${scope}`;
  answerContext.hidden = !runId;
  const nextStep = $("#next-step");
  const nextStepCopy = $("#next-step-copy");
  const waitingForApproval = loopState.status === "awaiting_approval";
  nextStepCopy.textContent = waitingForApproval
    ? "这项研究正在等待人工决策。审批后可在运行记录中继续原研究。"
    : citations.length
      ? "核验关键引用后，可继续追问、缩小资料范围，或导出研究记录。"
      : "当前结论缺少可引用证据。建议补充资料后重新运行，或缩小检索范围。";
  nextStep.hidden = !runId;
  $("#run-id").textContent = runId ? `运行 ${runId.slice(0, 8)}` : "当前运行";
  $("#citations").innerHTML = citations.length ? citations.map((citation) => `<div class="citation"><strong>${escapeHtml(citation.title)} | ${escapeHtml(citation.locator)}</strong>${escapeHtml(citation.excerpt)}</div>`).join("") : "";
  activeAnswer = { question, answer, citations, runId };
  $("#answer-provenance").hidden = !runId;
  renderAgentLoop({ run_id: runId, citations, plan_details: planDetails, ...loopState }, loopState.approval || null);
  renderPlan(planDetails || []);
}

async function ask() {
  const question = $("#question").value.trim();
  if (!question) return;
  setBusy(true); setStatus("研究中", "running");
  try {
    const response = await getJson("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, corpus_ids: [...selectedDocumentIds], mode: researchMode, require_citations: researchMode !== "quick" }) });
    lastRunId = response.run_id;
    saveHistoryMetadata(response.run_id, { mode: researchMode, scopeCount: selectedDocumentIds.size, createdAt: new Date().toISOString() });
    showAnswer(question, response.answer, response.citations || [], response.plan_details || [], response.run_id, { status: response.requires_approval ? "awaiting_approval" : "completed", approval: response.requires_approval ? { status: "pending", risk_level: "high" } : null });
    $("#question").value = "";
    notify(response.requires_approval ? "研究已提交，正在等待审批。" : "研究已完成，证据与运行记录已保存。");
    await refresh();
  } catch (error) {
    showAnswer(question, `请求失败：${formatError(error)}`, [], [], null);
    setStatus("错误", "error"); notify(`研究失败：${formatError(error)}`, "error");
  } finally { setBusy(false); }
}

async function createJsonTask(url, payload) {
  setBusy(true); setStatus("任务创建中", "running");
  try { return await getJson(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); }
  finally { setBusy(false); }
}

async function resumeRun(runId) {
  setBusy(true); setStatus("继续运行中", "running");
  try {
    const response = await getJson(`/api/runs/${encodeURIComponent(runId)}/resume`, { method: "POST" });
    lastRunId = response.run_id;
    const question = allRuns.find((run) => run.run_id === runId)?.question || "恢复运行";
    showAnswer(question, response.answer, response.citations || [], response.plan_details || [], response.run_id, { status: response.requires_approval ? "awaiting_approval" : "completed", approval: response.requires_approval ? { status: "pending", risk_level: "high" } : null });
    notify(response.requires_approval ? "运行进入下一项审批。" : "运行已继续并完成，证据已更新。");
    closeModal();
    await refresh();
  } catch (error) {
    notify(`无法继续运行：${formatError(error)}`, "error");
  } finally { setBusy(false); }
}

async function cancelRun(runId) {
  if (!window.confirm("请求在下一个安全工具边界取消此运行？")) return;
  setBusy(true); setStatus("正在请求取消", "running");
  try {
    await getJson(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
    notify("已记录取消请求；运行会在下一个安全边界停止。");
    closeModal();
    await refresh();
  } catch (error) {
    notify(`无法取消运行：${formatError(error)}`, "error");
  } finally { setBusy(false); }
}

async function recoverRun(runId) {
  setBusy(true); setStatus("正在恢复运行", "running");
  try {
    const response = await getJson(`/api/runs/${encodeURIComponent(runId)}/recover`, { method: "POST" });
    lastRunId = response.run_id;
    const question = allRuns.find((run) => run.run_id === runId)?.question || "失败恢复";
    showAnswer(question, response.answer, response.citations || [], response.plan_details || [], response.run_id, { status: response.requires_approval ? "awaiting_approval" : "completed" });
    notify("已在原运行中执行恢复；请查看工具状态与新轨迹。");
    closeModal();
    await refresh();
  } catch (error) {
    notify(`无法恢复运行：${formatError(error)}`, "error");
  } finally { setBusy(false); }
}

function openUtility(id) { const panel = $(id); if (panel) { panel.open = true; panel.scrollIntoView({ behavior: "smooth", block: "start" }); } }
function setActiveIngestTab(name) { document.querySelectorAll("[data-ingest-tab]").forEach((tab) => { const active = tab.dataset.ingestTab === name; tab.classList.toggle("active", active); tab.setAttribute("aria-selected", String(active)); }); document.querySelectorAll("[data-ingest-pane]").forEach((pane) => { const active = pane.dataset.ingestPane === name; pane.classList.toggle("active", active); pane.hidden = !active; }); }
function setSidebarCollapsed(collapsed) { const shell = $("#app-shell"); shell.classList.toggle("is-sidebar-collapsed", collapsed); const toggle = $("#sidebar-toggle"); toggle.setAttribute("aria-expanded", String(!collapsed)); toggle.setAttribute("aria-label", collapsed ? "展开侧边栏" : "收起侧边栏"); toggle.innerHTML = `<svg aria-hidden="true" viewBox="0 0 24 24"><path d="${collapsed ? "M9 18l6-6-6-6" : "M15 18l-6-6 6-6"}" /></svg>`; localStorage.setItem(sidebarKey, String(collapsed)); }

$("#ask-button").addEventListener("click", ask);
$("#question").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); ask(); } });
$("#new-task").addEventListener("click", () => { $("#question").value = ""; $("#question").focus(); });
$("#attach-button").addEventListener("click", () => openUtility("#ingest"));
$("#mode-button").addEventListener("click", () => { const panel = $("#mode-panel"); panel.hidden = !panel.hidden; $("#scope-panel").hidden = true; $("#mode-button").setAttribute("aria-expanded", String(!panel.hidden)); });
$("#scope-button").addEventListener("click", () => { const panel = $("#scope-panel"); panel.hidden = !panel.hidden; $("#mode-panel").hidden = true; $("#mode-button").setAttribute("aria-expanded", "false"); if (!panel.hidden) renderScope(); });
$("#scope-clear").addEventListener("click", () => { selectedDocumentIds.clear(); saveScope(); renderScope(); notify("本次研究将使用全部资料。"); });
$("#scope-restore").addEventListener("click", () => { const available = new Set(allDocuments.map((doc) => doc.document_id)); selectedDocumentIds = new Set(savedScopeIds().filter((id) => available.has(id))); renderScope(); notify(`已复用上次的 ${selectedDocumentIds.size} 份资料范围。`); });
$("#scope-list").addEventListener("change", (event) => { const input = event.target; if (!(input instanceof HTMLInputElement) || input.type !== "checkbox") return; if (input.checked) selectedDocumentIds.add(input.value); else selectedDocumentIds.delete(input.value); saveScope(); renderScope(); });
$("#scope-search").addEventListener("input", renderScope);
$("#scope-select-all").addEventListener("click", () => { const search = $("#scope-search").value.trim().toLowerCase(); allDocuments.filter((doc) => `${doc.title} ${doc.source}`.toLowerCase().includes(search)).forEach((doc) => selectedDocumentIds.add(doc.document_id)); saveScope(); renderScope(); });
document.querySelectorAll("[data-mode]").forEach((option) => option.addEventListener("click", () => setResearchMode(option.dataset.mode)));
document.querySelectorAll("[data-mobile-nav]").forEach((button) => button.addEventListener("click", () => { const target = button.dataset.mobileNav; document.querySelectorAll("[data-mobile-nav]").forEach((item) => item.classList.toggle("active", item === button)); if (target === "ask") document.getElementById("ask")?.scrollIntoView({ behavior: "smooth" }); else openUtility(`#${target}`); }));
$("#view-run-details").addEventListener("click", () => { if (lastRunId) openRun(lastRunId); });
$("#export-answer").addEventListener("click", () => {
  if (!activeAnswer) return;
  const citations = activeAnswer.citations.map((citation) => `- ${citation.title} | ${citation.locator}\n  ${citation.excerpt}`).join("\n");
  const blob = new Blob([`# ${activeAnswer.question}\n\n${activeAnswer.answer}\n\n## 引用\n${citations || "无"}\n\n运行：${activeAnswer.runId || "未追踪"}\n`], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a"); link.href = url; link.download = "researchops-answer.md"; link.click(); URL.revokeObjectURL(url);
  notify("回答已导出为 Markdown 文件。");
});
$("#refresh").addEventListener("click", refresh);
$("#sidebar-toggle")?.addEventListener("click", () => setSidebarCollapsed(!$("#app-shell").classList.contains("is-sidebar-collapsed")));
function closeContext() { $("#context-panel").classList.remove("is-open"); $("#context-scrim").hidden = true; }
$("#context-toggle").addEventListener("click", () => { $("#context-panel").classList.add("is-open"); $("#context-scrim").hidden = false; });
$("#context-close").addEventListener("click", closeContext);
$("#context-scrim").addEventListener("click", closeContext);
$("#document-search").addEventListener("input", renderDocuments);
$("#document-source").addEventListener("change", renderDocuments);

$("#login-form").addEventListener("submit", async (event) => { event.preventDefault(); const apiKey = $("#api-key").value.trim(); const userId = $("#login-user").value.trim(); const password = $("#login-password").value; localStorage.setItem(apiKeyKey, apiKey); if (userId || password) { const response = await getJson("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: apiKey || null, user_id: userId || null, password: password || null }) }); localStorage.setItem(tokenKey, response.access_token); } await refresh(); });
$("#file-ingest").addEventListener("submit", async (event) => { event.preventDefault(); const file = $("#file-input").files[0]; if (!file) return; setBusy(true); try { const body = new FormData(); body.append("file", file); const response = await getJson("/api/ingest", { method: "POST", body }); showAnswer("接入资料", `已索引 ${response.source}，共 ${response.chunks_indexed} 个片段。`, [], [], null); $("#file-input").value = ""; notify(`资料已接入：${response.chunks_indexed} 个片段。`); await refresh(); } catch (error) { showAnswer("接入资料", `请求失败：${formatError(error)}`, [], [], null); notify(`资料接入失败：${formatError(error)}`, "error"); } finally { setBusy(false); } });
$("#url-ingest").addEventListener("submit", async (event) => { event.preventDefault(); const url = $("#url-input").value.trim(); if (!url) return; const response = await createJsonTask("/api/ingest/url/async", { url }); showAnswer("接入 URL", `URL 接入任务已创建：${response.task_id.slice(0, 8)}`, [], [], null); $("#url-input").value = ""; notify("URL 接入任务已创建，可在任务队列中跟踪。"); openUtility("#operations"); await refresh(); });
$("#repo-ingest").addEventListener("submit", async (event) => { event.preventDefault(); const url = $("#repo-input").value.trim(); if (!url) return; const response = await createJsonTask("/api/ingest/github/async", { url, ref: $("#repo-ref").value.trim() || "main" }); showAnswer("接入 GitHub 仓库", `GitHub 接入任务已创建：${response.task_id.slice(0, 8)}`, [], [], null); $("#repo-input").value = ""; $("#repo-ref").value = ""; notify("GitHub 接入任务已创建，可在任务队列中跟踪。"); openUtility("#operations"); await refresh(); });
$("#text-ingest").addEventListener("submit", async (event) => { event.preventDefault(); const title = $("#text-title").value.trim(); const text = $("#text-body").value.trim(); if (!title || !text) return; const response = await createJsonTask("/api/ingest/text/async", { title, text, source: "manual" }); showAnswer("接入研究笔记", `文本接入任务已创建：${response.task_id.slice(0, 8)}`, [], [], null); $("#text-title").value = ""; $("#text-body").value = ""; notify("研究笔记已加入索引队列。"); openUtility("#operations"); await refresh(); });
$("#run-eval").addEventListener("click", async () => { setBusy(true); try { const response = await getJson("/api/eval/run", { method: "POST" }); $("#eval-list").innerHTML = item("通过率", response.pass_rate.toFixed(2)) + response.results.map((result) => item(result.case_id, result.passed ? "通过" : `缺少：${result.missing_terms.join(", ") || "无"}`)).join(""); } catch (error) { $("#eval-list").innerHTML = item("评测失败", formatError(error)); } finally { setBusy(false); } });
$("#recover-tasks").addEventListener("click", async () => { try { const response = await getJson("/api/system/tasks/recover", { method: "POST" }); showAnswer("恢复任务", `已恢复 ${response.recovered} 个卡住任务。`, [], [], null); await refresh(); } catch (error) { showAnswer("恢复任务", `请求失败：${formatError(error)}`, [], [], null); } });
$("#audit-filter").addEventListener("submit", async (event) => { event.preventDefault(); await refresh(); });
$("#user-create").addEventListener("submit", async (event) => { event.preventDefault(); const userId = $("#new-user-id").value.trim(); const password = $("#new-user-password").value; if (!userId || !password) return; await getJson("/api/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: userId, password, role: $("#new-user-role").value }) }); $("#new-user-id").value = ""; $("#new-user-password").value = ""; await refresh(); });

async function handleAction(event) {
  const target = event.target.closest("button, a"); if (!target) return;
  const prompt = target.dataset.prompt;
  if (prompt) { $("#question").value = prompt; $("#question").focus(); return; }
  const approve = target.dataset.approve; const reject = target.dataset.reject; const resumeRunId = target.dataset.resumeRun; const cancelRunId = target.dataset.cancelRun; const recoverRunId = target.dataset.recoverRun; const deleteUser = target.dataset.deleteUser; const cancelTask = target.dataset.cancelTask; const retryTask = target.dataset.retryTask; const replay = target.dataset.replay; const openRunId = target.dataset.openRun; const viewDocument = target.dataset.viewDocument; const deleteDocument = target.dataset.deleteDocument; const viewApproval = target.dataset.viewApproval;
  const scrollTo = target.dataset.scrollTo;
  if (target.dataset.openIngest) { openUtility("#ingest"); return; }
  if (target.dataset.restoreScope) { const available = new Set(allDocuments.map((doc) => doc.document_id)); selectedDocumentIds = new Set(savedScopeIds().filter((id) => available.has(id))); renderScope(); $("#question").focus(); notify(`已复用 ${selectedDocumentIds.size} 份资料范围。`); return; }
  if (scrollTo) { openUtility("#operations"); if (["trace", "metrics", "audit", "eval", "admin", "users"].includes(scrollTo)) $("#advanced-ops").open = true; requestAnimationFrame(() => document.getElementById(scrollTo)?.scrollIntoView({ behavior: "smooth", block: "start" })); return; }
  if (target.dataset.closeModal !== undefined) { closeModal(); return; }
  if (openRunId) { await openRun(openRunId); return; }
  if (resumeRunId) { await resumeRun(resumeRunId); return; }
  if (cancelRunId) { await cancelRun(cancelRunId); return; }
  if (recoverRunId) { await recoverRun(recoverRunId); return; }
  if (target.dataset.deleteRun) { const run = allRuns.find((item) => item.run_id === target.dataset.deleteRun); const label = run?.question || "这项研究"; if (!window.confirm(`删除“${label}”的回答、引用、执行轨迹与关联审批？该操作不可撤销。`)) return; await getJson(`/api/runs/${encodeURIComponent(target.dataset.deleteRun)}`, { method: "DELETE" }); if (lastRunId === target.dataset.deleteRun) { lastRunId = null; activeAnswer = null; $("#answer-area").hidden = true; $("#welcome").hidden = false; $("#agent-loop").hidden = true; $("#plan-section").hidden = true; } closeModal(); notify("研究记录已删除；系统保留了一条不含研究内容的删除审计。 "); await refresh(); return; }
  if (viewDocument) { const document = allDocuments.find((item) => item.document_id === viewDocument); const canManageDocuments = ["admin", "editor"].includes(currentUser?.role); if (document) showModal("资料详情", document.title, `<div class="detail-summary"><span>来源</span><strong>${escapeHtml(document.source)}</strong><span>索引状态</span><strong>${escapeHtml(document.status)}</strong><span>片段</span><strong>${document.chunk_count}</strong></div><p class="detail-copy">这份资料会在本次研究范围选择时作为独立检索源出现。</p><div class="actions"><button class="secondary" type="button" data-select-document="${escapeHtml(document.document_id)}">仅使用这份资料研究</button>${canManageDocuments ? `<button class="text-button danger-text" type="button" data-delete-document="${escapeHtml(document.document_id)}">删除资料</button>` : ""}</div>`); return; }
  if (viewApproval) { const approval = (await getJson("/api/approvals")).find((item) => item.approval_id === viewApproval); const run = approval && allRuns.find((item) => item.run_id === approval.run_id); const canApprove = currentUser?.role === "admin"; if (approval) showModal("审批详情", `${localize("risk", approval.risk_level)}风险操作`, `<div class="detail-summary"><span>操作</span><strong>${escapeHtml(approval.action)}</strong><span>原因</span><strong>${escapeHtml(approval.reason)}</strong><span>请求者</span><strong>${escapeHtml(approval.requester_id)}</strong><span>状态</span><strong>${escapeHtml(localize("state", approval.status))}</strong></div><p class="detail-copy">审批只记录授权决定。批准后，需要明确继续原运行；拒绝会阻止当前受控步骤，不会删除现有资料。</p>${canApprove && approval.status === "pending" ? `<div class="actions"><button class="primary" data-approve="${escapeHtml(approval.approval_id)}">批准</button><button class="secondary" data-reject="${escapeHtml(approval.approval_id)}">拒绝操作</button></div>` : canApprove && approval.status === "approved" && run?.status === "awaiting_approval" ? `<div class="actions"><button class="primary" data-resume-run="${escapeHtml(run.run_id)}">继续运行</button></div>` : ""}`); return; }
  if (target.dataset.selectDocument) { selectedDocumentIds = new Set([target.dataset.selectDocument]); saveScope(); renderScope(); closeModal(); $("#question").focus(); notify("已将研究范围限制为选定资料。"); return; }
  if (deleteDocument) { const document = allDocuments.find((item) => item.document_id === deleteDocument); if (!document) return; if (!window.confirm(`删除“${document.title}”及其 ${document.chunk_count} 个索引片段？此操作不可撤销。`)) return; await getJson(`/api/documents/${encodeURIComponent(deleteDocument)}`, { method: "DELETE" }); selectedDocumentIds.delete(deleteDocument); closeModal(); notify("资料及其索引片段已删除。"); await refresh(); return; }
  if (approve || reject) await getJson(`/api/approvals/${encodeURIComponent(approve || reject)}/decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved: Boolean(approve), reviewer: "dashboard" }) });
  if (deleteUser) await getJson(`/api/users/${encodeURIComponent(deleteUser)}`, { method: "DELETE" });
  if (cancelTask) await getJson(`/api/tasks/${encodeURIComponent(cancelTask)}/cancel`, { method: "POST" });
  if (retryTask) await getJson(`/api/tasks/${encodeURIComponent(retryTask)}/retry`, { method: "POST" });
  if (replay) { const response = await getJson(`/api/audit/replay/${encodeURIComponent(replay)}`); showAnswer("审计回放", JSON.stringify(response, null, 2), [], [], replay); }
  if (approve || reject) { notify(approve ? "审批已批准。可在该审批或运行详情中继续运行。" : "审批已拒绝，风险操作不会执行。"); closeModal(); }
  if (cancelTask) notify("已请求取消任务。");
  if (retryTask) notify("任务已进入重试队列。");
  if (approve || reject || deleteUser || cancelTask || retryTask) await refresh();
}

document.addEventListener("click", (event) => {
  handleAction(event).catch((error) => {
    notify(`操作失败：${formatError(error)}`, "error");
    setStatus("操作失败", "error");
  });
});

window.addEventListener("unhandledrejection", (event) => {
  event.preventDefault();
  notify(`操作失败：${formatError(event.reason)}`, "error");
  setStatus("操作失败", "error");
});

document.querySelectorAll("[data-ingest-tab]").forEach((tab) => tab.addEventListener("click", () => setActiveIngestTab(tab.dataset.ingestTab)));
document.querySelectorAll(".nav a").forEach((link) => link.addEventListener("click", () => { document.querySelectorAll(".nav a").forEach((nav) => nav.classList.toggle("active", nav === link)); if (link.hash === "#ingest") openUtility("#ingest"); if (consoleSectionIds.includes(link.hash.slice(1))) openUtility("#operations"); }));

$("#api-key").value = localStorage.getItem(apiKeyKey) || "";
setSidebarCollapsed(localStorage.getItem(sidebarKey) === "true");
setActiveIngestTab("file");
refresh();
