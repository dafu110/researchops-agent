import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from fastapi import Header, HTTPException

from app.core.config import settings
from app.core.json_state import atomic_json_write, load_json_or_default


ROLE_PERMISSIONS: dict[str, list[str]] = {
    "viewer": ["ask", "read_documents", "read_trace", "read_tasks", "read_audit"],
    "editor": [
        "ask",
        "read_documents",
        "read_trace",
        "read_tasks",
        "read_audit",
        "ingest",
        "run_eval",
        "retry_task",
        "cancel_task",
    ],
    "admin": [
        "ask",
        "read_documents",
        "read_trace",
        "read_tasks",
        "read_audit",
        "ingest",
        "run_eval",
        "retry_task",
        "cancel_task",
        "approve",
        "delete_run",
        "manage_users",
        "read_system_config",
    ],
}


@dataclass
class UserContext:
    user_id: str
    tenant_id: str
    role: str = "viewer"
    allowed_sources: list[str] = field(default_factory=list)

    @property
    def can_ingest(self) -> bool:
        return self.role in {"admin", "editor"}

    @property
    def can_approve(self) -> bool:
        return self.role == "admin"

    def has_permission(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, [])


class SessionService:
    def __init__(self) -> None:
        self.path = Path(settings.data_dir) / "sessions.json"
        self._lock = Lock()
        self._sessions: dict[str, dict] = {}
        self._load()

    def create(self, user: UserContext) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + settings.session_ttl_seconds
        with self._lock:
            self._sessions[token] = {
                "user": {
                    "user_id": user.user_id,
                    "tenant_id": user.tenant_id,
                    "role": user.role,
                    "allowed_sources": user.allowed_sources,
                },
                "expires_at": expires_at,
            }
            self._save()
        return token

    def get(self, token: str) -> UserContext | None:
        with self._lock:
            record = self._sessions.get(token)
            if not record:
                return None
            if int(record.get("expires_at", 0)) < int(time.time()):
                self._sessions.pop(token, None)
                self._save()
                return None
            return UserContext(**record["user"])

    def _load(self) -> None:
        if not self.path.exists():
            return
        self._sessions = load_json_or_default(self.path, {})

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(self.path, self._sessions)


def configured_api_users() -> dict[str, UserContext]:
    try:
        payload = json.loads(settings.api_keys_json)
    except json.JSONDecodeError:
        payload = []
    users = {}
    for item in payload:
        if not isinstance(item, dict) or "key" not in item:
            continue
        users[str(item["key"])] = UserContext(
            user_id=str(item.get("user_id", "api-user")),
            tenant_id=str(item.get("tenant_id", settings.default_tenant_id)),
            role=str(item.get("role", "viewer")),
            allowed_sources=list(item.get("allowed_sources", [])),
        )
    return users


def configured_password_users() -> dict[str, tuple[str, UserContext]]:
    try:
        payload = json.loads(settings.local_users_json)
    except json.JSONDecodeError:
        payload = []
    users = {}
    for item in payload:
        if not isinstance(item, dict) or "user_id" not in item or "password" not in item:
            continue
        user_id = str(item["user_id"])
        users[user_id] = (
            str(item["password"]),
            UserContext(
                user_id=user_id,
                tenant_id=str(item.get("tenant_id", settings.default_tenant_id)),
                role=str(item.get("role", "viewer")),
                allowed_sources=list(item.get("allowed_sources", [])),
            ),
        )
    return users


def authenticate_api_key(api_key: str | None) -> UserContext | None:
    users = configured_api_users()
    if api_key and api_key in users:
        return users[api_key]
    return None


def authenticate_password(user_id: str | None, password: str | None) -> UserContext | None:
    if not user_id or not password:
        return None
    from app.core.users import user_service

    stored_user = user_service.authenticate(user_id, password)
    if stored_user:
        return stored_user
    record = configured_password_users().get(user_id)
    if not record:
        return None
    expected_password, user = record
    if not secrets.compare_digest(expected_password, password):
        return None
    return user


async def current_user(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> UserContext:
    session_user = _user_from_authorization(authorization)
    if session_user:
        return session_user

    api_user = authenticate_api_key(x_api_key)
    if api_user:
        return api_user

    if (
        not configured_api_users()
        and not configured_password_users()
        and not settings.auth_required
        and settings.app_env.lower() in {"local", "development", "dev", "test"}
    ):
        return UserContext(
            user_id="local-dev",
            tenant_id=settings.default_tenant_id,
            role="admin",
        )
    raise HTTPException(status_code=401, detail="Authentication is required.")


def _user_from_authorization(authorization: str | None) -> UserContext | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return session_service.get(token)


def require_ingest(user: UserContext) -> None:
    if not user.can_ingest:
        raise HTTPException(status_code=403, detail="Ingest permission is required.")


def require_approval(user: UserContext) -> None:
    if not user.can_approve:
        raise HTTPException(status_code=403, detail="Approval permission is required.")


session_service = SessionService()
