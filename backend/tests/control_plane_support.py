"""Shared runtime target cleanup and provider API key setup for the test_control_plane_* modules."""

from sqlalchemy import select

from app.models import ControlPlaneRuntimeTarget
from app.services.secret import set_secret_value


async def _clear_runtime_targets(db):
    targets = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().all()
    for target in targets:
        await db.delete(target)
    await db.flush()


async def _set_provider_api_key_secret(db, provider, value):
    entry = await set_secret_value(
        db,
        tool_name=f"control_plane_provider:{provider.id}",
        field_name="api_key",
        project_id=None,
        value=value,
    )
    provider.api_key_secret_ref = entry.id
