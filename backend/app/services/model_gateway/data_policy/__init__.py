"""Server-owned workspace data classification for model-gateway dispatch.

The alias catalog declares a ``data_policy_class`` per admitted alias. This
package turns that declaration into an enforced control: it owns the server-side
classification source, the closed compatibility order, and the comparison that
runs before a gateway client is constructed and before any billable dispatch.

- :mod:`.classification` — the closed order and the effective-classification rule
  (project floor, session raise-only).
- :mod:`.source` — the async resolver, which reads the project row itself.
- :mod:`.gate` — the comparison, its fixed denial codes, and closed evidence.
"""

from .classification import (
    CLASSIFICATION_SOURCE_PROJECT_CONFIG,
    CLASSIFICATION_SOURCE_SESSION_RAISE,
    CLASSIFICATION_SOURCE_UNRESOLVED,
    DATA_CLASSIFICATION_LEVELS,
    DATA_CLASSIFICATION_ORDER,
    DATA_POLICY_CLASSIFICATION_CLEARED_FIELD,
    DATA_POLICY_CLASSIFICATION_FIELD,
    DATA_POLICY_CONFIG_KEY,
    DENIAL_SESSION_CLASS_UNKNOWN,
    DENIAL_WORKSPACE_CLASS_MISSING,
    DENIAL_WORKSPACE_CLASS_UNKNOWN,
    UNRESOLVED_DATA_CLASSIFICATION,
    WorkspaceDataClassification,
    classification_rank,
    normalized_classification,
    resolve_data_classification,
    unresolved_classification,
)
from .gate import (
    DATA_POLICY_PERMITTED_REASON,
    DENIAL_ALIAS_CLASS_UNKNOWN,
    DENIAL_CLASS_INSUFFICIENT,
    DENIAL_CONTEXT_UNVERIFIABLE,
    DataPolicyDecision,
    data_policy_decision,
)
from .source import resolve_workspace_data_classification

__all__ = [
    "CLASSIFICATION_SOURCE_PROJECT_CONFIG",
    "CLASSIFICATION_SOURCE_SESSION_RAISE",
    "CLASSIFICATION_SOURCE_UNRESOLVED",
    "DATA_CLASSIFICATION_LEVELS",
    "DATA_CLASSIFICATION_ORDER",
    "DATA_POLICY_CLASSIFICATION_CLEARED_FIELD",
    "DATA_POLICY_CLASSIFICATION_FIELD",
    "DATA_POLICY_CONFIG_KEY",
    "DATA_POLICY_PERMITTED_REASON",
    "DENIAL_ALIAS_CLASS_UNKNOWN",
    "DENIAL_CLASS_INSUFFICIENT",
    "DENIAL_CONTEXT_UNVERIFIABLE",
    "DENIAL_SESSION_CLASS_UNKNOWN",
    "DENIAL_WORKSPACE_CLASS_MISSING",
    "DENIAL_WORKSPACE_CLASS_UNKNOWN",
    "UNRESOLVED_DATA_CLASSIFICATION",
    "DataPolicyDecision",
    "WorkspaceDataClassification",
    "classification_rank",
    "data_policy_decision",
    "normalized_classification",
    "resolve_data_classification",
    "resolve_workspace_data_classification",
    "unresolved_classification",
]
