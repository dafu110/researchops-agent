import json
import time
from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import uuid4

from app.api.schemas import AskResponse, RunRecord, TokenUsage, ToolCallInput, ToolCallRecord, TraceStep
from app.core.config import settings
from app.core.json_state import atomic_json_write, load_json_or_default
from app.core.runtime_db import (
    init_schema,
    load_psycopg,
    psycopg_url,
    should_raise_postgres_errors,
    wants_postgres,
)


class TraceStore:
    """Single-process durable run state used by the local development runtime."""

    def __init__(self) -> None:
        self.data_dir = Path(settings.data_dir)
        self.state_path = self.data_dir / "traces.json"
        self._lock = Lock()
        self._runs: dict[str, list[TraceStep]] = {}
        self._records: dict[str, RunRecord] = {}
        self._tool_calls: dict[str, list[ToolCallRecord]] = {}
        self._load()

    def create_run(
        self,
        run_id: str,
        question: str,
        tenant_id: str = "default",
        user_id: str = "local-dev",
        corpus_ids: list[str] | None = None,
        mode: str = "evidence",
        require_citations: bool = True,
        max_cost_usd: float | None = None,
    ) -> RunRecord:
        record = RunRecord(
            run_id=run_id,
            question=question,
            status="created",
            tenant_id=tenant_id,
            user_id=user_id,
            corpus_ids=corpus_ids or [],
            mode=mode,
            require_citations=require_citations,
            max_cost_usd=max_cost_usd,
        )
        with self._lock:
            self._records[run_id] = record
            self._runs.setdefault(run_id, [])
            self._tool_calls.setdefault(run_id, [])
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

    def save_response(self, run_id: str, response: AskResponse) -> None:
        with self._lock:
            record = self._records.get(run_id)
            if record is None:
                return
            record.answer = response.answer
            record.citations = response.citations
            record.plan_details = response.plan_details
            record.requires_approval = response.requires_approval
            record.approval_id = response.approval_id
            record.final_answer = response.final_answer
            self._save()

    def list_runs(self, tenant_id: str | None = None, limit: int = 20) -> list[RunRecord]:
        with self._lock:
            records = list(self._records.values())
        if tenant_id:
            records = [record for record in records if record.tenant_id == tenant_id]
        return list(reversed(records[-limit:]))

    def delete_run(self, run_id: str, tenant_id: str) -> bool:
        with self._lock:
            record = self._records.get(run_id)
            if record is None or record.tenant_id != tenant_id:
                return False
            self._records.pop(run_id, None)
            self._runs.pop(run_id, None)
            self._tool_calls.pop(run_id, None)
            self._save()
        return True

    def add_step(
        self,
        run_id: str,
        name: str,
        status: str = "completed",
        latency_ms: int | None = None,
        error: str | None = None,
        input_payload: dict | None = None,
        output_payload: dict | None = None,
        model: str | None = None,
        token_usage: TokenUsage | None = None,
        cost_usd: float | None = None,
    ) -> TraceStep:
        step = TraceStep(
            step_id=str(uuid4()),
            name=name,
            status=status,
            latency_ms=latency_ms,
            error=error,
            input_payload=input_payload or {},
            output_payload=output_payload or {},
            model=model,
            token_usage=token_usage or TokenUsage(),
            cost_usd=cost_usd,
        )
        with self._lock:
            self._runs.setdefault(run_id, []).append(step)
            self._save()
        return step

    def get_steps(self, run_id: str) -> list[TraceStep]:
        with self._lock:
            return list(self._runs.get(run_id, []))

    def create_tool_call(
        self,
        run_id: str,
        tool: ToolCallInput,
        risk_level: str,
        timeout_ms: int,
        max_attempts: int,
        idempotency_key: str,
        cancellable: bool,
        recovery_action: str | None,
    ) -> ToolCallRecord:
        record = ToolCallRecord(
            tool_call_id=str(uuid4()),
            run_id=run_id,
            tool=tool,
            status="queued",
            risk_level=risk_level,
            timeout_ms=timeout_ms,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
            cancellable=cancellable,
            recovery_action=recovery_action,
        )
        with self._lock:
            self._tool_calls.setdefault(run_id, []).append(record)
            self._save()
        return record

    def update_tool_call(self, tool_call_id: str, **changes) -> ToolCallRecord | None:
        with self._lock:
            for records in self._tool_calls.values():
                for record in records:
                    if record.tool_call_id == tool_call_id:
                        for key, value in changes.items():
                            if value is not None and hasattr(record, key):
                                setattr(record, key, value)
                        record.updated_at = int(time.time())
                        self._save()
                        return record
        return None

    def get_tool_calls(self, run_id: str) -> list[ToolCallRecord]:
        with self._lock:
            return list(self._tool_calls.get(run_id, []))

    def find_completed_tool_call(
        self,
        run_id: str,
        idempotency_key: str,
    ) -> ToolCallRecord | None:
        with self._lock:
            return next(
                (
                    record
                    for record in self._tool_calls.get(run_id, [])
                    if record.idempotency_key == idempotency_key and record.status == "completed"
                ),
                None,
            )

    def request_cancel(self, run_id: str, tenant_id: str) -> bool:
        with self._lock:
            record = self._records.get(run_id)
            if record is None or record.tenant_id != tenant_id:
                return False
            if record.status in {"completed", "failed", "canceled", "rejected"}:
                return True
            record.cancel_requested = True
            record.status = "cancel_requested"
            self._save()
        return True

    def is_cancel_requested(self, run_id: str | None) -> bool:
        if not run_id:
            return False
        with self._lock:
            record = self._records.get(run_id)
            return bool(record and record.cancel_requested)

    def clear_cancel(self, run_id: str, tenant_id: str) -> bool:
        with self._lock:
            record = self._records.get(run_id)
            if record is None or record.tenant_id != tenant_id:
                return False
            record.cancel_requested = False
            self._save()
        return True

    def run_count(self, tenant_id: str | None = None) -> int:
        with self._lock:
            if tenant_id:
                return sum(1 for record in self._records.values() if record.tenant_id == tenant_id)
            return len(self._records)

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        payload = load_json_or_default(self.state_path, {})
        if "runs" in payload or "records" in payload:
            self._runs = {
                run_id: [TraceStep.model_validate(step) for step in steps]
                for run_id, steps in payload.get("runs", {}).items()
            }
            self._records = {
                run_id: RunRecord.model_validate(record)
                for run_id, record in payload.get("records", {}).items()
            }
            self._tool_calls = {
                run_id: [ToolCallRecord.model_validate(item) for item in items]
                for run_id, items in payload.get("tool_calls", {}).items()
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
        self._tool_calls = {}

    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": {run_id: record.model_dump() for run_id, record in self._records.items()},
            "runs": {run_id: [step.model_dump() for step in steps] for run_id, steps in self._runs.items()},
            "tool_calls": {
                run_id: [record.model_dump() for record in records]
                for run_id, records in self._tool_calls.items()
            },
        }
        atomic_json_write(self.state_path, payload)


