import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Personality, User
from ...schemas.core.personality import PersonalityResponse, PersonalityUpdate
from ...services.auth import get_current_user

router = APIRouter(prefix="/api/v1/personality", tags=["personality"])


@router.get("", response_model=PersonalityResponse)
async def get_personality(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Personality).where(Personality.user_id == current_user.id))
    personality = result.scalar_one_or_none()

    if not personality:
        personality = Personality(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
        )
        db.add(personality)
        await db.commit()

    return _to_response(personality)


@router.put("", response_model=PersonalityResponse)
async def update_personality(
    body: PersonalityUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Personality).where(Personality.user_id == current_user.id))
    personality = result.scalar_one_or_none()

    if not personality:
        personality = Personality(id=str(uuid.uuid4()), user_id=current_user.id)
        db.add(personality)

    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(personality, field, value)

    await db.commit()
    return _to_response(personality)


def _to_response(p: Personality) -> PersonalityResponse:
    return PersonalityResponse(
        id=p.id,
        user_id=p.user_id,
        language=p.language,
        detail_level=p.detail_level,
        communication_style=p.communication_style,
        output_format=p.output_format,
        custom_prompt=p.custom_prompt,
        timezone=p.timezone,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
    )
