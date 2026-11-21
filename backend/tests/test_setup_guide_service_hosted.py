"""With hosted providers only, the setup guide is ready without a local anchor unless credentials, a cleared workspace model or a priced default under cost caps is missing."""

import uuid

import pytest
from sqlalchemy import select

from app.models import LLMModel, LLMProvider, Project, User
from app.services.model_selection.platform_order import save_order
from app.services.setup_guide import get_setup_guide_status
from app.time_utils import utc_now


def _hosted_provider(*, with_key: bool) -> LLMProvider:
    return LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        provider_family="openrouter",
        driver="openrouter_api",
        runtime_kind="api",
        display_name="Hosted API",
        auth_mode="api_key",
        api_key_secret_ref=str(uuid.uuid4()) if with_key else None,
        is_global=True,
        is_active=True,
    )


def _active_model(provider: LLMProvider, model_id: str) -> LLMModel:
    return LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id=model_id,
        display_name=model_id,
        supports_tools=True,
        supports_streaming=True,
        is_active=True,
        last_synced_at=utc_now(),
    )


async def _make_first(db, model: LLMModel) -> None:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await save_order(db, model_keys=[model.catalog_key], fallback="next", actor_id=admin.id)
    await db.commit()


@pytest.mark.asyncio
async def test_hosted_only_setup_is_ready_without_local_anchor(db):
    provider = _hosted_provider(with_key=True)
    db.add(provider)
    await db.flush()
    model = _active_model(provider, "anthropic/claude-sonnet")
    model.cleared_up_to = "internal"
    db.add(model)
    await db.commit()
    await _make_first(db, model)

    status = await get_setup_guide_status(db)
    by_key = {step["key"]: step for step in status["steps"]}

    assert status["ready"] is True
    assert "local_anchor" not in by_key  # offered only while no provider can run
    assert by_key["models"]["status"] == "completed"
    assert by_key["default"]["status"] == "completed"
    assert by_key["default"]["detail"] == "anthropic/claude-sonnet is #1 and answers."


@pytest.mark.asyncio
async def test_hosted_provider_without_credentials_keeps_the_anchor_blocking(db):
    provider = _hosted_provider(with_key=False)
    db.add(provider)
    await db.flush()
    model = _active_model(provider, "anthropic/claude-sonnet")
    model.cleared_up_to = "internal"
    db.add(model)
    await db.commit()
    await _make_first(db, model)

    status = await get_setup_guide_status(db)
    by_key = {step["key"]: step for step in status["steps"]}

    assert status["ready"] is False
    # The model is #1, but only on a provider that may not run, so the default does not answer.
    assert by_key["default"]["status"] == "pending"
    assert "its provider cannot run" in by_key["default"]["detail"]


@pytest.mark.asyncio
async def test_a_workspace_without_a_cleared_model_is_named(db):
    provider = _hosted_provider(with_key=True)
    db.add(provider)
    await db.flush()
    model = _active_model(provider, "internal-only")
    model.cleared_up_to = "internal"
    db.add(model)
    db.add(Project(id=str(uuid.uuid4()), name="Vault", is_active=True,
                   config={"data_policy": {"classification": "restricted"}}))
    await db.commit()
    await _make_first(db, model)

    by_key = {step["key"]: step for step in (await get_setup_guide_status(db))["steps"]}

    assert by_key["workspaces"]["status"] == "pending"
    assert "no model cleared for their data class" in by_key["workspaces"]["detail"]
    assert by_key["workspaces"]["action"] == "open_explain"


@pytest.mark.asyncio
async def test_an_unpriced_default_under_cost_caps_is_not_ready(db):
    """A fresh install's first model has no price; with the default block policy every turn is refused."""
    from app.services.budget.unpriced_guard import POLICY_BLOCK, POLICY_WARN, set_unpriced_model_policy

    provider = _hosted_provider(with_key=True)
    db.add(provider)
    await db.flush()
    model = _active_model(provider, "anthropic/claude-sonnet")
    model.cleared_up_to = "internal"
    db.add(model)
    await db.commit()
    await _make_first(db, model)
    await set_unpriced_model_policy(db, POLICY_BLOCK)
    await db.commit()
    try:
        status = await get_setup_guide_status(db)
        by_key = {step["key"]: step for step in status["steps"]}
        assert status["ready"] is False
        assert by_key["default"]["status"] == "pending"
        assert "has no price" in by_key["default"]["detail"]

        model.pricing_input, model.pricing_output = 3.0, 15.0
        await db.commit()
        by_key = {step["key"]: step for step in (await get_setup_guide_status(db))["steps"]}
        assert by_key["default"]["status"] == "completed"
    finally:
        await set_unpriced_model_policy(db, POLICY_WARN)
        await db.commit()


@pytest.mark.asyncio
async def test_an_unpriced_default_under_warn_is_a_notice_not_a_blocker(db):
    provider = _hosted_provider(with_key=True)
    db.add(provider)
    await db.flush()
    model = _active_model(provider, "anthropic/claude-sonnet")
    model.cleared_up_to = "internal"
    db.add(model)
    await db.commit()
    await _make_first(db, model)

    status = await get_setup_guide_status(db)
    by_key = {step["key"]: step for step in status["steps"]}
    assert status["ready"] is True
    assert by_key["prices"]["blocking"] is False
    assert by_key["prices"]["detail"] == "anthropic/claude-sonnet has no price – costs are not counted."
    assert by_key["prices"]["action"] == "open_model_catalog"
