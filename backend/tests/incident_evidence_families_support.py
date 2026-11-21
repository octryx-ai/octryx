"""Shared helpers for the incident evidence family tests (test_incident_evidence_families*)."""

from __future__ import annotations

from app.services.workflow_checks.library import ToolUse

WINDOW = {"start": "2026-10-15T09:30:00Z", "end": None}


SCOPE = {"target_id": "checkout", "namespace": "shop", "required_families": ["kubernetes", "metrics"],
         "window": WINDOW}


IN_WINDOW = {"start": "2026-10-15T09:30:00Z", "end": "2026-10-15T10:05:00Z"}


def _use(name: str, result, *, succeeded: bool | None = None, call_id: str = "c1") -> ToolUse:
    ok = succeeded if succeeded is not None else not (isinstance(result, dict) and result.get("error"))
    return ToolUse(name=name, succeeded=ok, result=result, call_id=call_id)


def _check(**params) -> dict:
    return {"type": "evidence_families", "params": params, "blocking": True, "description": "families"}
