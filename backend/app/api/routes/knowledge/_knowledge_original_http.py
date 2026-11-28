"""Coded refusals of the Knowledge original routes (original bytes, display view, revision diff)."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from ....services.knowledge.ledger.errors import (
    EvidenceLedgerError,
    EvidenceRecordNotFoundError,
    WorkspaceNotAccessibleError,
)
from ....services.knowledge.ledger.original_errors import (
    OriginalLocationMismatchError,
    OriginalNotDisplayableError,
    OriginalNotStoredError,
    OriginalObjectMissingError,
)
from ._knowledge_evidence_http import FALLBACK_STATUS, STATUS_BY_STATE

logger = logging.getLogger(__name__)

CODE_WORKSPACE_NOT_FOUND = "workspace_not_found"
CODE_REVISION_NOT_FOUND = "revision_not_found"
CODE_ORIGINAL_NOT_STORED = "original_not_stored"
CODE_ORIGINAL_LOCATION_MISMATCH = "original_location_mismatch"
CODE_ORIGINAL_OBJECT_MISSING = "original_object_missing"
CODE_ORIGINAL_NOT_DISPLAYABLE = "original_not_displayable"

# (status, code, message) per error class; the order of checks is exact type, so subclasses never collide.
CODED_REFUSALS: dict[type[EvidenceLedgerError], tuple[int, str, str]] = {
    WorkspaceNotAccessibleError: (404, CODE_WORKSPACE_NOT_FOUND, "Workspace not found or not accessible."),
    EvidenceRecordNotFoundError: (
        404,
        CODE_REVISION_NOT_FOUND,
        "This revision does not exist for this source, is not visible to you, or was removed.",
    ),
    OriginalNotStoredError: (404, CODE_ORIGINAL_NOT_STORED, "No original is stored for this revision."),
    OriginalLocationMismatchError: (
        409,
        CODE_ORIGINAL_LOCATION_MISMATCH,
        "The original of this revision is recorded outside this deployment's knowledge storage partition.",
    ),
    OriginalObjectMissingError: (
        404,
        CODE_ORIGINAL_OBJECT_MISSING,
        "The original of this revision is missing in the knowledge object store.",
    ),
    OriginalNotDisplayableError: (
        415,
        CODE_ORIGINAL_NOT_DISPLAYABLE,
        "This original cannot be displayed as text; download it instead.",
    ),
}


def original_http_error(error: EvidenceLedgerError) -> HTTPException:
    coded = CODED_REFUSALS.get(type(error))
    if coded is None:
        status_code, message = STATUS_BY_STATE.get(error.state, FALLBACK_STATUS)
        code = error.state.value
    else:
        status_code, code, message = coded
    logger.info("Knowledge original request refused: code=%s", code)
    return HTTPException(status_code=status_code, detail={"code": code, "detail": message})


__all__ = [
    "CODED_REFUSALS",
    "CODE_ORIGINAL_LOCATION_MISMATCH",
    "CODE_ORIGINAL_NOT_DISPLAYABLE",
    "CODE_ORIGINAL_NOT_STORED",
    "CODE_ORIGINAL_OBJECT_MISSING",
    "CODE_REVISION_NOT_FOUND",
    "CODE_WORKSPACE_NOT_FOUND",
    "original_http_error",
]
