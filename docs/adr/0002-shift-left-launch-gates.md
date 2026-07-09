# ADR 0002: Shift-Left Launch Gates And Runtime Headers

## Status

Accepted.

## Context

ResearchOps Agent exposes an API, dashboard, background tasks, RAG storage, URL
ingestion, sandbox execution, and MCP integrations. These boundaries accept
untrusted input and can call external systems, so correctness cannot rely on
manual testing or launch-time review alone.

The project is applying the `addyosmani/agent-skills` release discipline:
security hardening at boundaries, CI quality gates before merge, observable
runtime behavior, and launch documentation that defines evidence, not vibes.

## Decision

Adopt shift-left launch gates and runtime response hardening:

1. CI runs Python compilation, lint, JavaScript syntax checks, tests, eval gate,
   and Docker build.
2. The FastAPI app emits `X-Request-ID` on every response and preserves incoming
   request IDs for correlation.
3. The app sets baseline browser security headers for the dashboard and API.
4. Docker images run as a non-root user, include a healthcheck, and have a
   default `uvicorn` command.
5. `.env.example` is committed with placeholders only; real secrets stay out of
   Git.

## Alternatives Considered

### Keep CI Minimal

Faster to maintain, but Docker and frontend syntax regressions would still be
caught late or by users. Rejected because this project is intended as a
portfolio-ready agent system.

### Add Security Headers At A Reverse Proxy Only

Valid for production, but local and preview deployments would remain weaker and
tests could not verify the contract. Rejected in favor of app-level defaults
that can still be overridden by infrastructure if needed.

## Consequences

- Every response has a correlation ID suitable for logs and support reports.
- Static dashboard pages get CSP, frame, referrer, permissions, and content-type
  protections by default.
- CI catches syntax, lint, test, eval, and Docker regressions before merge.
- Docker images are safer to run directly, while Docker Compose can still
  override commands for API and worker roles.

## Verification

```powershell
python -m compileall app tests scripts
python -m ruff check .
node --check app\static\app.js
python -m pytest -q
python scripts\run_eval_gate.py
docker build .
```
