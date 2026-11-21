"""Server-owned project context for governed model-alias admission.

The project ``model_policy`` decides which Octryx aliases a project may
dispatch. That decision is only trustworthy if the *project* it is made against
is server-owned, so it travels as this typed object rather than as a plain dict
that a model argument, a tool payload, or a request body could shape.

Every dispatch path reaches the gateway through exactly one door — the
``litellm_gateway`` provider driver — and the driver refuses to exist without an
admission object. The two possible states are therefore:

- a **verified** admission, built by a caller that read the project row itself
  (:func:`build_project_model_admission`);
- the **unverified** singleton, attached by the provider client-kwargs builder
  so that catalog/readiness work still functions while every chat dispatch is
  denied.

A path that cannot supply verified project context can consequently never
dispatch through the gateway. That is deliberate: the alternative is trusting an
unscoped caller's word about which project it is acting for.

The admission also carries the turn's server-owned data classification, so
the driver can compare it with the alias' declared ``data_policy_class`` at the
same boundary. The classification is resolved from the project row by
``services/model_gateway/data_policy.source``, never from the merged turn
project-config mapping this module receives — see that module for why.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..data_policy import (
    UNRESOLVED_DATA_CLASSIFICATION,
    DataPolicyDecision,
    WorkspaceDataClassification,
    data_policy_decision,
)
from .policy import (
    POLICY_REASON_CLASSIFICATION_ALIAS_NOT_ALLOWED,
    POLICY_REASON_CONTEXT_UNVERIFIABLE,
    ModelAliasAccessDecision,
    model_alias_access_decision,
)

# Keyword the provider factory and the runtime client kwargs use to carry the
# admission. Named explicitly so the runtime chain never needs to know more.
PROJECT_ADMISSION_KWARG = "project_model_admission"

ADMISSION_SOURCE_UNVERIFIED = "unverified_project_context"


@dataclass(frozen=True, slots=True)
class ProjectModelAdmission:
    """One project's model-alias admission authority for a single dispatch path."""

    project_id: str
    source: str
    verified: bool
    # The policy mapping is read from the project row by the builder. It is kept
    # out of the repr so a policy dump can never ride along in a traceback or a
    # logged provider-kwargs payload.
    policy: Mapping[str, Any] = field(repr=False, default_factory=dict)
    # The turn's effective workspace data classification. Its default is the
    # unresolved value, so an admission built without one denies every dispatch
    # instead of dispatching unclassified.
    data_classification: WorkspaceDataClassification = UNRESOLVED_DATA_CLASSIFICATION
    # The classification policy matrix's ``allowed_model_aliases`` per level; a level absent here
    # does not narrow. Read with the effective classification, so a replaced (stricter) classification
    # brings its own level's list.
    level_model_aliases: Mapping[str, frozenset[str]] = field(repr=False, default_factory=dict)
    # The Cedar principal of the request that built this admission (``policy_engine.request_principal``):
    # its later re-checks at the driver decide for the same user and session. Never part of the decision itself.
    principal: Any = field(repr=False, compare=False, default=None)

    def decide(self, alias: str | None) -> ModelAliasAccessDecision:
        """Return the auditable admission decision for one alias: the project grant, then the level's list.

        The Cedar policy engine evaluates the same question: in shadow mode its answer never changes this
        decision; in enforce mode a Cedar denial of an admitted alias is ``cedar_policy_denied``.
        """

        decision = self.builtin_decision(alias)
        from ...policy_engine.points import POINT_MODEL_ADMISSION, model_query
        from ...policy_engine.shadow import (
            REASON_CEDAR_POLICY_DENIED,
            LegacyDecision,
            enforced_denial,
            shadow_decision,
        )

        comparison = shadow_decision(
            POINT_MODEL_ADMISSION, LegacyDecision(decision.allowed, decision.reason), lambda: model_query(self, alias)
        )
        if enforced_denial(decision.allowed, comparison) is not None:
            return ModelAliasAccessDecision(decision.alias, False, REASON_CEDAR_POLICY_DENIED)
        return decision

    def builtin_decision(self, alias: str | None) -> ModelAliasAccessDecision:
        """The grant and the level's list alone (also the policy test bench's comparison)."""
        if not self.verified:
            return ModelAliasAccessDecision(
                str(alias or "").strip(),
                False,
                POLICY_REASON_CONTEXT_UNVERIFIABLE,
            )
        decision = model_alias_access_decision(alias, {"model_policy": dict(self.policy)})
        if not decision.allowed or not self.data_classification.resolved:
            return decision
        allowed = self.level_model_aliases.get(self.data_classification.classification)
        if allowed is not None and decision.alias not in allowed:
            return ModelAliasAccessDecision(decision.alias, False, POLICY_REASON_CLASSIFICATION_ALIAS_NOT_ALLOWED)
        return decision

    def decide_data_policy(self, alias_data_policy_class: Any) -> DataPolicyDecision:
        """Return the auditable data-policy decision for one alias allowance."""

        if not self.verified:
            return data_policy_decision(None, alias_data_policy_class)
        return data_policy_decision(self.data_classification, alias_data_policy_class)

    def evidence(self) -> dict[str, Any]:
        """Evidence about the *source* of the decision, never its contents."""

        return {"project_admission_source": self.source}


