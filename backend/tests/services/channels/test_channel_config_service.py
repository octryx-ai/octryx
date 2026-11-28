import uuid
from datetime import UTC, datetime

import pytest

from app.models.integration.channel_config import ChannelConfig
from app.models.project.project import Project
from app.services.channel_config import ChannelConfigService


@pytest.mark.asyncio
async def test_channel_config_service_create_and_get_all_preserve_existing_behavior(db) -> None:
    project = Project(id=str(uuid.uuid4()), name="Project Alpha")
    db.add(project)
    await db.commit()

    created = await ChannelConfigService.create(
        db,
        plugin_id="slack",
        name="   ",
        project_id=project.id,
        enabled=True,
        config={"channel": "alerts"},
    )

    assert created.name == "slack"
    assert created.project_id == project.id
    assert created.project_name == "Project Alpha"
    assert created.config == {"channel": "alerts"}

    configs = await ChannelConfigService.get_all(db)

    assert len(configs) == 1
    assert configs[0].id == created.id
    assert configs[0].project_name == "Project Alpha"


def test_channel_config_service_to_response_handles_corrupt_json() -> None:
    config = ChannelConfig(
        id=1,
        plugin_id="slack",
        name="Broken config",
        project_id=None,
        enabled=True,
        config="{not-json",
        updated_at=datetime.now(UTC),
    )

    payload = ChannelConfigService._to_response(config)

    assert payload.config == {}
