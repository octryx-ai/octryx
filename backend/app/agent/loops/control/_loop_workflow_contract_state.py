"""Helpers for preserving workflow contracts across resumed turns."""

from __future__ import annotations

from typing import Any

from ....services.secure_work.coding.verification_contract import (
    is_governed_coding_contract,
)

WORKFLOW_CONTRACT_METADATA_KEY = "workflow_contract"
EXPECTED_WORKFLOW_ID_METADATA_KEY = "expected_workflow_id"
_TRANSIENT_WORKFLOW_KEYS = frozenset({"subthread_context_pending", "sub_agents_already_spawned"})


def _normalize_workflow_contract(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _looks_like_sub_agent_resume_prompt(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if "get_context_from_subthreads" not in normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "consolidate the child findings",
            "consolidate the child sessions",
            "consolidate the findings",
            "subthread",
        )
    )


def _workflow_contract_identity_matches(lhs: dict[str, Any], rhs: dict[str, Any]) -> bool:
    left_workflow_id = str(lhs.get("workflow_id") or "").strip()
    right_workflow_id = str(rhs.get("workflow_id") or "").strip()
    if not left_workflow_id or left_workflow_id != right_workflow_id:
        return False

    comparable_keys = ("source_user_message", "topic", "artifact_path", "document_plan_path", "presentation_plan_path")
    for key in comparable_keys:
        left_value = str(lhs.get(key) or "").strip()
        right_value = str(rhs.get(key) or "").strip()
        if left_value and right_value and left_value != right_value:
            return False
    return True


def resolve_workflow_contract_for_turn(
    *,
    current_turn_content: str,
    built_workflow_contract: dict[str, Any] | None,
    session_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    built_contract = _normalize_workflow_contract(built_workflow_contract)
    metadata = dict(session_metadata or {})
    if metadata.get("allow_workflow_contracts") is False:
        return {}
    persisted_contract = _normalize_workflow_contract(metadata.get(WORKFLOW_CONTRACT_METADATA_KEY))
    # A governed coding contract is the session's mandate: follow-up operator
    # turns (deliver, retry, clarify) must run under it regardless of how the
    # router classified the new turn text.
    if is_governed_coding_contract(persisted_contract):
        return dict(persisted_contract)
    current_group_id = str(metadata.get("current_sub_agent_group_id") or "").strip()

    if current_group_id and persisted_contract:
        resumed_contract = dict(persisted_contract)
        resumed_contract["sub_agents_already_spawned"] = True
        resumed_contract["sub_agent_delegation_attempted"] = True
        if _looks_like_sub_agent_resume_prompt(current_turn_content):
            resumed_contract["subthread_context_pending"] = True
        return resumed_contract

    if (
        persisted_contract
        and built_contract
        and _workflow_contract_identity_matches(persisted_contract, built_contract)
    ):
        resumed_contract = dict(persisted_contract)
        resumed_contract.update(built_contract)
        return resumed_contract

    return built_contract


def _persistable_workflow_contract(workflow_contract: dict[str, Any] | None) -> dict[str, Any]:
    normalized_contract = _normalize_workflow_contract(workflow_contract)
    for key in _TRANSIENT_WORKFLOW_KEYS:
        normalized_contract.pop(key, None)
    return normalized_contract


def persist_workflow_contract_in_session(
    *,
    current_session: Any,
    workflow_contract: dict[str, Any] | None,
) -> None:
    normalized_contract = _persistable_workflow_contract(workflow_contract)
    if current_session is None or not normalized_contract:
        return
    metadata = dict(getattr(current_session, "metadata_", None) or {})
    if metadata.get(WORKFLOW_CONTRACT_METADATA_KEY) == normalized_contract:
        return
    metadata[WORKFLOW_CONTRACT_METADATA_KEY] = normalized_contract
    current_session.metadata_ = metadata


__all__ = [
    "EXPECTED_WORKFLOW_ID_METADATA_KEY",
    "WORKFLOW_CONTRACT_METADATA_KEY",
    "persist_workflow_contract_in_session",
    "resolve_workflow_contract_for_turn",
]
