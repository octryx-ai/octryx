"""The workflow part of the Effective setup, shared by platform chat and octryx-claude."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..run_capability.definition_contract import declared_workflow_capability
from ..workflow_checks.library import workflow_checks
from ..workflow_routing.tool_policy import normalized_tool_policy
from ..workflow_routing.workflow_selection import SELECTION_UNKNOWN_KEY, workflow_selection_from_resolution
from .parts import PART_WORKFLOW, SetupPart, tokens_of

WORKFLOWS_TAB = "workflowList"


async def workflow_part(
    db: AsyncSession, *, resolution: dict[str, Any], run_capability: dict[str, Any] | None
) -> SetupPart:
    """The selected workflow (the current phase of the session's workflow run), or why none is selected."""
    del db
    selection = workflow_selection_from_resolution(resolution)
    capability_class = str((run_capability or {}).get("class") or "read_only")
    if not selection.selected:
        unknown = selection.state == SELECTION_UNKNOWN_KEY
        return SetupPart(
            id=PART_WORKFLOW,
            title="Workflow",
            source_label="Unknown workflow key" if unknown else "No workflow selected",
            source_tab=WORKFLOWS_TAB,
            enforced="enforced",
            details={
                "selected": False,
                "state": selection.state,
                "reason": selection.reason_code,
                "capability_class": capability_class,
                "available_workflow_keys": list(resolution.get("available_workflow_keys") or [])[:50],
                "note": (
                    "The key is unknown: the turn needs clarification."
                    if unknown
                    else "No workflow runs in this turn; a proposed workflow starts as a workflow run."
                ),
            },
        )
    contract = resolution.get("workflow_contract") if isinstance(resolution.get("workflow_contract"), dict) else {}
    tool_policy = normalized_tool_policy(
        resolution.get("tool_policy") if isinstance(resolution.get("tool_policy"), dict) else {}
    )
    key = str(resolution.get("workflow_key") or "")
    return SetupPart(
        id=PART_WORKFLOW,
        title="Workflow",
        source_label=f"Workflows → {key}",
        source_tab=WORKFLOWS_TAB,
        enforced="enforced",
        tokens=tokens_of(str(contract.get("when_to_use") or "")),
        details={
            "selected": True,
            "key": key,
            "when_to_use": str(contract.get("when_to_use") or ""),
            "declared_class": declared_workflow_capability(resolution).capability_class,
            "capability_class": capability_class,
            "checks": workflow_checks(contract),
            "tool_policy": {"allowlist": list(tool_policy["allowlist"]), "denylist": list(tool_policy["denylist"])},
        },
    )


__all__ = ["WORKFLOWS_TAB", "workflow_part"]
