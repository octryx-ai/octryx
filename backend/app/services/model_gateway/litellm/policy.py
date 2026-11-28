"""Project-level admission policy for Octryx model aliases (``project_config["model_policy"]``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MODEL_POLICY_CONFIG_KEY = "model_policy"
# A Workspace that never chose its models may use every admitted one (clearance and data class still decide): every
# model is a LiteLLM alias, so without this a fresh install had no usable model. A saved policy replaces it.
DEFAULT_MODEL_POLICY: dict[str, Any] = {"allowed_aliases": [], "allow_all_admitted_aliases": True}


def effective_model_policy(config: Any) -> dict[str, Any]:
    policy = config.get(MODEL_POLICY_CONFIG_KEY) if isinstance(config, Mapping) else None
    return dict(policy) if isinstance(policy, Mapping) else dict(DEFAULT_MODEL_POLICY)

POLICY_REASON_MISSING_ALIAS = "missing_alias"
# No server-owned project could be resolved for this dispatch path, so no
# project policy can be evaluated. Deny-by-default applies to the *context*
# itself, not only to the alias.
POLICY_REASON_CONTEXT_UNVERIFIABLE = "project_policy_context_unverifiable"
POLICY_REASON_EXPLICIT_DENY = "explicit_alias_denial"
POLICY_REASON_EXPLICIT_ALLOW = "explicit_alias_grant"
POLICY_REASON_ALLOW_ALL = "policy_allow_all_admitted_aliases"
POLICY_REASON_NOT_GRANTED = "model_alias_not_granted_for_project"
# The Workspace's classification level narrows the aliases (classification policy matrix).
POLICY_REASON_CLASSIFICATION_ALIAS_NOT_ALLOWED = "model_alias_not_allowed_for_classification"


@dataclass(frozen=True, slots=True)
class ModelAliasAccessDecision:
    alias: str
    allowed: bool
    reason: str

    def to_metadata(self) -> dict[str, Any]:
        return {"alias": self.alias, "allowed": self.allowed, "reason": self.reason}


def _normalized_aliases(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item or "").strip() for item in value if str(item or "").strip()}


def model_alias_access_decision(
    alias: str | None,
    project_config: dict[str, Any] | None,
) -> ModelAliasAccessDecision:
    """Return the auditable project admission decision for one model alias."""

    normalized_alias = str(alias or "").strip()
    if not normalized_alias:
        return ModelAliasAccessDecision("", False, POLICY_REASON_MISSING_ALIAS)
    config = project_config if isinstance(project_config, dict) else {}
    policy = config.get(MODEL_POLICY_CONFIG_KEY)
    policy = policy if isinstance(policy, dict) else {}

    if normalized_alias in _normalized_aliases(policy.get("denied_aliases")):
        return ModelAliasAccessDecision(normalized_alias, False, POLICY_REASON_EXPLICIT_DENY)
    if normalized_alias in _normalized_aliases(policy.get("allowed_aliases")):
        return ModelAliasAccessDecision(normalized_alias, True, POLICY_REASON_EXPLICIT_ALLOW)
    if policy.get("allow_all_admitted_aliases") is True:
        return ModelAliasAccessDecision(normalized_alias, True, POLICY_REASON_ALLOW_ALL)
    return ModelAliasAccessDecision(normalized_alias, False, POLICY_REASON_NOT_GRANTED)


__all__ = [
    "DEFAULT_MODEL_POLICY",
    "MODEL_POLICY_CONFIG_KEY",
    "effective_model_policy",
    "POLICY_REASON_CLASSIFICATION_ALIAS_NOT_ALLOWED",
    "POLICY_REASON_CONTEXT_UNVERIFIABLE",
    "POLICY_REASON_ALLOW_ALL",
    "POLICY_REASON_EXPLICIT_ALLOW",
    "POLICY_REASON_EXPLICIT_DENY",
    "POLICY_REASON_MISSING_ALIAS",
    "POLICY_REASON_NOT_GRANTED",
    "ModelAliasAccessDecision",
    "model_alias_access_decision",
]