# Deny-by-default admission for every path that has no verifiable project.
UNVERIFIED_PROJECT_ADMISSION = ProjectModelAdmission(
    project_id="",
    source=ADMISSION_SOURCE_UNVERIFIED,
    verified=False,
)


def build_project_model_admission(
    *,
    project_id: Any,
    project_config: Any,
    source: str,
    data_classification: WorkspaceDataClassification,
    level_model_aliases: Mapping[str, frozenset[str]] | None = None,
) -> ProjectModelAdmission:
    """Build a verified admission, or the unverified singleton.

    ``project_id`` must be a non-empty server-resolved identifier and ``source``
    must name the boundary that resolved it; anything else yields the unverified
    singleton, which denies every dispatch.

    ``data_classification`` is required rather than defaulted so every boundary
    has to state which classification it resolved. It must come from
    ``resolve_workspace_data_classification``; a classification taken out of
    ``project_config`` would be caller-shapeable.

    ``level_model_aliases`` is the matrix's per-level alias lists
    (``data_classification.policy_matrix.model_allowlists``); the async boundaries always pass it, and
    ``None`` is the default matrix, which narrows no level.
    """

    normalized_project_id = str(project_id or "").strip()
    normalized_source = str(source or "").strip()
    if not normalized_project_id or not normalized_source:
        return UNVERIFIED_PROJECT_ADMISSION
    config = project_config if isinstance(project_config, Mapping) else {}
    policy = config.get("model_policy")
    classification = (
        data_classification
        if isinstance(data_classification, WorkspaceDataClassification)
        else UNRESOLVED_DATA_CLASSIFICATION
    )
    from ...policy_engine.request_principal import current_principal

    return ProjectModelAdmission(
        project_id=normalized_project_id,
        source=normalized_source,
        verified=True,
        policy=dict(policy) if isinstance(policy, Mapping) else {},
        principal=current_principal(),
        data_classification=classification,
        level_model_aliases=dict(level_model_aliases or {}),
    )


def resolved_project_admission(value: Any) -> ProjectModelAdmission | None:
    """Return the admission only when it is the typed, server-owned object."""

    return value if isinstance(value, ProjectModelAdmission) else None


__all__ = [
    "ADMISSION_SOURCE_UNVERIFIED",
    "PROJECT_ADMISSION_KWARG",
    "UNVERIFIED_PROJECT_ADMISSION",
    "ProjectModelAdmission",
    "build_project_model_admission",
    "resolved_project_admission",
]
