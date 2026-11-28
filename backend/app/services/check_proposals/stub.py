"""Proposed checks from fixtures (``settings.check_proposals_stub``) until the real store exists."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...config import get_settings, is_production_like_runtime_profile
from ...time_utils import utc_now
from .rules import (
    STATE_APPROVED,
    STATE_REJECTED,
    CheckProposalRefusedError,
    approve_refusal,
    editable_refusal,
    instead_refusal,
    reason_refusal,
)

FIXTURES = Path(__file__).with_name("fixtures.json")
SETTINGS_DEFAULTS = {"threshold": 2, "approver_permission": "workspace_owner",
                     "sources": ["review_fixed", "review_change_request", "pr_comment", "pipeline_cause", "revert",
                                 "refused_call"]}
_STORE: dict[str, dict[str, dict[str, Any]]] = {}


def enabled() -> bool:
    settings = get_settings()
    if is_production_like_runtime_profile(settings.runtime_profile):
        return False
    return bool(settings.check_proposals_stub)


@lru_cache(maxsize=1)
def _fixtures() -> list[dict[str, Any]]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def _workspace(workspace_id: str) -> dict[str, dict[str, Any]]:
    if workspace_id not in _STORE:
        _STORE[workspace_id] = {row["id"]: {**copy.deepcopy(row), "workspace_id": workspace_id} for row in _fixtures()}
    return _STORE[workspace_id]


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "evidence": {key: value for key, value in row["evidence"].items() if key != "occurrences"}}


def list_proposals(workspace_id: str, states: set[str] | None = None) -> dict[str, Any]:
    rows = sorted(_workspace(workspace_id).values(), key=lambda row: row["updated_at"], reverse=True)
    counts = {state: sum(1 for row in rows if row["state"] == state) for state in ("proposed", "approved", "rejected")}
    shown = [row for row in rows if not states or row["state"] in states]
    return {"items": [_summary(row) for row in shown], "next_cursor": None, "counts": counts, "stub": True}


def get(workspace_id: str, proposal_id: str) -> dict[str, Any]:
    row = _workspace(workspace_id).get(proposal_id)
    if row is None:
        raise CheckProposalRefusedError("not_found", "No such proposed check in this Workspace.", 404)
    return row


def _stamp(row: dict[str, Any]) -> dict[str, Any]:
    row["updated_at"] = utc_now().isoformat()
    return row


def edit(workspace_id: str, proposal_id: str, *, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    row = get(workspace_id, proposal_id)
    if refusal := editable_refusal(row):
        raise refusal
    changed = []
    if isinstance(body.get("message"), dict):
        changes = {k: str(v) for k, v in body["message"].items() if k in ("what", "why", "instead")}
        message = {**row["message"], **changes}
        if refusal := instead_refusal(message):
            raise refusal
        row["message"], changed = message, [*changed, *[f"message.{k}" for k in body["message"]]]
    if isinstance(body.get("draft"), dict):
        row["draft"] = {**row["draft"], **{k: v for k, v in body["draft"].items() if k in ("summary", "rule")}}
        changed += [f"draft.{k}" for k in body["draft"]]
    if body.get("severity") in ("warning", "error"):
        row["severity"], changed = body["severity"], [*changed, "severity"]
    if changed:
        row["edits"].append({"by": user_id, "at": utc_now().isoformat(), "fields": sorted(set(changed))})
    return _stamp(row)


def approve(workspace_id: str, proposal_id: str, *, user_id: str, may_approve: bool,
            accept_unproven: bool = False, note: str = "") -> dict[str, Any]:
    row = get(workspace_id, proposal_id)
    if refusal := approve_refusal(row, user_id=user_id, may_approve=may_approve, accept_unproven=accept_unproven):
        raise refusal
    row["state"] = STATE_APPROVED
    row["decision"] = {"state": STATE_APPROVED, "by": user_id, "at": utc_now().isoformat(), "reason": note[:500],
                       "accept_unproven": bool(accept_unproven)}
    return _stamp(row)


def reject(workspace_id: str, proposal_id: str, *, user_id: str, may_approve: bool, reason: str) -> dict[str, Any]:
    row = get(workspace_id, proposal_id)
    if refusal := editable_refusal(row):
        raise refusal
    if not may_approve:
        raise CheckProposalRefusedError("approver_permission_missing",
                      "You may not decide on checks in this Workspace; instead ask the Workspace owner.", 403)
    if refusal := reason_refusal(reason):
        raise refusal
    row["state"] = STATE_REJECTED
    row["decision"] = {"state": STATE_REJECTED, "by": user_id, "at": utc_now().isoformat(), "reason": reason.strip()}
    return _stamp(row)


def set_enabled(workspace_id: str, proposal_id: str, *, may_approve: bool, value: bool, reason: str) -> dict[str, Any]:
    row = get(workspace_id, proposal_id)
    if row["state"] != STATE_APPROVED:
        raise CheckProposalRefusedError("not_approved", "Only an approved check is switched on or off.")
    if not may_approve:
        raise CheckProposalRefusedError("approver_permission_missing",
                                        "Ask the Workspace owner to switch this check.", 403)
    if refusal := reason_refusal(reason):
        raise refusal
    row["enabled"] = bool(value)
    row.setdefault("switches", []).append({"enabled": bool(value), "reason": reason.strip(),
                                           "at": utc_now().isoformat()})
    return _stamp(row)


def workspace_settings() -> dict[str, Any]:
    return {key: {"value": value, "source": "default"} for key, value in SETTINGS_DEFAULTS.items()}


def reset() -> None:
    _STORE.clear()


__all__ = ["SETTINGS_DEFAULTS", "approve", "edit", "enabled", "get", "list_proposals", "reject", "reset",
           "set_enabled", "workspace_settings"]
