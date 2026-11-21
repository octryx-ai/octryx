"""Planner prompt packet construction for trace-only tool planning."""

from __future__ import annotations

from typing import Any

from app.services.prompt_catalog import render_prompt

from .contract import CONTRACT_VERSION, PLAN_MODE, SUPPORTED_INTENTS

MAX_PROMPT_CATALOG_ENTRIES = 40
MAX_DESCRIPTION_CHARS = 180


def _safe_catalog_entries(session_tool_catalog: dict[str, Any] | None) -> list[dict[str, Any]]:
    catalog = session_tool_catalog if isinstance(session_tool_catalog, dict) else {}
    entries = catalog.get("entries") if isinstance(catalog.get("entries"), list) else []
    safe_entries: list[dict[str, Any]] = []
    for entry in entries[:MAX_PROMPT_CATALOG_ENTRIES]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        safe_entries.append(
            {
                "name": name,
                "category": str(entry.get("category") or "general"),
                "risk_level": str(entry.get("risk_level") or "unknown"),
                "read_only": bool(entry.get("read_only")),
                "approval_hint": bool(entry.get("approval_hint")),
                "description": str(entry.get("description") or "")[:MAX_DESCRIPTION_CHARS],
            }
        )
    return safe_entries


def _validation_rules() -> list[str]:
    """One rule per line of the catalog key ``judge.planner.validation_rules``."""
    return [line for line in render_prompt("judge.planner.validation_rules").split("\n") if line.strip()]


def _required_output_schema() -> dict[str, Any]:
    return {
        "version": CONTRACT_VERSION,
        "mode": PLAN_MODE,
        "intent_class": sorted(SUPPORTED_INTENTS),
        "confidence": "number between 0 and 1",
        "selected_tools": [
            {
                "tool": "name from allowed_tool_catalog",
                "reason": "short operational reason",
                "expected_evidence": ["evidence type expected from this tool"],
            }
        ],
        "stop_criteria": ["observable completion condition"],
        "max_tool_calls": "integer budget for this plan",
        "requires_clarification": "boolean",
    }


def build_tool_plan_prompt_packet(
    *,
    current_turn_content: str,
    request_analysis: dict[str, Any] | None,
    workflow_contract: dict[str, Any] | None,
    session_tool_catalog: dict[str, Any] | None,
    draft_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the future LLM planner input as a compact, inspectable packet."""

    analysis = request_analysis if isinstance(request_analysis, dict) else {}
    workflow = workflow_contract if isinstance(workflow_contract, dict) else {}
    draft = draft_contract if isinstance(draft_contract, dict) else {}
    catalog = session_tool_catalog if isinstance(session_tool_catalog, dict) else {}
    intent_contract = draft.get("intent_contract") if isinstance(draft.get("intent_contract"), dict) else {}
    safe_entries = _safe_catalog_entries(catalog)
    omitted_count = max(0, int(catalog.get("tool_count") or 0) - len(safe_entries))
    return {
        "version": CONTRACT_VERSION,
        "mode": PLAN_MODE,
        "source": "planner_prompt_packet",
        "planner_call_status": "not_called",
        "user_request": current_turn_content,
        "intent_hint": draft.get("intent_class") or "unknown",
        "intent_contract": intent_contract,
        "supported_intents": sorted(SUPPORTED_INTENTS),
        "request_context": {
            "route_reason": analysis.get("route_reason"),
            "requested_domains": analysis.get("requested_domains") or analysis.get("domains") or [],
            "workflow_id": workflow.get("workflow_id"),
            "diagram_source": workflow.get("diagram_source"),
            "session_scope": catalog.get("session_scope"),
            "catalog_policy_source": catalog.get("policy_source"),
            "routing_policy_id": catalog.get("routing_policy_id"),
            "routing_policy_version_id": catalog.get("routing_policy_version_id"),
            "denied_tools": catalog.get("denied_tools") or [],
            "skipped_policy_tools": catalog.get("skipped_policy_tools") or [],
            "unavailable_policy_tools": catalog.get("unavailable_policy_tools") or [],
        },
        "allowed_tool_catalog": safe_entries,
        "omitted_tool_count": omitted_count,
        "validation_rules": _validation_rules(),
        "required_output_schema": _required_output_schema(),
    }


__all__ = ["build_tool_plan_prompt_packet"]
