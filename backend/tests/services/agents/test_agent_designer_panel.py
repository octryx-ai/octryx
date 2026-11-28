"""Agent Designer panel routes: governed save, owner scope, publish, configuration."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDefinitionRevision, AgentStep
from app.services.agent_definition_execution_states import AGENT_DEFINITION_EXECUTION_MODE_KEY
from app.services.system_config.values import set_system_config_value
from app.web.routers.panel_agent_designer import designer_origin
from tests.agent_definition_revision_fixtures import make_definition, make_user
from tests.conftest import ADMIN_PASSWORD

AGENT = {
    "name": "Designer Agent",
    "description": "Built visually",
    "goal": "Prove the designer path",
    "agent_type": "diagnosis",
    "thinking_level": "light",
    "branch_prefix": "octryx",
    "is_active": True,
}


async def _login_and_create(client: AsyncClient) -> str:
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303
    created = await client.post("/admin/chat/api/panel/agents", json=AGENT)
    assert created.status_code == 200
    return created.json()["id"]


async def _revision_count(db: AsyncSession, agent_id: str) -> int:
    return (
        await db.execute(select(func.count()).where(AgentDefinitionRevision.definition_id == agent_id))
    ).scalar_one()


def _two_step_document(loaded: dict) -> dict:
    document = loaded["document"]
    nodes = document["definition"]["nodes"]
    first = {
        "id": "new-1",
        "title": "Research",
        "node_type": "SingleLLMCallNode",
        "config": {"system_message": "Find."},
    }
    second = {"id": "new-2", "title": "Write", "node_type": "AgentNode", "config": {"system_message": "Write."}}
    document["definition"]["nodes"] = [nodes[0], first, second, nodes[-1]]
    document["definition"]["links"] = [
        {"source_id": "octryx-input", "target_id": "new-1"},
        {"source_id": "new-1", "target_id": "new-2"},
        {"source_id": "new-2", "target_id": "octryx-output"},
    ]
    return document


@pytest.mark.asyncio
async def test_saving_a_document_writes_the_steps_as_one_draft_revision(client: AsyncClient, db: AsyncSession) -> None:
    agent_id = await _login_and_create(client)
    loaded = (await client.get(f"/admin/chat/api/panel/agents/{agent_id}/designer-document")).json()
    before = await _revision_count(db, agent_id)

    saved = await client.put(
        f"/admin/chat/api/panel/agents/{agent_id}/designer-document", json={"document": _two_step_document(loaded)}
    )

    assert saved.status_code == 200
    body = saved.json()
    assert body["revision"]["status"] == "draft"
    assert await _revision_count(db, agent_id) == before + 1
    steps = (
        (await db.execute(select(AgentStep).where(AgentStep.agent_id == agent_id).order_by(AgentStep.position)))
        .scalars()
        .all()
    )
    assert [(step.position, step.name, step.instructions) for step in steps] == [
        (1, "Research", "Find."),
        (2, "Write", "Write."),
    ]
    # The reloaded document shows the same chain; step ids are now the stored ones.
    titles = [node["title"] for node in body["document"]["definition"]["nodes"]]
    assert titles == ["Input", "Research", "Write", "Output"]

    assert body["changed"] is True
    published = await client.post(
        f"/admin/chat/api/panel/agents/{agent_id}/designer-document/publish",
        json={"revision_id": body["revision"]["id"]},
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"


@pytest.mark.asyncio
async def test_the_document_says_which_content_a_run_executes(client: AsyncClient, db: AsyncSession) -> None:
    agent_id = await _login_and_create(client)
    url = f"/admin/chat/api/panel/agents/{agent_id}/designer-document"
    loaded = (await client.get(url)).json()
    # Unset key: the draft default runs the saved live definition; nothing is published yet.
    assert loaded["execution"] == {"mode": "draft", "published_revision_number": None}

    published = await client.post(f"{url}/publish", json={"revision_id": loaded["revision"]["id"]})
    assert published.status_code == 200
    await set_system_config_value(db, key=AGENT_DEFINITION_EXECUTION_MODE_KEY, value="published", description="test")
    await db.commit()

    execution = (await client.get(url)).json()["execution"]
    assert execution == {"mode": "published", "published_revision_number": published.json()["revision_number"]}


@pytest.mark.asyncio
async def test_publish_refuses_a_revision_that_is_no_longer_the_newest(client: AsyncClient, db: AsyncSession) -> None:
    agent_id = await _login_and_create(client)
    loaded = (await client.get(f"/admin/chat/api/panel/agents/{agent_id}/designer-document")).json()
    shown = loaded["revision"]["id"]
    # Another writer (the Agents form) adds a newer revision after the designer was loaded.
    renamed = await client.put(f"/admin/chat/api/panel/agents/{agent_id}", json={"name": "Renamed elsewhere"})
    assert renamed.status_code == 200

    refused = await client.post(
        f"/admin/chat/api/panel/agents/{agent_id}/designer-document/publish", json={"revision_id": shown}
    )
    assert refused.status_code == 409


@pytest.mark.asyncio
async def test_a_second_save_removes_dropped_steps_and_keeps_foreign_step_settings(
    client: AsyncClient, db: AsyncSession
) -> None:
    agent_id = await _login_and_create(client)
    loaded = (await client.get(f"/admin/chat/api/panel/agents/{agent_id}/designer-document")).json()
    first = (
        await client.put(
            f"/admin/chat/api/panel/agents/{agent_id}/designer-document", json={"document": _two_step_document(loaded)}
        )
    ).json()
    steps = (await db.execute(select(AgentStep).where(AgentStep.agent_id == agent_id))).scalars().all()
    kept = next(step for step in steps if step.name == "Research")
    kept.step_config = {**kept.step_config, "authored_elsewhere": True}
    await db.commit()

    document = first["document"]
    nodes = document["definition"]["nodes"]
    research = next(node for node in nodes if node["title"] == "Research")
    document["definition"]["nodes"] = [nodes[0], research, nodes[-1]]
    document["definition"]["links"] = [
        {"source_id": nodes[0]["id"], "target_id": research["id"]},
        {"source_id": research["id"], "target_id": nodes[-1]["id"]},
    ]
    saved = await client.put(f"/admin/chat/api/panel/agents/{agent_id}/designer-document", json={"document": document})

    assert saved.status_code == 200
    db.expire_all()
    remaining = (await db.execute(select(AgentStep).where(AgentStep.agent_id == agent_id))).scalars().all()
    assert [(step.id, step.name) for step in remaining] == [(kept.id, "Research")]
    assert remaining[0].step_config["authored_elsewhere"] is True


@pytest.mark.asyncio
async def test_over_long_fields_are_refused_not_cut(client: AsyncClient, db: AsyncSession) -> None:
    agent_id = await _login_and_create(client)
    loaded = (await client.get(f"/admin/chat/api/panel/agents/{agent_id}/designer-document")).json()
    document = _two_step_document(loaded)
    document["definition"]["nodes"][1]["title"] = "x" * 201

    refused = await client.put(
        f"/admin/chat/api/panel/agents/{agent_id}/designer-document", json={"document": document}
    )

    assert refused.status_code == 422
    assert refused.json()["issues"] == [{"code": "field_too_long", "node_ids": ["new-1"]}]


@pytest.mark.asyncio
async def test_a_refused_document_changes_nothing(client: AsyncClient, db: AsyncSession) -> None:
    agent_id = await _login_and_create(client)
    loaded = (await client.get(f"/admin/chat/api/panel/agents/{agent_id}/designer-document")).json()
    document = _two_step_document(loaded)
    document["definition"]["nodes"].append({"id": "r", "title": "Route", "node_type": "RouterNode", "config": {}})
    before = await _revision_count(db, agent_id)

    refused = await client.put(
        f"/admin/chat/api/panel/agents/{agent_id}/designer-document", json={"document": document}
    )

    assert refused.status_code == 422
    assert refused.json() == {
        "state": "invalid_document",
        "issues": [{"code": "unsupported_node_type", "node_ids": ["r"]}],
    }
    assert await _revision_count(db, agent_id) == before


@pytest.mark.asyncio
async def test_another_owners_definition_is_not_found(client: AsyncClient, db: AsyncSession) -> None:
    await _login_and_create(client)
    other = await make_user(db, label="designer-other")
    foreign = await make_definition(db, owner=other)
    await db.commit()

    assert (await client.get(f"/admin/chat/api/panel/agents/{foreign.id}/designer-document")).status_code == 404


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:8091", "http://localhost:8091"),
        ("https://designer.example.test/", "https://designer.example.test"),
        ("https://designer.example.test:443", "https://designer.example.test"),
        ("http://localhost:80", "http://localhost"),
        (None, None),
        ("http://localhost:8091/path", None),
        ("javascript:alert(1)", None),
        ("http://user:pw@localhost:8091", None),
    ],
)
def test_only_an_exact_origin_is_accepted_as_designer_origin(raw, expected) -> None:
    assert designer_origin(raw) == expected
