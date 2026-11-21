"""The data-policy comparison performed before any billable gateway dispatch.

An alias' ``data_policy_class`` is the *highest* sensitivity that alias is
approved to handle. A dispatch is permitted only when the workspace's effective
classification sits at or below it. Everything else — an unresolvable workspace
classification, an unresolvable alias class, or a workspace more sensitive than
the alias allowance — is an explicit denial with a fixed code.

A model may only be cleared for a level whose ``models_allowed`` is on
(``classification.MODEL_DATA_POLICY_CLASSES``, from the level registry), and a
workspace at a level without models (the built-in ``secret`` or a custom level
added that way) has no admissible gateway alias at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .classification import (
    CLASSIFICATION_SOURCE_PROJECT_CONFIG,
    CLASSIFICATION_SOURCE_SESSION_RAISE,
    CLASSIFICATION_SOURCE_UNRESOLVED,
    DATA_CLASSIFICATION_LEVELS,
    DENIAL_WORKSPACE_CLASS_UNKNOWN,
    MODEL_DATA_POLICY_CLASSES,
    WorkspaceDataClassification,
    classification_rank,
    normalized_classification,
)

# Fixed denial codes owned by this gate.
DENIAL_ALIAS_CLASS_UNKNOWN = "alias_data_policy_class_unknown"
DENIAL_CLASS_INSUFFICIENT = "data_policy_class_insufficient"
DENIAL_CONTEXT_UNVERIFIABLE = "data_policy_context_unverifiable"

DATA_POLICY_PERMITTED_REASON = "data_policy_class_permitted"

_CLASSIFICATION_SOURCES = frozenset(
    {
        CLASSIFICATION_SOURCE_PROJECT_CONFIG,
        CLASSIFICATION_SOURCE_SESSION_RAISE,
        CLASSIFICATION_SOURCE_UNRESOLVED,
    }
)


@dataclass(frozen=True, slots=True)
class DataPolicyDecision:
    """One auditable workspace-classification vs alias-allowance comparison."""

    allowed: bool
    reason: str
    workspace_classification: str
    workspace_classification_source: str
    alias_data_policy_class: str

    def evidence(self) -> dict[str, Any]:
        """Closed evidence: three closed-vocabulary values, nothing derived."""

        payload: dict[str, Any] = {}
        if self.workspace_classification in DATA_CLASSIFICATION_LEVELS:
            payload["workspace_data_classification"] = self.workspace_classification
        if self.workspace_classification_source in _CLASSIFICATION_SOURCES:
            payload["workspace_data_classification_source"] = self.workspace_classification_source
        if self.alias_data_policy_class in MODEL_DATA_POLICY_CLASSES:
            payload["data_policy_class"] = self.alias_data_policy_class
        return payload


def data_policy_decision(
    workspace: WorkspaceDataClassification | None,
    alias_data_policy_class: Any,
) -> DataPolicyDecision:
    """Compare a resolved workspace classification with an alias allowance."""

    alias_class = normalized_classification(alias_data_policy_class)
    if workspace is None:
        # No typed classification reached this boundary at all, so nothing can be
        # compared. Treated exactly like an unverifiable project context.
        return DataPolicyDecision(False, DENIAL_CONTEXT_UNVERIFIABLE, "", "", alias_class)
    if not workspace.resolved:
        return DataPolicyDecision(
            False,
            workspace.reason or DENIAL_CONTEXT_UNVERIFIABLE,
            "",
            workspace.source,
            alias_class,
        )
    alias_rank = classification_rank(alias_class)
    if alias_rank is None or alias_class not in MODEL_DATA_POLICY_CLASSES:
        return DataPolicyDecision(
            False,
            DENIAL_ALIAS_CLASS_UNKNOWN,
            workspace.classification,
            workspace.source,
            "",
        )
    workspace_rank = workspace.rank
    if workspace_rank is None:
        return DataPolicyDecision(
            False,
            DENIAL_WORKSPACE_CLASS_UNKNOWN,
            "",
            workspace.source,
            alias_class,
        )
    if workspace_rank > alias_rank or workspace.classification not in MODEL_DATA_POLICY_CLASSES:
        return DataPolicyDecision(
            False,
            DENIAL_CLASS_INSUFFICIENT,
            workspace.classification,
            workspace.source,
            alias_class,
        )
    return DataPolicyDecision(
        True,
        DATA_POLICY_PERMITTED_REASON,
        workspace.classification,
        workspace.source,
        alias_class,
    )


__all__ = [
    "DATA_POLICY_PERMITTED_REASON",
    "DENIAL_ALIAS_CLASS_UNKNOWN",
    "DENIAL_CLASS_INSUFFICIENT",
    "DENIAL_CONTEXT_UNVERIFIABLE",
    "DataPolicyDecision",
    "data_policy_decision",
]
