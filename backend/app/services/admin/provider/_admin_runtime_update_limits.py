"""Bounded numeric runtime settings: one table row per setting, applied in table order."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....runtime_limits import (
    MAX_APPROX_CHARS_PER_TOKEN,
    MAX_COMPLETION_TOKENS,
    MAX_LLM_CACHE_TTL_SECONDS,
    MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MAX_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    MAX_TRACE_MAX_DICT_ITEMS,
    MAX_TRACE_MAX_LIST_ITEMS,
    MAX_TRACE_MAX_STRING,
    MIN_APPROX_CHARS_PER_TOKEN,
    MIN_COMPLETION_TOKENS,
    MIN_LLM_CACHE_TTL_SECONDS,
    MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MIN_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    MIN_TRACE_MAX_DICT_ITEMS,
    MIN_TRACE_MAX_LIST_ITEMS,
    MIN_TRACE_MAX_STRING,
)
from ...system_config import (
    AGENT_APPROX_CHARS_PER_TOKEN_KEY,
    AGENT_DEFAULT_COMPLETION_TOKENS_KEY,
    AGENT_EXTENDED_COMPLETION_TOKENS_KEY,
    AGENT_LLM_CACHE_TOOLS_TTL_SECONDS_KEY,
    AGENT_LLM_CACHE_TTL_SECONDS_KEY,
    AGENT_LLM_TOOL_PLANNER_MAX_TOKENS_KEY,
    AGENT_LLM_TOOL_PLANNER_TIMEOUT_SECONDS_KEY,
    AGENT_REQUEST_COST_LIMIT_USD_KEY,
    AGENT_RUNTIME_REQUEST_TIMEOUT_SECONDS_KEY,
    AGENT_SAVED_SCRIPT_MAX_OUTPUT_CHARS_KEY,
    AGENT_SESSION_COST_LIMIT_USD_KEY,
    AGENT_TRACE_MAX_DICT_ITEMS_KEY,
    AGENT_TRACE_MAX_LIST_ITEMS_KEY,
    AGENT_TRACE_MAX_STRING_KEY,
    MIN_LLM_TOOL_PLANNER_MAX_TOKENS,
    MIN_LLM_TOOL_PLANNER_TIMEOUT_SECONDS,
    set_system_config_value,
)

# Raw values that clear the setting instead of storing it. Token and trace limits also treat zero as "unset".
CLEARED_BY_EMPTY_OR_ZERO = ("", 0, "0", None)
CLEARED_BY_EMPTY = ("", None)


class BoundedSetting(NamedTuple):
    field: str
    key: str
    low: Any
    high: Any
    description: str
    cleared_by: tuple[Any, ...] = CLEARED_BY_EMPTY_OR_ZERO
    convert: Callable[[Any], Any] = int
    # Planner settings answer a non-integer with a 400 instead of letting the conversion error escape.
    integer_refusal: bool = False


AGENT_LIMIT_SETTINGS = (
    BoundedSetting(
        "default_completion_tokens", AGENT_DEFAULT_COMPLETION_TOKENS_KEY, MIN_COMPLETION_TOKENS,
        MAX_COMPLETION_TOKENS, "Default max completion tokens for standard agent runs.",
    ),
    BoundedSetting(
        "extended_completion_tokens", AGENT_EXTENDED_COMPLETION_TOKENS_KEY, MIN_COMPLETION_TOKENS,
        MAX_COMPLETION_TOKENS, "Extended max completion tokens for change and deep-thinking runs.",
    ),
    BoundedSetting(
        "approx_chars_per_token", AGENT_APPROX_CHARS_PER_TOKEN_KEY, MIN_APPROX_CHARS_PER_TOKEN,
        MAX_APPROX_CHARS_PER_TOKEN, "Approximate char-per-token ratio used when trimming prompt history.",
    ),
    BoundedSetting(
        "trace_max_string", AGENT_TRACE_MAX_STRING_KEY, MIN_TRACE_MAX_STRING, MAX_TRACE_MAX_STRING,
        "Maximum string length preserved in turn traces.",
    ),
    BoundedSetting(
        "trace_max_list_items", AGENT_TRACE_MAX_LIST_ITEMS_KEY, MIN_TRACE_MAX_LIST_ITEMS, MAX_TRACE_MAX_LIST_ITEMS,
        "Maximum number of list items preserved in turn traces.",
    ),
    BoundedSetting(
        "trace_max_dict_items", AGENT_TRACE_MAX_DICT_ITEMS_KEY, MIN_TRACE_MAX_DICT_ITEMS, MAX_TRACE_MAX_DICT_ITEMS,
        "Maximum number of dict entries preserved in turn traces.",
    ),
    BoundedSetting(
        "saved_script_max_output_chars", AGENT_SAVED_SCRIPT_MAX_OUTPUT_CHARS_KEY, MIN_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
        MAX_SAVED_SCRIPT_MAX_OUTPUT_CHARS, "Maximum stdout/stderr characters retained for saved scripts.",
    ),
    BoundedSetting(
        "runtime_request_timeout_seconds", AGENT_RUNTIME_REQUEST_TIMEOUT_SECONDS_KEY,
        MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS, MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS,
        "Per-runtime-request timeout in seconds for model calls during agent turns.",
    ),
)

COST_AND_CACHE_SETTINGS = (
    BoundedSetting(
        "agent_session_cost_limit_usd", AGENT_SESSION_COST_LIMIT_USD_KEY, 0, 1_000_000,
        "Default per-session estimated agent cost limit in USD. Set to 0 to disable the default guard.",
        cleared_by=CLEARED_BY_EMPTY, convert=float,
    ),
    BoundedSetting(
        "agent_request_cost_limit_usd", AGENT_REQUEST_COST_LIMIT_USD_KEY, 0, 1_000_000,
        "Default per-request estimated agent cost limit in USD. Set to 0 to disable the default guard.",
        cleared_by=CLEARED_BY_EMPTY, convert=float,
    ),
    BoundedSetting(
        "llm_cache_ttl_seconds", AGENT_LLM_CACHE_TTL_SECONDS_KEY, MIN_LLM_CACHE_TTL_SECONDS,
        MAX_LLM_CACHE_TTL_SECONDS, "TTL in seconds for cacheable plain-language LLM responses without tool calls.",
        cleared_by=CLEARED_BY_EMPTY,
    ),
    BoundedSetting(
        "llm_cache_tools_ttl_seconds", AGENT_LLM_CACHE_TOOLS_TTL_SECONDS_KEY, MIN_LLM_CACHE_TTL_SECONDS,
        MAX_LLM_CACHE_TTL_SECONDS, "TTL in seconds for cacheable no-tool prompts that still include tool definitions.",
        cleared_by=CLEARED_BY_EMPTY,
    ),
)

PLANNER_SETTINGS = (
    BoundedSetting(
        "llm_tool_planner_max_tokens", AGENT_LLM_TOOL_PLANNER_MAX_TOKENS_KEY, MIN_LLM_TOOL_PLANNER_MAX_TOKENS,
        MAX_COMPLETION_TOKENS, "Maximum completion tokens for the trace-only LLM tool planner call.",
        cleared_by=CLEARED_BY_EMPTY, integer_refusal=True,
    ),
    BoundedSetting(
        "llm_tool_planner_timeout_seconds", AGENT_LLM_TOOL_PLANNER_TIMEOUT_SECONDS_KEY,
        MIN_LLM_TOOL_PLANNER_TIMEOUT_SECONDS, MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS,
        "Timeout in seconds for the trace-only LLM tool planner call.",
        cleared_by=CLEARED_BY_EMPTY, integer_refusal=True,
    ),
)


def _converted(setting: BoundedSetting, raw: Any) -> Any:
    if not setting.integer_refusal:
        return setting.convert(raw)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{setting.field} must be an integer") from exc


async def apply_bounded_setting(db: AsyncSession, payload: dict[str, Any], setting: BoundedSetting) -> None:
    if setting.field not in payload:
        return
    raw = payload.get(setting.field)
    if raw in setting.cleared_by:
        await set_system_config_value(db, key=setting.key, value=None)
        return
    value = _converted(setting, raw)
    if not (setting.low <= value <= setting.high):
        raise HTTPException(
            status_code=400,
            detail=f"{setting.field} must be between {setting.low} and {setting.high}",
        )
    await set_system_config_value(db, key=setting.key, value=str(value), description=setting.description)


async def apply_bounded_settings(
    db: AsyncSession, payload: dict[str, Any], settings: Sequence[BoundedSetting]
) -> None:
    for setting in settings:
        await apply_bounded_setting(db, payload, setting)
