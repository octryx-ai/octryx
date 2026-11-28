"""Exact-plan clarification answers. Role and Work Item scope are checked before the service runs, so a refused request
never reaches a provider and writes nothing."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.secure_work.access import get_scoped_change_plan, require_work_operator
from ....services.secure_work.plans.clarification_answers import answer_plan_clarifications
from ....services.secure_work.plans.clarification_revision import MAX_ANSWER_CHARS, MAX_ANSWERS, MAX_QUESTION_CHARS

router = APIRouter(tags=["secure-work"])


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_index: int = Field(ge=0)
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    answer: str = Field(max_length=MAX_ANSWER_CHARS * 2)


class ClarificationAnswersRequest(BaseModel):
    """Answers to one plan version's open questions; no model, runtime or workflow fields."""

    model_config = ConfigDict(extra="forbid")

    expected_latest_version: int = Field(ge=1)
    answers: list[ClarificationAnswer] = Field(min_length=1, max_length=MAX_ANSWERS)


@router.post("/change-plans/{change_plan_id}/clarification-answers")
async def post_change_plan_clarification_answers(
    change_plan_id: str,
    payload: ClarificationAnswersRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_change_plan(db, current_user, change_plan_id)
    result = await answer_plan_clarifications(
        db,
        change_plan_id=change_plan_id,
        current_user=current_user,
        expected_latest_version=payload.expected_latest_version,
        answers=[entry.model_dump() for entry in payload.answers],
    )
    await db.commit()
    return result
