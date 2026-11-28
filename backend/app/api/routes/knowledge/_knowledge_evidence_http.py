"""One status and detail mapping for the Knowledge Evidence outcome taxonomy."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import HTTPException

from ....services.knowledge.ledger.errors import WORKSPACE_NOT_FOUND_DETAIL, EvidenceLedgerError, EvidenceLedgerState

STATE_HEADER = "X-Knowledge-State"

logger = logging.getLogger(__name__)

STATUS_BY_STATE: dict[EvidenceLedgerState, tuple[int, str]] = {
    EvidenceLedgerState.DENIED: (403, "Access denied for this workspace."),
    EvidenceLedgerState.NOT_FOUND: (404, WORKSPACE_NOT_FOUND_DETAIL),
    EvidenceLedgerState.INVALID_REQUEST: (400, "Invalid knowledge evidence request."),
    EvidenceLedgerState.UNSUPPORTED_MEDIA_TYPE: (
        415,
        "This media type is not supported: upload a text document (txt, md, adoc, html, csv, json, xml) "
        "or a PDF/Office document (pdf, docx, pptx, xlsx).",
    ),
    # Real misconfiguration of the instance: an administrator must act.
    EvidenceLedgerState.NEEDS_CONFIGURATION: (503, "Workspace knowledge storage is not configured."),
    # A healthy instance with a Workspace that is not searchable yet: a state of the Workspace, not a failure.
    EvidenceLedgerState.NO_SOURCES: (409, "This Workspace has no knowledge sources yet. Add a source to search it."),
    EvidenceLedgerState.PROJECTION_PENDING: (
        409,
        "This Workspace's knowledge sources are not searchable yet: their projection is pending. "
        "Try again when it has run.",
    ),
    EvidenceLedgerState.UNAVAILABLE: (503, "Workspace knowledge storage is unavailable."),
    EvidenceLedgerState.LIMIT_EXCEEDED: (413, "Payload exceeds the supported size limit."),
    EvidenceLedgerState.CONTRACT_VIOLATION: (502, "Workspace knowledge dependency failed."),
}
FALLBACK_STATUS = (502, "Workspace knowledge dependency failed.")


def evidence_http_error(
    error: EvidenceLedgerError, *, details_by_error_type: Mapping[type, str] | None = None
) -> HTTPException:
    status_code, detail = STATUS_BY_STATE.get(error.state, FALLBACK_STATUS)
    if details_by_error_type is not None:
        detail = details_by_error_type.get(type(error), detail)
    logger.info("Workspace knowledge request refused: state=%s", error.state.value)
    return HTTPException(status_code=status_code, detail=detail, headers={STATE_HEADER: error.state.value})
