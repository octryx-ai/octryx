"""The steps of starting the local runtime: compose up (or the host fallback), then waiting until it answers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from .command_facts import (
    command_facts,
    command_failure_text,
    host_fallback_failure_text,
)


def _start_result(
    status: str,
    *,
    driver: str,
    endpoint_url: str,
    runtime: dict[str, Any],
    probe: dict[str, Any],
    started: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "status": status,
        "started": started,
        "driver": driver,
        "endpoint_url": endpoint_url,
        "runtime": runtime,
        "probe": probe,
        **extra,
    }


async def _compose_up(
    *,
    driver: str,
    endpoint_url: str,
    runtime: dict[str, Any],
    initial_probe: dict[str, Any],
    timeout_seconds: float,
    compose_command_func: Callable[..., list[str]],
    run_command_func: Callable[..., Any],
    start_host_process_func: Callable[..., Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Start the runtime with compose (or the host fallback); returns the run result and a failure, if any."""
    command = compose_command_func(
        compose_file=runtime["compose_file"],
        compose_profile=runtime["compose_profile"],
        action="up",
        compose_service=runtime["compose_service"],
    )
    run_result = await run_command_func(command, cwd=runtime["compose_cwd"], timeout_seconds=min(timeout_seconds, 60.0))
    facts = {"driver": driver, "endpoint_url": endpoint_url, "runtime": runtime, "probe": initial_probe}
    if not run_result["ok"] and runtime["allow_host_fallback"]:
        host_result = await start_host_process_func(driver=driver, endpoint_url=endpoint_url, runtime=runtime)
        if host_result["ok"]:
            run_result = {"ok": True, "returncode": 0, "host_fallback": True}
        else:
            return run_result, _start_result(
                "failed",
                **facts,
                command=command_facts(run_result, action="up"),
                error=host_fallback_failure_text(run_result, host_result),
            )
    elif not run_result["ok"]:
        return run_result, _start_result(
            "failed",
            **facts,
            command=command_facts(run_result, action="up"),
            error=command_failure_text(run_result, action="up"),
        )
    return run_result, None


async def _wait_until_ready(
    *,
    driver: str,
    endpoint_url: str,
    runtime: dict[str, Any],
    initial_probe: dict[str, Any],
    run_result: dict[str, Any],
    timeout_seconds: float,
    probe_driver_endpoint_func: Callable[..., Any],
    sleep_func: Callable[[float], Any],
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    latest_probe = initial_probe
    while asyncio.get_running_loop().time() < deadline:
        await sleep_func(2.0)
        latest_probe = await probe_driver_endpoint_func(driver, endpoint_url)
        if latest_probe["ok"]:
            return _start_result(
                "ready",
                driver=driver,
                endpoint_url=endpoint_url,
                runtime=runtime,
                probe=latest_probe,
                started=True,
                command=command_facts(run_result, action="up"),
            )
    return _start_result(
        "timeout",
        driver=driver,
        endpoint_url=endpoint_url,
        runtime=runtime,
        probe=latest_probe,
        command=command_facts(run_result, action="up"),
        error=latest_probe["error"] or f"{driver} did not become ready in time",
    )
