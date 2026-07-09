# ADR 0001: Planner, Tool Agent, And Approval Boundary

## Status

Accepted.

## Context

ResearchOps Agent supports retrieval, reports, SQL, sandboxed Python, and MCP tool calls. Some tools are read-only and low risk, while externally delegated or mutating tools can cross a trust boundary.

## Decision

The planner identifies tool intent and high-risk requests early. The tool execution layer enforces tool policy again before callbacks run. Tools marked `requires_approval` create or reuse an approval record and return `approval_required` until an approved record exists.

This creates two independent controls:

1. Planner-level workflow interruption for high-risk requests.
2. Tool-level enforcement for high-risk tools such as MCP calls.

## Consequences

- Tool policy is the final authority for whether a callback can run.
- Approval records must include actor, tenant, run ID, action, and risk level.
- Audit records must show blocked, failed, and completed tool attempts.
- New tools must be registered with a risk level and approval behavior.

## Verification

```powershell
python -m pytest tests\test_agent_flow.py tests\test_mcp_integration.py
python scripts\run_eval_gate.py
```
