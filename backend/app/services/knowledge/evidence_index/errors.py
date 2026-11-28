"""Fixed, secret-safe failure taxonomy of the Evidence index boundary. Constructors take no free text, and nothing is
chained from a driver exception."""

from __future__ import annotations

from enum import StrEnum


class EvidenceIndexState(StrEnum):
    UNAVAILABLE = "unavailable"
    CONTRACT_VIOLATION = "contract_violation"


class EvidenceIndexError(Exception):
    state: EvidenceIndexState = EvidenceIndexState.UNAVAILABLE
    default_message = "evidence index failed"

    def __init__(self) -> None:
        super().__init__(self.default_message)


class EvidenceIndexUnavailableError(EvidenceIndexError):
    state = EvidenceIndexState.UNAVAILABLE
    default_message = "evidence index is unavailable"


class EvidenceIndexContractError(EvidenceIndexError):
    state = EvidenceIndexState.CONTRACT_VIOLATION
    default_message = "evidence index call violated the registry contract"


__all__ = [
    "EvidenceIndexContractError",
    "EvidenceIndexError",
    "EvidenceIndexState",
    "EvidenceIndexUnavailableError",
]
