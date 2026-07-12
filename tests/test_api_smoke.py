from fastapi.testclient import TestClient

from app.main import app
from app.core.tasks import task_service
from app.rag.github_repo import parse_github_repo_url


client = TestClient(app)


def test_dashboard_smoke() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "ResearchOps" in response.text
    assert "资料接入" in response.text
    assert "审计日志" in response.text


def test_run_history_api_returns_persisted_answers() -> None:
    ask_response = client.post(
        "/api/ask",
        json={"question": "calculate 3 + 4", "corpus_ids": [], "require_citations": False},
    )

    assert ask_response.status_code == 200
    run_id = ask_response.json()["run_id"]
    runs_response = client.get("/api/runs")

    assert runs_response.status_code == 200
    run = next(item for item in runs_response.json() if item["run_id"] == run_id)
    assert run["answer"]
    assert run["plan_details"]


def test_approved_run_can_resume_through_the_api() -> None:
    pending_response = client.post(
        "/api/ask",
        json={"question": "Please delete this temporary record", "corpus_ids": []},
    )

    assert pending_response.status_code == 200
    pending = pending_response.json()
    approval_response = client.post(
        f"/api/approvals/{pending['approval_id']}/decision",
        json={"approved": True, "reviewer": "api-smoke"},
    )
    assert approval_response.status_code == 200

    resumed_response = client.post(f"/api/runs/{pending['run_id']}/resume")

    assert resumed_response.status_code == 200
    resumed = resumed_response.json()
    assert resumed["run_id"] == pending["run_id"]
    assert resumed["requires_approval"] is False


def test_rejected_approval_terminalizes_its_run() -> None:
    pending_response = client.post(
        "/api/ask",
        json={"question": "Please delete this rejected fixture", "corpus_ids": []},
    )
    pending = pending_response.json()
    decision_response = client.post(
        f"/api/approvals/{pending['approval_id']}/decision",
        json={"approved": False, "reviewer": "api-smoke"},
    )

    assert decision_response.status_code == 200
    run = next(item for item in client.get("/api/runs").json() if item["run_id"] == pending["run_id"])
    assert run["status"] == "rejected"
    assert client.post(
        f"/api/approvals/{pending['approval_id']}/decision",
        json={"approved": True, "reviewer": "api-smoke"},
    ).status_code == 409
    assert client.post(f"/api/runs/{pending['run_id']}/cancel").status_code == 409


def test_research_run_delete_removes_related_data() -> None:
    pending_response = client.post(
        "/api/ask",
        json={"question": "Please delete this run deletion fixture", "corpus_ids": []},
    )
    pending = pending_response.json()
    run_id = pending["run_id"]

    delete_response = client.delete(f"/api/runs/{run_id}")

    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    assert all(item["run_id"] != run_id for item in client.get("/api/runs").json())
    assert not any(item["run_id"] == run_id for item in client.get("/api/approvals").json())
    assert client.get(f"/api/runs/{run_id}/trace").status_code == 404
    assert client.get(f"/api/audit/replay/{run_id}").status_code == 404
    assert not client.get(f"/api/audit?run_id={run_id}").json()


def test_p0_contract_and_metrics_endpoints_are_visible() -> None:
    ask_response = client.post(
        "/api/ask",
        json={"question": "calculate 4 + 5", "corpus_ids": [], "require_citations": False},
    )
    assert ask_response.status_code == 200
    payload = ask_response.json()
    assert payload["final_answer"]["model"] == "deterministic-rag"
    assert payload["tool_calls"][0]["idempotency_key"]

    run_id = payload["run_id"]
    trace = client.get(f"/api/runs/{run_id}/trace")
    assert trace.status_code == 200
    assert trace.json()["steps"][0]["input_payload"]
    tools = client.get(f"/api/runs/{run_id}/tools")
    assert tools.status_code == 200
    assert tools.json()[0]["status"] == "completed"

    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert "p95_latency_ms" in metrics.json()
    contracts = client.get("/api/contracts")
    assert contracts.status_code == 200
    assert "tool_call" in contracts.json()


def test_document_delete_removes_indexed_document() -> None:
    ingest_response = client.post(
        "/api/ingest/text",
        json={"title": "Delete Fixture", "text": "Temporary indexed content.", "source": "delete-test"},
    )

    assert ingest_response.status_code == 200
    document_id = ingest_response.json()["document_id"]
    delete_response = client.delete(f"/api/documents/{document_id}")

    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    documents_response = client.get("/api/documents")
    assert all(item["document_id"] != document_id for item in documents_response.json())


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
