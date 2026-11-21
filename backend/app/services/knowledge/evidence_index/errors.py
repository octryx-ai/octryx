"""Fixed, secret-safe failure taxonomy of the Evidence index boundary.

Every error carries a stable ``state``. Messages are fixed per class and the constructors accept no
free text, so no statement, bound value or driver message can reach a public error. The client raises
them outside ``except`` blocks, so no driver exception is chained as ``__cause__`` or ``__context__``.
"""

from __future__ import annotations

from enum import StrEnum


class EvidenceIndexState(StrEnum):
    """Stable, distinguishable outcome states of the Evidence index."""

    UNAVAILABLE = "unavailable"
    CONTRACT_VIOLATION = "contract_violation"


class EvidenceIndexError(Exception):
    """Base class; ``state`` is the explicit outcome a caller must surface."""

    state: EvidenceIndexState = EvidenceIndexState.UNAVAILABLE
    default_message = "evidence index failed"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class EvidenceIndexUnavailableError(EvidenceIndexError):
    """The database did not answer the statement (connection, timeout or statement failure)."""

    state = EvidenceIndexState.UNAVAILABLE
    default_message = "evidence index is unavailable"


class EvidenceIndexContractError(EvidenceIndexError):
    """A call outside the registry, with the wrong parameters, or an answer outside the contract."""

    state = EvidenceIndexState.CONTRACT_VIOLATION
    default_message = "evidence index call violated the registry contract"


__all__ = [
    "EvidenceIndexContractError",
    "EvidenceIndexError",
    "EvidenceIndexState",
    "EvidenceIndexUnavailableError",
]
