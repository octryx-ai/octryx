"""Shared helpers for the test_runtime_readiness_fail_closed_* modules."""

import uuid

from sqlalchemy import select

from app.models import ControlPlaneRuntimeTarget, LLMProvider
from app.models.runtime.provider_oauth_config import ProviderOAuthConfig
from app.services.control_plane_service import upsert_runtime_target


async def _clear_runtime_targets(db):
    for target in (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().all():
        await db.delete(target)
    await db.flush()


async def _bedrock_target(db, *, credentials_configured: bool, model_id: str = "anthropic.claude-sonnet-4-6"):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="bedrock",
        driver="bedrock_api",
        display_name=f"Bedrock {uuid.uuid4().hex[:6]}",
        auth_mode="aws_credentials",
        aws_region="eu-central-1",
        default_model_id=model_id,
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    if credentials_configured:
        db.add(ProviderOAuthConfig(provider_id=provider.id, aws_static_credentials_configured=True))
        await db.flush()
    target = await upsert_runtime_target(db, provider=provider, model_id=model_id, make_primary=True, is_active=True)
    await db.commit()
    return provider, target
