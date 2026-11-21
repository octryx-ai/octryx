import pytest

from app.services.model_selection.platform_order import order_targets
from app.services.system_config.values import get_agent_default_model


@pytest.mark.asyncio
async def test_the_default_model_is_number_one_of_the_platform_order(db):
    first = (await order_targets(db))[0]

    assert await get_agent_default_model(db) == first.model_id


@pytest.mark.asyncio
async def test_without_an_active_runtime_target_there_is_no_default_model(db):
    for target in await order_targets(db):
        target.is_active = False
    await db.commit()

    assert await get_agent_default_model(db) == ""
