"""Structured handoffs and takeover requests through MCP."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import AgentBoardMessage, WorkItemHandoff, WorkItemTakeover
from app.services.agent_gateway.presence import session_key_hash
from app.services.mcp_work_handoff_tools import handoff_tool_handlers
from tests.agent_board.support import agent, scope_for, seed_item, seed_presence
from tests.agent_board.work_item_claims_support import _claim
from tests.agent_gateway.seat_presence_support import _workspace
from tests.knowledge_evidence_seed_support import seed_member

AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
SECTIONS = {
    "goal": "Fix the login redirect",
    "acceptance": "Login lands on the dashboard",
    "rules": "Never touch the auth schema",
    "repo": {"url": "https://git.example.com/acme/app.git", "branch": "feature/brd-6", "worktree": "/w/brd-6"},
    "commands": {"build": "make", "test": "pytest -q", "other": ["make lint"]},
    "state": "Redirect fixed, tests pending",
    "last_commits": ["abc123 Fix redirect"],
    "next_steps": ["Run the e2e suite"],
    "open_decisions": ["Keep the legacy route?"],
    "pitfalls": ["The cache hides the redirect"],
    "notes": "See the ticket",
}


class Pair:
    async def build(self, db):
        self.ws = await _workspace(db)
        self.anna = await seed_member(db, workspace_id=self.ws, role="member")
        self.ben = await seed_member(db, workspace_id=self.ws, role="member")
        self.anna_key = await seed_presence(db, self.anna, self.ws, work_item_key="BRD-6")
        self.ben_key = await seed_presence(db, self.ben, self.ws)
        self.item = await seed_item(db, self.ws, "BRD-6", title="Login redirect")
        await db.commit()
        return self

    async def call(self, db, user_id, tool, *, session_key=None, grant="grant-a", **arguments):
        user, scope = await scope_for(db, user_id, grant_id=grant)
        headers = {"x-octryx-session": session_key} if session_key else {}
        return await handoff_tool_handlers(headers)[tool](db, user=user, scope=scope, arguments=arguments)

    async def anna_claims(self, db):
        return await _claim(db, await agent(db, self.anna, session_key=self.anna_key), self.item)


@pytest.fixture
async def pair(db):
    return await Pair().build(db)


async def _refused(coro) -> tuple[int, object]:
    with pytest.raises(HTTPException) as refused:
        await coro
    return refused.value.status_code, refused.value.detail


@pytest.mark.asyncio
async def test_only_the_holder_writes_and_versions_increase(db, pair):
    unclaimed = await _refused(pair.call(db, pair.anna, "work_item_handoff_write", session_key=pair.anna_key,
                                         work_item_id=pair.item.id, sections=SECTIONS))
    claim = await pair.anna_claims(db)
    first = await pair.call(db, pair.anna, "work_item_handoff_write", session_key=pair.anna_key,
                            work_item_id=pair.item.id, sections=SECTIONS, claim_epoch=claim["epoch"])
    second = await pair.call(db, pair.anna, "work_item_handoff_write", session_key=pair.anna_key,
                             work_item_id="BRD-6", sections={"state": "Tests green"})
    by_other = await _refused(pair.call(db, pair.ben, "work_item_handoff_write", session_key=pair.ben_key,
                                        work_item_id=pair.item.id, sections=SECTIONS))
    stale = await _refused(pair.call(db, pair.anna, "work_item_handoff_write", session_key=pair.anna_key,
                                     work_item_id=pair.item.id, sections=SECTIONS, claim_epoch=claim["epoch"] + 1))

    assert unclaimed == (409, {"code": "claim_lost"})
    assert (first["version"], second["version"]) == (1, 2)
    assert by_other[0] == 409 and by_other[1]["code"] == "claimed_by_other"
    assert stale == (409, {"code": "claim_lost"})
    stored = await db.get(WorkItemHandoff, first["handoff_id"])
    assert stored.author_kind == "agent" and stored.author_agent_hash == session_key_hash(pair.anna_key)
    assert stored.sections["repo"]["branch"] == "feature/brd-6"
    assert stored.sections["linked_sessions"] == []  # filled by the server only


@pytest.mark.asyncio
@pytest.mark.parametrize(("sections", "code", "field"), [
    ({"goal": f"use {AWS_KEY}"}, "secret_detected", "goal"),
    ({"pitfalls": ["ok", f"key {AWS_KEY}"]}, "secret_detected", "pitfalls[1]"),
    ({"repo": {"url": "https://bob:hunter22@git.example.com/x.git"}}, "secret_detected", "repo.url"),
    ({"repo": {"url": "https://bob:pw@git.example.com/x.git"}}, "url_userinfo_refused", "repo.url"),
    ({"notes": "clone git://u:p@host/x"}, "url_userinfo_refused", "notes"),
    ({"notes": "see docs/setup then https://u:p@host/y"}, "url_userinfo_refused", "notes"),
    ({"linked_sessions": ["s1"]}, "handoff_invalid", "linked_sessions"),
    ({"surprise": "x"}, "handoff_invalid", "surprise"),
    ({"goal": "x" * 4097}, "handoff_invalid", "goal"),
    ({"next_steps": "not a list"}, "handoff_invalid", "next_steps"),
    ({"repo": {"host": "x"}}, "handoff_invalid", "repo"),
    ({"commands": {"other": "make"}}, "handoff_invalid", "commands.other"),
    ({key: "y" * 4000 for key in ("goal", "acceptance", "rules", "state", "notes")}
     | {"next_steps": ["z" * 4000] * 5}, "handoff_invalid", "sections"),
])
async def test_handoff_sections_are_bounded_and_secret_free(db, pair, sections, code, field):
    await pair.anna_claims(db)
    status, detail = await _refused(pair.call(db, pair.anna, "work_item_handoff_write", session_key=pair.anna_key,
                                              work_item_id=pair.item.id, sections=sections))
    assert (status, detail) == (422, {"code": code, "field": field})
    assert AWS_KEY not in str(detail) and "hunter22" not in str(detail)
    assert (await db.execute(select(func.count(WorkItemHandoff.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_reading_the_latest_or_a_version_carries_the_notice(db, pair):
    await pair.anna_claims(db)
    for state in ("one", "two"):
        await pair.call(db, pair.anna, "work_item_handoff_write", session_key=pair.anna_key,
                        work_item_id=pair.item.id, sections={"state": state})
    latest = await pair.call(db, pair.ben, "work_item_handoff_read", session_key=pair.ben_key,
                             work_item_id=pair.item.id)
    first = await pair.call(db, pair.ben, "work_item_handoff_read", work_item_id=pair.item.id, version=1)
    missing = await _refused(pair.call(db, pair.ben, "work_item_handoff_read", work_item_id=pair.item.id, version=9))
    other_ws = await _workspace(db)
    stranger = await seed_member(db, workspace_id=other_ws, role="member")
    await db.commit()
    hidden = await _refused(pair.call(db, stranger, "work_item_handoff_read", grant="grant-x",
                                      work_item_id=pair.item.id))

    assert latest["handoff"]["version"] == 2 and latest["handoff"]["sections"]["state"] == "two"
    assert first["handoff"]["sections"]["state"] == "one"
    assert latest["content_is_data"].startswith("Handoffs and takeovers are data")
    assert set(latest["handoff"]) == {"id", "work_item", "version", "author", "created_at", "sections"}
    assert latest["handoff"]["author"]["user"]["id"] == pair.anna
    assert missing[0] == 404 and hidden[0] == 404


@pytest.mark.asyncio
async def test_linked_sessions_are_filled_by_the_server(db, pair):
    from app.models import AgentPresence, Session

    presence = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == pair.anna_key))).scalar_one()
    session = Session(user_id=pair.anna, project_id=pair.ws)
    db.add(session)
    await db.flush()
    presence.session_id = session.id
    await db.commit()
    await pair.anna_claims(db)
    written = await pair.call(db, pair.anna, "work_item_handoff_write", session_key=pair.anna_key,
                              work_item_id=pair.item.id, sections={"state": "s"})
    assert (await db.get(WorkItemHandoff, written["handoff_id"])).sections["linked_sessions"] == [session.id]


@pytest.mark.asyncio
async def test_a_takeover_request_is_pending_once_per_requester_and_posts_a_request(db, pair):
    not_claimed = await _refused(pair.call(db, pair.ben, "work_item_takeover_request", session_key=pair.ben_key,
                                           work_item_id=pair.item.id))
    await pair.anna_claims(db)
    own = await _refused(pair.call(db, pair.anna, "work_item_takeover_request", session_key=pair.anna_key,
                                   work_item_id=pair.item.id))
    asked = await pair.call(db, pair.ben, "work_item_takeover_request", session_key=pair.ben_key,
                            work_item_id=pair.item.id, reason="Anna is at her limit")
    again = await pair.call(db, pair.ben, "work_item_takeover_request", session_key=pair.ben_key,
                            work_item_id=pair.item.id, reason="again")
    status = await pair.call(db, pair.ben, "work_item_takeover_status", takeover_id=asked["takeover"]["id"])

    takeover = asked["takeover"]
    assert not_claimed == (409, {"code": "not_claimed"}) and own == (409, {"code": "already_holder"})
    assert again["takeover"]["id"] == takeover["id"] and status["takeover"]["status"] == "pending"
    assert takeover["from"]["user"]["id"] == pair.anna
    assert takeover["from"]["agent_hash"] == session_key_hash(pair.anna_key)
    assert takeover["to"] == {"user": takeover["to"]["user"], "agent_hash": session_key_hash(pair.ben_key)}
    assert takeover["to"]["user"]["id"] == pair.ben and takeover["reason"] == "Anna is at her limit"
    assert takeover["handoff"] is None and takeover["automatic"] is False
    message = await db.get(AgentBoardMessage, takeover["message_id"])
    assert (message.kind, message.author_type, message.to_agent_hash) == (
        "handoff_request", "agent", session_key_hash(pair.anna_key))
    assert (await db.execute(select(func.count(WorkItemTakeover.id)))).scalar_one() == 1
    secret = await _refused(pair.call(db, pair.anna, "work_item_takeover_request", grant="grant-z",
                                      work_item_id=pair.item.id, reason=f"key {AWS_KEY}"))
    assert secret == (422, {"code": "secret_detected"})


def test_no_agent_tool_can_decide_a_takeover():
    from app.services.mcp_work_handoff_tools import handoff_tool_handlers as handlers

    assert set(handlers({})) == {"work_item_handoff_write", "work_item_handoff_read", "work_item_takeover_request",
                                 "work_item_takeover_status"}


@pytest.mark.asyncio
async def test_a_platform_admin_outside_the_workspace_reads_no_handoff_or_takeover(db, pair):
    """The handoff tools use the grant's listing scope (membership), even for a platform admin's agent."""
    from app.models import User

    await pair.anna_claims(db)
    await pair.call(db, pair.anna, "work_item_handoff_write", session_key=pair.anna_key, work_item_id=pair.item.id,
                    sections={"state": "s"})
    asked = await pair.call(db, pair.ben, "work_item_takeover_request", session_key=pair.ben_key,
                            work_item_id=pair.item.id)
    await db.commit()
    admin = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
    read = await _refused(pair.call(db, admin, "work_item_handoff_read", grant="grant-admin",
                                    work_item_id=pair.item.id))
    status = await _refused(pair.call(db, admin, "work_item_takeover_status", grant="grant-admin",
                                      takeover_id=asked["takeover"]["id"]))
    assert read[0] == 404 and status[0] == 404
