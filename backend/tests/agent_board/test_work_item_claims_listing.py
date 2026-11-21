"""who_is_working_on matches items in scope, and REST lists claims for members and lets admins release them."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog, User
from app.services.mcp_work_claim_tools import who_is_working_on
from tests.agent_board.support import agent, scope_for, seed_item, seed_presence
from tests.agent_board.work_item_claims_support import _claim, _two_members
from tests.agent_gateway.seat_presence_support import _bearer, _workspace
from tests.knowledge_evidence_seed_support import seed_member, seed_outsider

CLAIMS = "/api/v1/agent-board/claims"


# --- who_is_working_on --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_who_is_working_on_matches_key_title_epic_paths_and_presence_in_scope(db):
    workspace_id, anna, ben = await _two_members(db)
    item = await seed_item(db, workspace_id, "BRD-7", title="Rework billing export", epic="BRD-EPIC")
    await _claim(db, await agent(db, anna), item, paths=["src/billing"])
    await seed_presence(db, anna, workspace_id, work_item_key="BRD-7")
    other_ws = await _workspace(db)
    outsider_item = await seed_item(db, other_ws, "BRD-8", title="Rework billing elsewhere")
    stranger = await seed_member(db, workspace_id=other_ws, role="member")
    await _claim(db, await agent(db, stranger), outsider_item, paths=["src/billing"])
    user, scope = await scope_for(db, ben)

    async def ask(**arguments):
        return await who_is_working_on(db, user=user, scope=scope, arguments=arguments)

    for query in ("brd-7", "billing EXPORT", "BRD-EPIC"):
        answer = await ask(query=query)
        assert [claim["work_item"]["key"] for claim in answer["claims"]] == ["BRD-7"], query
    by_path = await ask(paths=["src/billing/export.py"])
    by_parent = await ask(paths=["./src/"])
    assert [c["work_item"]["key"] for c in by_path["claims"]] == [c["work_item"]["key"] for c in by_parent["claims"]]
    assert [c["work_item"]["key"] for c in by_path["claims"]] == ["BRD-7"]  # never another Workspace's claim
    assert (await ask(paths=["docs"]))["claims"] == []
    assert (await ask(query="BRD-7"))["presence"][0]["work_item"]["key"] == "BRD-7"
    assert (await ask(query="nothing"))["presence"] == [] and "content_is_data" in by_path
    unclear = await ask()
    assert unclear["state"] == "needs_clarification" and unclear["claims"] == [] and "content_is_data" in unclear


# --- REST --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rest_claims_are_listed_for_members_and_released_by_admins(client, db):
    workspace_id, anna, ben = await _two_members(db)
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    outsider = await seed_outsider(db)
    item = await seed_item(db, workspace_id, "BRD-3", title="Ship it")
    claimed = await _claim(db, await agent(db, anna), item, paths=["src"])
    await db.commit()

    listed = await client.get(CLAIMS, params={"project_id": workspace_id}, headers=await _bearer(ben))
    hidden = await client.get(CLAIMS, params={"project_id": workspace_id}, headers=await _bearer(outsider))
    by_member = await client.post(f"{CLAIMS}/{claimed['claim_id']}/release", headers=await _bearer(ben))
    by_outsider = await client.post(f"{CLAIMS}/{claimed['claim_id']}/release", headers=await _bearer(outsider))
    missing = await client.post(f"{CLAIMS}/nope/release", headers=await _bearer(owner))
    by_owner = await client.post(f"{CLAIMS}/{claimed['claim_id']}/release", headers=await _bearer(owner))
    after = await client.get(CLAIMS, params={"project_id": workspace_id}, headers=await _bearer(ben))

    entry = listed.json()["items"][0]
    assert set(entry) == {"id", "work_item", "holder", "epoch", "lease_until", "paths", "claimed_at"}
    assert entry["work_item"] == {"id": item.id, "key": "BRD-3", "title": "Ship it"}
    assert entry["holder"]["user"]["id"] == anna and entry["holder"]["kind"] == "mcp_session"
    assert (hidden.status_code, by_outsider.status_code, missing.status_code) == (404, 404, 404)
    assert by_member.status_code == 403
    assert by_owner.status_code == 200 and by_owner.json()["release_reason"] == "admin_released"
    assert after.json() == {"items": [], "viewer": {"user_id": ben, "can_admin": False}}
    assert (await client.get(CLAIMS, params={"project_id": workspace_id}, headers=await _bearer(owner))).json()[
        "viewer"] == {"user_id": owner, "can_admin": True}
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "agent_board.claim.admin_released"))).scalar_one()
    assert (audit.user_id, audit.resource_id) == (owner, claimed["claim_id"])


@pytest.mark.asyncio
async def test_a_platform_admin_may_release_any_claim(client, db):
    workspace_id, anna, _ = await _two_members(db)
    claimed = await _claim(db, await agent(db, anna), await seed_item(db, workspace_id))
    await db.commit()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    released = await client.post(f"{CLAIMS}/{claimed['claim_id']}/release", headers=await _bearer(admin.id))
    assert released.status_code == 200 and released.json()["release_reason"] == "admin_released"
