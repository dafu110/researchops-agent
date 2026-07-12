import time
from typing import Literal

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
    mode: Literal["quick", "evidence", "report"] = "evidence"
    require_citations: bool = True
    max_cost_usd: float | None = Field(default=None, ge=0)


class AuthLoginRequest(BaseModel):
    api_key: str | None = None
    user_id: str | None = None
    password: str | None = None


class AuthSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    tenant_id: str
    role: str


class UserProfile(BaseModel):
    user_id: str
    tenant_id: str
    role: str
    allowed_sources: list[str] = Field(default_factory=list)


class UserCreateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    password: str = Field(min_length=6)
    tenant_id: str = "default"
    role: str = "viewer"
    allowed_sources: list[str] = Field(default_factory=list)


class UserRecord(BaseModel):
    user_id: str
    tenant_id: str = "default"
    role: str = "viewer"
    allowed_sources: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    source_id: str
    title: str
    locator: str
    excerpt: str


class TokenUsage(BaseModel):
    """Token accounting for one model-backed step; estimates are explicitly marked."""

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated: bool = False


class FinalAnswer(BaseModel):
    """The typed, persisted output of the research stage."""

    content: str
    citations: list[Citation] = Field(default_factory=list)
    grounded: bool
    model: str
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float | None = Field(default=None, ge=0)


class PlanStepDetail(BaseModel):
    name: str
    stage: str
    goal: str
    mode: str = "automatic"
    tool_hint: str | None = None
    risk_level: str = "low"
    confidence: float = 1.0
    needs_tool: bool = False
    needs_approval: bool = False


class ToolCallInput(BaseModel):
    tool_name: str = Field(min_length=1)
    arguments: dict = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    """A durable, API-visible lifecycle record for a single tool invocation."""

    tool_call_id: str
    run_id: str
    tool: ToolCallInput
    status: str
    risk_level: str
    timeout_ms: int = Field(ge=1)
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=1, ge=1)
    idempotency_key: str
    cancellable: bool = True
    recovery_action: str | None = None
    output: dict | None = None
    error: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))


class AskResponse(BaseModel):
    run_id: str
    answer: str
    citations: list[Citation]
    requires_approval: bool = False
    approval_id: str | None = None
    plan: list[str] = Field(default_factory=list)
    plan_details: list[PlanStepDetail] = Field(default_factory=list)
    final_answer: FinalAnswer | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)


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
    attempts: int = 0
    max_attempts: int = 3
    cancel_requested: bool = False
    payload: dict = Field(default_factory=dict)
    result: dict | None = None
    error: str | None = None
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))


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


class SystemConfigResponse(BaseModel):
    app_env: str
    store_backend: str
    active_store: str
    task_backend: str
    auth_required: bool
    sandbox_mode: str
    embedding_provider: str
    agent_runtime: str
    roles: dict[str, list[str]]
    limits: dict[str, int | str]


class TraceStep(BaseModel):
    step_id: str
    name: str
    status: str
    latency_ms: int | None = None
    error: str | None = None
    input_payload: dict = Field(default_factory=dict)
    output_payload: dict = Field(default_factory=dict)
    model: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float | None = Field(default=None, ge=0)
    created_at: int = Field(default_factory=lambda: int(time.time()))


class RunRecord(BaseModel):
    run_id: str
    question: str
    status: str
    tenant_id: str = "default"
    user_id: str = "local-dev"
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    plan_details: list[PlanStepDetail] = Field(default_factory=list)
    requires_approval: bool = False
    approval_id: str | None = None
    corpus_ids: list[str] = Field(default_factory=list)
    mode: Literal["quick", "evidence", "report"] = "evidence"
    require_citations: bool = True
    max_cost_usd: float | None = Field(default=None, ge=0)
    final_answer: FinalAnswer | None = None
    cancel_requested: bool = False


class RunTraceResponse(BaseModel):
    run_id: str
    steps: list[TraceStep]
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)


class AuditReplayResponse(BaseModel):
    run_id: str
    trace: list[TraceStep]
    audit: list[AuditRecord]


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
    tool_status_correct: bool = True
    lifecycle_correct: bool = True
    matched_terms: list[str] = Field(default_factory=list)
    missing_terms: list[str] = Field(default_factory=list)


class EvalRunResponse(BaseModel):
    total_cases: int
    passed_cases: int
    pass_rate: float
    citation_correctness: float
    results: list[EvalCaseResult]


class AgentMetricsResponse(BaseModel):
    tenant_id: str
    total_runs: int
    terminal_runs: int
    success_rate: float
    p95_latency_ms: int | None = None
    total_tool_calls: int
    tool_failure_rate: float
    approval_rate: float
    average_task_cost_usd: float | None = None
    cost_sample_count: int = 0
