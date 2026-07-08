import hashlib
import json
import secrets
from pathlib import Path
from threading import Lock

from app.api.schemas import UserCreateRequest, UserRecord
from app.core.config import settings
from app.core.security import UserContext


class UserService:
    def __init__(self) -> None:
        self.path = Path(settings.data_dir) / "users.json"
        self._lock = Lock()
        self._records: dict[str, dict] = {}
        self._load()

    def create(self, request: UserCreateRequest) -> UserRecord:
        if request.role not in {"admin", "editor", "viewer"}:
            raise ValueError("role must be admin, editor, or viewer")
        salt = secrets.token_hex(16)
        record = {
            "user_id": request.user_id,
            "tenant_id": request.tenant_id,
            "role": request.role,
            "allowed_sources": request.allowed_sources,
            "salt": salt,
            "password_hash": _hash_password(request.password, salt),
        }
        with self._lock:
            self._records[request.user_id] = record
            self._save()
        return self._public_record(record)

    def list_records(self, tenant_id: str | None = None) -> list[UserRecord]:
        with self._lock:
            records = list(self._records.values())
        if tenant_id:
            records = [record for record in records if record["tenant_id"] == tenant_id]
        return [self._public_record(record) for record in records]

    def delete(self, user_id: str, tenant_id: str | None = None) -> bool:
        with self._lock:
            record = self._records.get(user_id)
            if not record:
                return False
            if tenant_id and record["tenant_id"] != tenant_id:
                return False
            self._records.pop(user_id)
            self._save()
            return True

    def authenticate(self, user_id: str, password: str) -> UserContext | None:
        with self._lock:
            record = self._records.get(user_id)
        if not record:
            return None
        password_hash = _hash_password(password, record["salt"])
        if not secrets.compare_digest(password_hash, record["password_hash"]):
            return None
        return UserContext(
            user_id=record["user_id"],
            tenant_id=record["tenant_id"],
            role=record["role"],
            allowed_sources=list(record.get("allowed_sources", [])),
        )

    def _public_record(self, record: dict) -> UserRecord:
        return UserRecord(
            user_id=record["user_id"],
            tenant_id=record["tenant_id"],
            role=record["role"],
            allowed_sources=list(record.get("allowed_sources", [])),
        )

    def _load(self) -> None:
        if not self.path.exists():
            return
        self._records = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._records, indent=2), encoding="utf-8")


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return digest.hex()


user_service = UserService()
