from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from app.api.schemas import (
    ApprovalDecision,
    ApprovalRecord,
    AskRequest,
    AskResponse,
    AuditRecord,
    AuthLoginRequest,
    AuthSessionResponse,
    DocumentSummary,
    EvalSummary,
    EvalRunResponse,
    IngestGitHubRepoRequest,
    IngestResponse,
    IngestTextRequest,
    IngestUrlRequest,
    RunTraceResponse,
    TaskCreateResponse,
    TaskRecord,
    UserCreateRequest,
    UserProfile,
    UserRecord,
)
from app.agents.orchestrator import AgentOrchestrator
from app.approvals.service import approval_service
from app.core.config import settings
from app.core.audit import audit_service
from app.core.network import URLFetchError, fetch_public_url
from app.core.security import (
    UserContext,
    authenticate_api_key,
    authenticate_password,
    current_user,
    require_approval,
    require_ingest,
    session_service,
)
from app.core.tasks import task_service
from app.core.traces import trace_store
from app.core.users import user_service
from app.evals.service import eval_service
from app.rag.extractors import extract_text_from_bytes
from app.rag.github_repo import extract_github_repo_text
from app.rag.store import knowledge_store

router = APIRouter()
orchestrator = AgentOrchestrator()


@router.post("/auth/login", response_model=AuthSessionResponse)
async def login(request: AuthLoginRequest) -> AuthSessionResponse:
    user = authenticate_api_key(request.api_key) or authenticate_password(
        request.user_id,
        request.password,
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    token = session_service.create(user)
    return AuthSessionResponse(
        access_token=token,
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        role=user.role,
    )


@router.get("/auth/me", response_model=UserProfile)
async def me(user: UserContext = Depends(current_user)) -> UserProfile:
    return UserProfile(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        role=user.role,
        allowed_sources=user.allowed_sources,
    )


@router.get("/users", response_model=list[UserRecord])
async def list_users(user: UserContext = Depends(current_user)) -> list[UserRecord]:
    require_approval(user)
    return user_service.list_records(user.tenant_id)


@router.post("/users", response_model=UserRecord)
async def create_user(
    request: UserCreateRequest,
    user: UserContext = Depends(current_user),
) -> UserRecord:
    require_approval(user)
    request.tenant_id = user.tenant_id
    try:
        return user_service.create(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/users/{user_id}", response_model=dict)
async def delete_user(user_id: str, user: UserContext = Depends(current_user)) -> dict:
    require_approval(user)
    deleted = user_service.delete(user_id, user.tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"deleted": True}


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest, user: UserContext = Depends(current_user)) -> AskResponse:
    return await orchestrator.answer(request, user)


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    file: UploadFile | None = File(default=None),
    source_url: str | None = Form(default=None),
    user: UserContext = Depends(current_user),
) -> IngestResponse:
    require_ingest(user)
    if file is not None:
        content = await file.read()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="File is larger than max_upload_bytes.")
        text = extract_text_from_bytes(file.filename or "upload.txt", content)
        document, chunks = knowledge_store.ingest_text(
            title=file.filename or "uploaded file",
            text=text,
            source="upload",
            tenant_id=user.tenant_id,
        )
        return IngestResponse(
            document_id=document.document_id,
            source=document.source,
            status=document.status,
            chunks_indexed=len(chunks),
        )

    if source_url is not None:
        return await ingest_url(IngestUrlRequest(url=source_url), user)

    raise HTTPException(status_code=400, detail="Provide either file or source_url.")


@router.post("/ingest/text", response_model=IngestResponse)
async def ingest_text(
    request: IngestTextRequest,
    user: UserContext = Depends(current_user),
) -> IngestResponse:
    require_ingest(user)
    document, chunks = knowledge_store.ingest_text(
        title=request.title,
        text=request.text,
        source=request.source,
        tenant_id=user.tenant_id,
    )
    return IngestResponse(
        document_id=document.document_id,
        source=document.source,
        status=document.status,
        chunks_indexed=len(chunks),
    )


