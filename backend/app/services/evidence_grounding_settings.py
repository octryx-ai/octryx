"""The Workspace setting ``evidence_grounding_policy`` (project config), validated.

Stored section: ``{"mode": "required"}`` (every turn in the Workspace obeys the
evidence-grounded answer contract), ``{"mode": "workflow"}`` or ``{}`` (the default: the selected
workflow and the configured high-risk agent types decide). The admin project-config write
(``admin_project_config_service``) refuses any other value with the closed code
``unsupported_evidence_grounding_mode``; a value stored past that check (a direct database write)
is read as the closed state ``needs_configuration`` and the contract applies (fail closed).

Edited in the admin UI: Workspace settings, Policies, "Evidence grounding".
"""

from __future__ import annotations

from typing import Any

EVIDENCE_GROUNDING_POLICY_CONFIG_KEY = "evidence_grounding_policy"
EVIDENCE_GROUNDING_MODE_FIELD = "mode"
EVIDENCE_GROUNDING_MODE_REQUIRED = "required"
EVIDENCE_GROUNDING_MODE_WORKFLOW = "workflow"
EVIDENCE_GROUNDING_MODES = (EVIDENCE_GROUNDING_MODE_WORKFLOW, EVIDENCE_GROUNDING_MODE_REQUIRED)
UNSUPPORTED_EVIDENCE_GROUNDING_MODE = "unsupported_evidence_grounding_mode"

SETTING_STATE_DEFAULT = "default"
SETTING_STATE_CONFIGURED = "configured"
SETTING_STATE_NEEDS_CONFIGURATION = "needs_configuration"


class EvidenceGroundingPolicyError(ValueError):
    """An out-of-vocabulary Workspace value; the admin config service maps it to a 400."""

    code = UNSUPPORTED_EVIDENCE_GROUNDING_MODE


def normalize_evidence_grounding_policy(value: Any) -> dict[str, Any]:
    """Validate the stored section; ``{}`` (or ``{"mode": null}``) is the default."""
    if value is not None and not isinstance(value, dict):
        raise EvidenceGroundingPolicyError(f"{EVIDENCE_GROUNDING_POLICY_CONFIG_KEY} must be an object")
    section = dict(value or {})
    unknown = sorted(set(section) - {EVIDENCE_GROUNDING_MODE_FIELD})
    if unknown:
        raise EvidenceGroundingPolicyError(
            f"{EVIDENCE_GROUNDING_POLICY_CONFIG_KEY} accepts only '{EVIDENCE_GROUNDING_MODE_FIELD}'; "
            f"got {', '.join(unknown)}"
        )
    mode = section.get(EVIDENCE_GROUNDING_MODE_FIELD)
    if mode is None:
        return {}
    if mode not in EVIDENCE_GROUNDING_MODES:
        raise EvidenceGroundingPolicyError(
            f"{EVIDENCE_GROUNDING_POLICY_CONFIG_KEY}.{EVIDENCE_GROUNDING_MODE_FIELD} must be one of: "
            + ", ".join(EVIDENCE_GROUNDING_MODES)
        )
    return {EVIDENCE_GROUNDING_MODE_FIELD: mode}


def workspace_evidence_grounding(project_config: Any) -> tuple[str, str]:
    """``(state, mode)`` of the Workspace's setting; an unreadable value is ``needs_configuration``."""
    config = project_config if isinstance(project_config, dict) else {}
    if EVIDENCE_GROUNDING_POLICY_CONFIG_KEY not in config:
        return SETTING_STATE_DEFAULT, EVIDENCE_GROUNDING_MODE_WORKFLOW
    try:
        section = normalize_evidence_grounding_policy(config.get(EVIDENCE_GROUNDING_POLICY_CONFIG_KEY))
    except EvidenceGroundingPolicyError:
        return SETTING_STATE_NEEDS_CONFIGURATION, ""
    mode = section.get(EVIDENCE_GROUNDING_MODE_FIELD)
    if not mode:
        return SETTING_STATE_DEFAULT, EVIDENCE_GROUNDING_MODE_WORKFLOW
    return SETTING_STATE_CONFIGURED, mode


__all__ = [
    "EVIDENCE_GROUNDING_MODES",
    "EVIDENCE_GROUNDING_MODE_REQUIRED",
    "EVIDENCE_GROUNDING_MODE_WORKFLOW",
    "EVIDENCE_GROUNDING_POLICY_CONFIG_KEY",
    "SETTING_STATE_CONFIGURED",
    "SETTING_STATE_DEFAULT",
    "SETTING_STATE_NEEDS_CONFIGURATION",
    "UNSUPPORTED_EVIDENCE_GROUNDING_MODE",
    "EvidenceGroundingPolicyError",
    "normalize_evidence_grounding_policy",
    "workspace_evidence_grounding",
]
