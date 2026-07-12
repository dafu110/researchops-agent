import ast
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from app.core.config import settings


class PythonSandbox:
    blocked_nodes = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)
    blocked_names = {"open", "exec", "eval", "__import__", "compile", "input"}

    def run(self, code: str) -> str:
        tree = ast.parse(code, mode="exec")
        for node in ast.walk(tree):
            if isinstance(node, self.blocked_nodes):
                raise ValueError("Imports and global state are disabled.")
            if isinstance(node, ast.Name) and node.id in self.blocked_names:
                raise ValueError(f"Blocked name: {node.id}")

        wrapper = self._wrap_code(code)
        if settings.sandbox_mode != "docker":
            raise RuntimeError("Docker sandbox mode is required for user-provided Python code.")
        return self._run_docker(wrapper)

    def _run_process(self, wrapper: str) -> str:
        with tempfile.TemporaryDirectory(prefix="researchops-sandbox-") as tmp:
            script_path = Path(tmp) / "sandboxed.py"
            script_path.write_text(wrapper, encoding="utf-8")
            process = subprocess.run(
                [sys.executable, "-I", "-S", str(script_path)],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=settings.sandbox_timeout_seconds,
                check=False,
                env={"PYTHONIOENCODING": "utf-8"},
            )
        if process.returncode != 0:
            return f"failed: {process.stderr.strip()[: settings.sandbox_max_output_chars]}"
        output = process.stdout.strip() or "completed"
        return output[: settings.sandbox_max_output_chars]

    def _run_docker(self, wrapper: str) -> str:
        with tempfile.TemporaryDirectory(prefix="researchops-sandbox-") as tmp:
            script_path = Path(tmp) / "sandboxed.py"
            script_path.write_text(wrapper, encoding="utf-8")
            command = [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--memory",
                settings.sandbox_memory,
                "--cpus",
                settings.sandbox_cpus,
                "--pids-limit",
                "64",
                "--read-only",
                "-v",
                f"{Path(tmp).resolve()}:/work:ro",
                "-w",
                "/work",
                settings.sandbox_docker_image,
                "python",
                "-I",
                "-S",
                "sandboxed.py",
            ]
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=settings.sandbox_timeout_seconds + 2,
                check=False,
            )
        if process.returncode != 0:
            rendered = " ".join(shlex.quote(part) for part in command[:10])
            return f"failed: {rendered}: {process.stderr.strip()[: settings.sandbox_max_output_chars]}"
        output = process.stdout.strip() or "completed"
        return output[: settings.sandbox_max_output_chars]

    def _wrap_code(self, code: str) -> str:
        return (
            "allowed_builtins = {"
            "'abs': abs, 'min': min, 'max': max, 'sum': sum, 'len': len, "
            "'range': range, 'round': round, 'print': print"
            "}\n"
            "__builtins__ = allowed_builtins\n"
            f"{code}\n"
        )


python_sandbox = PythonSandbox()
