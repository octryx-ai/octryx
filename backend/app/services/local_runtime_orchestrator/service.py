"""Local runtime orchestration for the managed Ollama service."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...models import LLMProvider
from .command_facts import command_facts, command_failure_text
from .host_process import _probe_driver_endpoint, _process_is_running, _read_pid, _run_command, _start_host_process
from .runtime_config import (
    DEFAULT_START_TIMEOUT_SECONDS,
    DEFAULT_STOP_TIMEOUT_SECONDS,
    _compose_command,
    _default_endpoint_url,
    resolve_local_runtime_config,
)
from .startup_steps import _compose_up, _start_result, _wait_until_ready


async def _ensure_local_runtime_started_impl(
    *,
    driver: str,
    endpoint_url: str,
    provider: LLMProvider | None = None,
    config_json: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_START_TIMEOUT_SECONDS,
    resolve_local_runtime_config_func: Callable[..., dict[str, Any]] | None = None,
    probe_driver_endpoint_func: Callable[..., Any] | None = None,
    compose_command_func: Callable[..., list[str]] | None = None,
    run_command_func: Callable[..., Any] | None = None,
    start_host_process_func: Callable[..., Any] | None = None,
    sleep_func: Callable[[float], Any] | None = None,
) -> dict[str, Any]:
    # Resolve at call time so monkeypatched module attributes take effect.
    resolve_local_runtime_config_func = resolve_local_runtime_config_func or resolve_local_runtime_config
    probe_driver_endpoint_func = probe_driver_endpoint_func or _probe_driver_endpoint
    compose_command_func = compose_command_func or _compose_command
    run_command_func = run_command_func or _run_command
    start_host_process_func = start_host_process_func or _start_host_process
    sleep_func = sleep_func or asyncio.sleep
    endpoint_url = str(endpoint_url or "").strip() or _default_endpoint_url(driver)
    runtime = resolve_local_runtime_config_func(driver=driver, provider=provider, config_json=config_json)
    initial_probe = await probe_driver_endpoint_func(driver, endpoint_url)
    facts = {"driver": driver, "endpoint_url": endpoint_url, "runtime": runtime, "probe": initial_probe}
    if initial_probe["ok"]:
        return _start_result("ready", **facts)
    if not runtime["auto_start"]:
        return _start_result("unavailable", **facts, error=initial_probe["error"])
    if runtime["strategy"] != "docker_compose":
        return _start_result(
            "unsupported", **facts, error=f"Unsupported local runtime strategy '{runtime['strategy']}'"
        )
    run_result, failure = await _compose_up(
        driver=driver,
        endpoint_url=endpoint_url,
        runtime=runtime,
        initial_probe=initial_probe,
        timeout_seconds=timeout_seconds,
        compose_command_func=compose_command_func,
        run_command_func=run_command_func,
        start_host_process_func=start_host_process_func,
    )
    if failure is not None:
        return failure
    return await _wait_until_ready(
        driver=driver,
        endpoint_url=endpoint_url,
        runtime=runtime,
        initial_probe=initial_probe,
        run_result=run_result,
        timeout_seconds=timeout_seconds,
        probe_driver_endpoint_func=probe_driver_endpoint_func,
        sleep_func=sleep_func,
    )


async def ensure_local_runtime_started(
    *,
    driver: str,
    endpoint_url: str,
    provider: LLMProvider | None = None,
    config_json: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_START_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return await _ensure_local_runtime_started_impl(
        driver=driver,
        endpoint_url=endpoint_url,
        provider=provider,
        config_json=config_json,
        timeout_seconds=timeout_seconds,
    )


def _host_process_stopped(driver: str, runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "stopped",
        "driver": driver,
        "runtime": runtime,
        "command": {
            "ok": True,
            "action": "host_process_stop",
            "result_code": "command_succeeded",
            "exit_code": None,
        },
    }


async def _stop_local_runtime_impl(
    *,
    driver: str,
    provider: LLMProvider | None = None,
    config_json: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_STOP_TIMEOUT_SECONDS,
    resolve_local_runtime_config_func: Callable[..., dict[str, Any]] | None = None,
    read_pid_func: Callable[[str], int | None] | None = None,
    process_is_running_func: Callable[[int | None], bool] | None = None,
    kill_func: Callable[[int, int], Any] | None = None,
    compose_command_func: Callable[..., list[str]] | None = None,
    run_command_func: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    # Resolve at call time so monkeypatched module attributes take effect.
    resolve_local_runtime_config_func = resolve_local_runtime_config_func or resolve_local_runtime_config
    read_pid_func = read_pid_func or _read_pid
    process_is_running_func = process_is_running_func or _process_is_running
    kill_func = kill_func or os.kill
    compose_command_func = compose_command_func or _compose_command
    run_command_func = run_command_func or _run_command
    runtime = resolve_local_runtime_config_func(driver=driver, provider=provider, config_json=config_json)
    pid = read_pid_func(runtime["pid_file"])
    if process_is_running_func(pid):
        kill_func(pid, signal.SIGTERM)
        Path(runtime["pid_file"]).unlink(missing_ok=True)
        return _host_process_stopped(driver, runtime)
    if runtime["strategy"] != "docker_compose":
        return {
            "status": "unsupported",
            "driver": driver,
            "runtime": runtime,
            "error": f"Unsupported local runtime strategy '{runtime['strategy']}'",
        }
    command = compose_command_func(
        compose_file=runtime["compose_file"],
        compose_profile=runtime["compose_profile"],
        action="stop",
        compose_service=runtime["compose_service"],
    )
    run_result = await run_command_func(command, cwd=runtime["compose_cwd"], timeout_seconds=timeout_seconds)
    if not run_result["ok"]:
        return {
            "status": "failed",
            "driver": driver,
            "runtime": runtime,
            "command": command_facts(run_result, action="stop"),
            "error": command_failure_text(run_result, action="stop"),
        }
    return {
        "status": "stopped",
        "driver": driver,
        "runtime": runtime,
        "command": command_facts(run_result, action="stop"),
    }


async def stop_local_runtime(
    *,
    driver: str,
    provider: LLMProvider | None = None,
    config_json: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_STOP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return await _stop_local_runtime_impl(
        driver=driver,
        provider=provider,
        config_json=config_json,
        timeout_seconds=timeout_seconds,
    )


async def ensure_provider_local_runtime_ready(provider: LLMProvider) -> dict[str, Any]:
    driver = str(getattr(provider, "driver", "") or "").strip()
    if driver != "ollama":
        return {"status": "ignored", "driver": driver}
    endpoint_url = str(getattr(provider, "endpoint_url", "") or "").strip()
    return await ensure_local_runtime_started(
        driver=driver,
        endpoint_url=endpoint_url,
        provider=provider,
    )
