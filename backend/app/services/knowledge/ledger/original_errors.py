"""Precise outcomes of opening one revision's original."""

from __future__ import annotations

from .errors import EvidenceLedgerError, EvidenceLedgerState


class OriginalNotStoredError(EvidenceLedgerError):
    state = EvidenceLedgerState.NOT_FOUND
    default_message = "no original is stored for this revision"


class OriginalLocationMismatchError(EvidenceLedgerError):
    state = EvidenceLedgerState.NEEDS_CONFIGURATION
    default_message = "the original is recorded outside this deployment's object partition"


class OriginalObjectMissingError(EvidenceLedgerError):
    state = EvidenceLedgerState.NOT_FOUND
    default_message = "the original object is missing in the object store"


class OriginalNotDisplayableError(EvidenceLedgerError):
    state = EvidenceLedgerState.UNSUPPORTED_MEDIA_TYPE
    default_message = "this original cannot be displayed as text"


__all__ = [
    "OriginalLocationMismatchError",
    "OriginalNotDisplayableError",
    "OriginalNotStoredError",
    "OriginalObjectMissingError",
]
