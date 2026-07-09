import json
from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import uuid4

from app.api.schemas import RunRecord, TraceStep
from app.core.config import settings
from app.core.runtime_db import (
    init_schema,
    load_psycopg,
    psycopg_url,
    should_raise_postgres_errors,
    wants_postgres,
)


class TraceStore:
    def __init__(self) -> None:
        self.data_dir = Path(settings.data_dir)
        self.state_path = self.data_dir / "traces.json"
        self._lock = Lock()
        self._runs: dict[str, list[TraceStep]] = {}
        self._records: dict[str, RunRecord] = {}
        self._load()

    def create_run(
        self,
        run_id: str,
        question: str,
        tenant_id: str = "default",
        user_id: str = "local-dev",
    ) -> RunRecord:
        record = RunRecord(
            run_id=run_id,
            question=question,
            status="created",
            tenant_id=tenant_id,
            user_id=user_id,
        )
        with self._lock:
            self._records[run_id] = record
            self._runs.setdefault(run_id, [])
            self._save()
        return record

    def set_status(self, run_id: str, status: str) -> None:
        with self._lock:
            record = self._records.get(run_id)
            if record:
                record.status = status
                self._save()

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._records.get(run_id)

    def add_step(
        self,
        run_id: str,
        name: str,
        status: str = "completed",
        latency_ms: int | None = None,
        error: str | None = None,
    ) -> TraceStep:
        step = TraceStep(
            step_id=str(uuid4()),
            name=name,
            status=status,
            latency_ms=latency_ms,
            error=error,
        )
        with self._lock:
            self._runs.setdefault(run_id, []).append(step)
            self._save()
        return step

    def get_steps(self, run_id: str) -> list[TraceStep]:
        with self._lock:
            return list(self._runs.get(run_id, []))

    def run_count(self, tenant_id: str | None = None) -> int:
        with self._lock:
            if tenant_id:
                return sum(1 for record in self._records.values() if record.tenant_id == tenant_id)
            return len(self._runs)

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        if "runs" in payload or "records" in payload:
            self._runs = {
                run_id: [TraceStep.model_validate(step) for step in steps]
                for run_id, steps in payload.get("runs", {}).items()
            }
            self._records = {
                run_id: RunRecord.model_validate(record)
                for run_id, record in payload.get("records", {}).items()
            }
            return
        self._runs = {
            run_id: [TraceStep.model_validate(step) for step in steps]
            for run_id, steps in payload.items()
        }
        self._records = {
            run_id: RunRecord(
                run_id=run_id,
                question="legacy run",
                status="completed",
                tenant_id=settings.default_tenant_id,
            )
            for run_id in self._runs
        }

    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": {
                run_id: record.model_dump()
                for run_id, record in self._records.items()
            },
            "runs": {
                run_id: [step.model_dump() for step in steps]
                for run_id, steps in self._runs.items()
            },
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class timed_step:
    def __init__(self, run_id: str, name: str) -> None:
        self.run_id = run_id
        self.name = name
        self.started = 0.0

    def __enter__(self) -> "timed_step":
        self.started = perf_counter()
        trace_store.set_status(self.run_id, self.name)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        latency_ms = int((perf_counter() - self.started) * 1000)
        status = "failed" if exc else "completed"
        trace_store.add_step(
            self.run_id,
            self.name,
            status=status,
            latency_ms=latency_ms,
            error=str(exc) if exc else None,
        )
        return False


class PostgresTraceStore:
    def __init__(self) -> None:
        self.psycopg = load_psycopg()
        self.database_url = psycopg_url()
        init_schema(self.psycopg, self.database_url)

    def create_run(
        self,
        run_id: str,
        question: str,
        tenant_id: str = "default",
        user_id: str = "local-dev",
    ) -> RunRecord:
        record = RunRecord(
            run_id=run_id,
            question=question,
            status="created",
            tenant_id=tenant_id,
            user_id=user_id,
        )
        with self.psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO runs (run_id, question, status, tenant_id, user_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    question = EXCLUDED.question,
                    status = EXCLUDED.status,
                    tenant_id = EXCLUDED.tenant_id,
                    user_id = EXCLUDED.user_id
                """,
                (
                    record.run_id,
                    record.question,
                    record.status,
                    record.tenant_id,
                    record.user_id,
                ),
            )
        return record

    def set_status(self, run_id: str, status: str) -> None:
        with self.psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE runs SET status = %s WHERE run_id = %s",
                (status, run_id),
            )

    def get_run(self, run_id: str) -> RunRecord | None:
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT run_id, question, status, tenant_id, user_id FROM runs WHERE run_id = %s",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return RunRecord(
            run_id=row[0],
            question=row[1],
            status=row[2],
            tenant_id=row[3],
            user_id=row[4],
        )

    def add_step(
        self,
        run_id: str,
        name: str,
        status: str = "completed",
        latency_ms: int | None = None,
        error: str | None = None,
    ) -> TraceStep:
        step = TraceStep(
            step_id=str(uuid4()),
            name=name,
            status=status,
            latency_ms=latency_ms,
            error=error,
        )
        with self.psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO runs (run_id, question, status)
                VALUES (%s, %s, %s)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (run_id, "legacy run", status),
            )
            connection.execute(
                """
                INSERT INTO trace_steps (step_id, run_id, name, status, latency_ms, error)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    step.step_id,
                    run_id,
                    step.name,
                    step.status,
                    step.latency_ms,
                    step.error,
                ),
            )
        return step

    def get_steps(self, run_id: str) -> list[TraceStep]:
        with self.psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                """
                SELECT step_id, name, status, latency_ms, error
                FROM trace_steps
                WHERE run_id = %s
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            TraceStep(
                step_id=row[0],
                name=row[1],
                status=row[2],
                latency_ms=row[3],
                error=row[4],
            )
            for row in rows
        ]

    def run_count(self, tenant_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM runs"
        params: tuple[str, ...] = ()
        if tenant_id:
            sql += " WHERE tenant_id = %s"
            params = (tenant_id,)
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute(sql, params).fetchone()
        return int(row[0]) if row else 0


def _build_trace_store():
    if wants_postgres():
        try:
            return PostgresTraceStore()
        except Exception:
            if should_raise_postgres_errors():
                raise
    return TraceStore()


trace_store = _build_trace_store()
