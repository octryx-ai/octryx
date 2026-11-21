from pathlib import Path

import httpx
import pytest

from app.services.local_runtime_orchestrator import (
    _probe_driver_endpoint,
    _read_pid,
    ensure_local_runtime_started,
    resolve_local_runtime_config,
    stop_local_runtime,
)


def test_resolve_local_runtime_config_defaults_for_ollama():
    config = resolve_local_runtime_config(driver="ollama")

    assert config["strategy"] == "docker_compose"
    assert config["compose_service"] == "ollama"
    assert config["compose_profile"] == ""
    assert config["auto_start"] is True
    assert config["allow_host_fallback"] is False


@pytest.mark.asyncio
async def test_ensure_local_runtime_started_starts_compose_when_probe_fails(monkeypatch):
    probes = iter(
        [
            {"ok": False, "status": "error", "model_ids": [], "error": "down"},
            {"ok": True, "status": "ok", "model_ids": ["gemma4:e4b"], "error": ""},
        ]
    )

    async def fake_probe(driver: str, endpoint_url: str, *, timeout_seconds: float = 10.0):
        return next(probes)

    async def fake_run_command(args: list[str], *, cwd: str, timeout_seconds: float):
        return {"ok": True, "command": args, "stdout": "started", "stderr": "", "returncode": 0}

    async def fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._probe_driver_endpoint", fake_probe)
    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._run_command", fake_run_command)
    monkeypatch.setattr("app.services.local_runtime_orchestrator.service.asyncio.sleep", fake_sleep)

    result = await ensure_local_runtime_started(driver="ollama", endpoint_url="http://localhost:11434")

    assert result["status"] == "ready"
    assert result["started"] is True
    assert result["runtime"]["compose_service"] == "ollama"


@pytest.mark.asyncio
async def test_stop_local_runtime_uses_compose_stop(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_run_command(args: list[str], *, cwd: str, timeout_seconds: float):
        captured["args"] = args
        captured["cwd"] = cwd
        return {"ok": True, "command": args, "stdout": "", "stderr": "", "returncode": 0}

    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._run_command", fake_run_command)

    result = await stop_local_runtime(driver="ollama")

    assert result["status"] == "stopped"
    assert captured["args"] == [
        "docker",
        "compose",
        "-f",
        result["runtime"]["compose_file"],
        "stop",
        "ollama",
    ]


@pytest.mark.asyncio
async def test_ensure_local_runtime_started_does_not_fall_back_to_host_process_by_default(monkeypatch):
    async def fake_probe(driver: str, endpoint_url: str, *, timeout_seconds: float = 10.0):
        return {"ok": False, "status": "error", "model_ids": [], "error": "down"}

    async def fake_run_command(args: list[str], *, cwd: str, timeout_seconds: float):
        return {"ok": False, "command": args, "stdout": "", "stderr": "docker unavailable", "returncode": 1}

    async def fake_start_host_process(*, driver: str, endpoint_url: str, runtime: dict[str, object]):
        raise AssertionError("host fallback must require explicit config")

    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._probe_driver_endpoint", fake_probe)
    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._run_command", fake_run_command)
    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._start_host_process", fake_start_host_process)

    result = await ensure_local_runtime_started(driver="ollama", endpoint_url="http://localhost:11434")

    assert result["status"] == "failed"
    assert result["runtime"]["allow_host_fallback"] is False
    assert result["error"] == "docker_compose_up_failed exit_code=1"


@pytest.mark.asyncio
async def test_ensure_local_runtime_started_falls_back_to_host_process_when_explicitly_allowed(monkeypatch):
    probes = iter(
        [
            {"ok": False, "status": "error", "model_ids": [], "error": "down"},
            {"ok": True, "status": "ok", "model_ids": ["gemma4:e4b"], "error": ""},
        ]
    )

    async def fake_probe(driver: str, endpoint_url: str, *, timeout_seconds: float = 10.0):
        return next(probes)

    async def fake_run_command(args: list[str], *, cwd: str, timeout_seconds: float):
        return {"ok": False, "command": args, "stdout": "", "stderr": "docker unavailable", "returncode": 1}

    async def fake_start_host_process(*, driver: str, endpoint_url: str, runtime: dict[str, object]):
        return {"ok": True, "binary": "/opt/homebrew/bin/ollama", "pid": 12345, "reused": False}

    async def fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._probe_driver_endpoint", fake_probe)
    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._run_command", fake_run_command)
    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._start_host_process", fake_start_host_process)
    monkeypatch.setattr("app.services.local_runtime_orchestrator.service.asyncio.sleep", fake_sleep)

    result = await ensure_local_runtime_started(
        driver="ollama",
        endpoint_url="http://localhost:11434",
        config_json={"local_runtime_allow_host_fallback": True},
    )

    assert result["status"] == "ready"
    assert result["started"] is True
    assert result["command"]["host_fallback"] is True


@pytest.mark.asyncio
async def test_ensure_local_runtime_started_treats_string_false_as_denied(monkeypatch):
    async def fake_probe(driver: str, endpoint_url: str, *, timeout_seconds: float = 10.0):
        return {"ok": False, "status": "error", "model_ids": [], "error": "down"}

    async def fake_run_command(args: list[str], *, cwd: str, timeout_seconds: float):
        return {"ok": False, "command": args, "stdout": "", "stderr": "docker unavailable", "returncode": 1}

    async def fake_start_host_process(*, driver: str, endpoint_url: str, runtime: dict[str, object]):
        raise AssertionError("string false must not enable host fallback")

    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._probe_driver_endpoint", fake_probe)
    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._run_command", fake_run_command)
    monkeypatch.setattr("app.services.local_runtime_orchestrator.service._start_host_process", fake_start_host_process)

    result = await ensure_local_runtime_started(
        driver="ollama",
        endpoint_url="http://localhost:11434",
        config_json={"local_runtime_allow_host_fallback": "false"},
    )

    assert result["status"] == "failed"
    assert result["runtime"]["allow_host_fallback"] is False


@pytest.mark.asyncio
async def test_probe_driver_endpoint_returns_error_payload_for_httpx_failure(monkeypatch):
    class _BrokenClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, path: str):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kwargs: _BrokenClient(),
    )

    result = await _probe_driver_endpoint("ollama", "http://localhost:11434")

    assert result["ok"] is False
    assert result["status"] == "error"
    assert result["error"] == "local_runtime_probe_failed error_type=ConnectError"


def test_read_pid_returns_none_for_invalid_pid_file(tmp_path):
    pid_path = Path(tmp_path) / "runtime.pid"
    pid_path.write_text("not-a-pid", encoding="utf-8")

    assert _read_pid(str(pid_path)) is None