@router.post("/ingest/text/async", response_model=TaskCreateResponse)
async def ingest_text_async(
    request: IngestTextRequest,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(current_user),
) -> TaskCreateResponse:
    require_ingest(user)
    task = task_service.create("ingest_text", request.title, user.tenant_id, user.user_id)
    _enqueue_task(
        background_tasks,
        "researchops.ingest_text",
        [task.task_id, request.model_dump(), user_context_payload(user)],
        lambda: _run_ingest_text_task(task.task_id, request, user),
    )
    return TaskCreateResponse(task_id=task.task_id, status=task.status)


@router.post("/ingest/url", response_model=IngestResponse)
async def ingest_url(
    request: IngestUrlRequest,
    user: UserContext = Depends(current_user),
) -> IngestResponse:
    require_ingest(user)
    try:
        content = fetch_public_url(request.url)
    except URLFetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="URL content is larger than max_upload_bytes.")

    text = extract_text_from_bytes(request.url, content)
    document, chunks = knowledge_store.ingest_text(
        title=request.title or request.url,
        text=text,
        source=request.url,
        tenant_id=user.tenant_id,
    )
    return IngestResponse(
        document_id=document.document_id,
        source=document.source,
        status=document.status,
        chunks_indexed=len(chunks),
    )


@router.post("/ingest/url/async", response_model=TaskCreateResponse)
async def ingest_url_async(
    request: IngestUrlRequest,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(current_user),
) -> TaskCreateResponse:
    require_ingest(user)
    task = task_service.create("ingest_url", request.title or request.url, user.tenant_id, user.user_id)
    _enqueue_task(
        background_tasks,
        "researchops.ingest_url",
        [task.task_id, request.model_dump(), user_context_payload(user)],
        lambda: _run_ingest_url_task(task.task_id, request, user),
    )
    return TaskCreateResponse(task_id=task.task_id, status=task.status)


@router.post("/ingest/github/async", response_model=TaskCreateResponse)
async def ingest_github_repo_async(
    request: IngestGitHubRepoRequest,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(current_user),
) -> TaskCreateResponse:
    require_ingest(user)
    task = task_service.create("ingest_github_repo", request.url, user.tenant_id, user.user_id)
    _enqueue_task(
        background_tasks,
        "researchops.ingest_github_repo",
        [task.task_id, request.model_dump(), user_context_payload(user)],
        lambda: _run_ingest_github_repo_task(task.task_id, request, user),
    )
    return TaskCreateResponse(task_id=task.task_id, status=task.status)


@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents(user: UserContext = Depends(current_user)) -> list[DocumentSummary]:
    return [
        DocumentSummary(
            document_id=document.document_id,
            title=document.title,
            source=document.source,
            chunk_count=chunk_count,
            status=document.status,
        )
        for document, chunk_count in knowledge_store.list_documents(user.tenant_id)
        if not user.allowed_sources or document.source in user.allowed_sources
    ]


@router.get("/runs/{run_id}/trace", response_model=RunTraceResponse)
async def get_trace(
    run_id: str,
    user: UserContext = Depends(current_user),
) -> RunTraceResponse:
    run = trace_store.get_run(run_id)
    if run and run.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return RunTraceResponse(run_id=run_id, steps=trace_store.get_steps(run_id))


