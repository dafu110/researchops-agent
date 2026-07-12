import subprocess

import pytest

from app.core.config import settings
from app.tools.sandbox import PythonSandbox


def test_process_sandbox_runs_basic_code() -> None:
    settings.sandbox_mode = "process"

    with pytest.raises(RuntimeError, match="Docker"):
        PythonSandbox().run("print(sum(range(5)))")


def test_sandbox_blocks_open() -> None:
    settings.sandbox_mode = "process"

    try:
        PythonSandbox().run("print(open('secret.txt').read())")
    except ValueError as exc:
        assert "Blocked name" in str(exc)
    else:
        raise AssertionError("Expected sandbox to block open().")


def test_process_sandbox_rejects_dunder_import_escape() -> None:
    settings.sandbox_mode = "process"

    with pytest.raises(RuntimeError, match="Docker"):
        PythonSandbox().run("print(print.__self__.__import__('os').getcwd())")


def test_docker_sandbox_uses_resource_limits(monkeypatch) -> None:
    settings.sandbox_mode = "docker"
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    output = PythonSandbox().run("print('ok')")

    assert output == "ok"
    command = captured["command"]
    assert "--network" in command and "none" in command
    assert "--memory" in command and settings.sandbox_memory in command
    assert "--cpus" in command and settings.sandbox_cpus in command
    settings.sandbox_mode = "process"
