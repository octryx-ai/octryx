"""The setup guide is ready once a gateway model runs, unless credentials or a cleared workspace model is missing."""

import uuid

import pytest
from sqlalchemy import select

from app.models import LLMModel, LLMProvider, Project, User
from app.services.model_selection.platform_order import save_order
from app.services.setup_guide import get_setup_guide_status
from app.time_utils import utc_now
from tests.model_gateway.conftest import ALIAS, gateway_provider


def _hosted_provider(*, with_key: bool) -> LLMProvider:
    return gateway_provider(display_name="Hosted API", is_global=True,
                            api_key_secret_ref=str(uuid.uuid4()) if with_key else None)


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
async def test_a_runnable_gateway_model_makes_the_setup_ready(db):
    provider = _hosted_provider(with_key=True)
    db.add(provider)
    await db.flush()
    model = _active_model(provider, ALIAS)
    model.cleared_up_to = "internal"
    db.add(model)
    await db.commit()
    await _make_first(db, model)

    status = await get_setup_guide_status(db)
    by_key = {step["key"]: step for step in status["steps"]}

    assert status["ready"] is True
    assert by_key["models"]["status"] == "completed"
    assert by_key["default"]["status"] == "completed"
    assert by_key["default"]["detail"] == f"{ALIAS} is #1 and answers."


@pytest.mark.asyncio
async def test_a_gateway_without_credentials_keeps_the_default_pending(db):
    provider = _hosted_provider(with_key=False)
    db.add(provider)
    await db.flush()
    model = _active_model(provider, ALIAS)
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
