import json
import time
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.api.schemas import TaskRecord
from app.core.config import settings
from app.core.json_state import atomic_json_write, load_json_or_default


class TaskService:
    def __init__(self) -> None:
        self.data_dir = Path(settings.data_dir)
        self.state_path = self.data_dir / "tasks.json"
        self._lock = Lock()
        self._records: dict[str, TaskRecord] = {}
        self._load()

    def create(
        self,
        kind: str,
        title: str,
        tenant_id: str = "default",
        user_id: str = "local-dev",
        payload: dict | None = None,
    ) -> TaskRecord:
        record = TaskRecord(
            task_id=str(uuid4()),
            kind=kind,
            status="queued",
            title=title,
            tenant_id=tenant_id,
            user_id=user_id,
            payload=payload or {},
        )
        with self._lock:
            self._records[record.task_id] = record
            self._save()
        return record

    def start(self, task_id: str) -> bool:
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                return False
            if record.cancel_requested or record.status == "canceled":
                record.status = "canceled"
                record.updated_at = _now()
                self._save()
                return False
            record.status = "running"
            record.attempts += 1
            record.updated_at = _now()
            self._save()
            return True

    def complete(self, task_id: str, result: dict) -> None:
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                return
            if record.cancel_requested:
                record.status = "canceled"
                record.error = "Task was canceled before completion."
            else:
                record.status = "completed"
                record.result = result
                record.error = None
            record.updated_at = _now()
            self._save()

    def fail(self, task_id: str, error: str) -> None:
        self._update(task_id, status="failed", error=error)

    def cancel(self, task_id: str, tenant_id: str | None = None) -> TaskRecord | None:
        with self._lock:
            record = self._records.get(task_id)
            if record is None or (tenant_id and record.tenant_id != tenant_id):
                return None
            if record.status in {"completed", "failed", "canceled"}:
                return record
            record.cancel_requested = True
            if record.status == "queued":
                record.status = "canceled"
                record.error = "Task was canceled before it started."
            else:
                record.error = "Cancellation requested; worker will stop at the next checkpoint."
            record.updated_at = _now()
            self._save()
            return record

    def retry(self, task_id: str, tenant_id: str | None = None) -> TaskRecord | None:
        with self._lock:
            record = self._records.get(task_id)
            if record is None or (tenant_id and record.tenant_id != tenant_id):
                return None
            if record.status not in {"failed", "canceled"}:
                return record
            if record.attempts >= record.max_attempts:
                record.error = f"Retry limit reached ({record.max_attempts})."
                record.updated_at = _now()
                self._save()
                return record
            record.status = "queued"
            record.cancel_requested = False
            record.result = None
            record.error = None
            record.updated_at = _now()
            self._save()
            return record

    def recover_stale_running(self, max_age_seconds: int = 3600) -> int:
        cutoff = _now() - max_age_seconds
        recovered = 0
        with self._lock:
            for record in self._records.values():
                if record.status == "running" and record.updated_at < cutoff:
                    record.status = "failed"
                    record.error = "Recovered stale running task after worker interruption."
                    record.updated_at = _now()
                    recovered += 1
            if recovered:
                self._save()
        return recovered

    def get(self, task_id: str, tenant_id: str | None = None) -> TaskRecord | None:
        with self._lock:
            record = self._records.get(task_id)
        if record and tenant_id and record.tenant_id != tenant_id:
            return None
        return record

    def list_records(self, tenant_id: str | None = None) -> list[TaskRecord]:
        with self._lock:
            records = list(self._records.values())
        if tenant_id:
            records = [record for record in records if record.tenant_id == tenant_id]
        return list(reversed(records[-50:]))

    def _update(
        self,
        task_id: str,
        status: str,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                return
            record.status = status
            record.updated_at = _now()
            if result is not None:
                record.result = result
            if error is not None:
                record.error = error
            if error is None and status == "completed":
                record.error = None
            self._save()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        payload = load_json_or_default(self.state_path, [])
        self._records = {
            item["task_id"]: TaskRecord.model_validate(item)
            for item in payload
        }

    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = [record.model_dump() for record in self._records.values()]
        atomic_json_write(self.state_path, payload)


task_service = TaskService()


def _now() -> int:
    return int(time.time())
