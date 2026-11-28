from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models import Project, UserProject
from app.models.security.compliance_audit import AUDIT_ADMIN_CHANGE, AUDIT_CONNECTOR_ACCESS, AUDIT_RUNTIME_ACTION
from app.services.compliance_audit.service import create_audit_record
from app.services.mcp_audit_vocabulary import READINESS_MISSING_SECRET, connect_blocked
from app.services.project.private_workspace import PRIVATE_ACCESS_MODE
from app.time_utils import utc_now
from tests.policy_engine_support import bearer, make_user

RECORDS = "/api/v1/admin/compliance-audit/records"
KINDS = "/api/v1/admin/compliance-audit/kinds"


async def _workspace(db, **fields) -> Project:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True, **fields)
    db.add(project)
    await db.flush()
    return project


async def _record(db, project_id: str | None, event_type: str = AUDIT_ADMIN_CHANGE, **fields):
    return await create_audit_record(db, event_type=event_type, resource_type="mcp_server", project_id=project_id,
                                     **fields)


async def _ids(client, user_id: str, **params) -> set[str]:
    response = await client.get(RECORDS, params=params, headers=bearer(user_id))
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["records"]}


@pytest.mark.asyncio
async def test_platform_admin_sees_every_record_except_foreign_private_workspaces(client, db):
    admin = await make_user(db, admin=True)
    other = await make_user(db, admin=False)
    shared = await _workspace(db)
    private = await _workspace(db, access_mode=PRIVATE_ACCESS_MODE, owner_user_id=other)
    in_shared = await _record(db, shared.id)
    platform_wide = await _record(db, None)
    hidden = await _record(db, private.id)

    seen = await _ids(client, admin)
    assert {in_shared.id, platform_wide.id} <= seen and hidden.id not in seen
    assert (await client.get(RECORDS, params={"workspace_id": private.id}, headers=bearer(admin))).status_code == 404


@pytest.mark.asyncio
async def test_workspace_admin_sees_only_their_workspaces(client, db):
    user = await make_user(db, admin=False)
    own = await _workspace(db)
    member_only = await _workspace(db)
    foreign = await _workspace(db)
    db.add_all([UserProject(user_id=user, project_id=own.id, role="admin"),
                UserProject(user_id=user, project_id=member_only.id, role="member")])
    await db.flush()
    mine = await _record(db, own.id)
    await _record(db, member_only.id)
    await _record(db, foreign.id)
    await _record(db, None)

    assert await _ids(client, user) == {mine.id}
    kinds = (await client.get(KINDS, headers=bearer(user))).json()
    assert [w["id"] for w in kinds["workspaces"]] == [own.id] and kinds["platform_admin"] is False


@pytest.mark.asyncio
async def test_unknown_foreign_and_member_only_workspace_answer_the_same_404(client, db):
    user = await make_user(db, admin=False)
    own = await _workspace(db)
    member_only = await _workspace(db)
    foreign = await _workspace(db)
    db.add_all([UserProject(user_id=user, project_id=own.id, role="owner"),
                UserProject(user_id=user, project_id=member_only.id, role="member")])
    await db.flush()

    answers = [await client.get(RECORDS, params={"workspace_id": ws}, headers=bearer(user))
               for ws in (str(uuid.uuid4()), foreign.id, member_only.id)]
    assert {a.status_code for a in answers} == {404}
    assert len({str(a.json().get("detail")) for a in answers}) == 1


@pytest.mark.asyncio
async def test_a_user_without_an_administered_workspace_is_refused(client, db):
    user = await make_user(db, admin=False)
    member_only = await _workspace(db)
    db.add(UserProject(user_id=user, project_id=member_only.id, role="member"))
    await db.flush()

    assert (await client.get(RECORDS, headers=bearer(user))).status_code == 403
    assert (await client.get(KINDS, headers=bearer(user))).status_code == 403


@pytest.mark.asyncio
async def test_filters_by_kind_and_time_range(client, db):
    admin = await make_user(db, admin=True)
    ws = await _workspace(db)
    change = await _record(db, ws.id, AUDIT_ADMIN_CHANGE)
    action = await _record(db, ws.id, AUDIT_RUNTIME_ACTION)
    old = await _record(db, ws.id, AUDIT_RUNTIME_ACTION)
    old.created_at = utc_now() - timedelta(days=10)
    await db.commit()

    assert await _ids(client, admin, workspace_id=ws.id, event_type=AUDIT_RUNTIME_ACTION) == {action.id, old.id}
    since = (utc_now() - timedelta(days=1)).isoformat() + "Z"
    assert await _ids(client, admin, workspace_id=ws.id, since=since) == {change.id, action.id}
    until = (utc_now() - timedelta(days=5)).isoformat()
    assert await _ids(client, admin, workspace_id=ws.id, until=until) == {old.id}
    refused = await client.get(RECORDS, params={"event_type": "nope"}, headers=bearer(admin))
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_pages_follow_the_cursor_without_gaps_or_repeats(client, db):
    admin = await make_user(db, admin=True)
    ws = await _workspace(db)
    at = utc_now()
    created = []
    for index in range(5):
        record = await _record(db, ws.id)
        record.created_at = at - timedelta(minutes=index // 2)
        created.append(record.id)
    await db.commit()

    seen: list[str] = []
    cursor = None
    while True:
        params = {"workspace_id": ws.id, "limit": 2, **({"cursor": cursor} if cursor else {})}
        page = (await client.get(RECORDS, params=params, headers=bearer(admin))).json()
        seen += [row["id"] for row in page["records"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert sorted(seen) == sorted(created) and len(seen) == 5
    assert (await client.get(RECORDS, params={"cursor": "%%%"}, headers=bearer(admin))).status_code == 422


@pytest.mark.asyncio
async def test_details_show_only_the_writers_known_fields_and_count_the_rest(client, db):
    admin = await make_user(db, admin=True)
    ws = await _workspace(db)
    known = await create_audit_record(
        db, event_type=AUDIT_CONNECTOR_ACCESS, resource_type="mcp_server_registration", project_id=ws.id,
        actor_user_id=admin, details={"action": connect_blocked(READINESS_MISSING_SECRET), "owner_scope": "workspace",
                                      "revision": 3, "credential_binding_count": 1, "endpoint": "tracker.internal"})
    unknown = await _record(db, ws.id, details={"server": "tracker", "tools": ["search"]})

    rows = {row["id"]: row for row in (await client.get(
        RECORDS, params={"workspace_id": ws.id}, headers=bearer(admin))).json()["records"]}
    # credential_binding_count is redacted on write, which flags the record: its counts are hidden too.
    assert rows[known.id]["details"] == {"action": connect_blocked(READINESS_MISSING_SECRET), "owner_scope": "workspace"}
    assert rows[known.id]["hidden_field_count"] == 3
    assert rows[unknown.id]["details"] == {} and rows[unknown.id]["hidden_field_count"] == 2
    assert rows[known.id]["actor"]["id"] == admin and rows[known.id]["workspace"] == {"id": ws.id, "name": ws.name}
