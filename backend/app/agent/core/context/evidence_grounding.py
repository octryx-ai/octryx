"""Evidence-grounded answer policy, decided by explicit settings only.

The answer contract applies when an explicit source asks for it; the prompt is never read:

1. the selected workflow's contract carries ``requires_sources`` or ``requires_live_evidence``
   (definition governance, ``selected_contract.DEFINITION_GOVERNED_FIELDS``);
2. the agent type is a configured high-risk type (``agent.evidence_grounding_config``
   ``high_risk_agent_types``, seeded from :data:`DEFAULT_HIGH_RISK_AGENT_TYPES`);
3. the Workspace setting ``evidence_grounding_policy`` (project config,
   ``services/evidence_grounding_settings``) has ``mode: required``. ``workflow`` or unset leaves
   the decision to 1 and 2. A stored value the admin write would refuse is the closed state
   ``needs_configuration``: the contract applies (fail closed, it only adds caution) and the
   recorded policy names the state.

All three are edited in the admin UI: the workflow definition, the runtime settings
("Evidence grounding", ``agent.evidence_grounding_config``) and the Workspace policies.

Two wordings of the same turn therefore get the same policy: nothing is matched over the prompt text.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from ....services.evidence_grounding_settings import (
    EVIDENCE_GROUNDING_MODE_REQUIRED,
    SETTING_STATE_DEFAULT,
    SETTING_STATE_NEEDS_CONFIGURATION,
    workspace_evidence_grounding,
)
from ....services.prompt_catalog import render_prompt
from ....services.prompt_catalog.registry import prompt_key_registry

DEFAULT_HIGH_RISK_AGENT_TYPES: frozenset[str] = frozenset({
    "knowledge",
    "knowledge_pack_builder",
    "stable_jira_worker",
    "document_updater",
})

TRIGGER_WORKFLOW_REQUIRES_SOURCES = "workflow_requires_sources"
TRIGGER_WORKFLOW_REQUIRES_LIVE_EVIDENCE = "workflow_requires_live_evidence"
TRIGGER_HIGH_RISK_AGENT_TYPE = "high_risk_agent_type"
TRIGGER_WORKSPACE_REQUIRED = "workspace_setting_required"
TRIGGER_WORKSPACE_NEEDS_CONFIGURATION = "workspace_setting_needs_configuration"


@dataclass(frozen=True)
class EvidenceGroundingPolicy:
    """Resolved policy for a single agent turn."""

    applies: bool
    triggers: tuple[str, ...]
    evidence_available: bool
    evidence_sources: tuple[str, ...]
    reason: str
    workspace_setting: str = SETTING_STATE_DEFAULT

    def to_metadata(self) -> dict[str, Any]:
        return {
            "applies": self.applies,
            "triggers": list(self.triggers),
            "evidence_available": self.evidence_available,
            "evidence_sources": list(self.evidence_sources),
            "reason": self.reason,
            "workspace_setting": self.workspace_setting,
        }


def _grounding_triggers(
    contract: Mapping[str, Any],
    *,
    agent_type: str,
    effective_agent_types: Collection[str],
    setting_state: str,
    workspace_mode: str,
) -> list[str]:
    triggers: list[str] = []
    if contract.get("requires_sources") is True:
        triggers.append(TRIGGER_WORKFLOW_REQUIRES_SOURCES)
    if contract.get("requires_live_evidence") is True:
        triggers.append(TRIGGER_WORKFLOW_REQUIRES_LIVE_EVIDENCE)
    if str(agent_type or "").strip().lower() in effective_agent_types:
        triggers.append(TRIGGER_HIGH_RISK_AGENT_TYPE)
    if setting_state == SETTING_STATE_NEEDS_CONFIGURATION:
        triggers.append(TRIGGER_WORKSPACE_NEEDS_CONFIGURATION)
    elif workspace_mode == EVIDENCE_GROUNDING_MODE_REQUIRED:
        triggers.append(TRIGGER_WORKSPACE_REQUIRED)
    return triggers


def resolve_evidence_grounding_policy(
    *,
    workflow_contract: Mapping[str, Any] | None,
    agent_type: str,
    project_id: str | None,
    project_config: Mapping[str, Any] | None = None,
    high_risk_agent_types: Collection[str] | None = None,
    has_project_knowledge: bool = False,
    has_engineering_knowledge: bool = False,
    has_repo_knowledge: bool = False,
    has_runtime_engineering_pack: bool = False,
) -> EvidenceGroundingPolicy:
    """Return whether the turn obeys the evidence-grounded answer contract (module docstring).

    ``high_risk_agent_types`` is the configured list (system config); None falls back to the code
    defaults for callers without database access (tests, tooling).
    """
    contract = workflow_contract if isinstance(workflow_contract, Mapping) else {}
    effective_agent_types = (
        {str(item or "").strip().lower() for item in high_risk_agent_types}
        if high_risk_agent_types is not None
        else DEFAULT_HIGH_RISK_AGENT_TYPES
    )
    setting_state, workspace_mode = workspace_evidence_grounding(dict(project_config or {}))
    triggers = _grounding_triggers(
        contract,
        agent_type=agent_type,
        effective_agent_types=effective_agent_types,
        setting_state=setting_state,
        workspace_mode=workspace_mode,
    )
    if not triggers:
        return EvidenceGroundingPolicy(
            applies=False, triggers=(), evidence_available=False, evidence_sources=(),
            reason="no_explicit_grounding_source", workspace_setting=setting_state,
        )

    sources = [
        source
        for source, present in (
            ("project_knowledge", has_project_knowledge),
            ("engineering_knowledge", has_engineering_knowledge),
            ("engineering_pack_runtime", has_runtime_engineering_pack),
            ("repository_context", has_repo_knowledge),
        )
        if present
    ]
    if not project_id:
        reason = "grounding_without_project_scope"
    else:
        reason = "grounding_with_retrieved_context" if sources else "grounding_without_retrieved_context"
    return EvidenceGroundingPolicy(
        applies=True,
        triggers=tuple(triggers),
        evidence_available=bool(sources),
        evidence_sources=tuple(sources),
        reason=reason,
        workspace_setting=setting_state,
    )


def _applies_because(triggers: tuple[str, ...]) -> str:
    """The trigger labels (catalog keys ``evidence.trigger.<trigger>``); an unknown trigger shows its code."""
    labels = [
        render_prompt(f"evidence.trigger.{item}") if f"evidence.trigger.{item}" in prompt_key_registry() else item
        for item in triggers
    ]
    return "; ".join(labels) or render_prompt("evidence.trigger.default")


def render_evidence_grounding_prompt(policy: EvidenceGroundingPolicy) -> str:
    """Render the answer contract injected into the agent runtime prompt (catalog keys ``evidence.*``)."""

    if not policy.applies:
        return ""
    evidence_status = (
        render_prompt("evidence.status_available", evidence_sources=", ".join(policy.evidence_sources))
        if policy.evidence_available
        else render_prompt("evidence.status_missing")
    )
    return render_prompt(
        "evidence.grounding_contract",
        applies_because=_applies_because(policy.triggers),
        evidence_status=evidence_status,
    )


__all__ = [
    "DEFAULT_HIGH_RISK_AGENT_TYPES",
    "EvidenceGroundingPolicy",
    "render_evidence_grounding_prompt",
    "resolve_evidence_grounding_policy",
]
