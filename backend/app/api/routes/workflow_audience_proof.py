"""Authenticated personal Inbox action; challenge coordinates are not authority."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.workflow_runs.documentation.audience_contract import AudienceProofError

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.workflow_runs.documentation.proof_actor import record_owned_challenge

router = APIRouter()


@router.post("/audience-receipts/{challenge_id}/record")
async def record_personal_audience_check(
    challenge_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await record_owned_challenge(db, current_user, challenge_id)
    except AudienceProofError as error:
        await db.commit()
        raise HTTPException(error.status, detail={"code": error.code,
                            "detail": "Audience proof could not be recorded."}) from None
    except EvidenceLedgerError:
        await db.rollback()
        raise HTTPException(503, detail="Knowledge is unavailable for this audience check.") from None
