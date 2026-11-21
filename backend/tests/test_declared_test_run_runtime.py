"""Declared tests honour the configured runtime: a refusal or an unavailable runtime spawns nothing and pauses the run, and a host selection runs the venv with runtime metadata."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.services.workflow_checks.test_command_outcome import ENVIRONMENT, reclassify
from app.tools.registry import TOOL_REGISTRY
from tests.declared_test_run_support import (  # noqa: F401
    NEW_TEST,
    SILENT,
    _checks_turn,
    _phase,
    _server_pipeline,
    _stale_report,
)

# --- through the platform's execution runtime, never a direct host spawn -----------------------------------------


def _spawn_counter(monkeypatch) -> dict[str, int]:
    """Counts the lowest host spawns (exec and shell): a refused runtime must reach neither."""
    import asyncio

    calls = {"host": 0}

    async def host(*_args, **_kwargs):
        calls["host"] += 1

        async def communicate(*_a):
            return b"", b""

        return SimpleNamespace(communicate=communicate, returncode=0, kill=lambda: None, pid=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", host)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", host)
    return calls


@pytest.mark.asyncio
async def test_declared_tests_honor_runtime_refusal_before_host_execution(db, tmp_path, monkeypatch):
    # The runtime is asked, the host is never spawned.
    from app.services import code_quality_service, execution_runtime

    _run, context, _root = await _phase(db, tmp_path, interpreter=SILENT)
    context.project_config = {**context.project_config, "execution_runtime_provider": "docker",
                              "execution_runtime_allow_host_fallback": False}
    calls = {"runtime": 0}

    async def refusal(**_kwargs):
        calls["runtime"] += 1
        return SimpleNamespace(exit_code=None, stdout="", stderr="runtime refused", timed_out=False,
                               metadata={"provider": "docker", "refused": True})

    monkeypatch.setattr(execution_runtime, "execute_with_runtime", refusal)
    monkeypatch.setattr(code_quality_service, "execute_with_runtime", refusal)
    spawns = _spawn_counter(monkeypatch)
    result = await TOOL_REGISTRY["run_test_suite"].execute({}, context)
    assert spawns["host"] == 0 and calls["runtime"] == 1, (calls, spawns, result)


@pytest.mark.asyncio
async def test_an_unavailable_runtime_without_fallback_spawns_nothing_and_pauses_the_run(db, tmp_path, monkeypatch):
    from app.exceptions.base import ExecutionRuntimeUnavailableError
    from app.services.execution_runtime import service as runtime_service

    run, context, root = await _phase(db, tmp_path, interpreter=sys.executable)
    stale = _stale_report(root)
    context.project_config = {**context.project_config, "execution_runtime_provider": "docker",
                              "execution_runtime_allow_host_fallback": False}

    async def docker_unavailable(**_kwargs):
        raise ExecutionRuntimeUnavailableError("docker is not reachable")

    monkeypatch.setattr(runtime_service, "_run_docker_command_impl", docker_unavailable)
    spawns = _spawn_counter(monkeypatch)

    result = await TOOL_REGISTRY["run_test_suite"].execute({}, context)

    assert spawns["host"] == 0  # the real boundary refused: no host fallback, no spawn
    assert result["execution_runtime"]["provider"] == "docker" and result["execution_runtime"]["host_fallback"] is False
    assert result["test_report"] == {"fresh": False} and not stale.exists()
    _uses, failure = reclassify([SimpleNamespace(name="run_test_suite", succeeded=True, result=result, params={})],
                                [])
    assert failure is not None and failure["kind"] == ENVIRONMENT
    assert "execution runtime did not start the declared test command (docker)" in failure["reason"] + str(
        result["stderr"])
    await _checks_turn(db, context, [{"tool_name": "run_test_suite", "status": "success", "result": result}])
    assert (run.status, run.pause_reason) == ("paused", "environment_not_ready")
    assert not dict(run.context.get("tests") or {}).get("runs")


@pytest.mark.asyncio
async def test_when_the_configured_runtime_selects_the_host_the_venv_runs_with_runtime_metadata(db, tmp_path):
    _run, context, working_copy = await _phase(db, tmp_path, interpreter=sys.executable)
    context.project_config = {**context.project_config, "execution_runtime_provider": "host"}

    result = await TOOL_REGISTRY["run_test_suite"].execute({}, context)

    runtime = result["execution_runtime"]
    assert runtime["requested_provider"] == "host" and runtime["host_fallback"] is False
    assert runtime["cwd"] == str(working_copy) and runtime["shell_mode"] is True
    started_as, path, _venv_dir = (working_copy / ".venv" / "invocations.log").read_text().splitlines()[0].split("|")
    assert started_as == str(working_copy / ".venv" / "bin" / "python")
    assert path.split(":")[0] == str(working_copy / ".venv" / "bin")
    assert result["test_report"]["fresh"] is True and NEW_TEST in result["failed_tests"]
