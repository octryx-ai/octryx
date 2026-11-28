"""Optional numeric runtime settings: stored as given, cleared when empty, applied in table order."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from ...system_config import (
    AGENT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB_KEY,
    AGENT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT_KEY,
    AGENT_LLM_SECURITY_ANALYZER_DENY_THRESHOLD_KEY,
    AGENT_LLM_SECURITY_ANALYZER_REVIEW_THRESHOLD_KEY,
    AGENT_LLM_SECURITY_ANALYZER_TIMEOUT_SECONDS_KEY,
    set_system_config_value,
)


class OptionalNumber(NamedTuple):
    field: str
    key: str
    description: str


DOCKER_LIMIT_SETTINGS = (
    OptionalNumber(
        "execution_runtime_docker_memory_mb",
        AGENT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB_KEY,
        "Memory limit in MB for Docker-backed execution.",
    ),
    OptionalNumber(
        "execution_runtime_docker_pids_limit",
        AGENT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT_KEY,
        "PID limit for Docker-backed execution.",
    ),
)

SECURITY_ANALYZER_SETTINGS = (
    OptionalNumber(
        "llm_security_analyzer_timeout_seconds",
        AGENT_LLM_SECURITY_ANALYZER_TIMEOUT_SECONDS_KEY,
        "Timeout in seconds for the LLM-backed runtime security analyzer.",
    ),
    OptionalNumber(
        "llm_security_analyzer_review_threshold",
        AGENT_LLM_SECURITY_ANALYZER_REVIEW_THRESHOLD_KEY,
        "Minimum LLM risk score that escalates a command to manual review.",
    ),
    OptionalNumber(
        "llm_security_analyzer_deny_threshold",
        AGENT_LLM_SECURITY_ANALYZER_DENY_THRESHOLD_KEY,
        "Minimum LLM risk score that blocks a command outright.",
    ),
)


async def apply_optional_numbers(
    db: AsyncSession, payload: dict[str, Any], settings: Sequence[OptionalNumber]
) -> None:
    for setting in settings:
        if setting.field not in payload:
            continue
        raw_value = payload.get(setting.field)
        await set_system_config_value(
            db,
            key=setting.key,
            value=str(int(raw_value)) if raw_value not in ("", None) else None,
            description=setting.description,
        )
