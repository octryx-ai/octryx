"""Probing the runtime endpoint, running compose commands and starting the runtime as a host process."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ..error_facts import error_text
from .command_facts import HOST_BINARY_NOT_FOUND, HOST_START_NOT_CONFIGURED
from .runtime_config import LOCAL_RUNTIME_DATA_DIR


async def _probe_driver_endpoint_impl(
    driver: str,
    endpoint_url: str,
    *,
    timeout_seconds: float = 10.0,
    async_client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    # Resolve at call time so a monkeypatched httpx.AsyncClient takes effect.
    async_client_factory = async_client_factory or httpx.AsyncClient
    normalized = str(endpoint_url or "").strip().rstrip("/")
    if not normalized:
        return {"ok": False, "status": "error", "error": "endpoint_url is required"}
    root_url = normalized[:-3] if normalized.endswith("/v1") else normalized
    try:
        async with async_client_factory(base_url=root_url, timeout=timeout_seconds) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            payload = response.json()
            model_ids = [
                str(item.get("name") or item.get("model") or "").strip()
                for item in payload.get("models", []) or []
                if isinstance(item, dict) and str(item.get("name") or item.get("model") or "").strip()
            ]
            return {"ok": True, "status": "ok", "model_ids": model_ids, "error": ""}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        failure = error_text("local_runtime_probe_failed", exc)
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            failure = f"{failure} http_status={int(exc.response.status_code)}"
        return {"ok": False, "status": "error", "model_ids": [], "error": failure}


async def _probe_driver_endpoint(driver: str, endpoint_url: str, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    return await _probe_driver_endpoint_impl(driver, endpoint_url, timeout_seconds=timeout_seconds)


async def _run_command_impl(
    args: list[str],
    *,
    cwd: str,
    timeout_seconds: float,
    create_subprocess_exec: Callable[..., Any] = asyncio.create_subprocess_exec,
) -> dict[str, Any]:
    """Run a compose command; its output is discarded, only the exit status is kept."""
    process = await create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return {"ok": False, "command": args, "returncode": None, "timed_out": True}
    return {"ok": process.returncode == 0, "command": args, "returncode": process.returncode}


async def _run_command(args: list[str], *, cwd: str, timeout_seconds: float) -> dict[str, Any]:
    return await _run_command_impl(args, cwd=cwd, timeout_seconds=timeout_seconds)


def _read_pid(pid_file: str) -> int | None:
    try:
        return int(Path(pid_file).read_text("utf-8").strip())
    except (OSError, ValueError):
        return None


def _process_is_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _resolve_runtime_binary_impl(
    driver: str,
    runtime: dict[str, Any],
    *,
    which_func: Callable[[str], str | None] = shutil.which,
) -> str:
    configured = str(runtime.get("binary_path") or "").strip()
    if configured:
        return configured
    if driver == "ollama":
        resolved = which_func("ollama")
        if resolved:
            return resolved
    return ""


def _resolve_runtime_binary(driver: str, runtime: dict[str, Any]) -> str:
    return _resolve_runtime_binary_impl(driver, runtime)


async def _start_host_process_impl(
    *,
    driver: str,
    endpoint_url: str,
    runtime: dict[str, Any],
    resolve_runtime_binary_func: Callable[[str, dict[str, Any]], str] = _resolve_runtime_binary,
    read_pid_func: Callable[[str], int | None] = _read_pid,
    process_is_running_func: Callable[[int | None], bool] = _process_is_running,
    create_subprocess_exec: Callable[..., Any] = asyncio.create_subprocess_exec,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    binary = resolve_runtime_binary_func(driver, runtime)
    if not binary:
        return {"ok": False, "error_code": HOST_BINARY_NOT_FOUND}
    LOCAL_RUNTIME_DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_path = Path(runtime["log_file"])
    pid_path = Path(runtime["pid_file"])
    existing_pid = read_pid_func(str(pid_path))
    if process_is_running_func(existing_pid):
        return {"ok": True, "binary": binary, "pid": existing_pid, "reused": True}
    if driver == "ollama":
        args = [binary, "serve"]
        env = dict(environ or os.environ)
        root_url = endpoint_url[:-3] if endpoint_url.endswith("/v1") else endpoint_url
        env["OLLAMA_HOST"] = root_url.replace("http://", "").replace("https://", "")
    else:
        return {"ok": False, "error_code": HOST_START_NOT_CONFIGURED}
    log_handle = open(log_path, "ab")
    process = await create_subprocess_exec(
        *args,
        stdout=log_handle,
        stderr=log_handle,
        start_new_session=True,
        env=env,
    )
    log_handle.close()
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return {"ok": True, "binary": binary, "pid": process.pid, "reused": False}


async def _start_host_process(
    *,
    driver: str,
    endpoint_url: str,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    return await _start_host_process_impl(driver=driver, endpoint_url=endpoint_url, runtime=runtime)
