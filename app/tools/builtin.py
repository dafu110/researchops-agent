import ast
import json
import operator
import re
from dataclasses import dataclass

from app.core.audit import audit_service
from app.core.traces import trace_store
from app.rag.store import knowledge_store
from app.tools.mcp import mcp_registry
from app.tools.permissions import policy_for_tool
from app.tools.reports import report_writer
from app.tools.sandbox import python_sandbox
from app.tools.sql import sql_tool


@dataclass
class ToolResult:
    name: str
    output: str


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
    def __init__(self) -> None:
        self.calculator = SafeCalculator()

    def run(
        self,
        question: str,
        run_id: str | None = None,
        actor_id: str = "local-dev",
        tenant_id: str = "default",
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        lowered = question.lower()

        expression = self._extract_expression(question)
        if expression:
            results.append(
                self._safe_tool(
                    "calculator",
                    lambda: f"{expression} = {self.calculator.evaluate(expression):g}",
                    run_id,
                    actor_id,
                    tenant_id,
                )
            )

        if any(
            term in lowered
            for term in (
                "knowledge",
                "documents",
                "chunks",
                "corpus",
                "\u77e5\u8bc6\u5e93",
                "\u6587\u6863\u6570\u91cf",
            )
        ):
            document_count = len(knowledge_store.list_documents())
            chunk_count = knowledge_store.count_chunks()
            results.append(
                ToolResult(
                    name="knowledge_stats",
                    output=f"documents={document_count}, chunks={chunk_count}",
                )
            )
            self._audit("knowledge_stats", "completed", f"documents={document_count}", run_id, actor_id, tenant_id)

        if any(term in lowered for term in ("eval", "run_count", "trace", "\u8bc4\u4f30")):
            results.append(
                ToolResult(
                    name="eval_summary",
                    output=f"runs={trace_store.run_count()}, chunks={knowledge_store.count_chunks()}",
                )
            )
            self._audit("eval_summary", "completed", "local eval summary", run_id, actor_id, tenant_id)

        sql = self._extract_sql(question)
        if sql:
            results.append(self._safe_tool("read_only_sql", lambda: sql_tool.query(sql), run_id, actor_id, tenant_id))

        code = self._extract_code(question)
        if code:
            results.append(self._safe_tool("python_sandbox", lambda: python_sandbox.run(code), run_id, actor_id, tenant_id))

        if "mcp" in lowered:
            results.append(ToolResult(name="mcp_registry", output=mcp_registry.describe()))
            self._audit("mcp_registry", "completed", "listed MCP servers", run_id, actor_id, tenant_id)
            mcp_call = self._extract_mcp_call(question)
            if mcp_call:
                server_name, tool_name, arguments = mcp_call
                results.append(
                    self._safe_tool(
                        "mcp_call",
                        lambda: mcp_registry.call_tool(server_name, tool_name, arguments),
                        run_id,
                        actor_id,
                        tenant_id,
                    )
                )

        if any(term in lowered for term in ("report", "markdown", "\u62a5\u544a")):
            results.append(
                self._safe_tool(
                    "report_writer",
                    lambda: f"created {report_writer.write_markdown('ResearchOps Agent Report', question)}",
                    run_id,
                    actor_id,
                    tenant_id,
                )
            )

        return results

    def _extract_expression(self, question: str) -> str | None:
        match = re.search(r"([-+*/().%\d\s]*\d[-+*/().%\d\s]*)", question)
        if not match:
            return None
        expression = match.group(1).strip()
        if not expression or not re.search(r"\d", expression):
            return None
        return expression

    def _extract_sql(self, question: str) -> str | None:
        match = re.search(r"(select\s+.+)", question, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        sql = match.group(1).strip()
        sql = re.split(r"\s+(?:and|then)\s+", sql, maxsplit=1, flags=re.IGNORECASE)[0]
        sql = sql.split(";")[0].strip()
        return sql.rstrip(",")

    def _extract_code(self, question: str) -> str | None:
        match = re.search(r"```python\s*(.*?)```", question, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else None

    def _extract_mcp_call(self, question: str) -> tuple[str, str, dict] | None:
        match = re.search(
            r"mcp\s+call\s+([\w.-]+)\s+([\w.-]+)\s*(\{.*\})?",
            question,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None
        raw_args = match.group(3) or "{}"
        try:
            arguments = json.loads(raw_args)
        except Exception:
            arguments = {}
        return match.group(1), match.group(2), arguments

    def _safe_tool(
        self,
        name: str,
        callback,
        run_id: str | None = None,
        actor_id: str = "local-dev",
        tenant_id: str = "default",
    ) -> ToolResult:
        try:
            output = callback()
            self._audit(name, "completed", str(output), run_id, actor_id, tenant_id)
            return ToolResult(name=name, output=output)
        except Exception as exc:
            self._audit(name, "failed", str(exc), run_id, actor_id, tenant_id)
            return ToolResult(name=name, output=f"failed: {exc}")

    def _audit(
        self,
        name: str,
        status: str,
        detail: str,
        run_id: str | None,
        actor_id: str,
        tenant_id: str,
    ) -> None:
        policy = policy_for_tool(name)
        audit_service.record(
            action="tool_call",
            target=name,
            risk_level=policy.risk_level,
            status=status,
            detail=detail,
            run_id=run_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
        )


builtin_tools = BuiltinTools()
