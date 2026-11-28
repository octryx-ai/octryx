"""What to do about each failed check, said in the Stop's answer."""

from __future__ import annotations

from typing import Any

PREFIX = "remedy."
STOP_TYPES = ("code_style", "declared_tests", "system_tests", "questions_asked", "item_result")


def remedy_types() -> tuple[str, ...]:
    from ...workflow_checks.library import CHECK_TYPES

    return (*CHECK_TYPES, *STOP_TYPES)


def _command(contract: dict[str, Any]) -> str:
    from ..run_texts import run_text

    pinned = dict(dict(contract.get("environment_pin") or {}).get("environment") or {})
    prepared = dict(dict(contract.get("preparation") or {}).get("environment") or {})
    found = str(pinned.get("test") or prepared.get("test") or "").strip()
    return found or run_text("remedy.no_command")


def _tools(params: dict[str, Any]) -> str:
    names = params.get("tools")
    names = [str(name) for name in names] if isinstance(names, list) else [str(names)] if names else []
    return ", ".join(names) or "the tool the check names"


def line(result: Any, checks: list[Any], contract: dict[str, Any]) -> str:
    from ..run_texts import run_text

    what = str(getattr(result, "description", "") or getattr(result, "type", ""))
    kind = str(getattr(result, "type", ""))
    if kind not in remedy_types():
        return what
    params = next((dict(check.get("params") or {}) for check in checks if isinstance(check, dict)
                   and check.get("type") == kind and str(check.get("description") or kind) == what), {})
    if not params:
        params = next((dict(check.get("params") or {}) for check in checks if isinstance(check, dict)
                       and check.get("type") == kind), {})
    how = run_text(f"{PREFIX}{kind}", command=_command(contract), tools=_tools(params))
    return f"{what}: {how}" if how else what


def missing(results: list[Any], checks: list[Any], contract: dict[str, Any]) -> str:
    return "; ".join(line(result, checks, contract) for result in results)


__all__ = ["PREFIX", "STOP_TYPES", "line", "missing", "remedy_types"]
