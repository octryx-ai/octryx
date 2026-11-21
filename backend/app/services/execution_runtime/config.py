"""Execution runtime configuration: system settings plus project overrides, normalized and bounded."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..system_config import get_agent_runtime_settings

DEFAULT_EXECUTION_RUNTIME_PROVIDER = "host"
DEFAULT_EXECUTION_RUNTIME_DOCKER_IMAGE = "python:3.11-slim"
DEFAULT_EXECUTION_RUNTIME_NETWORK_MODE = "none"
DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE = "compat"
DEFAULT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB = 512
DEFAULT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT = 256
ALLOWED_EXECUTION_RUNTIME_PROVIDERS = {"host", "docker"}
ALLOWED_EXECUTION_RUNTIME_NETWORK_MODES = {"none", "bridge", "host"}
ALLOWED_EXECUTION_RUNTIME_SANDBOX_MODES = {"compat", "hard"}

RuntimeSettingsLoader = Callable[[AsyncSession], Awaitable[Mapping[str, Any]]]


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_provider(raw_value: Any) -> str:
    value = str(raw_value or DEFAULT_EXECUTION_RUNTIME_PROVIDER).strip().lower()
    return value if value in ALLOWED_EXECUTION_RUNTIME_PROVIDERS else DEFAULT_EXECUTION_RUNTIME_PROVIDER


def _normalize_network_mode(raw_value: Any) -> str:
    value = str(raw_value or DEFAULT_EXECUTION_RUNTIME_NETWORK_MODE).strip().lower()
    return value if value in ALLOWED_EXECUTION_RUNTIME_NETWORK_MODES else DEFAULT_EXECUTION_RUNTIME_NETWORK_MODE


def _normalize_sandbox_mode(raw_value: Any) -> str:
    value = str(raw_value or DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE).strip().lower()
    return value if value in ALLOWED_EXECUTION_RUNTIME_SANDBOX_MODES else DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE


def _bounded_int(raw_value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(raw_value).strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


@dataclass(frozen=True)
class ExecutionRuntimeConfig:
    provider: str = DEFAULT_EXECUTION_RUNTIME_PROVIDER
    docker_image: str = DEFAULT_EXECUTION_RUNTIME_DOCKER_IMAGE
    docker_network_mode: str = DEFAULT_EXECUTION_RUNTIME_NETWORK_MODE
    allow_host_fallback: bool = False
    sandbox_mode: str = DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE
    docker_memory_mb: int = DEFAULT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB
    docker_pids_limit: int = DEFAULT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT


def _docker_limits(project_config: Mapping[str, Any], runtime_settings: Mapping[str, Any]) -> tuple[int, int]:
    """The container's memory (MB) and process limit, project value first, each bounded."""
    docker_memory_mb = _bounded_int(
        project_config.get("execution_runtime_docker_memory_mb")
        or runtime_settings.get("execution_runtime_docker_memory_mb"),
        default=DEFAULT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB,
        minimum=128,
        maximum=8192,
    )
    docker_pids_limit = _bounded_int(
        project_config.get("execution_runtime_docker_pids_limit")
        or runtime_settings.get("execution_runtime_docker_pids_limit"),
        default=DEFAULT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT,
        minimum=32,
        maximum=4096,
    )
    return docker_memory_mb, docker_pids_limit


async def _resolve_execution_runtime_config_impl(
    db: AsyncSession | None,
    *,
    project_config: Mapping[str, Any] | None = None,
    runtime_settings_loader: RuntimeSettingsLoader = get_agent_runtime_settings,
) -> ExecutionRuntimeConfig:
    runtime_settings = await runtime_settings_loader(db) if db is not None else {}
    project_config = project_config or {}
    provider = _normalize_provider(
        project_config.get("execution_runtime_provider")
        or runtime_settings.get("execution_runtime_provider")
        or DEFAULT_EXECUTION_RUNTIME_PROVIDER
    )
    docker_image = (
        str(
            project_config.get("execution_runtime_docker_image")
            or runtime_settings.get("execution_runtime_docker_image")
            or DEFAULT_EXECUTION_RUNTIME_DOCKER_IMAGE
        ).strip()
        or DEFAULT_EXECUTION_RUNTIME_DOCKER_IMAGE
    )
    docker_network_mode = _normalize_network_mode(
        project_config.get("execution_runtime_docker_network_mode")
        or project_config.get("execution_runtime_network_mode")
        or runtime_settings.get("execution_runtime_docker_network_mode")
        or DEFAULT_EXECUTION_RUNTIME_NETWORK_MODE
    )
    allow_host_fallback = _as_bool(
        project_config.get("execution_runtime_allow_host_fallback"),
        _as_bool(runtime_settings.get("execution_runtime_allow_host_fallback"), False),
    )
    sandbox_mode = _normalize_sandbox_mode(
        project_config.get("execution_runtime_sandbox_mode")
        or runtime_settings.get("execution_runtime_sandbox_mode")
        or DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE
    )
    docker_memory_mb, docker_pids_limit = _docker_limits(project_config, runtime_settings)
    if sandbox_mode == "hard":
        allow_host_fallback = False
    return ExecutionRuntimeConfig(
        provider=provider,
        docker_image=docker_image,
        docker_network_mode=docker_network_mode,
        allow_host_fallback=allow_host_fallback,
        sandbox_mode=sandbox_mode,
        docker_memory_mb=docker_memory_mb,
        docker_pids_limit=docker_pids_limit,
    )


async def resolve_execution_runtime_config(
    db: AsyncSession | None,
    *,
    project_config: Mapping[str, Any] | None = None,
) -> ExecutionRuntimeConfig:
    return await _resolve_execution_runtime_config_impl(db, project_config=project_config)
