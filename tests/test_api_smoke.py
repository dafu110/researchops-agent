from fastapi.testclient import TestClient

from app.main import app
from app.rag.github_repo import parse_github_repo_url


client = TestClient(app)


def test_dashboard_smoke() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Research Task Workspace" in response.text
    assert "Ingest Sources" in response.text
    assert "Tool Audit" in response.text


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


def test_tool_call_writes_audit_record() -> None:
    response = client.post(
        "/api/ask",
        json={"question": "calculate 2 + 2", "corpus_ids": [], "require_citations": False},
    )

    assert response.status_code == 200
    audit_response = client.get("/api/audit")
    assert audit_response.status_code == 200
    assert any(item["target"] == "calculator" for item in audit_response.json())


def test_github_repo_url_parser() -> None:
    assert parse_github_repo_url("https://github.com/dafu110/researchops-agent") == (
        "dafu110",
        "researchops-agent",
    )
