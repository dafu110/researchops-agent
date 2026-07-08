# Architecture

## Goal

ResearchOps Agent turns research work into an auditable workflow:

1. Ingest sources.
2. Retrieve evidence.
3. Answer with citations.
4. Use tools when needed.
5. Pause risky actions for approval.
6. Record trace and eval metrics.

## Components

```mermaid
flowchart LR
  UI["Dashboard / API"] --> API["FastAPI"]
  API --> Orchestrator["Agent Orchestrator"]
  Orchestrator --> Planner["Planner Agent"]
  Orchestrator --> Research["Research Agent"]
  Orchestrator --> Tool["Tool Agent"]
  Orchestrator --> Approval["Approval Service"]
  Research --> Retriever["Hybrid Retriever"]
  Retriever --> Embeddings["Embedding Service"]
  Retriever --> Store["Knowledge Store"]
  Retriever --> Reranker["Reranker"]
  Tool --> SQL["Read-only SQL"]
  Tool --> Sandbox["Python Sandbox"]
  Tool --> Reports["Report Writer"]
  Tool --> MCP["MCP Registry"]
  Orchestrator --> Trace["Trace Store"]
  API --> Eval["Eval Service"]
```

## RAG

The MVP now uses hybrid retrieval:

- Local or OpenAI embeddings.
- Keyword overlap scoring.
- Weighted semantic + keyword score.
- Reranker score before final top-k selection.
- Citations include document ID, title, locator, and excerpt.

`db/schema.sql` contains a pgvector schema for the production path.

## Agent Runtime

Default mode is `auto`. With `OPENAI_API_KEY`, the Research Agent uses the
OpenAI Agents SDK. Without a key, it uses the deterministic local orchestrator.

```env
AGENT_RUNTIME=auto
```

When enabled, the Research Agent uses the OpenAI Agents SDK with:

- `Agent`
- `Runner`
- `function_tool`

The local path remains available when no API key is configured.

## Permissions

API keys map to a user, role, tenant, and optional source allowlist. Ingested
documents store `tenant_id` in metadata. Retrieval and document listing are
filtered by tenant and source allowlist. Runs, trace access, approvals, and eval
summaries are tenant-scoped.

| Role | Ask | Ingest | Approve |
| --- | --- | --- | --- |
| viewer | yes | no | no |
| editor | yes | yes | no |
| admin | yes | yes | yes |

## Tools

Tool Agent supports:

- Calculator.
- Read-only SQLite SQL.
- Restricted Python sandbox with process mode and optional Docker mode.
- Markdown report writer.
- MCP server registry and stdio/HTTP JSON-RPC execution from `MCP_SERVERS_JSON`.

`scripts/example_mcp_server.py` provides a real stdio MCP-style example for
integration testing.

Mutation-style actions are not executed directly. The Planner routes risky
requests to the approval queue.

URL ingestion crosses a network trust boundary. The fetcher rejects non-HTTP
schemes, embedded credentials, private or reserved network addresses, and
unvalidated redirect targets. Deployments can also require a domain allowlist.

## Eval

Golden-set evals check:

- Expected answer terms.
- Citation presence and expected fixture source.
- Approval behavior for unsafe requests.
- Pass rate.
- Citation correctness rate.

The suite seeds each case with a dedicated fixture document, then constrains the
question to that fixture corpus. It covers RAG, tool capability, vector
retrieval, observability, approval safety, missing-context behavior, and sandbox
boundary cases. It is wired into CI as an eval gate.

## Execution Lifecycle

```text
created -> planner -> tool_agent? -> rag_research -> awaiting_approval | completed
```

The trace store persists run metadata with `tenant_id`, `user_id`, question, and
status. This keeps trace timelines auditable and allows tenant-scoped access.

Long-running UI actions can create task records:

```text
queued -> running -> completed | failed
```

Text ingestion, URL ingestion, and eval runs are exposed through async API
endpoints with task status records. Celery task functions are available for the
same workload class when Redis workers are enabled.

## Tool Permissions And Audit

Built-in tools have explicit risk levels. Calculator and knowledge stats are
low risk, SQL and sandbox are medium risk, and MCP calls are high risk. Tool
calls write audit records with actor, tenant, run ID, target, risk level, status,
and a short result summary.

## Remaining Production Work

- Persist runs and traces in PostgreSQL.
- Promote asynchronous PDF/URL/GitHub ingestion routes onto Celery tasks.
- Add stricter MCP server/tool allowlists and enforce per-tool approval policies.
- Add richer planner state transitions, retries, and resumable failures.
- Expand evals with adversarial prompt-injection and tool-failure fixtures.
- Add stronger sandbox isolation defaults for hosted deployments.
