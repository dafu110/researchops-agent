# Launch Hardening Checklist

## Blocking Gates

- High-risk MCP tool calls must be blocked before execution unless approved.
- URL ingestion must reject private, reserved, localhost, and link-local targets.
- Docker sandbox mode should be used for hosted code execution.
- PostgreSQL/pgvector should be used for the production store.
- Every HTTP response must include a correlation `X-Request-ID`.
- Dashboard/API responses must include baseline security headers.
- Docker images must run as a non-root user and expose a healthcheck.
- Local `.venv`, caches, JSON runtime state, uploaded files, and generated reports must stay out of Git.

## Recommended Pre-Launch Commands

```powershell
python -m ruff check .
python -m compileall app tests scripts
node --check app\static\app.js
python -m pytest -q
python scripts\run_eval_gate.py
```

When Docker Compose is running:

```powershell
python scripts\validate_postgres_store.py
```

## Portfolio Polish

- Keep `docs/assets/dashboard.png` current.
- Add release notes that distinguish local JSON mode from PostgreSQL/pgvector mode.
- Include one demo trace showing planner, tool approval, RAG answer, audit replay, and eval gate.

## Agent-Skills Mapping

- Security and hardening: validate URL/file inputs, enforce MCP approval, set browser security headers, keep secrets out of Git.
- API and interface design: maintain typed Pydantic schemas and stable response contracts.
- CI/CD and automation: run compile, lint, tests, eval gate, JavaScript syntax checks, and Docker build on CI.
- Observability and instrumentation: propagate `X-Request-ID` for request correlation.
- Shipping and launch: keep rollback and launch-readiness evidence in docs before publishing.
