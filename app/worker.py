import asyncio

from celery import Celery

from app.core.config import settings
from app.core.security import UserContext
from app.core.tasks import task_service
from app.evals.service import eval_service
from app.rag.github_repo import extract_github_repo_text
from app.rag.store import knowledge_store

celery_app = Celery("researchops_agent", broker=settings.redis_url, backend=settings.redis_url)


@celery_app.task(name="researchops.ingest_text")
def ingest_text_task(task_id: str, request: dict, user: dict) -> dict:
    context = _user_context(user)
    try:
        if not task_service.start(task_id):
            return {}
        document, chunks = knowledge_store.ingest_text(
            title=str(request["title"]),
            text=str(request["text"]),
            source=str(request.get("source", "manual")),
            tenant_id=context.tenant_id,
        )
        result = _ingest_result(document.document_id, document.source, document.status, len(chunks))
        task_service.complete(task_id, result)
        return result
    except Exception as exc:
        task_service.fail(task_id, str(exc))
        raise


@celery_app.task(name="researchops.ingest_url")
def ingest_url_task(task_id: str, request: dict, user: dict) -> dict:
    from app.api.routes import _run_ingest_url_task
    from app.api.schemas import IngestUrlRequest

    _run_ingest_url_task(task_id, IngestUrlRequest.model_validate(request), _user_context(user))
    task = task_service.get(task_id)
    if task and task.result:
        return task.result
    if task and task.error:
        raise RuntimeError(task.error)
    return {}


@celery_app.task(name="researchops.ingest_github_repo")
def ingest_github_repo_task(task_id: str, request: dict, user: dict) -> dict:
    context = _user_context(user)
    try:
        if not task_service.start(task_id):
            return {}
        repo_name, text = extract_github_repo_text(str(request["url"]), str(request.get("ref", "main")))
        document, chunks = knowledge_store.ingest_text(
            title=f"GitHub Repo: {repo_name}",
            text=text,
            source=str(request["url"]),
            tenant_id=context.tenant_id,
        )
        result = _ingest_result(document.document_id, document.source, document.status, len(chunks))
        task_service.complete(task_id, result)
        return result
    except Exception as exc:
        task_service.fail(task_id, str(exc))
        raise


@celery_app.task(name="researchops.run_eval")
def run_eval_task(task_id: str, user: dict) -> dict:
    try:
        if not task_service.start(task_id):
            return {}
        result = asyncio.run(eval_service.run_golden(_user_context(user)))
        payload = result.model_dump()
        task_service.complete(task_id, payload)
        return payload
    except Exception as exc:
        task_service.fail(task_id, str(exc))
        raise


def _user_context(payload: dict) -> UserContext:
    return UserContext(
        user_id=str(payload.get("user_id", "worker")),
        tenant_id=str(payload.get("tenant_id", settings.default_tenant_id)),
        role=str(payload.get("role", "admin")),
        allowed_sources=list(payload.get("allowed_sources", [])),
    )


def _ingest_result(document_id: str, source: str, status: str, chunks_indexed: int) -> dict:
    return {
        "document_id": document_id,
        "source": source,
        "status": status,
        "chunks_indexed": chunks_indexed,
    }
