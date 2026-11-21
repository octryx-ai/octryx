"""The audience a person approved is immutable for that publication."""
from __future__ import annotations

from typing import Any

FIELDS = ("semantics", "principal_user_id", "outsider_user_id", "source_key")


def audience_snapshot(config: dict[str, Any] | None, workspace_id: str | None) -> dict[str, str]:
    raw = dict(dict((config or {}).get("feature_documentation") or {}).get("audience_proof") or {})
    return {"workspace_id": str(workspace_id or ""),
            **{key: str(raw.get(key) or "").strip() for key in FIELDS}}


def audience_binding_problem(payload: dict[str, Any], config: dict[str, Any] | None,
                             workspace_id: str | None) -> str:
    approved = dict(payload.get("audience") or {})
    expected = audience_snapshot(config, workspace_id)
    if any(not expected[key] for key in (*FIELDS, "workspace_id")):
        return "the publication audience is not completely configured"
    if any(approved.get(key) != expected[key] for key in expected):
        return "the publication audience changed; confirm its new audience before publishing or proving it"
    return ""
