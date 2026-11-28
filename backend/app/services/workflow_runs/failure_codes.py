"""Structured failure codes of platform steps: codes, never message texts."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CONTEXT_KEY = "last_failure"
NODE_DETERMINISTIC_KEY = "deterministic_failures"


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("failure_codes.json").read_text(encoding="utf-8"))


def entry(code: str) -> dict[str, Any]:
    return dict(_data()["codes"].get(str(code or "")) or {})


def deterministic(code: str, node_config: dict[str, Any] | None = None) -> bool:
    extra = {str(item) for item in dict(node_config or {}).get(NODE_DETERMINISTIC_KEY) or []}
    return bool(code) and (entry(code).get("deterministic") is True or code in extra)


def cause_of_failure(failure: dict[str, Any] | None) -> tuple[str, str]:
    code = str(dict(failure or {}).get("code") or "")
    if entry(code).get("cause"):
        return entry(code)["cause"], f"failure_codes.{code}"
    return _data()["unmapped_cause"], "failure_codes.unmapped"


def record(run: Any, node_id: str, *, code: str, reason: str) -> None:
    failures = dict(dict(run.context or {}).get(CONTEXT_KEY) or {})
    failures[node_id] = {"code": code, "reason": reason[:600]}
    run.context = {**dict(run.context or {}), CONTEXT_KEY: failures}


def last(run: Any, node_id: str) -> dict[str, Any] | None:
    found = dict(dict(getattr(run, "context", None) or {}).get(CONTEXT_KEY) or {}).get(node_id)
    return dict(found) if isinstance(found, dict) else None


__all__ = ["CONTEXT_KEY", "cause_of_failure", "deterministic", "entry", "last", "record"]
