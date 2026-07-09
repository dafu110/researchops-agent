import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.api.schemas import ApprovalDecision, ApprovalRecord, ApprovalRequest
from app.core.config import settings
from app.core.runtime_db import (
    init_schema,
    load_psycopg,
    psycopg_url,
    should_raise_postgres_errors,
    wants_postgres,
)


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


class PostgresApprovalService:
    def __init__(self) -> None:
        self.psycopg = load_psycopg()
        self.database_url = psycopg_url()
        init_schema(self.psycopg, self.database_url)

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
        with self.psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO approvals
                  (approval_id, run_id, action, reason, risk_level, status, reviewer,
                   tenant_id, requester_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.approval_id,
                    record.run_id,
                    record.action,
                    record.reason,
                    record.risk_level,
                    record.status,
                    record.reviewer,
                    record.tenant_id,
                    record.requester_id,
                ),
            )
        return record

    def decide(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        tenant_id: str | None = None,
    ) -> ApprovalRecord | None:
        filters = ["approval_id = %s"]
        params: list[str] = [approval_id]
        if tenant_id:
            filters.append("tenant_id = %s")
            params.append(tenant_id)
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                f"""
                UPDATE approvals
                SET status = %s, reviewer = %s
                WHERE {" AND ".join(filters)}
                RETURNING approval_id, run_id, action, reason, risk_level, status,
                          reviewer, tenant_id, requester_id
                """,
                ("approved" if decision.approved else "rejected", decision.reviewer, *params),
            ).fetchone()
        return _approval_from_row(row) if row else None

    def list_records(self, tenant_id: str | None = None) -> list[ApprovalRecord]:
        sql = (
            "SELECT approval_id, run_id, action, reason, risk_level, status, reviewer, "
            "tenant_id, requester_id FROM approvals"
        )
        params: tuple[str, ...] = ()
        if tenant_id:
            sql += " WHERE tenant_id = %s"
            params = (tenant_id,)
        sql += " ORDER BY created_at ASC"
        with self.psycopg.connect(self.database_url) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_approval_from_row(row) for row in rows]

    def find_for_run_action(
        self,
        run_id: str,
        action: str,
        tenant_id: str | None = None,
        statuses: set[str] | None = None,
    ) -> ApprovalRecord | None:
        filters = ["run_id = %s", "action = %s"]
        params: list[object] = [run_id, action]
        if tenant_id is not None:
            filters.append("tenant_id = %s")
            params.append(tenant_id)
        if statuses is not None:
            filters.append("status = ANY(%s)")
            params.append(list(statuses))
        sql = (
            "SELECT approval_id, run_id, action, reason, risk_level, status, reviewer, "
            "tenant_id, requester_id FROM approvals WHERE "
            + " AND ".join(filters)
            + " ORDER BY created_at DESC LIMIT 1"
        )
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute(sql, tuple(params)).fetchone()
        return _approval_from_row(row) if row else None


def _approval_from_row(row) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=row[0],
        run_id=row[1],
        action=row[2],
        reason=row[3],
        risk_level=row[4],
        status=row[5],
        reviewer=row[6],
        tenant_id=row[7],
        requester_id=row[8],
    )


def _build_approval_service():
    if wants_postgres():
        try:
            return PostgresApprovalService()
        except Exception:
            if should_raise_postgres_errors():
                raise
    return ApprovalService()


approval_service = _build_approval_service()
