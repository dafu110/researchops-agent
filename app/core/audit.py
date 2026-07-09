import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.api.schemas import AuditRecord
from app.core.config import settings
from app.core.runtime_db import (
    init_schema,
    load_psycopg,
    psycopg_url,
    should_raise_postgres_errors,
    wants_postgres,
)


class AuditService:
    def __init__(self) -> None:
        self.data_dir = Path(settings.data_dir)
        self.state_path = self.data_dir / "audit.json"
        self._lock = Lock()
        self._records: list[AuditRecord] = []
        self._load()

    def record(
        self,
        action: str,
        target: str,
        risk_level: str,
        status: str,
        detail: str = "",
        run_id: str | None = None,
        actor_id: str = "local-dev",
        tenant_id: str = "default",
    ) -> AuditRecord:
        record = AuditRecord(
            audit_id=str(uuid4()),
            run_id=run_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            action=action,
            target=target,
            risk_level=risk_level,
            status=status,
            detail=detail[:500],
        )
        with self._lock:
            self._records.append(record)
            self._records = self._records[-500:]
            self._save()
        return record

    def list_records(
        self,
        tenant_id: str | None = None,
        risk_level: str | None = None,
        status: str | None = None,
        target: str | None = None,
        run_id: str | None = None,
    ) -> list[AuditRecord]:
        with self._lock:
            records = list(self._records)
        if tenant_id:
            records = [record for record in records if record.tenant_id == tenant_id]
        if risk_level:
            records = [record for record in records if record.risk_level == risk_level]
        if status:
            records = [record for record in records if record.status == status]
        if target:
            records = [record for record in records if record.target == target]
        if run_id:
            records = [record for record in records if record.run_id == run_id]
        return list(reversed(records[-50:]))

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self._records = [AuditRecord.model_validate(item) for item in payload]

    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = [record.model_dump() for record in self._records]
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class PostgresAuditService:
    def __init__(self) -> None:
        self.psycopg = load_psycopg()
        self.database_url = psycopg_url()
        init_schema(self.psycopg, self.database_url)

    def record(
        self,
        action: str,
        target: str,
        risk_level: str,
        status: str,
        detail: str = "",
        run_id: str | None = None,
        actor_id: str = "local-dev",
        tenant_id: str = "default",
    ) -> AuditRecord:
        record = AuditRecord(
            audit_id=str(uuid4()),
            run_id=run_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            action=action,
            target=target,
            risk_level=risk_level,
            status=status,
            detail=detail[:500],
        )
        with self.psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO audit_records
                  (audit_id, run_id, actor_id, tenant_id, action, target, risk_level, status, detail)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.audit_id,
                    record.run_id,
                    record.actor_id,
                    record.tenant_id,
                    record.action,
                    record.target,
                    record.risk_level,
                    record.status,
                    record.detail,
                ),
            )
        return record

    def list_records(
        self,
        tenant_id: str | None = None,
        risk_level: str | None = None,
        status: str | None = None,
        target: str | None = None,
        run_id: str | None = None,
    ) -> list[AuditRecord]:
        filters = []
        params: list[str] = []
        if tenant_id:
            filters.append("tenant_id = %s")
            params.append(tenant_id)
        if risk_level:
            filters.append("risk_level = %s")
            params.append(risk_level)
        if status:
            filters.append("status = %s")
            params.append(status)
        if target:
            filters.append("target = %s")
            params.append(target)
        if run_id:
            filters.append("run_id = %s")
            params.append(run_id)

        sql = (
            "SELECT audit_id, run_id, actor_id, tenant_id, action, target, risk_level, status, detail "
            "FROM audit_records"
        )
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY created_at DESC LIMIT 50"

        with self.psycopg.connect(self.database_url) as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [
            AuditRecord(
                audit_id=row[0],
                run_id=row[1],
                actor_id=row[2],
                tenant_id=row[3],
                action=row[4],
                target=row[5],
                risk_level=row[6],
                status=row[7],
                detail=row[8],
            )
            for row in rows
        ]


def _build_audit_service():
    if wants_postgres():
        try:
            return PostgresAuditService()
        except Exception:
            if should_raise_postgres_errors():
                raise
    return AuditService()


audit_service = _build_audit_service()
