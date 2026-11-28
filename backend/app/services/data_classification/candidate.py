"""A candidate classification policy for previews."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .policy_rules import ClassificationPolicy

_candidate: ContextVar[ClassificationPolicy | None] = ContextVar("classification_policy_candidate", default=None)


@contextmanager
def candidate_policy(policy: ClassificationPolicy) -> Iterator[None]:
    token = _candidate.set(policy)
    try:
        yield
    finally:
        _candidate.reset(token)


def current_candidate() -> ClassificationPolicy | None:
    return _candidate.get()


__all__ = ["candidate_policy", "current_candidate"]
