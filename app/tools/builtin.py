import ast
import hashlib
import json
import operator
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from time import perf_counter

from app.api.schemas import ApprovalRequest, ToolCallInput
from app.approvals.service import approval_service
from app.core.config import settings
from app.core.audit import audit_service
from app.core.traces import trace_store
from app.rag.store import knowledge_store
from app.tools.mcp import mcp_registry
from app.tools.permissions import ToolPolicy, policy_for_tool
from app.tools.reports import report_writer
from app.tools.sandbox import python_sandbox
from app.tools.sql import sql_tool


@dataclass
class ToolResult:
    name: str
    output: str
    status: str = "completed"
    tool_call_id: str | None = None
    requires_approval: bool = False
    approval_id: str | None = None


class ToolExecutionError(RuntimeError):
    pass


class ToolTimeoutError(TimeoutError):
    pass


class SafeCalculator:
    operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def evaluate(self, expression: str) -> float:
        node = ast.parse(expression, mode="eval")
        return float(self._eval(node.body))

    def _eval(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in self.operators:
            return self.operators[type(node.op)](self._eval(node.left), self._eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in self.operators:
            return self.operators[type(node.op)](self._eval(node.operand))
        raise ValueError("Only numeric arithmetic expressions are allowed.")


class BuiltinTools:
    """Least-privilege tool adapter with a durable call lifecycle per invocation."""

    def __init__(self) -> None:
        self.calculator = SafeCalculator()

    def run(self, question: str, run_id: str | None = None, actor_id: str = "local-dev", tenant_id: str = "default") -> list[ToolResult]:
        results: list[ToolResult] = []
        lowered = question.lower()

        expression = self._extract_expression(question)
        if expression and len(results) < settings.agent_max_tool_calls:
            results.append(self._safe_tool("calculator", {"expression": expression}, lambda: f"{expression} = {self.calculator.evaluate(expression):g}", run_id, actor_id, tenant_id))

        if len(results) < settings.agent_max_tool_calls and any(term in lowered for term in ("knowledge", "documents", "chunks", "corpus", "知识库", "文档数量")):
            results.append(self._safe_tool("knowledge_stats", {}, lambda: self._knowledge_stats(tenant_id), run_id, actor_id, tenant_id))

        if len(results) < settings.agent_max_tool_calls and any(term in lowered for term in ("eval", "run_count", "trace", "评估")):
            results.append(self._safe_tool("eval_summary", {}, lambda: f"runs={trace_store.run_count(tenant_id)}, chunks={knowledge_store.count_chunks(tenant_id=tenant_id)}", run_id, actor_id, tenant_id))

        sql = self._extract_sql(question)
        if sql and len(results) < settings.agent_max_tool_calls:
            results.append(self._safe_tool("read_only_sql", {"query": sql}, lambda: sql_tool.query(sql), run_id, actor_id, tenant_id))

        code = self._extract_code(question)
        if code and len(results) < settings.agent_max_tool_calls:
            results.append(self._safe_tool("python_sandbox", {"code": code}, lambda: python_sandbox.run(code), run_id, actor_id, tenant_id))

        if "mcp" in lowered and len(results) < settings.agent_max_tool_calls:
            results.append(self._safe_tool("mcp_registry", {}, mcp_registry.describe, run_id, actor_id, tenant_id))
            mcp_call = self._extract_mcp_call(question)
            if mcp_call and len(results) < settings.agent_max_tool_calls:
                server_name, tool_name, arguments = mcp_call
                results.append(self._safe_tool("mcp_call", {"server": server_name, "tool": tool_name, "arguments": arguments}, lambda: mcp_registry.call_tool(server_name, tool_name, arguments), run_id, actor_id, tenant_id))

        if len(results) < settings.agent_max_tool_calls and any(term in lowered for term in ("report", "markdown", "报告")):
            results.append(self._safe_tool("report_writer", {"title": "ResearchOps Agent Report"}, lambda: f"created {report_writer.write_markdown('ResearchOps Agent Report', question)}", run_id, actor_id, tenant_id))

        return results

    def _safe_tool(self, name: str, arguments: dict, callback, run_id: str | None, actor_id: str, tenant_id: str) -> ToolResult:
        policy = policy_for_tool(name)
        call_input = ToolCallInput(tool_name=name, arguments=arguments)
        idempotency_key = self._idempotency_key(run_id, call_input)
        if run_id:
            existing = trace_store.find_completed_tool_call(run_id, idempotency_key)
            if existing:
                cached = (existing.output or {}).get("text", "")
                return ToolResult(name=name, output=str(cached), status="completed", tool_call_id=existing.tool_call_id)

        tool_call = trace_store.create_tool_call(
            run_id=run_id or "untracked-tool-run",
            tool=call_input,
            risk_level=policy.risk_level,
            timeout_ms=policy.timeout_seconds * 1000,
            max_attempts=policy.max_attempts,
            idempotency_key=idempotency_key,
            cancellable=policy.cancellable,
            recovery_action=f"POST /api/runs/{run_id}/recover" if run_id else None,
        )

        if self._is_canceled(run_id):
            return self._finish_canceled(name, tool_call.tool_call_id, run_id, actor_id, tenant_id)

        if policy.requires_approval:
            approval = self._ensure_tool_approval(name, policy.risk_level, run_id, actor_id, tenant_id)
            if approval.status != "approved":
                detail = f"approval_required: {approval.approval_id}"
                trace_store.update_tool_call(tool_call.tool_call_id, status="blocked", output={"approval_id": approval.approval_id}, error=detail)
                self._audit(name, "blocked", detail, run_id, actor_id, tenant_id)
                return ToolResult(name=name, output=f"approval_required: {name} requires admin approval ({approval.approval_id})", status="blocked", tool_call_id=tool_call.tool_call_id, requires_approval=True, approval_id=approval.approval_id)

        final_error = ""
        for attempt in range(1, policy.max_attempts + 1):
            if self._is_canceled(run_id):
                return self._finish_canceled(name, tool_call.tool_call_id, run_id, actor_id, tenant_id)
            trace_store.update_tool_call(tool_call.tool_call_id, status="running", attempt=attempt, error="", output={})
            started = perf_counter()
            try:
                output = self._run_with_timeout(callback, policy)
                if str(output).startswith("failed:"):
                    raise ToolExecutionError(str(output))
                latency_ms = int((perf_counter() - started) * 1000)
                if self._is_canceled(run_id):
                    return self._finish_canceled(name, tool_call.tool_call_id, run_id, actor_id, tenant_id, latency_ms)
                trace_store.update_tool_call(tool_call.tool_call_id, status="completed", output={"text": str(output)}, latency_ms=latency_ms)
                self._audit(name, "completed", f"tool_call_id={tool_call.tool_call_id}; attempt={attempt}; {str(output)[:300]}", run_id, actor_id, tenant_id)
                return ToolResult(name=name, output=str(output), status="completed", tool_call_id=tool_call.tool_call_id)
            except Exception as exc:
                final_error = str(exc)
                status = "timeout" if isinstance(exc, (ToolTimeoutError, TimeoutError)) or "timed out" in final_error.lower() else "failed"
                latency_ms = int((perf_counter() - started) * 1000)
                retryable = policy.idempotent and attempt < policy.max_attempts and status != "timeout"
                trace_store.update_tool_call(tool_call.tool_call_id, status="retrying" if retryable else status, error=final_error[:500], latency_ms=latency_ms)
                self._audit(name, "retrying" if retryable else status, f"tool_call_id={tool_call.tool_call_id}; attempt={attempt}; {final_error[:300]}", run_id, actor_id, tenant_id)
                if not retryable:
                    return ToolResult(name=name, output=f"{status}: {final_error}", status=status, tool_call_id=tool_call.tool_call_id)

        return ToolResult(name=name, output=f"failed: {final_error}", status="failed", tool_call_id=tool_call.tool_call_id)

    @staticmethod
    def _run_with_timeout(callback, policy: ToolPolicy):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="researchops-tool")
        future = executor.submit(callback)
        try:
            return future.result(timeout=policy.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise ToolTimeoutError(f"{policy.name} exceeded {policy.timeout_seconds}s timeout") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _finish_canceled(self, name: str, tool_call_id: str, run_id: str | None, actor_id: str, tenant_id: str, latency_ms: int | None = None) -> ToolResult:
        detail = "Cancellation requested; the tool did not start a new attempt."
        trace_store.update_tool_call(tool_call_id, status="canceled", error=detail, latency_ms=latency_ms)
        self._audit(name, "canceled", f"tool_call_id={tool_call_id}; {detail}", run_id, actor_id, tenant_id)
        return ToolResult(name=name, output="canceled: tool execution stopped at a safe checkpoint", status="canceled", tool_call_id=tool_call_id)

    @staticmethod
    def _idempotency_key(run_id: str | None, tool: ToolCallInput) -> str:
        payload = json.dumps({"run_id": run_id or "untracked", "tool": tool.tool_name, "arguments": tool.arguments}, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_canceled(run_id: str | None) -> bool:
        return bool(run_id and trace_store.is_cancel_requested(run_id))

    @staticmethod
    def _knowledge_stats(tenant_id: str) -> str:
        return f"documents={len(knowledge_store.list_documents(tenant_id))}, chunks={knowledge_store.count_chunks(tenant_id=tenant_id)}"

    @staticmethod
    def _extract_expression(question: str) -> str | None:
        match = re.search(r"([-+*/().%\d\s]*\d[-+*/().%\d\s]*)", question)
        if not match:
            return None
        expression = match.group(1).strip()
        return expression if expression and re.search(r"\d", expression) else None

    @staticmethod
    def _extract_sql(question: str) -> str | None:
        match = re.search(r"(select\s+.+)", question, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        sql = re.split(r"\s+(?:and|then)\s+", match.group(1).strip(), maxsplit=1, flags=re.IGNORECASE)[0]
        return sql.split(";")[0].strip().rstrip(",")

    @staticmethod
    def _extract_code(question: str) -> str | None:
        match = re.search(r"```python\s*(.*?)```", question, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_mcp_call(question: str) -> tuple[str, str, dict] | None:
        match = re.search(r"mcp\s+call\s+([\w.-]+)\s+([\w.-]+)\s*(\{.*\})?", question, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        try:
            arguments = json.loads(match.group(3) or "{}")
        except Exception:
            arguments = {}
        return match.group(1), match.group(2), arguments

    def _ensure_tool_approval(self, name: str, risk_level: str, run_id: str | None, actor_id: str, tenant_id: str):
        approval_run_id = run_id or "untracked-tool-run"
        action = f"tool:{name}"
        existing = approval_service.find_for_run_action(approval_run_id, action, tenant_id=tenant_id, statuses={"pending", "approved"})
        if existing:
            return existing
        return approval_service.create(ApprovalRequest(run_id=approval_run_id, action=action, reason=f"Tool policy requires approval before executing {name}.", risk_level=risk_level, tenant_id=tenant_id, requester_id=actor_id))

    @staticmethod
    def _audit(name: str, status: str, detail: str, run_id: str | None, actor_id: str, tenant_id: str) -> None:
        policy = policy_for_tool(name)
        audit_service.record(action="tool_call", target=name, risk_level=policy.risk_level, status=status, detail=detail, run_id=run_id, actor_id=actor_id, tenant_id=tenant_id)


builtin_tools = BuiltinTools()
