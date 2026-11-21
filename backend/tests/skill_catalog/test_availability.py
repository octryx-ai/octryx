"""Availability flags — per version, reviewed, with write-time invariants per surface."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project, Skill
from app.services.skill_catalog.effective import effective_skills
from tests.policy_engine_support import bearer, make_user
from tests.skill_catalog.fake_git import MARKET_LATER, OFFICIAL
from tests.skill_catalog.support import BASE, category, force_publish

# Two published chat-only skills as a fixture.
pytestmark = pytest.mark.usefixtures("chat_skills")


async def _save(client, admin, skill_id, version, etag, **payload):
    return await client.put(f"{BASE}/skills/{skill_id}/versions/{version}", json=payload,
                            headers={**bearer(admin), "If-Match": etag})


@pytest.mark.asyncio
async def test_availability_changes_only_through_a_reviewed_version(client, db):
    admin = await make_user(db, admin=True)
    project_id = (await db.execute(select(Project.id).where(Project.name == "acme-orders"))).scalar_one()
    docs = (await category(db, "engineering.documentation")).id
    created = await client.post(f"{BASE}/skills", headers=bearer(admin), json={
        "name": "notes-writer", "category_id": docs, "frontmatter": {"description": "d"}, "body": "\n# N\n",
        "available_octryx_claude": False})
    skill_id = created.json()["skill_id"]
    await force_publish(db, skill_id, approver_id=admin)
    chat = {item.skill.name for item in await effective_skills(db, project_id=project_id, surface="platform_chat")}
    claude = {item.skill.name for item in await effective_skills(db, project_id=project_id, surface="octryx_claude")}
    assert "notes-writer" in chat and "notes-writer" not in claude
    draft = (await client.post(f"{BASE}/skills/{skill_id}/edit", headers=bearer(admin))).json()
    saved = await _save(client, admin, skill_id, 2, draft["digest"], available_octryx_claude=True,
                        available_platform_chat=False)
    assert saved.json()["digest"] != draft["digest"]
    still = {item.skill.name for item in await effective_skills(db, project_id=project_id, surface="octryx_claude")}
    assert "notes-writer" not in still  # the draft is not delivered until it is published
    await force_publish(db, skill_id, approver_id=admin)
    chat = {item.skill.name for item in await effective_skills(db, project_id=project_id, surface="platform_chat")}
    claude = {item.skill.name for item in await effective_skills(db, project_id=project_id, surface="octryx_claude")}
    assert "notes-writer" not in chat and "notes-writer" in claude
    listed = (await client.get(f"{BASE}/skills", params={"surface": "octryx_claude"}, headers=bearer(admin))).json()
    assert "notes-writer" in {row["name"] for row in listed["items"]}


@pytest.mark.asyncio
async def test_an_mcp_entry_never_becomes_a_chat_skill(client, db, fake_git):
    admin = await make_user(db, admin=True)
    terraform = (await category(db, "iac.terraform")).id
    imported = await client.post(f"{BASE}/import/git", headers=bearer(admin), json={
        "url": OFFICIAL, "ref": "main", "marketplace_plugin": "terraform", "commit": MARKET_LATER,
        "items": [{"kind": "mcp_server", "path": "external_plugins/terraform", "name": "terraform",
                   "category_id": terraform}]})
    skill_id = imported.json()["imported"][0]["skill_id"]
    version = (await client.get(f"{BASE}/skills/{skill_id}/versions/1", headers=bearer(admin))).json()
    refused = await _save(client, admin, skill_id, 1, version["digest"], available_platform_chat=True)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "skill_mcp_not_on_platform_chat"


@pytest.mark.asyncio
async def test_a_legacy_name_outside_the_spec_is_never_delivered_to_claude_code(client, db):
    admin = await make_user(db, admin=True)
    skill = (await db.execute(select(Skill).where(Skill.name == "alert-diagnosis"))).scalar_one()
    skill_id = skill.id
    skill.name = "Alert Diagnosis"  # a pre-catalog name the spec does not allow
    await db.commit()
    draft = (await client.post(f"{BASE}/skills/{skill_id}/edit", headers=bearer(admin))).json()
    assert draft["state"] == "draft", draft
    refused = await _save(client, admin, skill_id, 2, draft["digest"], available_octryx_claude=True)
    assert refused.json()["detail"]["code"] == "skill_name_not_deliverable"
