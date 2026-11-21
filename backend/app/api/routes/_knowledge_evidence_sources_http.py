"""Error details and the authoring check shared by the Workspace Knowledge source route modules."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ...services.knowledge.ingestion.spans import MAX_SPANS_PER_REVISION
from ...services.knowledge.ingestion.text_ingest import MAX_TEXT_BYTES, MAX_UPLOAD_BYTES
from ...services.knowledge.ledger.errors import (
    EvidenceLedgerError,
    EvidenceParserNotConfiguredError,
    EvidencePayloadTooLargeError,
    EvidenceSpanLimitExceededError,
)
from ._knowledge_evidence_http import evidence_http_error

_BYTE_LIMIT_DETAIL = (
    f"Payload exceeds the supported size limit: {MAX_TEXT_BYTES} bytes for text documents, "
    f"{MAX_UPLOAD_BYTES} bytes for PDF and Office documents."
)


# The state -> status mapping is shared with every other Workspace Knowledge route
# module (``_knowledge_evidence_http``). Two different capacity limits share
# ``limit_exceeded`` on this surface, and a caller can only act on the one that was
# actually hit, so each names its own bound here.
_DETAIL_BY_ERROR_TYPE = {
    EvidencePayloadTooLargeError: _BYTE_LIMIT_DETAIL,
    EvidenceSpanLimitExceededError: (
        f"Document splits into more than {MAX_SPANS_PER_REVISION} evidence spans. "
        "Split it into smaller documents and upload them separately."
    ),
    EvidenceParserNotConfiguredError: (
        "PDF and Office documents are parsed in the Docling sandbox, which this Instance has not configured."
    ),
}


def _http_error(error: EvidenceLedgerError) -> HTTPException:
    return evidence_http_error(error, details_by_error_type=_DETAIL_BY_ERROR_TYPE)


async def authorize_author(db: AsyncSession, current_user: User, workspace_id: str) -> AuthorizedWorkspace:
    """The Workspace for a caller with the authoring role; a reader gets 403, ledger errors map as on every route."""
    try:
        return await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id, require_author=True)
    except WorkspaceWriteForbiddenError:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError as error:
        raise _http_error(error) from None
