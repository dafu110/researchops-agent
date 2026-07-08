import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.api.schemas import ApprovalDecision, ApprovalRecord, ApprovalRequest
from app.core.config import settings


class ApprovalService:
    def __init__(self) -> None:
        self.data_dir = Path(settings.data_dir)
        self.state_path = self.data_dir / "approvals.json"
        self._lock = Lock()
        self._records: dict[str, ApprovalRecord] = {}
        self._load()

    def create(self, request: ApprovalRequest) -> ApprovalRecord:
        record = ApprovalRecord(
            approval_id=str(uuid4()),
            run_id=request.run_id,
            action=request.action,
            reason=request.reason,
            risk_level=request.risk_level,
            status="pending",
            tenant_id=request.tenant_id,
            requester_id=request.requester_id,
        )
        with self._lock:
            self._records[record.approval_id] = record
            self._save()
        return record

    def decide(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        tenant_id: str | None = None,
    ) -> ApprovalRecord | None:
        with self._lock:
            record = self._records.get(approval_id)
            if record is None:
                return None
            if tenant_id and record.tenant_id != tenant_id:
                return None
            record.status = "approved" if decision.approved else "rejected"
            record.reviewer = decision.reviewer
            self._save()
            return record

    def list_records(self, tenant_id: str | None = None) -> list[ApprovalRecord]:
        with self._lock:
            records = list(self._records.values())
        if tenant_id:
            records = [record for record in records if record.tenant_id == tenant_id]
        return records

    def find_for_run_action(
        self,
        run_id: str,
        action: str,
        tenant_id: str | None = None,
        statuses: set[str] | None = None,
    ) -> ApprovalRecord | None:
        with self._lock:
            records = list(self._records.values())
        matches = [
            record
            for record in records
            if record.run_id == run_id
            and record.action == action
            and (tenant_id is None or record.tenant_id == tenant_id)
            and (statuses is None or record.status in statuses)
        ]
        return matches[-1] if matches else None

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self._records = {
            item["approval_id"]: ApprovalRecord.model_validate(item)
            for item in payload
        }

    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = [record.model_dump() for record in self._records.values()]
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


approval_service = ApprovalService()
