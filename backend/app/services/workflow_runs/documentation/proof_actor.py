"""Personal Inbox audience checks under the caller's real authentication."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import DocumentationAudienceReceipt, User
from ...knowledge.runtime import get_evidence_runtime
from .audience_contract import AudienceProofError
from .receipt_record import record_audience_receipt


async def record_owned_challenge(db: AsyncSession, user: User, challenge_id: str) -> dict:
    receipt = (await db.execute(select(DocumentationAudienceReceipt).where(
        DocumentationAudienceReceipt.challenge_id == challenge_id,
        DocumentationAudienceReceipt.expected_principal_id == user.id,
    ))).scalar_one_or_none()
    if receipt is None:
        raise AudienceProofError("unknown_challenge", "no such audience challenge", status=404)
    recorded = await record_audience_receipt(
        db, current_user=user, workspace_id=receipt.workspace_id,
        proof_request={"challenge_id": challenge_id}, runtime=get_evidence_runtime(),
    )
    from .s1_graph import audience_receipt_recorded

    await audience_receipt_recorded(db, receipt.run_id)
    # No page, run, query or hit metadata in the personal action response.
    return {"proof": recorded}
