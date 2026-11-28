"""A Workspace's governance alias through ``PUT /api/v1/workspaces/{ws}/content-handling/governance-alias``."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, UserProject, WorkspaceContentGovernance, WorkspaceContentHandling
from app.services.content_security import handling_settings
from app.services.content_security.handling import SURFACE_GATEWAY, SURFACE_PLATFORM, content_handling
from tests.factories import make_project
from tests.policy_engine_support import bearer, make_user

ALIAS = "approved-model"
OTHER = "approved-other"


async def _workspace(db) -> str:
    return (await make_project(db, name=f"governance-{uuid.uuid4().hex[:6]}", commit=True)).id


async def _member(db, workspace_id: str, role: str) -> str:
    user_id = await make_user(db, admin=False)
    db.add(UserProject(user_id=user_id, project_id=workspace_id, role=role))
    await db.commit()
    return user_id


def _url(workspace_id: str, path: str = "governance-alias") -> str:
    return f"/api/v1/workspaces/{workspace_id}/content-handling/{path}"


@pytest.fixture(autouse=True)
def aliases(monkeypatch):
    async def approvals(_db):
        return {ALIAS: frozenset({"pii"}), OTHER: frozenset({"pii"})}

    monkeypatch.setattr(handling_settings, "alias_approvals", approvals)


async def _audits(db) -> list[dict]:
    db.expire_all()
    rows = (await db.execute(select(AuditLog).where(AuditLog.action == "content_handling.changed")
                             .order_by(AuditLog.created_at))).scalars().all()
    return [row.details for row in rows]


async def _stored(db) -> list[tuple[str, str]]:
    db.expire_all()
    rows = (await db.execute(select(WorkspaceContentGovernance))).scalars().all()
    return [(row.workspace_id, row.governance_alias) for row in rows]


async def test_an_admin_sets_changes_and_clears_the_alias_and_every_change_is_audited(client, db) -> None:
    workspace = await _workspace(db)
    admin = await _member(db, workspace, "admin")

    answer = await client.put(_url(workspace), headers=bearer(admin), json={"alias": f" {ALIAS} "})
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"workspace_id": workspace, "governance_alias": ALIAS}
    view = (await client.get(f"/api/v1/workspaces/{workspace}/content-handling", headers=bearer(admin))).json()
    assert view["governance_alias"] == ALIAS
    assert all("reroute_alias" not in item for item in view["kinds"]), "per-kind aliases are gone"
    assert (await client.put(_url(workspace), headers=bearer(admin), json={"alias": ALIAS})).status_code == 200
    assert (await client.put(_url(workspace), headers=bearer(admin), json={"alias": OTHER})).status_code == 200
    cleared = await client.put(_url(workspace), headers=bearer(admin), json={"alias": None})
    assert cleared.json() == {"workspace_id": workspace, "governance_alias": None}
    assert (await client.put(_url(workspace), headers=bearer(admin), json={"alias": None})).status_code == 200

    assert await _stored(db) == []
    assert await _audits(db) == [
        {"workspace_id": workspace, "kind": "governance_alias", "old": None, "new": ALIAS},
        {"workspace_id": workspace, "kind": "governance_alias", "old": ALIAS, "new": OTHER},
        {"workspace_id": workspace, "kind": "governance_alias", "old": OTHER, "new": None},
    ], "an unchanged alias writes no audit row"
    rows = (await db.execute(select(AuditLog).where(AuditLog.action == "content_handling.changed"))).scalars().all()
    assert {(row.user_id, row.resource_type, row.resource_id) for row in rows} == {
        (admin, "workspace_content_handling", f"{workspace}:governance_alias")}


async def test_a_member_gets_403_and_an_outsider_404(client, db) -> None:
    workspace = await _workspace(db)
    member = await _member(db, workspace, "member")
    outsider = await make_user(db, admin=False)
    assert (await client.put(_url(workspace), headers=bearer(member), json={"alias": ALIAS})).status_code == 403
    for target in (workspace, str(uuid.uuid4())):
        answer = await client.put(_url(target), headers=bearer(outsider), json={"alias": ALIAS})
        assert answer.status_code == 404 and answer.json()["detail"]["code"] == "project_not_found"
    platform_admin = await make_user(db, admin=True)
    assert (await client.put(_url(workspace), headers=bearer(platform_admin),
                             json={"alias": ALIAS})).status_code == 200
    assert await _stored(db) == [(workspace, ALIAS)]


@pytest.mark.parametrize("body", [{"alias": "not-a-gateway-alias"}, {"alias": "  "}, {"alias": 3}, {}, ["x"]])
async def test_an_alias_that_is_not_an_active_governed_alias_is_refused(client, db, body) -> None:
    workspace = await _workspace(db)
    admin = await _member(db, workspace, "admin")
    answer = await client.put(_url(workspace), headers=bearer(admin), json=body)
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "content_handling_alias_unknown"
    assert await _stored(db) == [] and await _audits(db) == []


async def test_a_kind_reroutes_only_with_the_alias_and_the_alias_stays_while_it_does(client, db) -> None:
    workspace = await _workspace(db)
    admin = await _member(db, workspace, "admin")

    refused = await client.put(_url(workspace, "email"), headers=bearer(admin), json={"action": "reroute"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "content_handling_alias_required"
    await client.put(_url(workspace), headers=bearer(admin), json={"alias": ALIAS})
    for kind, action in (("email", "reroute"), ("phone", "mask_reroute")):
        answer = await client.put(_url(workspace, kind), headers=bearer(admin), json={"action": action})
        assert answer.status_code == 200 and answer.json()["action"] == action

    in_use = await client.put(_url(workspace), headers=bearer(admin), json={"alias": None})
    assert in_use.status_code == 409
    assert in_use.json()["detail"]["code"] == "content_handling_alias_in_use"
    assert in_use.json()["detail"]["kinds"] == ["email", "phone"]
    # Another active alias may replace it while kinds reroute: they then go there.
    assert (await client.put(_url(workspace), headers=bearer(admin), json={"alias": OTHER})).status_code == 200
    plan = await content_handling(db, workspace, SURFACE_PLATFORM)
    assert (plan.governance_alias, plan.action("email"), plan.action("phone")) == (OTHER, "reroute", "mask_reroute")
    assert (await content_handling(db, workspace, SURFACE_GATEWAY)).governance_alias == OTHER

    for kind in ("email", "phone"):
        await client.put(_url(workspace, kind), headers=bearer(admin), json={"action": "mask"})
    assert (await client.put(_url(workspace), headers=bearer(admin), json={"alias": None})).status_code == 200
    assert await _stored(db) == []
    assert (await content_handling(db, workspace, SURFACE_PLATFORM)).governance_alias is None
    stored = (await db.execute(select(WorkspaceContentHandling))).scalars().all()
    assert sorted((row.kind, row.action) for row in stored) == [("email", "mask"), ("phone", "mask")]


async def test_a_workspace_without_settings_and_no_workspace_have_no_alias(db) -> None:
    workspace = await _workspace(db)
    assert (await content_handling(db, workspace, SURFACE_PLATFORM)).governance_alias is None
    assert (await content_handling(db, None, SURFACE_PLATFORM)).governance_alias is None


@pytest.mark.committed_db  # one session per request, as in production
async def test_concurrent_first_sets_give_one_change_and_a_typed_conflict(client, db, monkeypatch) -> None:
    workspace = await _workspace(db)
    admin = await _member(db, workspace, "admin")
    arrived, release = [], asyncio.Event()
    read = handling_settings.governance_row

    async def governance_row(session, workspace_id):
        row = await read(session, workspace_id)
        arrived.append(workspace_id)
        if len(arrived) >= 2:
            release.set()
        try:  # under row locks (PostgreSQL) the second read waits for the first edit instead: serialized
            await asyncio.wait_for(release.wait(), timeout=2)
        except TimeoutError:
            pass
        return row

    monkeypatch.setattr(handling_settings, "governance_row", governance_row)
    answers = await asyncio.gather(*(client.put(_url(workspace), headers=bearer(admin), json={"alias": alias})
                                     for alias in (ALIAS, OTHER)))

    codes = sorted(answer.status_code for answer in answers)
    assert codes in ([200, 200], [200, 409]), [answer.text for answer in answers]
    if codes == [200, 409]:
        lost = next(answer for answer in answers if answer.status_code == 409).json()["detail"]
        assert lost["code"] == "content_handling_conflict"
    transitions = [(item["old"], item["new"]) for item in await _audits(db)]
    assert len(transitions) == codes.count(200) and transitions[0][0] is None
    for (_old, new), (following_old, _new) in zip(transitions, transitions[1:]):
        assert following_old == new
    assert await _stored(db) == [(workspace, transitions[-1][1])]
