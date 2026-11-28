"""Whose seat reviews a run, and on which of the person's devices."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, UserDevice, WorkflowRun

SOURCE_REQUESTER = "requester"


async def seat_person(db: AsyncSession, run: WorkflowRun) -> tuple[User | None, str]:
    from ...pr_review_bot.seat_choice import bot_seat_person, is_bot_run

    if is_bot_run(run):
        chosen = await bot_seat_person(db, run)
        return (chosen.user, chosen.source) if chosen is not None else (None, "")
    return (await db.get(User, run.requested_by) if run.requested_by else None), SOURCE_REQUESTER


async def seat_phases(db: AsyncSession, run: WorkflowRun) -> list[list[tuple[User, str]]]:
    from ...pr_review_bot.seat_choice import bot_seat_phases, is_bot_run

    if is_bot_run(run):
        return [[(person.user, person.source) for person in phase] for phase in await bot_seat_phases(db, run)]
    user = await db.get(User, run.requested_by) if run.requested_by else None
    return [[(user, SOURCE_REQUESTER)]] if user is not None else []


def _any_folder(device: UserDevice) -> str:
    return next((str(folder) for folder in device.folders or [] if str(folder).strip()), "")


async def folderless_devices(db: AsyncSession, user: User, known: list[UserDevice]) -> list[tuple[UserDevice, str]]:
    from ....models.security.device import DEVICE_STATUS_ACTIVE

    devices = (await db.execute(select(UserDevice).where(
        UserDevice.owner_user_id == user.id, UserDevice.status == DEVICE_STATUS_ACTIVE,
    ).order_by(UserDevice.name))).scalars().all()
    ids = {device.id for device in known}
    return [(device, _any_folder(device)) for device in devices if device.id not in ids and _any_folder(device)]


__all__ = ["SOURCE_REQUESTER", "folderless_devices", "seat_person", "seat_phases"]
