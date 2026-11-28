"""Bounded numeric runtime settings: one table row per setting, applied in table order."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....runtime_limits import (
    MAX_APPROX_CHARS_PER_TOKEN,
    MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MAX_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    MAX_TRACE_MAX_DICT_ITEMS,
    MAX_TRACE_MAX_LIST_ITEMS,
    MAX_TRACE_MAX_STRING,
    MIN_APPROX_CHARS_PER_TOKEN,
    MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MIN_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    MIN_TRACE_MAX_DICT_ITEMS,
    MIN_TRACE_MAX_LIST_ITEMS,
    MIN_TRACE_MAX_STRING,
)
from ...system_config import (
    AGENT_APPROX_CHARS_PER_TOKEN_KEY,
    AGENT_REQUEST_COST_LIMIT_USD_KEY,
    AGENT_RUNTIME_REQUEST_TIMEOUT_SECONDS_KEY,
    AGENT_SAVED_SCRIPT_MAX_OUTPUT_CHARS_KEY,
    AGENT_SESSION_COST_LIMIT_USD_KEY,
    AGENT_TRACE_MAX_DICT_ITEMS_KEY,
    AGENT_TRACE_MAX_LIST_ITEMS_KEY,
    AGENT_TRACE_MAX_STRING_KEY,
    set_system_config_value,
)

# Raw values that clear the setting instead of storing it. Agent and trace limits also treat zero as "unset".
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


AGENT_LIMIT_SETTINGS = (
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

COST_LIMIT_SETTINGS = (
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
)


async def apply_bounded_setting(db: AsyncSession, payload: dict[str, Any], setting: BoundedSetting) -> None:
    if setting.field not in payload:
        return
    raw = payload.get(setting.field)
    if raw in setting.cleared_by:
        await set_system_config_value(db, key=setting.key, value=None)
        return
    value = setting.convert(raw)
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
