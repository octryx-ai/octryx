"""Precise outcomes of opening one revision's original.

A single Workspace 404 for every refusal would make a missing object read exactly like an
unknown Workspace. These classes keep the ledger's secret-safe shape (fixed message, no
free text) and add the distinctions a person can act on *after* the Workspace and the
revision are known to be readable:

- the revision exists but no original object is recorded for it;
- the ledger points at a key outside this deployment's Workspace partition (the
  configured prefix and the ledger disagree);
- the object is absent in the configured store;
- the original is not text, so it can be downloaded but not displayed or diffed.

The Workspace refusal (``WorkspaceNotAccessibleError``) and the record refusal
(``EvidenceRecordNotFoundError``) stay indistinguishable inside their own class: an
unknown, foreign, ACL-hidden, or tombstoned revision is still one outcome.
"""

from __future__ import annotations

from .errors import EvidenceLedgerError, EvidenceLedgerState


class OriginalNotStoredError(EvidenceLedgerError):
    """The revision is readable, but its ledger row records no object to open."""

    state = EvidenceLedgerState.NOT_FOUND
    default_message = "no original is stored for this revision"


class OriginalLocationMismatchError(EvidenceLedgerError):
    """The recorded key lies outside this Workspace's partition under the configured prefix."""

    state = EvidenceLedgerState.NEEDS_CONFIGURATION
    default_message = "the original is recorded outside this deployment's object partition"


class OriginalObjectMissingError(EvidenceLedgerError):
    """The recorded object does not exist in the configured object store."""

    state = EvidenceLedgerState.NOT_FOUND
    default_message = "the original object is missing in the object store"


class OriginalNotDisplayableError(EvidenceLedgerError):
    """A PDF or Office original, or bytes that are not UTF-8 text: download only."""

    state = EvidenceLedgerState.UNSUPPORTED_MEDIA_TYPE
    default_message = "this original cannot be displayed as text"


__all__ = [
    "OriginalLocationMismatchError",
    "OriginalNotDisplayableError",
    "OriginalNotStoredError",
    "OriginalObjectMissingError",
]