@router.get("/approvals", response_model=list[ApprovalRecord])
async def list_approvals(user: UserContext = Depends(current_user)) -> list[ApprovalRecord]:
    return approval_service.list_records(user.tenant_id)


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalRecord)
async def decide_approval(
    approval_id: str,
    decision: ApprovalDecision,
    user: UserContext = Depends(current_user),
) -> ApprovalRecord:
    require_approval(user)
    record = approval_service.decide(approval_id, decision, tenant_id=user.tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Approval not found.")
    return record


@router.get("/eval/summary", response_model=EvalSummary)
async def eval_summary(user: UserContext = Depends(current_user)) -> EvalSummary:
    documents = knowledge_store.list_documents(user.tenant_id)
    chunk_count = knowledge_store.count_chunks(tenant_id=user.tenant_id)
    run_count = trace_store.run_count(user.tenant_id)
    citation_coverage = 1.0 if chunk_count and run_count else 0.0
    return EvalSummary(
        document_count=len(documents),
        chunk_count=chunk_count,
        run_count=run_count,
        citation_coverage=citation_coverage,
    )


@router.post("/eval/run", response_model=EvalRunResponse)
async def run_eval(user: UserContext = Depends(current_user)) -> EvalRunResponse:
    return await eval_service.run_golden(user)


@router.post("/eval/run/async", response_model=TaskCreateResponse)
async def run_eval_async(
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(current_user),
) -> TaskCreateResponse:
    task = task_service.create("eval_run", "评测门禁", user.tenant_id, user.user_id)
    _enqueue_task(
        background_tasks,
        "researchops.run_eval",
        [task.task_id, user_context_payload(user)],
        lambda: _run_eval_task(task.task_id, user),
    )
    return TaskCreateResponse(task_id=task.task_id, status=task.status)


@router.get("/tasks", response_model=list[TaskRecord])
async def list_tasks(user: UserContext = Depends(current_user)) -> list[TaskRecord]:
    return task_service.list_records(user.tenant_id)


@router.get("/tasks/{task_id}", response_model=TaskRecord)
async def get_task(task_id: str, user: UserContext = Depends(current_user)) -> TaskRecord:
    task = task_service.get(task_id, user.tenant_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@router.get("/audit", response_model=list[AuditRecord])
async def list_audit(user: UserContext = Depends(current_user)) -> list[AuditRecord]:
    return audit_service.list_records(user.tenant_id)


def _run_ingest_text_task(task_id: str, request: IngestTextRequest, user: UserContext) -> None:
    try:
        task_service.start(task_id)
        document, chunks = knowledge_store.ingest_text(
            title=request.title,
            text=request.text,
            source=request.source,
            tenant_id=user.tenant_id,
        )
        task_service.complete(
            task_id,
            {
                "document_id": document.document_id,
                "source": document.source,
                "status": document.status,
                "chunks_indexed": len(chunks),
            },
        )
    except Exception as exc:
        task_service.fail(task_id, str(exc))


def _run_ingest_url_task(task_id: str, request: IngestUrlRequest, user: UserContext) -> None:
    try:
        task_service.start(task_id)
        content = fetch_public_url(request.url)
        if len(content) > settings.max_upload_bytes:
            raise ValueError("URL content is larger than max_upload_bytes.")
        text = extract_text_from_bytes(request.url, content)
        document, chunks = knowledge_store.ingest_text(
            title=request.title or request.url,
            text=text,
            source=request.url,
            tenant_id=user.tenant_id,
        )
        task_service.complete(
            task_id,
            {
                "document_id": document.document_id,
                "source": document.source,
                "status": document.status,
                "chunks_indexed": len(chunks),
            },
        )
    except Exception as exc:
        task_service.fail(task_id, str(exc))


def _run_ingest_github_repo_task(
    task_id: str,
    request: IngestGitHubRepoRequest,
    user: UserContext,
) -> None:
    try:
        task_service.start(task_id)
        repo_name, text = extract_github_repo_text(request.url, request.ref)
        document, chunks = knowledge_store.ingest_text(
            title=f"GitHub Repo: {repo_name}",
            text=text,
            source=request.url,
            tenant_id=user.tenant_id,
        )
        task_service.complete(
            task_id,
            {
                "document_id": document.document_id,
                "source": document.source,
                "status": document.status,
                "chunks_indexed": len(chunks),
            },
        )
    except Exception as exc:
        task_service.fail(task_id, str(exc))


def _run_eval_task(task_id: str, user: UserContext) -> None:
    import asyncio

    try:
        task_service.start(task_id)
        result = asyncio.run(eval_service.run_golden(user))
        task_service.complete(task_id, result.model_dump())
    except Exception as exc:
        task_service.fail(task_id, str(exc))


def _enqueue_task(
    background_tasks: BackgroundTasks,
    celery_name: str,
    celery_args: list,
    local_callback,
) -> None:
    if settings.task_backend == "celery":
        from app.worker import celery_app

        celery_app.send_task(celery_name, args=celery_args)
        return
    background_tasks.add_task(local_callback)


def user_context_payload(user: UserContext) -> dict:
    return {
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "allowed_sources": user.allowed_sources,
    }
