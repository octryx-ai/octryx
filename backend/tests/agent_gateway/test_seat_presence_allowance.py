"""Presence and allowance: who sees the allowance on REST and MCP, idle sessions and allowance parsing."""

# ruff: noqa: F811  (the shared ``anthropic`` fixture is imported, then requested by name)
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.models import AgentPresence, User
from app.services.agent_gateway.allowance import parse_allowance
from app.time_utils import utc_now
from tests.agent_gateway.seat_presence_support import (
    PRESENCE,
    SEAT,
    _bearer,
    _body,
    _gateway_headers,
    _register,
    _seat_headers,
    _seat_session,
    _workspace,
)
from tests.agent_gateway.seat_upstream_support import anthropic  # noqa: F401 - fixture
from tests.knowledge_evidence_seed_support import seed_member


@pytest.mark.asyncio
async def test_allowance_is_shown_only_to_workspace_admins_and_owners(client, db, anthropic):
    workspace_id, member_id, gateway, credential = await _seat_session(client, db)
    await client.post(SEAT, json=_body(), headers=_seat_headers(gateway, credential))
    owner_id = await seed_member(db, workspace_id=workspace_id, role="owner")
    outsider_workspace = await _workspace(db)
    outsider_id = await seed_member(db, workspace_id=outsider_workspace, role="owner")
    await db.commit()

    member_view = (await client.get(PRESENCE, params={"project_id": workspace_id}, headers=await _bearer(member_id))).json()
    owner_view = (await client.get(PRESENCE, params={"project_id": workspace_id}, headers=await _bearer(owner_id))).json()
    outsider = await client.get(PRESENCE, params={"project_id": workspace_id}, headers=await _bearer(outsider_id))

    [member_item], [owner_item] = member_view["items"], owner_view["items"]
    assert member_item["allowance"] is None
    assert owner_item["allowance"] == {
        "five_hour_pct": 12.0, "five_hour_resets_at": owner_item["allowance"]["five_hour_resets_at"],
        "seven_day_pct": 95.0, "seven_day_resets_at": owner_item["allowance"]["seven_day_resets_at"],
        "status": "allowed_warning"}
    assert {key: owner_item[key] for key in ("client", "profile", "state", "branch", "model")} == {
        "client": "octryx-claude", "profile": "seat", "state": "active", "branch": "feature/brd-6",
        "model": "claude-sonnet-5"}
    assert gateway["x-octryx-session"] not in json.dumps(owner_view)
    assert owner_item["session_key_hash"] == hashlib.sha256(gateway["x-octryx-session"].encode()).hexdigest()[:24]
    assert outsider.status_code == 404 and "items" not in outsider.text


@pytest.mark.asyncio
async def test_a_quiet_session_reads_idle(client, db):
    workspace_id = await _workspace(db, classification="internal")
    owner_id = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()
    await _register(client, await _gateway_headers(db, owner_id, workspace_id), profile="governed")
    row = (await db.execute(select(AgentPresence).where(AgentPresence.project_id == workspace_id))).scalar_one()
    row.last_seen_at = utc_now() - timedelta(minutes=11)
    await db.commit()

    [item] = (await client.get(PRESENCE, params={"project_id": workspace_id}, headers=await _bearer(owner_id))).json()["items"]

    assert (item["state"], item["allowance"]) == ("idle", None)


@pytest.mark.asyncio
async def test_the_mcp_presence_tool_has_the_same_rules(db, client, anthropic):
    from app.services.mcp_agent_presence_tools import agent_presence_list
    from app.services.mcp_work_access import build_work_grant_scope

    workspace_id, member_id, gateway, credential = await _seat_session(client, db)
    await client.post(SEAT, json=_body(), headers=_seat_headers(gateway, credential))
    owner_id = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    async def listed(user_id: str, project_id: str = workspace_id) -> dict[str, Any]:
        user = await db.get(User, user_id)
        scope = await build_work_grant_scope(db, user=user, grant_id=None, binding=None)
        return await agent_presence_list(db, user=user, scope=scope, arguments={"project_id": project_id})

    assert (await listed(member_id))["items"][0]["allowance"] is None
    assert (await listed(owner_id))["items"][0]["allowance"]["seven_day_pct"] == 95.0
    other = await _workspace(db)
    with pytest.raises(Exception) as refused:
        await listed(member_id, other)
    assert getattr(refused.value, "status_code", None) == 403


def test_allowance_parsing_ignores_missing_and_malformed_values():
    assert not parse_allowance({}).observed
    parsed = parse_allowance({"Anthropic-Ratelimit-Unified-5h-Utilization": "0.5",
                              "anthropic-ratelimit-unified-7d-utilization": "nan",
                              "anthropic-ratelimit-unified-7d-reset": "12",
                              "anthropic-ratelimit-unified-status": "Allowed; drop table"})
    assert (parsed.five_hour_pct, parsed.seven_day_pct, parsed.seven_day_resets_at, parsed.status) == (50.0, None, None, None)
    assert parse_allowance({"anthropic-ratelimit-unified-5h-utilization": "1.2"}).limit_reached
    assert parse_allowance({"anthropic-ratelimit-unified-5h-status": "rejected"}).limit_reached


@pytest.mark.asyncio
async def test_a_platform_admin_gets_the_allowance_on_rest_and_mcp_alike(client, db, anthropic):
    from app.services.mcp_agent_presence_tools import agent_presence_list
    from app.services.mcp_work_access import build_work_grant_scope

    workspace_id, _member, gateway, credential = await _seat_session(client, db)
    await client.post(SEAT, json=_body(), headers=_seat_headers(gateway, credential))
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    rest = (await client.get(PRESENCE, params={"project_id": workspace_id}, headers=await _bearer(admin.id))).json()
    scope = await build_work_grant_scope(db, user=admin, grant_id=None, binding=None)
    mcp = await agent_presence_list(db, user=admin, scope=scope, arguments={"project_id": workspace_id})
    bound_elsewhere = await build_work_grant_scope(db, user=admin, grant_id=None, binding=frozenset({"other-ws"}))

    assert rest["items"][0]["allowance"]["seven_day_pct"] == mcp["items"][0]["allowance"]["seven_day_pct"] == 95.0
    with pytest.raises(Exception) as refused:
        await agent_presence_list(db, user=admin, scope=bound_elsewhere, arguments={"project_id": workspace_id})
    assert getattr(refused.value, "status_code", None) == 403
