"""``GET /api/v1/agent-gateway/daily-budget``: the launcher reads only its own user's budget and seat allowance,
inside the token's Workspace binding."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import AgentPresence, Project, Session, UsageEvent
from app.services.agent_gateway.contract import GATEWAY_EXTERNAL_SOURCE, SESSION_KEY_METADATA
from app.services.agent_gateway.daily_budget import utc_day_window
from app.time_utils import utc_now
from tests.agent_gateway.seat_presence_support import _workspace
from tests.agent_gateway.test_gateway_workspaces import _token
from tests.knowledge_evidence_seed_support import seed_member

PATH = "/api/v1/agent-gateway/daily-budget"


async def _spend(db, user_id: str, amount: str, *, gateway: bool = True) -> None:
    session = Session(id=str(uuid.uuid4()), user_id=user_id, agent_type="external_agent" if gateway else "chat",
                      status="completed",
                      metadata_={"external_source": GATEWAY_EXTERNAL_SOURCE, SESSION_KEY_METADATA: str(uuid.uuid4())})
    db.add(session)
    db.add(UsageEvent(session_id=session.id, user_id=user_id, provider="litellm", model="m", cost=Decimal(amount)))
    await db.commit()


async def _presence(db, user_id: str, workspace_id: str, *, profile: str, pct: float, minutes_ago: int) -> None:
    now = utc_now()
    db.add(AgentPresence(id=str(uuid.uuid4()), session_key=str(uuid.uuid4()), user_id=user_id,
                         project_id=workspace_id, profile=profile, client="octryx-claude", state="active", device_key=user_id[:32],
                         five_hour_pct=pct, five_hour_resets_at=now + timedelta(hours=2), seven_day_pct=pct / 2,
                         seven_day_resets_at=now + timedelta(days=3), allowance_status="allowed",
                         allowance_updated_at=now - timedelta(minutes=minutes_ago), last_seen_at=now))
    await db.commit()


@pytest.mark.asyncio
async def test_the_launcher_reads_its_own_daily_budget_and_seat_allowance(client, db):
    workspace_id, foreign = await _workspace(db), await _workspace(db)
    user = await seed_member(db, workspace_id=workspace_id, role="member")
    other = await seed_member(db, workspace_id=workspace_id, role="member")
    await _spend(db, user, "3.25")
    await _spend(db, user, "1.00", gateway=False)
    await _spend(db, other, "40.00")
    await _presence(db, user, foreign, profile="seat", pct=42.0, minutes_ago=5)
    await _presence(db, user, workspace_id, profile="seat", pct=10.0, minutes_ago=60)
    await _presence(db, user, workspace_id, profile="governed", pct=99.0, minutes_ago=1)
    await _presence(db, other, workspace_id, profile="seat", pct=77.0, minutes_ago=0)
    headers = await _token(db, user)

    answer = await client.get(PATH, params={"workspace_id": workspace_id}, headers=headers)

    assert answer.status_code == 200 and answer.headers["cache-control"] == "no-store"
    body = answer.json()
    _, day_end = utc_day_window(utc_now())
    assert {key: body[key] for key in ("state", "reason", "workspace_id", "limit_usd", "spent_usd", "resets_at")} == {
        "state": "allowed", "reason": None, "workspace_id": workspace_id, "limit_usd": 200.0, "spent_usd": 3.25,
        "resets_at": f"{day_end.isoformat()}Z"}
    allowance = body["seat_allowance"]
    assert (allowance["five_hour_pct"], allowance["seven_day_pct"], allowance["status"]) == (42.0, 21.0, "allowed")
    assert foreign not in answer.text, "only the numbers travel, never the row's Workspace"

    (await db.get(Project, workspace_id)).config = {"agent_gateway_policy": {"session_budget": {
        "per_user_daily_usd": 3}, "tool_rules": []}}
    await db.commit()
    exhausted = (await client.get(PATH, params={"workspace_id": workspace_id}, headers=headers)).json()
    assert (exhausted["state"], exhausted["reason"], exhausted["limit_usd"]) == (
        "denied", "gateway_daily_budget_exhausted", 3.0)
    # A Workspace policy without its own budget has the platform's.
    (await db.get(Project, workspace_id)).config = {"agent_gateway_policy": {"tool_rules": []}}
    await db.commit()
    inherited = (await client.get(PATH, params={"workspace_id": workspace_id}, headers=headers)).json()
    assert (inherited["state"], inherited["reason"], inherited["limit_usd"]) == ("allowed", None, 200.0)
    (await db.get(Project, workspace_id)).config = {"agent_gateway_policy": {"session_budget": {
        "per_user_daily_usd": "x"}}}
    await db.commit()
    invalid = (await client.get(PATH, params={"workspace_id": workspace_id}, headers=headers)).json()
    assert (invalid["state"], invalid["reason"], invalid["limit_usd"], invalid["spent_usd"]) == (
        "needs_configuration", "gateway_policy_invalid", None, None)

    other_view = (await client.get(PATH, params={"workspace_id": workspace_id}, headers=await _token(db, other))).json()
    assert other_view["seat_allowance"]["five_hour_pct"] == 77.0


@pytest.mark.asyncio
async def test_a_foreign_or_unbound_workspace_and_a_missing_token_are_refused(client, db):
    workspace_id, second, foreign = await _workspace(db), await _workspace(db), await _workspace(db)
    user = await seed_member(db, workspace_id=workspace_id, role="member")
    from app.models.security.user import UserProject

    db.add(UserProject(user_id=user, project_id=second, role="member"))
    await db.commit()

    not_member = await client.get(PATH, params={"workspace_id": foreign}, headers=await _token(db, user))
    unbound = await client.get(PATH, params={"workspace_id": second}, headers=await _token(db, user, bound=[workspace_id]))
    missing = await client.get(PATH, params={"workspace_id": workspace_id})

    for refused in (not_member, unbound):
        assert refused.status_code == 403 and refused.json() == {"state": "denied", "reason": "workspace_not_authorized"}
        assert refused.headers["x-octryx-gateway-reason"] == "workspace_not_authorized"
    assert missing.status_code == 401
