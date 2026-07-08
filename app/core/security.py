import json
from dataclasses import dataclass, field

from fastapi import Header, HTTPException

from app.core.config import settings


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


def _configured_users() -> dict[str, UserContext]:
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


async def current_user(x_api_key: str | None = Header(default=None)) -> UserContext:
    users = _configured_users()
    if not users and not settings.auth_required:
        return UserContext(
            user_id="local-dev",
            tenant_id=settings.default_tenant_id,
            role="admin",
        )
    if x_api_key and x_api_key in users:
        return users[x_api_key]
    raise HTTPException(status_code=401, detail="Valid X-API-Key header is required.")


def require_ingest(user: UserContext) -> None:
    if not user.can_ingest:
        raise HTTPException(status_code=403, detail="Ingest permission is required.")


def require_approval(user: UserContext) -> None:
    if not user.can_approve:
        raise HTTPException(status_code=403, detail="Approval permission is required.")
