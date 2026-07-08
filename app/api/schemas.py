from pydantic import BaseModel, Field


class IngestTextRequest(BaseModel):
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source: str = "manual"


class IngestUrlRequest(BaseModel):
    url: str = Field(min_length=1)
    title: str | None = None


class IngestGitHubRepoRequest(BaseModel):
    url: str = Field(min_length=1)
    ref: str = "main"


class DocumentSummary(BaseModel):
    document_id: str
    title: str
    source: str
    chunk_count: int
    status: str


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    corpus_ids: list[str] = Field(default_factory=list)
    require_citations: bool = True
    max_cost_usd: float | None = None


class Citation(BaseModel):
    source_id: str
    title: str
    locator: str
    excerpt: str


class AskResponse(BaseModel):
    run_id: str
    answer: str
    citations: list[Citation]
    requires_approval: bool = False
    approval_id: str | None = None
    plan: list[str] = Field(default_factory=list)


class IngestResponse(BaseModel):
    document_id: str
    source: str
    status: str
    chunks_indexed: int = 0


class TaskRecord(BaseModel):
    task_id: str
    kind: str
    status: str
    title: str
    tenant_id: str = "default"
    user_id: str = "local-dev"
    result: dict | None = None
    error: str | None = None


class TaskCreateResponse(BaseModel):
    task_id: str
    status: str


class AuditRecord(BaseModel):
    audit_id: str
    run_id: str | None = None
    actor_id: str = "local-dev"
    tenant_id: str = "default"
    action: str
    target: str
    risk_level: str = "low"
    status: str = "completed"
    detail: str = ""


class TraceStep(BaseModel):
    step_id: str
    name: str
    status: str
    latency_ms: int | None = None
    error: str | None = None


class RunRecord(BaseModel):
    run_id: str
    question: str
    status: str
    tenant_id: str = "default"
    user_id: str = "local-dev"


class RunTraceResponse(BaseModel):
    run_id: str
    steps: list[TraceStep]


class ApprovalRequest(BaseModel):
    run_id: str
    action: str
    reason: str
    risk_level: str = "high"
    tenant_id: str = "default"
    requester_id: str = "local-dev"


class ApprovalDecision(BaseModel):
    approved: bool
    reviewer: str = "local-user"


class ApprovalRecord(BaseModel):
    approval_id: str
    run_id: str
    action: str
    reason: str
    risk_level: str
    status: str
    reviewer: str | None = None
    tenant_id: str = "default"
    requester_id: str = "local-dev"


class EvalSummary(BaseModel):
    document_count: int
    chunk_count: int
    run_count: int
    citation_coverage: float


class EvalCaseResult(BaseModel):
    case_id: str
    question: str
    passed: bool
    citation_correct: bool
    approval_correct: bool = True
    matched_terms: list[str] = Field(default_factory=list)
    missing_terms: list[str] = Field(default_factory=list)


class EvalRunResponse(BaseModel):
    total_cases: int
    passed_cases: int
    pass_rate: float
    citation_correctness: float
    results: list[EvalCaseResult]
