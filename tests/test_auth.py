import asyncio
import json

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import (
    authenticate_api_key,
    authenticate_password,
    current_user,
    session_service,
)
from app.main import app


client = TestClient(app)


def test_api_key_authentication_builds_user_context(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "api_keys_json",
        json.dumps(
            [
                {
                    "key": "test-key",
                    "user_id": "analyst",
                    "tenant_id": "tenant-a",
                    "role": "editor",
                    "allowed_sources": ["manual"],
                }
            ]
        ),
    )

    user = authenticate_api_key("test-key")

    assert user is not None
    assert user.user_id == "analyst"
    assert user.tenant_id == "tenant-a"
    assert user.can_ingest is True
    assert user.allowed_sources == ["manual"]


def test_password_login_and_bearer_session(monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_keys_json", "[]")
    monkeypatch.setattr(
        settings,
        "local_users_json",
        json.dumps(
            [
                {
                    "user_id": "admin",
                    "password": "secret",
                    "tenant_id": "tenant-a",
                    "role": "admin",
                }
            ]
        ),
    )
    user = authenticate_password("admin", "secret")
    assert user is not None

    token = session_service.create(user)
    loaded_user = asyncio.run(current_user(authorization=f"Bearer {token}"))

    assert loaded_user.user_id == "admin"
    assert loaded_user.can_approve is True


def test_admin_can_create_and_delete_tenant_user(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "api_keys_json",
        json.dumps(
            [
                {
                    "key": "admin-key",
                    "user_id": "admin",
                    "tenant_id": "tenant-users",
                    "role": "admin",
                }
            ]
        ),
    )

    create_response = client.post(
        "/api/users",
        headers={"X-API-Key": "admin-key"},
        json={
            "user_id": "new-user",
            "password": "secret-password",
            "role": "viewer",
        },
    )

    assert create_response.status_code == 200
    assert create_response.json()["tenant_id"] == "tenant-users"

    list_response = client.get("/api/users", headers={"X-API-Key": "admin-key"})
    assert any(user["user_id"] == "new-user" for user in list_response.json())

    delete_response = client.delete("/api/users/new-user", headers={"X-API-Key": "admin-key"})
    assert delete_response.status_code == 200


def test_viewer_cannot_run_evaluations(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "api_keys_json",
        json.dumps(
            [{"key": "viewer-key", "user_id": "viewer", "tenant_id": "tenant-a", "role": "viewer"}]
        ),
    )

    response = client.post("/api/eval/run", headers={"X-API-Key": "viewer-key"})

    assert response.status_code == 403


def test_evaluation_does_not_write_to_the_callers_tenant(monkeypatch) -> None:
    from app.evals.service import eval_service
    from app.rag.store import knowledge_store
    from app.core.traces import trace_store
    from app.core.security import UserContext

    user = UserContext(user_id="eval-user", tenant_id="eval-isolation", role="editor")
    before_documents = knowledge_store.list_documents(user.tenant_id)
    before_runs = trace_store.list_runs(user.tenant_id, limit=1000)

    response = asyncio.run(eval_service.run_golden(user))

    assert response.total_cases
    assert knowledge_store.list_documents(user.tenant_id) == before_documents
    assert trace_store.list_runs(user.tenant_id, limit=1000) == before_runs
