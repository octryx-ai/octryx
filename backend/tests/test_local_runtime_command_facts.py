"""Contract: the local runtime orchestrator returns closed codes and exit status, never compose output (X6)."""

from __future__ import annotations

import json

import pytest

from app.services.local_runtime_orchestrator import ensure_local_runtime_started, stop_local_runtime
from app.services.local_runtime_orchestrator.host_process import _run_command_impl

FAKE_TOKEN = "ghp_X6" + "fakeTokenAbcdefghijklmnopqrstuvwxyz0123"
CREDENTIALED_URL = "https://user:tok3n@host/x.git"
INTERNAL_PATH = "/srv/internal/x6-secret-path"
COMPOSE_OUTPUT = f"pull {CREDENTIALED_URL} denied for {FAKE_TOKEN} reading {INTERNAL_PATH}"
SERVICE = "app.services.local_runtime_orchestrator.service"


def _assert_clean(value: object) -> None:
    serialized = json.dumps(value, default=str)
    for marker in (FAKE_TOKEN, "tok3n", CREDENTIALED_URL, INTERNAL_PATH):
        assert marker not in serialized


class _FakeProcess:
    returncode = 17

    async def communicate(self):
        return COMPOSE_OUTPUT.encode(), COMPOSE_OUTPUT.encode()


@pytest.mark.asyncio
async def test_compose_output_never_leaves_the_command_runner():
    async def fake_exec(*args, **kwargs):
        return _FakeProcess()

    result = await _run_command_impl(
        ["docker", "compose", "up"], cwd=".", timeout_seconds=5, create_subprocess_exec=fake_exec
    )

    assert result == {"ok": False, "command": ["docker", "compose", "up"], "returncode": 17}
    _assert_clean(result)


@pytest.mark.asyncio
async def test_start_and_stop_failures_return_closed_codes_even_when_a_runner_leaks_output(monkeypatch):
    async def fake_probe(driver, endpoint_url, *, timeout_seconds=10.0):
        return {"ok": False, "status": "error", "model_ids": [], "error": "local_runtime_probe_failed"}

    async def leaky_run_command(args, *, cwd, timeout_seconds):
        return {"ok": False, "command": args, "stdout": COMPOSE_OUTPUT, "stderr": COMPOSE_OUTPUT, "returncode": 17}

    async def failing_host_start(*, driver, endpoint_url, runtime):
        return {"ok": False, "error_code": "local_binary_not_found", "error": COMPOSE_OUTPUT}

    monkeypatch.setattr(f"{SERVICE}._probe_driver_endpoint", fake_probe)
    monkeypatch.setattr(f"{SERVICE}._run_command", leaky_run_command)
    monkeypatch.setattr(f"{SERVICE}._start_host_process", failing_host_start)

    started = await ensure_local_runtime_started(driver="ollama", endpoint_url="http://localhost:11434")
    fallback = await ensure_local_runtime_started(
        driver="ollama",
        endpoint_url="http://localhost:11434",
        config_json={"local_runtime_allow_host_fallback": True},
    )
    stopped = await stop_local_runtime(driver="ollama")

    assert started["error"] == "docker_compose_up_failed exit_code=17"
    assert started["command"] == {"ok": False, "action": "up", "result_code": "command_failed", "exit_code": 17}
    assert fallback["error"] == (
        "local_runtime_start_failed docker_compose_up_failed exit_code=17 host_error=local_binary_not_found"
    )
    assert stopped["error"] == "docker_compose_stop_failed exit_code=17"
    for result in (started, fallback, stopped):
        # ``runtime`` echoes the admin's own configuration, not command output.
        _assert_clean({key: value for key, value in result.items() if key != "runtime"})
