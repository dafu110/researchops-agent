import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.api.schemas import TaskRecord
from app.core.config import settings


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
    ) -> TaskRecord:
        record = TaskRecord(
            task_id=str(uuid4()),
            kind=kind,
            status="queued",
            title=title,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        with self._lock:
            self._records[record.task_id] = record
            self._save()
        return record

    def start(self, task_id: str) -> None:
        self._update(task_id, status="running")

    def complete(self, task_id: str, result: dict) -> None:
        self._update(task_id, status="completed", result=result, error=None)

    def fail(self, task_id: str, error: str) -> None:
        self._update(task_id, status="failed", error=error)

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
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self._records = {
            item["task_id"]: TaskRecord.model_validate(item)
            for item in payload
        }

    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = [record.model_dump() for record in self._records.values()]
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


task_service = TaskService()
