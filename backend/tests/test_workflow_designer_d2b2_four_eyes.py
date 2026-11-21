"""The author of a draft requests a review and a second admin publishes it; without review the author cannot publish unless they are the single admin, and an invalid draft cannot be put up for review."""

from __future__ import annotations

import uuid

import pytest

from app.models import FlowDefinitionVersion
from app.services.governance.approval_rule import APPROVAL_RULE_CONFIG_KEY
from app.services.system_config.values import set_system_config_value
from tests.policy_engine_support import bearer
from tests.s4_fragment_support import FLOWS, make_admin
from tests.workflow_designer_d2b2_support import result_definition

# --- 4. four-eyes publish ----------------------------------------------------------------------------------------

async def _draft(client, author, definition: dict | None = None, **extra) -> dict:
    created = await client.post(FLOWS, headers=bearer(author.id), json={
        "key": f"d2b2-{uuid.uuid4().hex[:8]}", "name": "Assess", "definition": definition or result_definition(),
        **extra})
    assert created.status_code == 200, created.text
    return created.json()["versions"][0]


def _version(flow: dict, version_id: str) -> dict:
    return next(item for item in flow["versions"] if item["id"] == version_id)


@pytest.mark.asyncio
async def test_the_author_requests_a_review_and_a_second_admin_publishes(client, db):
    author, reviewer = await make_admin(db), await make_admin(db)
    await db.commit()
    version = await _draft(client, author)

    stranger = await client.post(f"{FLOWS}/versions/{version['id']}/request-review", headers=bearer(reviewer.id))
    assert stranger.status_code == 403
    requested = await client.post(f"{FLOWS}/versions/{version['id']}/request-review", headers=bearer(author.id))
    assert requested.status_code == 200, requested.text
    row = _version(requested.json(), version["id"])
    assert row["status"] == "draft"
    assert row["publish_metadata"]["review"]["state"] == "awaiting_approval"
    assert row["publish_metadata"]["review"]["requested_by"] == author.id

    own = await client.post(f"{FLOWS}/versions/{version['id']}/publish", headers=bearer(author.id),
                            json={"publish_metadata": {"approval_mode": "four_eyes"}})
    assert own.status_code == 409 and own.json()["detail"]["reason"] == "workflow_four_eyes"

    published = await client.post(f"{FLOWS}/versions/{version['id']}/publish", headers=bearer(reviewer.id),
                                  json={"publish_metadata": {"approval_mode": "self"}})
    assert published.status_code == 200, published.text
    row = _version(published.json(), version["id"])
    assert row["status"] == "published" and row["published_by"] == reviewer.id
    # The request body never states its own approval: the decision's mode is written last.
    assert row["publish_metadata"]["approval_mode"] == "four_eyes"
    review = row["publish_metadata"]["review"]
    assert (review["state"], review["requested_by"], review["approved_by"]) == ("approved", author.id, reviewer.id)


@pytest.mark.asyncio
async def test_the_author_cannot_publish_without_review_and_a_seed_marker_does_not_exempt(client, db):
    author = await make_admin(db)
    await db.commit()
    from app.services.workflow_runs.seeding import SEED_MARKER, definition_digest

    definition = result_definition()
    version = await _draft(client, author, definition, runtime_settings={
        "seed": SEED_MARKER, "seed_digest": definition_digest(definition)})
    assert "seed" not in version["runtime_settings"]  # only the seeders mark a seed
    own = await client.post(f"{FLOWS}/versions/{version['id']}/publish", headers=bearer(author.id))
    assert own.status_code == 409 and own.json()["detail"]["reason"] == "workflow_four_eyes"


@pytest.mark.asyncio
async def test_the_single_admin_rule_lets_the_author_publish(client, db):
    author = await make_admin(db)
    await set_system_config_value(db, key=APPROVAL_RULE_CONFIG_KEY, value="single_admin",
                                  record_prompt_revision=False)
    await db.commit()
    version = await _draft(client, author)
    published = await client.post(f"{FLOWS}/versions/{version['id']}/publish", headers=bearer(author.id))
    assert published.status_code == 200, published.text
    metadata = _version(published.json(), version["id"])["publish_metadata"]
    assert metadata["approval_mode"] == "self" and metadata["review"]["state"] == "approved"


@pytest.mark.asyncio
async def test_an_invalid_draft_cannot_be_put_up_for_review(client, db):
    author = await make_admin(db)
    await db.commit()
    version = await _draft(client, author)
    row = await db.get(FlowDefinitionVersion, version["id"])
    broken = result_definition()
    broken["edges"] = [edge for edge in broken["edges"] if edge["id"] != "n"]
    row.definition_json = broken
    await db.commit()
    refused = await client.post(f"{FLOWS}/versions/{version['id']}/request-review", headers=bearer(author.id))
    assert refused.status_code == 422
    assert any(error["code"] == "decision_unrouted" for error in refused.json()["detail"]["errors"])
