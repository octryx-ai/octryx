"""Who caused a run's pause: platform, agent, environment or person."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PLATFORM, AGENT, ENVIRONMENT, PERSON = "platform", "agent", "environment", "person"
RUNTIME_FAILED, ACTION_FAILED, LOOP_LIMIT = "runtime_failed", "action_failed", "loop_limit"
CHECKS_FAILED = "checks_failed"
RULE_UNMAPPED = "unmapped"


def _runtime_class(reason: str) -> bool:
    from .states import RUNTIME_FAILURE_REASONS

    return reason in RUNTIME_FAILURE_REASONS


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("pause_causes.json").read_text(encoding="utf-8"))


def causes() -> tuple[str, ...]:
    return tuple(_data()["causes"])


def _by_code(table: dict[str, str], prefixes: dict[str, str], code: str) -> tuple[str, str]:
    if code in table:
        return table[code], "codes"
    prefix = max((item for item in prefixes if code.startswith(item)), key=len, default="")
    return (prefixes[prefix], prefix) if prefix else ("", "")


def split_reason(reason: str, detail: dict[str, Any] | None = None) -> str:
    if reason != RUNTIME_FAILED:
        return reason
    split = _data()["runtime_failed_split"]
    found, _rule = _by_code(split["codes"], split["prefixes"], str(dict(detail or {}).get("code") or ""))
    return found or reason


def _uncertain_cause(data: dict[str, Any], reason: str, detail: dict[str, Any]) -> tuple[str, str] | None:
    key = str(detail.get("code") or "") if _runtime_class(reason) else reason
    rule = dict(data.get("reasons_with_uncertain_check") or {}).get(key)
    if not isinstance(rule, dict):
        return None
    control = next((str(item) for item in detail.get("uncertain_checks") or []
                    if any(str(item).startswith(prefix) for prefix in rule.get("controls") or [])), None)
    return (str(rule["cause"]), f"uncertain_check.{control}") if control else None


def cause_of(reason: str, detail: dict[str, Any] | None = None) -> tuple[str, str]:
    data, detail = _data(), dict(detail or {})
    unsure = _uncertain_cause(data, reason, detail)
    if unsure is not None:
        return unsure
    if _runtime_class(reason) and detail.get("code"):
        reason = RUNTIME_FAILED
        code = str(detail.get("code") or "")
        if code in data["runtime_failed_codes"]:
            return data["runtime_failed_codes"][code], f"runtime_failed_codes.{code}"
        prefix = max((item for item in data["runtime_failed_prefixes"] if code.startswith(item)), key=len,
                     default="")
        if prefix:
            return data["runtime_failed_prefixes"][prefix], f"runtime_failed_prefixes.{prefix}"
        return data["unmapped"], RULE_UNMAPPED
    from .failure_codes import entry as failure_entry

    if detail.get("code") and failure_entry(str(detail["code"])).get("cause") and not _runtime_class(reason):
        # A step's structured failure code (``failure_codes``) names who caused it, whatever the pause reason.
        return failure_entry(str(detail["code"]))["cause"], f"failure_codes.{detail['code']}"
    if reason in (LOOP_LIMIT, CHECKS_FAILED) and isinstance(detail.get("last_failure"), dict):
        from .failure_codes import cause_of_failure

        return cause_of_failure(detail["last_failure"])
    if reason == ACTION_FAILED:
        failure = str(detail.get("failure_class") or "")
        if failure in data["action_failed_classes"]:
            return data["action_failed_classes"][failure], f"action_failed_classes.{failure}"
        return data["action_failed_default"], "action_failed_default"
    if reason in data["reasons"]:
        return data["reasons"][reason], f"reasons.{reason}"
    return data["unmapped"], RULE_UNMAPPED


def metric_reason(reason: str, detail: dict[str, Any] | None = None) -> str:
    code = str(dict(detail or {}).get("code") or "")
    return f"{reason}:{code}"[:80] if reason == RUNTIME_FAILED and code else reason


__all__ = ["AGENT", "ENVIRONMENT", "PERSON", "PLATFORM", "RULE_UNMAPPED", "cause_of", "causes", "metric_reason",
           "split_reason"]
