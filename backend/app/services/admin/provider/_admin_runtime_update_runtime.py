"""Execution-runtime and safety update handlers for admin runtime settings."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...security_analyzer import normalize_security_analyzer_chain
from ...system_config import (
    AGENT_EXECUTION_RUNTIME_ALLOW_HOST_FALLBACK_KEY,
    AGENT_EXECUTION_RUNTIME_DOCKER_IMAGE_KEY,
    AGENT_EXECUTION_RUNTIME_DOCKER_NETWORK_MODE_KEY,
    AGENT_EXECUTION_RUNTIME_PROVIDER_KEY,
    AGENT_EXECUTION_RUNTIME_SANDBOX_MODE_KEY,
    AGENT_SECURITY_ANALYZER_CHAIN_KEY,
    set_system_config_value,
)
from ._admin_runtime_update_thresholds import (
    DOCKER_LIMIT_SETTINGS,
    SECURITY_ANALYZER_SETTINGS,
    apply_optional_numbers,
)
from ._admin_runtime_update_workspace import apply_office_settings, apply_session_workspace_settings

_HOST_FALLBACK_DESCRIPTION = (
    "Explicit opt-in to allow docker-backed execution to fall back "
    "to host execution when docker is unavailable."
)
_HARD_SANDBOX_HOST_NETWORK_REFUSAL = (
    "execution_runtime_docker_network_mode=host is not allowed when execution_runtime_sandbox_mode=hard"
)


async def apply_execution_and_safety_settings(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    runtime_settings: dict[str, Any],
) -> None:
    effective_sandbox_mode = (
        str(
            payload.get("execution_runtime_sandbox_mode")
            or runtime_settings["execution_runtime_sandbox_mode"]
            or "compat"
        )
        .strip()
        .lower()
    )
    effective_network_mode = (
        str(
            payload.get("execution_runtime_docker_network_mode")
            or runtime_settings["execution_runtime_docker_network_mode"]
            or "none"
        )
        .strip()
        .lower()
    )
    await _apply_provider_and_image(db, payload)
    await _apply_docker_network_mode(db, payload, effective_sandbox_mode=effective_sandbox_mode)
    await _apply_host_fallback(db, payload, effective_sandbox_mode=effective_sandbox_mode)
    await _apply_sandbox_mode(db, payload, effective_network_mode=effective_network_mode)
    await apply_optional_numbers(db, payload, DOCKER_LIMIT_SETTINGS)
    await apply_session_workspace_settings(db, payload)
    await apply_office_settings(db, payload)
    await apply_optional_numbers(db, payload, SECURITY_ANALYZER_SETTINGS)
    if "security_analyzer_chain" in payload:
        normalized_chain = normalize_security_analyzer_chain(payload.get("security_analyzer_chain"))
        await set_system_config_value(
            db,
            key=AGENT_SECURITY_ANALYZER_CHAIN_KEY,
            value=json.dumps(normalized_chain),
            description="Ordered analyzer chain for runtime command security decisions.",
        )


async def _apply_provider_and_image(db: AsyncSession, payload: dict[str, Any]) -> None:
    if "execution_runtime_provider" in payload:
        value = str(payload.get("execution_runtime_provider") or "").strip().lower()
        if value not in {"host", "docker"}:
            raise HTTPException(status_code=400, detail="execution_runtime_provider must be one of: host, docker")
        await set_system_config_value(
            db,
            key=AGENT_EXECUTION_RUNTIME_PROVIDER_KEY,
            value=value,
            description="Execution runtime provider for bash, CLI, kubectl, and saved script execution.",
        )
    if "execution_runtime_docker_image" in payload:
        await set_system_config_value(
            db,
            key=AGENT_EXECUTION_RUNTIME_DOCKER_IMAGE_KEY,
            value=str(payload.get("execution_runtime_docker_image") or "").strip() or None,
            description="Docker image used by the execution runtime when provider=docker.",
        )


async def _apply_docker_network_mode(
    db: AsyncSession, payload: dict[str, Any], *, effective_sandbox_mode: str
) -> None:
    if "execution_runtime_docker_network_mode" not in payload:
        return
    value = str(payload.get("execution_runtime_docker_network_mode") or "").strip().lower()
    if value not in {"none", "bridge", "host"}:
        raise HTTPException(
            status_code=400,
            detail="execution_runtime_docker_network_mode must be one of: none, bridge, host",
        )
    if effective_sandbox_mode == "hard" and value == "host":
        raise HTTPException(status_code=400, detail=_HARD_SANDBOX_HOST_NETWORK_REFUSAL)
    await set_system_config_value(
        db,
        key=AGENT_EXECUTION_RUNTIME_DOCKER_NETWORK_MODE_KEY,
        value=value,
        description="Network mode used for docker-backed command execution.",
    )


async def _apply_host_fallback(db: AsyncSession, payload: dict[str, Any], *, effective_sandbox_mode: str) -> None:
    if "execution_runtime_allow_host_fallback" not in payload:
        return
    if effective_sandbox_mode == "hard" and bool(payload.get("execution_runtime_allow_host_fallback")):
        raise HTTPException(
            status_code=400,
            detail="execution_runtime_allow_host_fallback must be false when execution_runtime_sandbox_mode=hard",
        )
    await set_system_config_value(
        db,
        key=AGENT_EXECUTION_RUNTIME_ALLOW_HOST_FALLBACK_KEY,
        value="true" if bool(payload.get("execution_runtime_allow_host_fallback")) else None,
        description=_HOST_FALLBACK_DESCRIPTION,
    )


async def _apply_sandbox_mode(db: AsyncSession, payload: dict[str, Any], *, effective_network_mode: str) -> None:
    if "execution_runtime_sandbox_mode" not in payload:
        return
    value = str(payload.get("execution_runtime_sandbox_mode") or "").strip().lower()
    if value not in {"compat", "hard"}:
        raise HTTPException(
            status_code=400,
            detail="execution_runtime_sandbox_mode must be one of: compat, hard",
        )
    if value == "hard" and effective_network_mode == "host":
        raise HTTPException(status_code=400, detail=_HARD_SANDBOX_HOST_NETWORK_REFUSAL)
    await set_system_config_value(
        db,
        key=AGENT_EXECUTION_RUNTIME_SANDBOX_MODE_KEY,
        value=value,
        description=(
            "Sandbox mode for Docker-backed execution. Hard mode applies "
            "stricter isolation and disables host fallback."
        ),
    )
    if value == "hard":
        # Hard mode never keeps a host fallback that was switched on earlier.
        await set_system_config_value(
            db,
            key=AGENT_EXECUTION_RUNTIME_ALLOW_HOST_FALLBACK_KEY,
            value=None,
            description=_HOST_FALLBACK_DESCRIPTION,
        )
