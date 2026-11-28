"""Shared helpers for the test_runtime_readiness_fail_closed_* modules."""

import uuid

from sqlalchemy import select

from app.models import ControlPlaneRuntimeTarget
from app.services.control_plane_service import upsert_runtime_target
from app.services.model_gateway.litellm.readiness import READINESS_REASON_VIRTUAL_KEY_NOT_CONFIGURED
from tests.model_gateway.conftest import ALIAS, gateway_provider

#: The readiness reason of a gateway target without its virtual key.
KEY_MISSING = READINESS_REASON_VIRTUAL_KEY_NOT_CONFIGURED


async def _clear_runtime_targets(db):
    for target in (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().all():
        await db.delete(target)
    await db.flush()


def restore_key(provider) -> None:
    provider.api_key_secret_ref = str(uuid.uuid4())


async def _gateway_target(db, *, credentials_configured: bool, model_id: str = ALIAS):
    provider = gateway_provider(display_name=f"Gateway {uuid.uuid4().hex[:6]}", default_model_id=model_id,
                                is_global=True,
                                api_key_secret_ref=str(uuid.uuid4()) if credentials_configured else None)
    db.add(provider)
    await db.flush()
    target = await upsert_runtime_target(db, provider=provider, model_id=model_id, make_primary=True, is_active=True)
    await db.commit()
    return provider, target
