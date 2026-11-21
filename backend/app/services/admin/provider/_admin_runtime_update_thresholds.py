"""Optional numeric runtime settings: stored as given, cleared when empty, applied in table order."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from ...system_config import (
    AGENT_ELASTIC_ITERATION_MAX_BONUS_KEY,
    AGENT_ELASTIC_ITERATION_UNIQUE_TOOL_THRESHOLD_KEY,
    AGENT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB_KEY,
    AGENT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT_KEY,
    AGENT_LLM_SECURITY_ANALYZER_DENY_THRESHOLD_KEY,
    AGENT_LLM_SECURITY_ANALYZER_REVIEW_THRESHOLD_KEY,
    AGENT_LLM_SECURITY_ANALYZER_TIMEOUT_SECONDS_KEY,
    AGENT_STUCK_LOOP_BLOCKED_TOOL_THRESHOLD_KEY,
    AGENT_STUCK_LOOP_NO_TOOL_DUPLICATE_THRESHOLD_KEY,
    AGENT_STUCK_LOOP_NO_TOOL_SIMILARITY_THRESHOLD_KEY,
    AGENT_STUCK_LOOP_REPEATED_JIRA_THRESHOLD_KEY,
    AGENT_STUCK_LOOP_SUMMARY_REPEAT_THRESHOLD_KEY,
    AGENT_STUCK_LOOP_TOOL_REPEAT_THRESHOLD_KEY,
    set_system_config_value,
)


class OptionalNumber(NamedTuple):
    field: str
    key: str
    description: str
    convert: Callable[[Any], Any] = int


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

ANALYZER_AND_STUCK_LOOP_SETTINGS = (
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
    OptionalNumber(
        "stuck_loop_tool_repeat_threshold",
        AGENT_STUCK_LOOP_TOOL_REPEAT_THRESHOLD_KEY,
        "Repeated same-tool calls before the dedicated stuck-loop detector fires.",
    ),
    OptionalNumber(
        "stuck_loop_blocked_tool_threshold",
        AGENT_STUCK_LOOP_BLOCKED_TOOL_THRESHOLD_KEY,
        "Blocked tool attempts before the dedicated stuck-loop detector fires.",
    ),
    OptionalNumber(
        "stuck_loop_repeated_jira_threshold",
        AGENT_STUCK_LOOP_REPEATED_JIRA_THRESHOLD_KEY,
        "Repeated Jira expansion attempts after repo evidence before detector escalation.",
    ),
    OptionalNumber(
        "stuck_loop_no_tool_duplicate_threshold",
        AGENT_STUCK_LOOP_NO_TOOL_DUPLICATE_THRESHOLD_KEY,
        "Duplicate no-tool assistant responses before the detector stops the run.",
    ),
    OptionalNumber(
        "stuck_loop_summary_repeat_threshold",
        AGENT_STUCK_LOOP_SUMMARY_REPEAT_THRESHOLD_KEY,
        "Repeated previous-step summaries before the detector intervenes.",
    ),
    OptionalNumber(
        "stuck_loop_no_tool_similarity_threshold",
        AGENT_STUCK_LOOP_NO_TOOL_SIMILARITY_THRESHOLD_KEY,
        "Similarity threshold for duplicate no-tool response detection.",
        convert=float,
    ),
)

ELASTIC_ITERATION_SETTINGS = (
    OptionalNumber(
        "elastic_iteration_max_bonus",
        AGENT_ELASTIC_ITERATION_MAX_BONUS_KEY,
        "Maximum bonus iterations granted by the elastic iteration service.",
    ),
    OptionalNumber(
        "elastic_iteration_unique_tool_threshold",
        AGENT_ELASTIC_ITERATION_UNIQUE_TOOL_THRESHOLD_KEY,
        "Minimum unique tool count before elastic iterations are granted.",
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
            value=str(setting.convert(raw_value)) if raw_value not in ("", None) else None,
            description=setting.description,
        )
