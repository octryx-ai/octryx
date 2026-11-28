"""The start dialog's "Automatic" names the governed model that is configured, never a fixed one."""

from __future__ import annotations

import pytest
from sqlalchemy import update

from app.models import ControlPlaneRuntimeTarget
from app.services.workflow_runs.runtime_target.target import auto_help, governed_model_label


@pytest.mark.asyncio
async def test_automatic_names_the_first_active_runtimes_model_and_provider(db):
    assert await governed_model_label(db) == "baseline-model (LiteLLM (Default))"
    text = await auto_help(db)
    assert text.startswith("Uses a free seat on your device first. Otherwise it runs governed with "
                           "baseline-model (LiteLLM (Default))")
    assert "Bedrock" not in text


@pytest.mark.asyncio
async def test_without_an_active_runtime_it_says_the_platforms_model(db):
    await db.execute(update(ControlPlaneRuntimeTarget).values(is_active=False))
    await db.flush()
    assert await governed_model_label(db) is None
    assert "governed with the platform's model" in await auto_help(db)


@pytest.mark.asyncio
async def test_a_public_model_api_without_a_key_says_governed_cannot_run(db):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.services.workflow_runs.runtime_target.target import GOVERNED_KEY_MISSING, governed_key_missing

    target = (await db.execute(select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.is_active.is_(True))
                               .options(selectinload(ControlPlaneRuntimeTarget.provider))
                               .order_by(ControlPlaneRuntimeTarget.priority, ControlPlaneRuntimeTarget.created_at)
                               .limit(1))).scalars().first()
    provider = target.provider
    assert not await governed_key_missing(db)
    provider.endpoint_url, provider.auth_mode, provider.api_key_secret_ref = "https://api.anthropic.com/v1", "api_key", None
    await db.flush()
    assert await governed_key_missing(db)
    text = await auto_help(db)
    assert GOVERNED_KEY_MISSING in text and "octryx-claude login --seat" in text and "runs governed with" not in text
    provider.endpoint_url = "http://127.0.0.1:8080/v1"
    await db.flush()
    assert not await governed_key_missing(db)