class timed_step:
    def __init__(
        self,
        run_id: str,
        name: str,
        input_payload: dict | None = None,
        model: str | None = None,
        token_usage: TokenUsage | None = None,
        cost_usd: float | None = None,
    ) -> None:
        self.run_id = run_id
        self.name = name
        self.input_payload = input_payload or {}
        self.output_payload: dict = {}
        self.model = model
        self.token_usage = token_usage or TokenUsage()
        self.cost_usd = cost_usd
        self.started = 0.0

    def __enter__(self) -> "timed_step":
        self.started = perf_counter()
        trace_store.set_status(self.run_id, self.name)
        return self

    def set_output(self, output_payload: dict) -> None:
        self.output_payload = output_payload

    def __exit__(self, exc_type, exc, traceback) -> bool:
        latency_ms = int((perf_counter() - self.started) * 1000)
        trace_store.add_step(
            self.run_id,
            self.name,
            status="failed" if exc else "completed",
            latency_ms=latency_ms,
            error=str(exc) if exc else None,
            input_payload=self.input_payload,
            output_payload=self.output_payload,
            model=self.model,
            token_usage=self.token_usage,
            cost_usd=self.cost_usd,
        )
        return False


class PostgresTraceStore:
    """PostgreSQL implementation of the same trace/tool lifecycle contract."""

    def __init__(self) -> None:
        self.psycopg = load_psycopg()
        self.database_url = psycopg_url()
        init_schema(self.psycopg, self.database_url)

    def create_run(self, run_id: str, question: str, tenant_id: str = "default", user_id: str = "local-dev", corpus_ids: list[str] | None = None, mode: str = "evidence", require_citations: bool = True, max_cost_usd: float | None = None) -> RunRecord:
        record = RunRecord(run_id=run_id, question=question, status="created", tenant_id=tenant_id, user_id=user_id, corpus_ids=corpus_ids or [], mode=mode, require_citations=require_citations, max_cost_usd=max_cost_usd)
        with self.psycopg.connect(self.database_url) as connection:
            connection.execute(
                """INSERT INTO runs (run_id, question, status, tenant_id, user_id, corpus_ids, mode, require_citations, max_cost_usd)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET question = EXCLUDED.question, status = EXCLUDED.status,
                tenant_id = EXCLUDED.tenant_id, user_id = EXCLUDED.user_id, corpus_ids = EXCLUDED.corpus_ids,
                mode = EXCLUDED.mode, require_citations = EXCLUDED.require_citations, max_cost_usd = EXCLUDED.max_cost_usd""",
                (record.run_id, record.question, record.status, record.tenant_id, record.user_id, json.dumps(record.corpus_ids), record.mode, record.require_citations, record.max_cost_usd),
            )
        return record

    def set_status(self, run_id: str, status: str) -> None:
        with self.psycopg.connect(self.database_url) as connection:
            connection.execute("UPDATE runs SET status = %s WHERE run_id = %s", (status, run_id))

    def get_run(self, run_id: str) -> RunRecord | None:
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute("SELECT run_id, question, status, tenant_id, user_id, answer, citations, plan_details, requires_approval, approval_id, corpus_ids, mode, require_citations, max_cost_usd, final_answer, cancel_requested FROM runs WHERE run_id = %s", (run_id,)).fetchone()
        return self._record_from_row(row) if row else None

    def save_response(self, run_id: str, response: AskResponse) -> None:
        with self.psycopg.connect(self.database_url) as connection:
            connection.execute("""UPDATE runs SET answer = %s, citations = %s, plan_details = %s, requires_approval = %s, approval_id = %s, final_answer = %s WHERE run_id = %s""", (response.answer, json.dumps([item.model_dump() for item in response.citations]), json.dumps([item.model_dump() for item in response.plan_details]), response.requires_approval, response.approval_id, json.dumps(response.final_answer.model_dump()) if response.final_answer else None, run_id))

    def list_runs(self, tenant_id: str | None = None, limit: int = 20) -> list[RunRecord]:
        sql = "SELECT run_id, question, status, tenant_id, user_id, answer, citations, plan_details, requires_approval, approval_id, corpus_ids, mode, require_citations, max_cost_usd, final_answer, cancel_requested FROM runs"
        params: list[object] = []
        if tenant_id:
            sql += " WHERE tenant_id = %s"
            params.append(tenant_id)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self.psycopg.connect(self.database_url) as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [self._record_from_row(row) for row in rows]

    def delete_run(self, run_id: str, tenant_id: str) -> bool:
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute("DELETE FROM runs WHERE run_id = %s AND tenant_id = %s RETURNING run_id", (run_id, tenant_id)).fetchone()
        return row is not None

    def add_step(self, run_id: str, name: str, status: str = "completed", latency_ms: int | None = None, error: str | None = None, input_payload: dict | None = None, output_payload: dict | None = None, model: str | None = None, token_usage: TokenUsage | None = None, cost_usd: float | None = None) -> TraceStep:
        step = TraceStep(step_id=str(uuid4()), name=name, status=status, latency_ms=latency_ms, error=error, input_payload=input_payload or {}, output_payload=output_payload or {}, model=model, token_usage=token_usage or TokenUsage(), cost_usd=cost_usd)
        with self.psycopg.connect(self.database_url) as connection:
            connection.execute("INSERT INTO trace_steps (step_id, run_id, name, status, latency_ms, error, input_payload, output_payload, model, token_usage, cost_usd) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (step.step_id, run_id, step.name, step.status, step.latency_ms, step.error, json.dumps(step.input_payload), json.dumps(step.output_payload), step.model, json.dumps(step.token_usage.model_dump()), step.cost_usd))
        return step

    def get_steps(self, run_id: str) -> list[TraceStep]:
        with self.psycopg.connect(self.database_url) as connection:
            rows = connection.execute("SELECT step_id, name, status, latency_ms, error, input_payload, output_payload, model, token_usage, cost_usd, EXTRACT(EPOCH FROM created_at)::integer FROM trace_steps WHERE run_id = %s ORDER BY created_at ASC", (run_id,)).fetchall()
        return [TraceStep(step_id=row[0], name=row[1], status=row[2], latency_ms=row[3], error=row[4], input_payload=row[5] or {}, output_payload=row[6] or {}, model=row[7], token_usage=row[8] or {}, cost_usd=row[9], created_at=row[10]) for row in rows]

    def create_tool_call(self, run_id: str, tool: ToolCallInput, risk_level: str, timeout_ms: int, max_attempts: int, idempotency_key: str, cancellable: bool, recovery_action: str | None) -> ToolCallRecord:
        record = ToolCallRecord(tool_call_id=str(uuid4()), run_id=run_id, tool=tool, status="queued", risk_level=risk_level, timeout_ms=timeout_ms, max_attempts=max_attempts, idempotency_key=idempotency_key, cancellable=cancellable, recovery_action=recovery_action)
        self._save_tool_call(record)
        return record

    def update_tool_call(self, tool_call_id: str, **changes) -> ToolCallRecord | None:
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute("SELECT tool_call_id, run_id, tool, status, risk_level, timeout_ms, attempt, max_attempts, idempotency_key, cancellable, recovery_action, output, error, latency_ms, EXTRACT(EPOCH FROM created_at)::integer, EXTRACT(EPOCH FROM updated_at)::integer FROM tool_calls WHERE tool_call_id = %s", (tool_call_id,)).fetchone()
        if row is None:
            return None
        record = self._tool_call_from_row(row)
        for key, value in changes.items():
            if value is not None and hasattr(record, key):
                setattr(record, key, value)
        record.updated_at = int(time.time())
        self._save_tool_call(record)
        return record

    def get_tool_calls(self, run_id: str) -> list[ToolCallRecord]:
        with self.psycopg.connect(self.database_url) as connection:
            rows = connection.execute("SELECT tool_call_id, run_id, tool, status, risk_level, timeout_ms, attempt, max_attempts, idempotency_key, cancellable, recovery_action, output, error, latency_ms, EXTRACT(EPOCH FROM created_at)::integer, EXTRACT(EPOCH FROM updated_at)::integer FROM tool_calls WHERE run_id = %s ORDER BY created_at ASC", (run_id,)).fetchall()
        return [self._tool_call_from_row(row) for row in rows]

    def find_completed_tool_call(self, run_id: str, idempotency_key: str) -> ToolCallRecord | None:
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute("SELECT tool_call_id, run_id, tool, status, risk_level, timeout_ms, attempt, max_attempts, idempotency_key, cancellable, recovery_action, output, error, latency_ms, EXTRACT(EPOCH FROM created_at)::integer, EXTRACT(EPOCH FROM updated_at)::integer FROM tool_calls WHERE run_id = %s AND idempotency_key = %s AND status = 'completed' ORDER BY created_at DESC LIMIT 1", (run_id, idempotency_key)).fetchone()
        return self._tool_call_from_row(row) if row else None

    def request_cancel(self, run_id: str, tenant_id: str) -> bool:
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute("UPDATE runs SET cancel_requested = TRUE, status = 'cancel_requested' WHERE run_id = %s AND tenant_id = %s AND status NOT IN ('completed', 'failed', 'canceled', 'rejected') RETURNING run_id", (run_id, tenant_id)).fetchone()
        return row is not None or self.get_run(run_id) is not None

    def is_cancel_requested(self, run_id: str | None) -> bool:
        if not run_id:
            return False
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute("SELECT cancel_requested FROM runs WHERE run_id = %s", (run_id,)).fetchone()
        return bool(row and row[0])

    def clear_cancel(self, run_id: str, tenant_id: str) -> bool:
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute("UPDATE runs SET cancel_requested = FALSE WHERE run_id = %s AND tenant_id = %s RETURNING run_id", (run_id, tenant_id)).fetchone()
        return row is not None

    def run_count(self, tenant_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM runs"
        params: tuple[str, ...] = ()
        if tenant_id:
            sql += " WHERE tenant_id = %s"
            params = (tenant_id,)
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def _save_tool_call(self, record: ToolCallRecord) -> None:
        with self.psycopg.connect(self.database_url) as connection:
            connection.execute("""INSERT INTO tool_calls (tool_call_id, run_id, tool, status, risk_level, timeout_ms, attempt, max_attempts, idempotency_key, cancellable, recovery_action, output, error, latency_ms, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) ON CONFLICT (tool_call_id) DO UPDATE SET tool = EXCLUDED.tool, status = EXCLUDED.status, risk_level = EXCLUDED.risk_level, timeout_ms = EXCLUDED.timeout_ms, attempt = EXCLUDED.attempt, max_attempts = EXCLUDED.max_attempts, output = EXCLUDED.output, error = EXCLUDED.error, latency_ms = EXCLUDED.latency_ms, updated_at = now()""", (record.tool_call_id, record.run_id, json.dumps(record.tool.model_dump()), record.status, record.risk_level, record.timeout_ms, record.attempt, record.max_attempts, record.idempotency_key, record.cancellable, record.recovery_action, json.dumps(record.output) if record.output is not None else None, record.error, record.latency_ms))

    @staticmethod
    def _record_from_row(row) -> RunRecord:
        return RunRecord(run_id=row[0], question=row[1], status=row[2], tenant_id=row[3], user_id=row[4], answer=row[5], citations=row[6] or [], plan_details=row[7] or [], requires_approval=row[8] or False, approval_id=row[9], corpus_ids=row[10] or [], mode=row[11] or "evidence", require_citations=row[12], max_cost_usd=row[13], final_answer=row[14], cancel_requested=row[15] or False)

    @staticmethod
    def _tool_call_from_row(row) -> ToolCallRecord:
        return ToolCallRecord(tool_call_id=row[0], run_id=row[1], tool=row[2] or {}, status=row[3], risk_level=row[4], timeout_ms=row[5], attempt=row[6], max_attempts=row[7], idempotency_key=row[8], cancellable=row[9], recovery_action=row[10], output=row[11], error=row[12], latency_ms=row[13], created_at=row[14], updated_at=row[15])


def _build_trace_store():
    if wants_postgres():
        try:
            return PostgresTraceStore()
        except Exception:
            if should_raise_postgres_errors():
                raise
    return TraceStore()


trace_store = _build_trace_store()
