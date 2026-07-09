import pytest

from app.approvals import service as approval_module
from app.core import audit as audit_module
from app.core import traces as trace_module
from app.core.config import settings
from app.core.runtime_db import psycopg_url


def test_runtime_services_fall_back_to_json_when_auto_postgres_unavailable(monkeypatch) -> None:
    def unavailable():
        raise RuntimeError("postgres unavailable")

    monkeypatch.setattr(settings, "store_backend", "auto")
    monkeypatch.setattr(audit_module, "PostgresAuditService", unavailable)
    monkeypatch.setattr(trace_module, "PostgresTraceStore", unavailable)
    monkeypatch.setattr(approval_module, "PostgresApprovalService", unavailable)
    monkeypatch.setattr(audit_module, "AuditService", lambda: "json-audit")
    monkeypatch.setattr(trace_module, "TraceStore", lambda: "json-trace")
    monkeypatch.setattr(approval_module, "ApprovalService", lambda: "json-approval")

    assert audit_module._build_audit_service() == "json-audit"
    assert trace_module._build_trace_store() == "json-trace"
    assert approval_module._build_approval_service() == "json-approval"


def test_runtime_services_raise_when_postgres_backend_is_required(monkeypatch) -> None:
    def unavailable():
        raise RuntimeError("postgres unavailable")

    monkeypatch.setattr(settings, "store_backend", "postgres")
    monkeypatch.setattr(audit_module, "PostgresAuditService", unavailable)
    monkeypatch.setattr(trace_module, "PostgresTraceStore", unavailable)
    monkeypatch.setattr(approval_module, "PostgresApprovalService", unavailable)

    with pytest.raises(RuntimeError, match="postgres unavailable"):
        audit_module._build_audit_service()
    with pytest.raises(RuntimeError, match="postgres unavailable"):
        trace_module._build_trace_store()
    with pytest.raises(RuntimeError, match="postgres unavailable"):
        approval_module._build_approval_service()


def test_runtime_db_uses_psycopg_url_scheme() -> None:
    assert (
        psycopg_url("postgresql+psycopg://researchops:pw@localhost:5432/researchops")
        == "postgresql://researchops:pw@localhost:5432/researchops"
    )
