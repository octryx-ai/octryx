"""S4.2, D-S4-4: an API-authored fragment version is published by a second admin; a shipped seed is exempt."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AuditLog
from app.services.flow_draft_service import save_flow_draft
from app.services.governance.approval_rule import APPROVAL_RULE_CONFIG_KEY
from app.services.governance.four_eyes import SELF_APPROVAL_AUDIT_ACTION
from app.services.system_config.values import set_system_config_value
from app.services.workflow_runs.fragments.store import FRAGMENT_SEED_MARKER
from tests.policy_engine_support import bearer
from tests.s4_fragment_support import (
    FLOWS,
    create,
    digest,
    make_admin,
    probe_fragment,
    publish,
    unique_key,
    version_row,
)


@pytest.mark.asyncio
async def test_the_author_cannot_publish_their_own_fragment_and_a_second_admin_can(db):
    author, reviewer = await make_admin(db), await make_admin(db)
    created = await create(db, author, unique_key("s4-probe-confirm"), probe_fragment())
    version_id = created["versions"][0]["id"]

    with pytest.raises(HTTPException) as refused:
        await publish(db, version_id, author)
    assert refused.value.status_code == 409 and refused.value.detail["reason"] == "fragment_four_eyes"
    assert (await version_row(db, version_id)).status == "draft"

    await publish(db, version_id, reviewer)
    row = await version_row(db, version_id)
    assert row.status == "published" and row.published_by == reviewer.id
    assert row.publish_metadata["approval_mode"] == "four_eyes"


@pytest.mark.asyncio
async def test_the_platform_single_admin_rule_lets_the_author_publish_and_is_audited(db):
    author = await make_admin(db)
    await set_system_config_value(db, key=APPROVAL_RULE_CONFIG_KEY, value="single_admin")
    created = await create(db, author, unique_key("s4-probe-confirm"), probe_fragment())
    version_id = created["versions"][0]["id"]

    await publish(db, version_id, author)
    row = await version_row(db, version_id)
    assert row.status == "published" and row.publish_metadata["approval_mode"] == "self"
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == SELF_APPROVAL_AUDIT_ACTION,
                                                     AuditLog.resource_id == version_id))).scalar_one()
    assert audit.user_id == author.id and audit.details["approval_mode"] == "self"


@pytest.mark.asyncio
async def test_a_seeded_fragment_is_exempt(db):
    seeder = await make_admin(db)
    definition = probe_fragment()
    created = await create(db, seeder, unique_key("sf-seed"), definition,
                           runtime_settings={"seed": FRAGMENT_SEED_MARKER, "seed_digest": digest(definition)})
    version_id = created["versions"][0]["id"]
    await publish(db, version_id, seeder)
    assert (await version_row(db, version_id)).status == "published"

    saved = await save_flow_draft(db, flow_id=created["id"], current_user=seeder, payload={
        "expected_latest_version_id": version_id, "definition": probe_fragment(label="Edited"), "name": "seed"})
    draft = max(saved["versions"], key=lambda item: item["version"])
    assert "seed" not in draft["runtime_settings"] and "seed_digest" not in draft["runtime_settings"]
    with pytest.raises(HTTPException) as refused:
        await publish(db, draft["id"], seeder)
    assert refused.value.detail["reason"] == "fragment_four_eyes"


@pytest.mark.asyncio
async def test_the_api_never_marks_a_fragment_as_a_seed(client, db):
    author = await make_admin(db)
    await db.commit()
    definition = probe_fragment()
    created = await client.post(FLOWS, headers=bearer(author.id), json={
        "key": unique_key("s4-forged"), "name": "Forged", "definition": definition,
        "runtime_settings": {"seed": FRAGMENT_SEED_MARKER, "seed_digest": digest(definition), "keep": 1}})
    assert created.status_code == 200, created.text
    version = created.json()["versions"][0]
    assert version["runtime_settings"] == {"keep": 1}
    own = await client.post(f"{FLOWS}/versions/{version['id']}/publish", headers=bearer(author.id))
    assert own.status_code == 409 and own.json()["detail"]["reason"] == "fragment_four_eyes"
