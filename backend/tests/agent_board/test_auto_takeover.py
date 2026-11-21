"""The Workspace handoff policy and automatic takeover."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.models import AgentBoardMessage, AuditLog, Notification, Project, WorkItemClaim, WorkItemTakeover
from app.services.agent_board.auto_takeover import maybe_auto_confirm
from app.services.agent_gateway.policy import load_workspace_policy
from app.services.agent_gateway.presence import session_key_hash
from app.time_utils import utc_now
from tests.agent_board.auto_takeover_support import (  # noqa: F401
    AUTO,
    _auto_ready,
    _presence,
    _request,
    _set_policy,
    board,
)
from tests.agent_board.board_rest_support import _get
from tests.agent_board.support import scope_for
from tests.agent_board.work_item_claims_support import _fenced
from tests.agent_gateway.seat_presence_support import _bearer

POLICY = "/api/v1/workspaces/{}/agent-gateway/handoff-policy"


# --- policy ----------------------------------------------------------------------------------------------


async def _put(client, board, user_id, body):  # noqa: F811
    return await client.put(POLICY.format(board.ws), json=body, headers=await _bearer(user_id))


@pytest.mark.asyncio
async def test_the_policy_is_read_by_members_and_written_by_admins(client, db, board):  # noqa: F811
    default = await client.get(POLICY.format(board.ws), headers=await _bearer(board.ben))
    assert default.json() == {"project_id": board.ws, "source": "default", "can_edit": False, "handoff": {
        "mode": "confirm", "auto_threshold_pct": 90.0, "require_spare_pct": 50.0, "allowed_requesters": "members",
        "push": "branch", "auto_trigger_pct": 99.0, "offer_timeout_minutes": 10.0}}
    assert (await _put(client, board, board.ben, AUTO)).status_code == 403
    assert (await client.get(POLICY.format(board.ws), headers=await _bearer(board.outsider))).status_code == 404
    assert (await _put(client, board, board.outsider, AUTO)).status_code == 404
    written = await _put(client, board, board.owner, {"mode": "auto", "auto_threshold_pct": 80})
    by_platform_admin = await _put(client, board, board.platform_admin, AUTO)

    assert written.status_code == 200 and written.json()["source"] == "workspace"
    assert written.json()["handoff"] == {**AUTO, "auto_threshold_pct": 80.0, "require_spare_pct": 50.0,
                                         "push": "branch", "auto_trigger_pct": 99.0, "offer_timeout_minutes": 10.0}
    assert by_platform_admin.status_code == 200 and by_platform_admin.json()["handoff"]["auto_threshold_pct"] == 90
    audits = (await db.execute(select(AuditLog).where(
        AuditLog.action == "admin.agent_gateway.handoff_policy_updated"))).scalars().all()
    assert [audit.user_id for audit in audits] == [board.owner, board.platform_admin]
    assert audits[1].details["before"]["auto_threshold_pct"] == 80.0
    loaded = await load_workspace_policy(db, board.ws)  # the baseline stays: tool rules and budget
    assert loaded.source == "baseline" and loaded.policy.tool_rules and loaded.policy.daily_budget_usd is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(("body", "code", "field"), [
    ({"mode": "sometimes"}, "invalid_handoff_mode", "agent_gateway_policy.handoff.mode"),
    ({"auto_threshold_pct": 0}, "invalid_percentage", "agent_gateway_policy.handoff.auto_threshold_pct"),
    ({"auto_threshold_pct": "90"}, "invalid_percentage", "agent_gateway_policy.handoff.auto_threshold_pct"),
    ({"require_spare_pct": 100}, "invalid_percentage", "agent_gateway_policy.handoff.require_spare_pct"),
    ({"allowed_requesters": "everyone"}, "invalid_allowed_requesters",
     "agent_gateway_policy.handoff.allowed_requesters"),
    ({"surprise": 1}, "unknown_field", "agent_gateway_policy.handoff.surprise"),
    ({"push": "force"}, "invalid_push_mode", "agent_gateway_policy.handoff.push"),
    ({"auto_trigger_pct": 101}, "invalid_percentage", "agent_gateway_policy.handoff.auto_trigger_pct"),
])
async def test_invalid_policy_values_are_a_coded_422(client, db, board, body, code, field):  # noqa: F811
    refused = await _put(client, board, board.owner, body)
    assert refused.status_code == 422 and refused.json()["detail"] == {"errors": [{"code": code, "field": field}]}
    project = await db.get(Project, board.ws)
    await db.refresh(project)
    assert "agent_gateway_policy" not in (project.config or {})


@pytest.mark.asyncio
async def test_a_broken_stored_policy_refuses_the_handoff_write(client, db, board):  # noqa: F811
    project = await db.get(Project, board.ws)
    project.config = {**(project.config or {}), "agent_gateway_policy": {"tool_rules": "broken"}}
    await db.commit()
    refused = await _put(client, board, board.owner, AUTO)
    assert refused.status_code == 422 and refused.json()["detail"]["errors"][0]["code"] == "agent_gateway_policy_invalid"


# --- automatic confirmation --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_mode_confirms_by_the_server_with_the_same_transfer(client, db, board):  # noqa: F811
    await _auto_ready(db, board)
    takeover = await _request(db, board)

    assert takeover["status"] == "confirmed" and takeover["decided_by"] == {"kind": "system"}
    assert takeover["policy_mode"] == "auto"
    new = (await db.execute(select(WorkItemClaim).where(
        WorkItemClaim.work_item_id == board.item.id, WorkItemClaim.released_at.is_(None)))).scalar_one()
    assert (new.holder_ref_hash, new.epoch) == (session_key_hash(board.ben_key), board.claim["epoch"] + 1)
    _, anna_scope = await scope_for(db, board.anna)
    with pytest.raises(Exception) as fenced:
        await _fenced(db, board.anna, anna_scope, "work_item_note", {"work_item": board.item.id},
                      session_key=board.anna_key)
    assert fenced.value.detail["code"] == "claim_lost"
    accept = (await db.execute(select(AgentBoardMessage).where(AgentBoardMessage.kind == "handoff_accept"))).scalar_one()
    assert accept.author_type == "system"
    row = await db.get(WorkItemTakeover, takeover["id"])
    assert row.decided_by is None and row.policy_snapshot["mode"] == "auto"
    assert all(row.policy_snapshot["conditions"].values())
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "agent_board.takeover.confirmed"))).scalar_one()
    assert audit.details["decided_by"] == "system" and audit.details["policy"]["require_spare_pct"] == 50.0

    notes = (await db.execute(select(Notification).where(
        Notification.type == "agent_board_info.handoff_auto"))).scalars().all()
    assert {note.user_id for note in notes} == {board.anna, board.ben}
    assert notes[0].title.startswith("BRD-6 was handed over automatically from agent of ")
    assert notes[0].body is None
    action = (await _get(client, "/action-needed", board.ben)).json()
    assert not [entry for entry in action["items"] if entry["kind"] == "handoff_confirm"]
    for note in notes:  # an info notification is never resolved by the action-needed sync
        await db.refresh(note)
        assert note.is_read is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("case", "expected"), [
    ("holder_below_threshold", "pending"),
    ("holder_limit_reached", "confirmed"),
    ("holder_stale", "confirmed"),
    ("holder_stopped", "confirmed"),
    ("requester_too_busy", "pending"),
    ("requester_exactly_at_spare", "confirmed"),
    ("requester_seat_unknown", "pending"),
    ("requester_limit_reached", "pending"),
    ("requester_stale", "pending"),
    ("admins_only_member", "pending"),
    ("admins_only_admin", "confirmed"),
    ("no_handoff", "pending"),
    ("mode_confirm", "pending"),
])
async def test_each_auto_condition(db, board, case, expected):  # noqa: F811
    policy = dict(AUTO)
    if case == "mode_confirm":
        policy["mode"] = "confirm"
    if case.startswith("admins_only"):
        policy["allowed_requesters"] = "admins_and_owners"
    await _set_policy(db, board, policy)
    anna, ben = await _presence(db, board.anna_key), await _presence(db, board.ben_key)
    anna.seven_day_pct = 95.0
    if case == "holder_below_threshold":
        anna.seven_day_pct = 50.0
    if case == "holder_limit_reached":
        anna.seven_day_pct, anna.state = None, "limit_reached"
    if case == "holder_stale":
        anna.seven_day_pct, anna.last_seen_at = None, utc_now() - timedelta(minutes=11)
    if case == "holder_stopped":
        anna.seven_day_pct, anna.stopped_at = None, utc_now()
    if case == "requester_too_busy":
        ben.seven_day_pct = 51.0
    if case == "requester_exactly_at_spare":
        ben.seven_day_pct = 50.0
    if case == "requester_seat_unknown":
        ben.profile = "seat"
    if case == "requester_limit_reached":
        ben.state = "limit_reached"
    if case == "requester_stale":
        ben.last_seen_at = utc_now() - timedelta(minutes=11)
    if case == "admins_only_admin":
        from app.models.security.user import UserProject

        membership = (await db.execute(select(UserProject).where(UserProject.user_id == board.ben))).scalar_one()
        membership.role = "admin"
    if case != "no_handoff":
        await board.handoff(db, "v1")
    await db.commit()
    takeover = await _request(db, board)
    assert takeover["status"] == expected
    assert takeover["decided_by"] == ({"kind": "system"} if expected == "confirmed" else None)


@pytest.mark.asyncio
async def test_a_pending_takeover_still_needs_a_person_and_the_human_decision_wins_a_race(client, db, board):  # noqa: F811
    await _set_policy(db, board, AUTO)  # no handoff yet: stays pending (falls back to confirm)
    anna = await _presence(db, board.anna_key)
    anna.seven_day_pct = 95.0
    await db.commit()
    takeover = await _request(db, board)
    assert takeover["status"] == "pending" and takeover["policy_mode"] == "auto"
    await board.handoff(db, "v1")
    stale = await db.get(WorkItemTakeover, takeover["id"])
    # A person declines first; the server's attempt with its still-pending copy loses at the compare-and-set.
    await db.execute(update(WorkItemTakeover).where(WorkItemTakeover.id == stale.id).values(
        status="declined", decided_at=utc_now(), decided_by=board.ben, decided_by_kind="human")
        .execution_options(synchronize_session=False))
    assert await maybe_auto_confirm(db, stale) is False
    await db.refresh(stale)
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    await db.refresh(claim)
    assert claim.released_at is None
    listed = (await _get(client, "/takeovers", board.ben, project_id=board.ws)).json()["items"][0]
    assert listed["status"] == "declined" and listed["decided_by"]["kind"] == "human"
    assert listed["decided_by"]["user"]["id"] == board.ben


@pytest.mark.asyncio
async def test_human_decisions_carry_the_human_kind(client, db, board):  # noqa: F811
    takeover = await _request(db, board)
    assert takeover["policy_mode"] == "confirm" and takeover["decided_by"] is None
    confirmed = await client.post(f"/api/v1/agent-board/takeovers/{takeover['id']}/confirm",
                                  headers=await _bearer(board.owner))
    decided = confirmed.json()["takeover"]["decided_by"]
    assert decided["kind"] == "human" and decided["user"]["id"] == board.owner
