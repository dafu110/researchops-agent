from fastapi.testclient import TestClient

from app.main import app
from app.core.tasks import task_service
from app.rag.github_repo import parse_github_repo_url


client = TestClient(app)


def test_dashboard_smoke() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "研究任务工作台" in response.text
    assert "资料接入" in response.text
    assert "审计日志" in response.text


def test_health_response_has_security_and_request_headers() -> None:
    response = client.get("/health", headers={"X-Request-ID": "test-request-id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-id"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_async_text_ingest_and_task_queue() -> None:
    response = client.post(
        "/api/ingest/text/async",
        json={
            "title": "API Smoke Fixture",
            "text": "API smoke test document with citations tasks and queue visibility.",
            "source": "api-smoke",
        },
    )

    assert response.status_code == 200
    task_id = response.json()["task_id"]
    task_response = client.get(f"/api/tasks/{task_id}")
    assert task_response.status_code == 200
    assert task_response.json()["status"] in {"queued", "running", "completed"}
    assert task_response.json()["payload"]["request"]["title"] == "API Smoke Fixture"


def test_task_cancel_and_retry_controls() -> None:
    create_response = client.post(
        "/api/ingest/text/async",
        json={
            "title": "Task Control Fixture",
            "text": "Task control document.",
            "source": "task-control",
        },
    )
    task_id = create_response.json()["task_id"]

    cancel_response = client.post(f"/api/tasks/{task_id}/cancel")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] in {"completed", "canceled", "failed"}

    failed_task = task_service.create(
        "ingest_text",
        "Retry Fixture",
        payload={
            "request": {
                "title": "Retry Fixture",
                "text": "Retryable task fixture.",
                "source": "retry-test",
            },
            "user": {"user_id": "local-dev", "tenant_id": "default", "role": "admin"},
        },
    )
    assert task_service.start(failed_task.task_id) is True
    task_service.fail(failed_task.task_id, "forced failure")

    retry_response = client.post(f"/api/tasks/{failed_task.task_id}/retry")

    assert retry_response.status_code == 200
    assert retry_response.json()["status"] in {"queued", "running", "completed"}


def test_tool_call_writes_audit_record() -> None:
    response = client.post(
        "/api/ask",
        json={"question": "calculate 2 + 2", "corpus_ids": [], "require_citations": False},
    )

    assert response.status_code == 200
    audit_response = client.get("/api/audit")
    assert audit_response.status_code == 200
    assert any(item["target"] == "calculator" for item in audit_response.json())

    filtered_response = client.get("/api/audit?target=calculator&risk_level=low")
    assert filtered_response.status_code == 200
    assert filtered_response.json()
    assert all(item["target"] == "calculator" for item in filtered_response.json())


def test_system_config_exposes_runtime_and_roles() -> None:
    response = client.get("/api/system/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_store"] in {"json", "postgres"}
    assert "admin" in payload["roles"]


def test_github_repo_url_parser() -> None:
    assert parse_github_repo_url("https://github.com/dafu110/researchops-agent") == (
        "dafu110",
        "researchops-agent",
    )
