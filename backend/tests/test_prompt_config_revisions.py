"""Prompt config revision ledger: system prompt variant routing (templates in the prompt catalog)."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import delete, select

from app.agent.core.prompts.prompt_templates import PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY
from app.models import Project, PromptConfigRevision, SystemConfig
from app.services.prompt_governance import (
    record_project_prompt_revisions,
    rollback_prompt_config_revision,
)
from app.services.system_config import set_system_config_value
from app.services.system_config.constants import AGENT_SYSTEM_PROMPT_VARIANT_CONFIG_KEY


@pytest.mark.asyncio
async def test_global_variant_routing_revisions_skip_unchanged_and_roll_back(db, auth_user):
    config_key = AGENT_SYSTEM_PROMPT_VARIANT_CONFIG_KEY
    await _clear_prompt_key(db, config_key)
    first = json.dumps({"standard": "minimal"})

    await set_system_config_value(db, key=config_key, value=first, updated_by=auth_user.id)
    await set_system_config_value(db, key=config_key, value=first, updated_by=auth_user.id)
    await set_system_config_value(db, key=config_key, value=json.dumps({"standard": "full"}), updated_by=auth_user.id)

    revisions = (
        await db.execute(
            select(PromptConfigRevision)
            .where(PromptConfigRevision.config_key == config_key)
            .order_by(PromptConfigRevision.version.asc())
        )
    ).scalars().all()
    assert [revision.version for revision in revisions] == [1, 2]

    rollback = await rollback_prompt_config_revision(db, revision_id=revisions[0].id, created_by=auth_user.id)

    assert (await db.get(SystemConfig, config_key)).value == first
    assert rollback.version == 3
    assert rollback.change_source == "rollback"


@pytest.mark.asyncio
async def test_project_variant_routing_revision_rolls_back_the_override(db, auth_user):
    project = Project(id=str(uuid.uuid4()), name=f"prompt-rollback-{uuid.uuid4()}", config={})
    db.add(project)
    await db.flush()
    first = {PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY: {"variant_routing": {"standard": "minimal"}}}
    second = {PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY: {"variant_routing": {"standard": "summary"}}}

    first_revision = (
        await record_project_prompt_revisions(
            db, project_id=project.id, before_config={}, after_config=first, created_by=auth_user.id
        )
    )[0]
    project.config = second
    await record_project_prompt_revisions(
        db, project_id=project.id, before_config=first, after_config=second, created_by=auth_user.id
    )
    rollback = await rollback_prompt_config_revision(db, revision_id=first_revision.id, created_by=auth_user.id)

    assert project.config[PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY]["variant_routing"]["standard"] == "minimal"
    assert rollback.version == 3


async def _clear_prompt_key(db, config_key: str) -> None:
    await db.execute(delete(PromptConfigRevision).where(PromptConfigRevision.config_key == config_key))
    await db.execute(delete(SystemConfig).where(SystemConfig.key == config_key))
    await db.flush()
