"""The path check of the coding agent's own edit and patch tools."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog
from ..agent_gateway.policy import load_workspace_policy
from ..agent_gateway.tool_check import DECISION_DENY, evaluate_tool_check
from ..policy_engine.gateway_point import gateway_query
from ..policy_engine.points import POINT_GATEWAY_TOOL_CHECK
from ..policy_engine.principals import load_principal_isolated
from ..policy_engine.runtime import MODE_OFF, current_runtime, maintain_policy_runtime
from ..policy_engine.shadow import LegacyDecision, enforced_denial, shadow_decision
from ..policy_engine.workspace_facts import load_workspace_classification_isolated

logger = logging.getLogger(__name__)

BLOCKING_RUNTIME_EFFECTS = {"block", "review_required"}
RUNTIME_DECISION_VERSION = "coding_policy_decision.v2"
RUNTIME_POLICY_ACTION = "secure_work.coding_policy_runtime_decision"
EDIT_TOOL = "Edit"


def clean_paths(paths: list[str]) -> list[str]:
    clean: list[str] = []
    for path in paths:
        value = str(path or "").strip().replace("\\", "/").lstrip("/")
        if value and value not in clean:
            clean.append(value)
    return clean


@dataclass(frozen=True)
class RuntimePolicySubject:
    user_id: str
    session_id: str | None
    project_id: str | None
    work_item_id: str | None
    tool_name: str
    paths: tuple[str, ...]


async def enforce_workspace_path_policy(
    db: AsyncSession | None,
    *,
    user_id: str | None,
    session_id: str | None,
    project_id: str | None,
    work_item_id: str | None,
    tool_name: str,
    paths: list[str],
    proposed: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The decision for a workspace mutation of ``paths``: allowed, warn, review_required or blocked. ``proposed``
    maps a path to the content the write leaves, when the tool knows it (a phase's formatting-only rule reads it)."""

    subject = RuntimePolicySubject(
        user_id=str(user_id or "").strip(),
        session_id=str(session_id or "").strip() or None,
        project_id=str(project_id or "").strip() or None,
        work_item_id=str(work_item_id or "").strip() or None,
        tool_name=str(tool_name or "").strip(),
        paths=tuple(clean_paths(paths)),
    )
    if db is None or not subject.paths:
        return build_allowed_policy_decision(subject=subject, reason="No database or paths available for evaluation.")
    from ..workflow_runs.path_rules import phase_path_outcomes

    outcomes = [
        *await _policy_outcomes(db, subject),
        # The current phase of the workflow run the session follows.
        *await phase_path_outcomes(db, subject.session_id, list(subject.paths), proposed={
            clean: text for path, text in (proposed or {}).items() for clean in clean_paths([path])}),
    ]
    decision = _build_decision(subject=subject, outcomes=outcomes)
    await _audit_decision(db, subject=subject, decision=decision)
    return decision


def _blocked(source: str, rule: str, reason: str, path: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_id": rule,
        "name": rule,
        "policy_type": source,
        "severity": "high",
        "enforcement_mode": "block",
        "effect": "block",
        "blocking": True,
        "reason": reason,
        "remediation": "",
        "evidence": {"paths": [path], **evidence},
    }


async def _policy_outcomes(db: AsyncSession, subject: RuntimePolicySubject) -> list[dict[str, Any]]:
    if not subject.project_id:
        return []
    loaded = await load_workspace_policy(db, subject.project_id)
    if loaded.policy is None:
        return []
    await maintain_policy_runtime()
    runtime_on = current_runtime().mode != MODE_OFF
    principal = records = classification = None
    if runtime_on:
        principal, records = await load_principal_isolated(subject.user_id or None, session_id=subject.session_id)
        classification = await load_workspace_classification_isolated(subject.project_id)
    outcomes: list[dict[str, Any]] = []
    for path in subject.paths:
        hook_input = {"tool_name": EDIT_TOOL, "tool_input": {"file_path": path}, "cwd": ""}
        rules = evaluate_tool_check(loaded.policy, hook_input)
        if rules.decision == DECISION_DENY:
            outcomes.append(
                _blocked("workspace_tool_rule", rules.rule_id or rules.reason, rules.message or rules.reason, path, {})
            )
            continue
        if not runtime_on:
            continue
        comparison = shadow_decision(
            POINT_GATEWAY_TOOL_CHECK,
            LegacyDecision(True, "allowed"),
            lambda: gateway_query(
                workspace_id=subject.project_id,
                gateway=loaded.policy,
                hook_input=hook_input,
                principal=principal,
                principal_records=records,
                classification=classification,
            ),
        )
        denial = enforced_denial(True, comparison)
        if denial is not None:
            outcomes.append(
                _blocked(
                    "cedar_policy",
                    ", ".join(denial.policy_ids) or "policy engine",
                    denial.message,
                    path,
                    {"policy_ids": list(denial.policy_ids), "decision_id": denial.decision_id},
                )
            )
    return outcomes


def build_allowed_policy_decision(*, subject: RuntimePolicySubject, reason: str) -> dict[str, Any]:
    return {
        "version": RUNTIME_DECISION_VERSION,
        "status": "allowed",
        "blocking": False,
        "reason": reason,
        "tool_name": subject.tool_name,
        "paths": list(subject.paths),
        "outcomes": [],
        "summary": {"pass": 0, "warn": 0, "review_required": 0, "block": 0, "skipped": 0},
    }


def _build_decision(*, subject: RuntimePolicySubject, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    if not outcomes:
        return build_allowed_policy_decision(subject=subject, reason="No rule or policy denied these paths.")
    summary = {"pass": 0, "warn": 0, "review_required": 0, "block": 0, "skipped": 0}
    for outcome in outcomes:
        effect = str(outcome.get("effect") or "skipped")
        summary[effect] = summary.get(effect, 0) + 1
    blocking = [outcome for outcome in outcomes if outcome.get("effect") in BLOCKING_RUNTIME_EFFECTS]
    status = (
        "blocked"
        if any(outcome.get("effect") == "block" for outcome in blocking)
        else "review_required"
        if blocking
        else "warn"
        if summary.get("warn")
        else "allowed"
    )
    return {
        "version": RUNTIME_DECISION_VERSION,
        "status": status,
        "blocking": bool(blocking),
        "reason": _decision_reason(status),
        "tool_name": subject.tool_name,
        "paths": list(subject.paths),
        "outcomes": outcomes,
        "summary": summary,
    }


async def _audit_decision(db: AsyncSession, *, subject: RuntimePolicySubject, decision: dict[str, Any]) -> None:
    if not subject.user_id:
        return
    db.add(
        AuditLog(
            user_id=subject.user_id,
            session_id=subject.session_id,
            action=RUNTIME_POLICY_ACTION,
            resource_type="work_item" if subject.work_item_id else "coding_policy",
            resource_id=subject.work_item_id,
            project_id=subject.project_id,
            details={
                "project_id": subject.project_id,
                "tool_name": subject.tool_name,
                "paths": list(subject.paths),
                "decision": decision,
            },
        )
    )
    await db.flush()


def _decision_reason(status: str) -> str:
    if status == "blocked":
        return "A Workspace rule or policy blocked this workspace mutation."
    if status == "review_required":
        return "A rule requires review before this workspace mutation."
    if status == "warn":
        return "A rule produced a warning for this workspace mutation."
    return "The Workspace rules and policies allowed this workspace mutation."
