"""Prompt variant routing from the database with its code fallback, the one-time seed and the locked workspace route."""

import pytest
from sqlalchemy import delete

from app.agent.core.prompts.prompt_builder import build_system_prompt
from app.agent.core.prompts.prompt_templates import (
    PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY,
    build_system_prompt_config_metadata,
    ensure_system_prompt_variant_routing,
    load_system_prompt_variant_routing,
    resolve_effective_system_prompt_config,
    resolve_system_prompt_variant,
)
from app.models import SystemConfig
from app.services.system_config import set_system_config_value
from tests.runtime_defaults_support import _Mode


@pytest.mark.asyncio
async def test_prompt_variant_routing_can_be_externalized_to_db(db) -> None:
    await set_system_config_value(
        db,
        key="agent.system_prompt.variant_map",
        value='{"standard":"summary"}',
    )
    await db.commit()

    routing = await load_system_prompt_variant_routing(db)
    mode = _Mode("diagnosis", "Diagnosis", "diagnosis")

    prompt = build_system_prompt(
        agent_type="diagnosis",
        agent_mode=mode,
        personality="",
        memory="",
        skills="",
        prompt_variant="standard",
        thinking_level="deep",
        prompt_variant_routing=routing,
    )

    assert resolve_system_prompt_variant("standard", prompt_variant_routing=routing) == "summary"
    assert "For cross-system summaries or daily digests" in prompt
    assert "Selected mode: light" in prompt


@pytest.mark.asyncio
async def test_prompt_variant_routing_falls_back_to_code_defaults_when_db_value_is_invalid(db) -> None:
    await set_system_config_value(
        db,
        key="agent.system_prompt.variant_map",
        value='{"standard":"not-a-real-variant"}',
    )
    await db.commit()

    routing = await load_system_prompt_variant_routing(db)
    mode = _Mode("diagnosis", "Diagnosis", "diagnosis")

    prompt = build_system_prompt(
        agent_type="diagnosis",
        agent_mode=mode,
        personality="",
        memory="",
        skills="",
        prompt_variant="standard",
        thinking_level="deep",
        prompt_variant_routing=routing,
    )

    assert routing == {}
    assert resolve_system_prompt_variant("standard", prompt_variant_routing=routing) == "full"
    assert "Use deeper reasoning before responding" in prompt


@pytest.mark.asyncio
async def test_prompt_variant_routing_returns_empty_mapping_when_json_is_malformed(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_get_system_config_value(*_args, **_kwargs) -> str:
        return "{"

    monkeypatch.setattr(
        "app.agent.core.prompts.prompt_templates.get_system_config_value",
        _fake_get_system_config_value,
    )

    routing = await load_system_prompt_variant_routing(db)

    assert routing == {}


@pytest.mark.asyncio
async def test_variant_routing_seed_is_written_once_and_never_over_an_edit(db) -> None:
    await db.execute(delete(SystemConfig).where(SystemConfig.key == "agent.system_prompt.variant_map"))
    await db.commit()

    assert await ensure_system_prompt_variant_routing(db) is True
    routing = await load_system_prompt_variant_routing(db)
    await set_system_config_value(db, key="agent.system_prompt.variant_map", value='{"standard":"summary"}')
    assert await ensure_system_prompt_variant_routing(db) is False

    assert routing["bounded_evidence"] == "bounded_evidence"
    assert routing["standard"] == "full"
    assert await load_system_prompt_variant_routing(db) == {"standard": "summary"}


def test_workspace_variant_routing_wins_and_the_bounded_route_stays_locked() -> None:
    effective = resolve_effective_system_prompt_config(
        prompt_variant_routing={"standard": "full", "bounded_evidence": "bounded_evidence"},
        project_config={
            PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY: {"variant_routing": {"standard": "minimal", "bounded_evidence": "full"}}
        },
        project_id="project-1",
    )
    standard = build_system_prompt_config_metadata(
        requested_variant="standard",
        prompt_variant_routing=effective.variant_routing,
        routing_sources=effective.routing_sources,
        scope=effective.scope,
    )
    bounded = build_system_prompt_config_metadata(
        requested_variant="bounded_evidence",
        prompt_variant_routing=effective.variant_routing,
        routing_sources=effective.routing_sources,
        scope=effective.scope,
    )

    assert effective.variant_routing == {"standard": "minimal", "bounded_evidence": "bounded_evidence"}
    assert standard["scope"] == {
        "type": "project",
        "project_id": "project-1",
        "config_key": PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY,
        "routing_overrides": ["bounded_evidence", "standard"],
    }
    assert standard["resolved_variant"] == "minimal"
    assert standard["routing"]["source"] == "project"
    # The template is named by its catalog reference from the bound prompt set (the seed in unit tests).
    assert standard["template"]["key"] == "system.base.minimal"
    assert standard["template"]["ref"] == "system.base.minimal@seed"
    assert standard["template"]["digest"].startswith("sha256:")
    assert bounded["resolved_variant"] == "bounded_evidence"
