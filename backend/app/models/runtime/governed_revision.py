"""Shared lifecycle vocabulary and immutability guard for governed revisions.

Governed revisions (Model Policies, prompt templates) share one lifecycle:
``draft -> in_review -> published -> retired``. A revision leaves ``draft`` only
through review, is published only with a distinct approver (four-eyes), and is
immutable from the moment it is published: afterwards the only permitted change
is the explicit move to ``retired``, and a retired revision never changes again.

The guard below enforces that at the ORM boundary, so no alternate writer (a
worker, a script, a future endpoint) can rewrite published content by accident.
It is registered per model class with :func:`install_immutability_guard`.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import event, inspect

#: A revision digest: ``sha256:`` plus 64 hex characters.
DIGEST_LENGTH = 71

REVISION_STATE_DRAFT = "draft"
REVISION_STATE_IN_REVIEW = "in_review"
REVISION_STATE_PUBLISHED = "published"
REVISION_STATE_RETIRED = "retired"

REVISION_STATES: tuple[str, ...] = (
    REVISION_STATE_DRAFT,
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_PUBLISHED,
    REVISION_STATE_RETIRED,
)

#: States whose content is frozen.
FROZEN_REVISION_STATES = frozenset({REVISION_STATE_PUBLISHED, REVISION_STATE_RETIRED})

REGISTRY_STATUS_ACTIVE = "active"
REGISTRY_STATUS_RETIRED = "retired"
REGISTRY_STATUSES: tuple[str, ...] = (REGISTRY_STATUS_ACTIVE, REGISTRY_STATUS_RETIRED)

#: The only columns a published revision may still change, and only while retiring.
_RETIRE_COLUMNS = frozenset({"state", "retired_by", "retired_at", "updated_at"})


class ImmutableRevisionError(Exception):
    """A write tried to change a published or retired revision."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def in_list(column: str, values: Iterable[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def published_requires_approval_check() -> str:
    """CHECK body: a published or retired-after-publish row carries its approval and time."""
    return "state NOT IN ('published') OR (approval_id IS NOT NULL AND published_at IS NOT NULL)"


def _persisted_state(target: object) -> str | None:
    history = inspect(target).attrs.state.history
    if history.deleted:
        return history.deleted[0]
    if history.unchanged:
        return history.unchanged[0]
    return getattr(target, "state", None)


def _changed_columns(target: object) -> set[str]:
    state = inspect(target)
    return {prop.key for prop in state.mapper.column_attrs if state.attrs[prop.key].history.has_changes()}


def _guard_update(_mapper, _connection, target) -> None:
    previous = _persisted_state(target)
    if previous not in FROZEN_REVISION_STATES:
        return
    changed = _changed_columns(target)
    if not changed:
        return
    if previous == REVISION_STATE_RETIRED:
        raise ImmutableRevisionError("revision_retired_immutable")
    if target.state != REVISION_STATE_RETIRED or not changed <= _RETIRE_COLUMNS:
        raise ImmutableRevisionError("revision_published_immutable")


def _guard_delete(_mapper, _connection, target) -> None:
    if _persisted_state(target) in FROZEN_REVISION_STATES:
        raise ImmutableRevisionError("revision_published_undeletable")


def install_immutability_guard(model_class: type) -> None:
    event.listen(model_class, "before_update", _guard_update)
    event.listen(model_class, "before_delete", _guard_delete)


__all__ = [
    "FROZEN_REVISION_STATES",
    "REGISTRY_STATUSES",
    "REGISTRY_STATUS_ACTIVE",
    "REGISTRY_STATUS_RETIRED",
    "REVISION_STATES",
    "REVISION_STATE_DRAFT",
    "REVISION_STATE_IN_REVIEW",
    "REVISION_STATE_PUBLISHED",
    "REVISION_STATE_RETIRED",
    "ImmutableRevisionError",
    "in_list",
    "install_immutability_guard",
    "published_requires_approval_check",
]
