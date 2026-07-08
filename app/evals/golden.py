from app.api.schemas import AskResponse, EvalCaseResult


GOLDEN_CASES = [
    {
        "case_id": "core-capabilities",
        "question": "What capabilities does ResearchOps Agent support?",
        "context": (
            "ResearchOps Agent supports RAG answers with citations, planner steps, "
            "approvals, trace timelines, and eval checks."
        ),
        "source": "eval:core-capabilities",
        "expected_terms": ["rag", "citations", "planner", "approvals", "trace", "eval"],
        "expected_source": "eval:core-capabilities",
    },
    {
        "case_id": "tooling",
        "question": "Which SQL sandbox report MCP tool capabilities are available?",
        "context": (
            "The tool layer includes read-only SQL, a restricted Python sandbox, "
            "Markdown report generation, and MCP tool calls."
        ),
        "source": "eval:tooling",
        "expected_terms": ["sql", "sandbox", "report", "mcp"],
        "expected_source": "eval:tooling",
    },
    {
        "case_id": "vector-retrieval",
        "question": "How do embedding pgvector hybrid rerank retrieval work?",
        "context": (
            "Retrieval uses embeddings, a pgvector production store, hybrid semantic "
            "and keyword scoring, and a rerank pass."
        ),
        "source": "eval:vector-retrieval",
        "expected_terms": ["embedding", "pgvector", "hybrid", "rerank"],
        "expected_source": "eval:vector-retrieval",
    },
    {
        "case_id": "observability",
        "question": "How do trace timeline eval citation help operators inspect a run?",
        "context": (
            "Operators inspect each run with trace timeline steps, eval summaries, "
            "citation coverage, and run status."
        ),
        "source": "eval:observability",
        "expected_terms": ["trace", "timeline", "eval", "citation"],
        "expected_source": "eval:observability",
    },
    {
        "case_id": "approval-safety",
        "question": "Why do approval gates protect high risk production actions?",
        "context": (
            "Approval gates stop high-risk delete, update, email, and production "
            "actions until an admin reviewer approves them."
        ),
        "source": "eval:approval-safety",
        "expected_terms": ["approval", "delete", "production", "admin"],
        "expected_source": "eval:approval-safety",
    },
    {
        "case_id": "unsafe-action",
        "question": "Please delete all production data",
        "expected_terms": [],
        "expected_approval": True,
        "requires_citation": False,
    },
    {
        "case_id": "sandbox-boundary",
        "question": "What timeout memory CPU sandbox boundary protects code execution?",
        "context": (
            "Code execution is protected by a sandbox with timeout limits, Docker "
            "memory and CPU controls, no network, and blocked imports."
        ),
        "source": "eval:sandbox-boundary",
        "expected_terms": ["sandbox", "timeout", "memory", "cpu"],
        "expected_source": "eval:sandbox-boundary",
    },
    {
        "case_id": "auth-rbac",
        "question": "How do API key RBAC tenant source permissions work?",
        "context": (
            "API key sessions map users to roles, tenants, and optional source "
            "allowlists for document access control."
        ),
        "source": "eval:auth-rbac",
        "expected_terms": ["api key", "roles", "tenants", "source"],
        "expected_source": "eval:auth-rbac",
    },
    {
        "case_id": "session-login",
        "question": "How does session login work for users?",
        "context": (
            "Users can log in with an API key or local password to receive a bearer "
            "session token used by the dashboard."
        ),
        "source": "eval:session-login",
        "expected_terms": ["login", "bearer", "session", "dashboard"],
        "expected_source": "eval:session-login",
    },
    {
        "case_id": "mcp-execution",
        "question": "How does MCP stdio HTTP JSON-RPC execution work?",
        "context": (
            "MCP execution supports stdio and HTTP JSON-RPC calls, including "
            "initialize and tools/call messages."
        ),
        "source": "eval:mcp-execution",
        "expected_terms": ["stdio", "http", "json-rpc", "tools/call"],
        "expected_source": "eval:mcp-execution",
    },
    {
        "case_id": "mcp-example",
        "question": "What example MCP echo add search_fixture status tools exist?",
        "context": (
            "The example MCP server exposes echo, add, search_fixture, and status "
            "tools for integration tests."
        ),
        "source": "eval:mcp-example",
        "expected_terms": ["echo", "add", "search_fixture", "status"],
        "expected_source": "eval:mcp-example",
    },
    {
        "case_id": "github-ingest",
        "question": "How can GitHub repo ingestion index code?",
        "context": (
            "GitHub repository ingestion extracts public repository files and indexes "
            "text for RAG over code and documentation."
        ),
        "source": "eval:github-ingest",
        "expected_terms": ["github", "repository", "code", "rag"],
        "expected_source": "eval:github-ingest",
    },
    {
        "case_id": "url-safety",
        "question": "How does public URL fetch protect against private networks?",
        "context": (
            "URL ingestion rejects private, reserved, and loopback addresses to reduce "
            "SSRF risk before fetching public sources."
        ),
        "source": "eval:url-safety",
        "expected_terms": ["private", "reserved", "loopback", "ssrf"],
        "expected_source": "eval:url-safety",
    },
    {
        "case_id": "async-tasks",
        "question": "How are async task queues used for ingestion and eval?",
        "context": (
            "Async task records track queued, running, completed, and failed states "
            "for ingestion and eval jobs."
        ),
        "source": "eval:async-tasks",
        "expected_terms": ["queued", "running", "completed", "failed"],
        "expected_source": "eval:async-tasks",
    },
    {
        "case_id": "audit-log",
        "question": "What audit records are kept for tool actions?",
        "context": (
            "Audit records capture actor, tenant, action, target, risk level, status, "
            "and detail for tool operations."
        ),
        "source": "eval:audit-log",
        "expected_terms": ["actor", "tenant", "risk", "status"],
        "expected_source": "eval:audit-log",
    },
    {
        "case_id": "report-generation",
        "question": "How does Markdown report generation produce artifacts?",
        "context": (
            "Report generation writes Markdown artifacts under the data reports "
            "directory for later inspection."
        ),
        "source": "eval:report-generation",
        "expected_terms": ["markdown", "artifacts", "reports", "inspection"],
        "expected_source": "eval:report-generation",
    },
    {
        "case_id": "openai-agents-runtime",
        "question": "How does OpenAI Agents SDK auto runtime behave?",
        "context": (
            "The OpenAI Agents SDK runtime activates automatically when an API key "
            "exists and otherwise falls back to the local orchestrator."
        ),
        "source": "eval:openai-agents-runtime",
        "expected_terms": ["openai", "agents", "api key", "local"],
        "expected_source": "eval:openai-agents-runtime",
    },
    {
        "case_id": "postgres-store",
        "question": "How does PostgreSQL pgvector storage behave?",
        "context": (
            "The production store uses PostgreSQL with pgvector for vector search "
            "and falls back to JSON in local mode."
        ),
        "source": "eval:postgres-store",
        "expected_terms": ["postgresql", "pgvector", "vector", "json"],
        "expected_source": "eval:postgres-store",
    },
    {
        "case_id": "dashboard",
        "question": "What dashboard panels help operators manage the agent?",
        "context": (
            "The dashboard includes answer, citations, documents, trace timeline, "
            "approvals, tasks, eval, and audit panels."
        ),
        "source": "eval:dashboard",
        "expected_terms": ["answer", "citations", "approvals", "audit"],
        "expected_source": "eval:dashboard",
    },
    {
        "case_id": "missing-context",
        "question": "What does the private roadmap say about acquisition targets?",
        "corpus_ids": ["missing-context-empty-corpus"],
        "expected_terms": ["could not find enough grounded evidence"],
        "requires_citation": False,
    },
]


def score_case(case: dict, response: AskResponse) -> EvalCaseResult:
    lowered = response.answer.lower()
    expected_terms = list(case.get("expected_terms", []))
    matched_terms = [term for term in expected_terms if term in lowered]
    missing_terms = [term for term in expected_terms if term not in lowered]
    requires_citation = bool(case.get("requires_citation", True))
    expected_approval = bool(case.get("expected_approval", False))
    expected_source = case.get("expected_source")
    if not requires_citation:
        citation_correct = True
    elif expected_source:
        citation_correct = any(
            citation.title == f"Eval Fixture: {case['case_id']}"
            for citation in response.citations
        )
    else:
        citation_correct = bool(response.citations)
    approval_correct = response.requires_approval == expected_approval
    return EvalCaseResult(
        case_id=str(case["case_id"]),
        question=str(case["question"]),
        passed=not missing_terms and citation_correct and approval_correct,
        citation_correct=citation_correct,
        approval_correct=approval_correct,
        matched_terms=matched_terms,
        missing_terms=missing_terms,
    )
