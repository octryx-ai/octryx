"""Save-time checks of content obligations: the annotations a custom policy may carry."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.services.content_detection.custom_definitions import DetectorDefinitions

from ..content_detection.vocabulary import (
    BUILTIN_DETECTOR_IDS,
    CUSTOM_PREFIX,
    MASK_STYLES,
    builtin_detector,
)
from .schema import ACTION_CALL_MODEL, ACTION_RECEIVE_TOOL_RESULT

OBLIGATIONS = ("mask", "reroute", "mask_reroute")
ISSUE_OBLIGATION = "obligation_invalid"
ISSUE_MASK = "obligation_mask_invalid"
ISSUE_ROUTE = "obligation_reroute_invalid"
ISSUE_TARGET_UNKNOWN = "reroute_target_unknown"
ISSUE_TARGET_NOT_APPROVED = "reroute_target_not_approved"


def _issue(policy_id: str, code: str, message: str) -> dict[str, str]:
    return {"policy_id": policy_id, "code": code, "message": message}


def _actions(body: Mapping[str, Any]) -> list[str]:
    scope = body.get("action") or {}
    if scope.get("op") == "==":
        return [str((scope.get("entity") or {}).get("id") or "")]
    if scope.get("op") == "in":
        return [str(item.get("id") or "") for item in scope.get("entities") or []]
    return []


def _items(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def obligation_issues(policy_id: str, body: Mapping[str, Any]) -> list[dict[str, str]]:
    annotations = body.get("annotations") or {}
    kind = annotations.get("obligation")
    extra = {"mask", "mask_style", "reroute_to"} & set(annotations)
    if kind is None:
        return [_issue(policy_id, ISSUE_OBLIGATION, "@mask, @mask_style and @reroute_to need an @obligation.")] \
            if extra else []
    actions = _actions(body)
    issues: list[dict[str, str]] = []
    if kind not in OBLIGATIONS or actions not in ([ACTION_CALL_MODEL], [ACTION_RECEIVE_TOOL_RESULT]):
        issues.append(_issue(policy_id, ISSUE_OBLIGATION, "An obligation is mask, reroute or mask_reroute on a "
                             "policy for exactly one action: Call a model or Receive a tool result."))
        return issues
    if actions == [ACTION_RECEIVE_TOOL_RESULT] and kind != "mask":
        issues.append(_issue(policy_id, ISSUE_OBLIGATION, "Tool results can be masked or blocked, not routed."))
    if kind in ("mask", "mask_reroute"):
        detectors = _items(str(annotations.get("mask") or ""))
        # A detector the platform no longer has is ignored at run time, never an issue; at least
        # one detector it still has must remain.
        if not any(item in BUILTIN_DETECTOR_IDS or item.startswith(CUSTOM_PREFIX) for item in detectors):
            issues.append(_issue(policy_id, ISSUE_MASK, "@mask lists the detectors to mask (comma-separated)."))
    style = annotations.get("mask_style")
    if style is not None and style not in MASK_STYLES:
        issues.append(_issue(policy_id, ISSUE_MASK, "@mask_style is last4, type_token, country_last4 or full."))
    if kind in ("reroute", "mask_reroute") and not str(annotations.get("reroute_to") or "").strip():
        issues.append(_issue(policy_id, ISSUE_ROUTE, "@reroute_to names the approved model alias."))
    return issues


def _named_categories(statement_text: str, definitions: DetectorDefinitions) -> set[str]:
    literals = set(statement_text.split('"')[1::2])
    categories = {item.id for item in definitions.all_categories()}
    named = literals & categories
    for literal in literals:
        info = builtin_detector(literal)
        if info is not None:
            named.add(info.category)
    named |= {item.category for item in definitions.detectors if item.id in literals}
    return named


def check_obligation_targets(statements: Iterable[Any], definitions: DetectorDefinitions,
                             approvals: Mapping[str, frozenset[str]]) -> list[dict[str, str]]:
    custom = {item.id for item in definitions.detectors}
    issues: list[dict[str, str]] = []
    for statement in statements:
        annotations = statement.annotations
        if annotations.get("obligation") is None:
            continue
        unknown = [item for item in _items(str(annotations.get("mask") or ""))
                   if item.startswith(CUSTOM_PREFIX) and item not in custom]
        if unknown:
            issues.append(_issue(statement.policy_id, ISSUE_MASK, "Unknown custom detector: " + ", ".join(unknown)))
        target = str(annotations.get("reroute_to") or "").strip()
        if not target:
            continue
        if target not in approvals:
            issues.append(_issue(statement.policy_id, ISSUE_TARGET_UNKNOWN,
                                 "The route target is not an alias of an active model gateway."))
            continue
        missing = sorted(_named_categories(statement.text, definitions) - approvals[target])
        if missing:
            issues.append(_issue(statement.policy_id, ISSUE_TARGET_NOT_APPROVED,
                                 f"{target} is not approved for: {', '.join(missing)} (Model gateway aliases → "
                                 "Approved for sensitive data)."))
    return issues


__all__ = [
    "ISSUE_MASK",
    "ISSUE_OBLIGATION",
    "ISSUE_ROUTE",
    "ISSUE_TARGET_NOT_APPROVED",
    "ISSUE_TARGET_UNKNOWN",
    "check_obligation_targets",
    "obligation_issues",
]
