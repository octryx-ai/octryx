"""The closed Workspace data classification and the order dispatch compares against."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence, Set
from dataclasses import dataclass
from typing import Any

from ...data_classification.levels import level_registry

DATA_POLICY_CONFIG_KEY = "data_policy"
DATA_POLICY_CLASSIFICATION_FIELD = "classification"
# Set by the admin config path when an admin clears the classification: never refilled by a default.
DATA_POLICY_CLASSIFICATION_CLEARED_FIELD = "classification_cleared"


class _LevelOrder(Sequence[str]):
    def __getitem__(self, index: Any) -> Any:
        return level_registry().order[index]

    def __len__(self) -> int:
        return len(level_registry().order)

    def __iter__(self) -> Iterator[str]:
        return iter(level_registry().order)

    def __contains__(self, value: object) -> bool:
        return value in level_registry()

    def __eq__(self, other: object) -> bool:
        return tuple(self) == (tuple(other) if isinstance(other, Sequence) and not isinstance(other, str) else other)

    def __hash__(self) -> int:
        return hash(tuple(self))

    def __repr__(self) -> str:
        return repr(tuple(self))


class _LevelSet(Set[str]):
    def __init__(self, *, model_levels: bool = False) -> None:
        self._model_levels = model_levels

    def _keys(self) -> tuple[str, ...]:
        registry = level_registry()
        return registry.model_levels() if self._model_levels else registry.order

    def __contains__(self, value: object) -> bool:
        return value in self._keys()

    def __iter__(self) -> Iterator[str]:
        return iter(self._keys())

    def __len__(self) -> int:
        return len(self._keys())

    def __repr__(self) -> str:
        return repr(frozenset(self._keys()))


# Ascending sensitivity, from the one level registry, so the gateway and the platform classification service can
# never drift into two different orders.
DATA_CLASSIFICATION_ORDER: Sequence[str] = _LevelOrder()
DATA_CLASSIFICATION_LEVELS: Set[str] = _LevelSet()
# The levels a model may be cleared for (a gateway alias's ``data_policy_class``): every level whose
# ``models_allowed`` is on (the built-in top level, Secret, is not).
MODEL_DATA_POLICY_CLASSES: Set[str] = _LevelSet(model_levels=True)

# Where the effective classification came from. Closed: these reach evidence.
CLASSIFICATION_SOURCE_PROJECT_CONFIG = "project_config"
CLASSIFICATION_SOURCE_SESSION_RAISE = "session_raise"
CLASSIFICATION_SOURCE_UNRESOLVED = "unresolved"

# Fixed denial codes for a classification that cannot be used.
DENIAL_WORKSPACE_CLASS_MISSING = "workspace_data_classification_missing"
DENIAL_WORKSPACE_CLASS_UNKNOWN = "workspace_data_classification_unknown"
DENIAL_SESSION_CLASS_UNKNOWN = "session_data_classification_unknown"


def classification_rank(value: Any) -> int | None:
    """Return the sensitivity rank of a classification, or ``None`` if unknown."""

    normalized = normalized_classification(value)
    return level_registry().rank(normalized) if normalized else None


def normalized_classification(value: Any) -> str:
    """Lowercase a classification candidate without judging it."""

    return str(value or "").strip().lower()


def declared_classification(section: Any) -> str:
    if not isinstance(section, Mapping):
        return ""
    return normalized_classification(section.get(DATA_POLICY_CLASSIFICATION_FIELD))


@dataclass(frozen=True, slots=True)
class WorkspaceDataClassification:
    """The effective, server-resolved classification for one dispatch path.
    ``classification`` is empty exactly when ``reason`` says why no usable value exists."""

    classification: str
    source: str
    reason: str

    @property
    def resolved(self) -> bool:
        return bool(self.classification)

    @property
    def rank(self) -> int | None:
        return classification_rank(self.classification) if self.classification else None

    def evidence(self) -> dict[str, Any]:
        """Closed evidence about the classification, never about its contents."""

        return {
            "workspace_data_classification": self.classification,
            "workspace_data_classification_source": self.source,
        }


def unresolved_classification(reason: str) -> WorkspaceDataClassification:
    """A classification that denies, carrying the closed reason it denies for."""

    return WorkspaceDataClassification("", CLASSIFICATION_SOURCE_UNRESOLVED, reason)


# Deny-by-default classification for every path that resolved no project row.
UNRESOLVED_DATA_CLASSIFICATION = unresolved_classification(DENIAL_WORKSPACE_CLASS_MISSING)


def resolve_data_classification(
    *,
    project_data_policy: Any,
    session_data_policy: Any = None,
) -> WorkspaceDataClassification:
    """The effective classification from the project row's ``data_policy``; the session's may only raise it."""

    project_value = declared_classification(project_data_policy)
    if not project_value:
        return unresolved_classification(DENIAL_WORKSPACE_CLASS_MISSING)
    project_rank = classification_rank(project_value)
    if project_rank is None:
        return unresolved_classification(DENIAL_WORKSPACE_CLASS_UNKNOWN)

    session_value = declared_classification(session_data_policy)
    if not session_value:
        return WorkspaceDataClassification(project_value, CLASSIFICATION_SOURCE_PROJECT_CONFIG, "")
    session_rank = classification_rank(session_value)
    if session_rank is None:
        # An unreadable session value is refused rather than ignored: silently
        # continuing on the floor would make a broken writer look configured.
        return unresolved_classification(DENIAL_SESSION_CLASS_UNKNOWN)
    if session_rank <= project_rank:
        # Equal or lower never wins. The project floor is the authority; the
        # session may only tighten it.
        return WorkspaceDataClassification(project_value, CLASSIFICATION_SOURCE_PROJECT_CONFIG, "")
    return WorkspaceDataClassification(session_value, CLASSIFICATION_SOURCE_SESSION_RAISE, "")


__all__ = [
    "CLASSIFICATION_SOURCE_PROJECT_CONFIG",
    "CLASSIFICATION_SOURCE_SESSION_RAISE",
    "CLASSIFICATION_SOURCE_UNRESOLVED",
    "DATA_CLASSIFICATION_LEVELS",
    "DATA_CLASSIFICATION_ORDER",
    "DATA_POLICY_CLASSIFICATION_CLEARED_FIELD",
    "DATA_POLICY_CLASSIFICATION_FIELD",
    "DATA_POLICY_CONFIG_KEY",
    "DENIAL_SESSION_CLASS_UNKNOWN",
    "DENIAL_WORKSPACE_CLASS_MISSING",
    "DENIAL_WORKSPACE_CLASS_UNKNOWN",
    "MODEL_DATA_POLICY_CLASSES",
    "UNRESOLVED_DATA_CLASSIFICATION",
    "WorkspaceDataClassification",
    "classification_rank",
    "declared_classification",
    "normalized_classification",
    "resolve_data_classification",
    "unresolved_classification",
]
