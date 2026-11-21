"""The client handoff control plane: prepare resolves the items, commit writes the handoff with the work state and requests a takeover, and its refusals."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import AgentBoardMessage, Project, WorkItemTakeover
from app.services.agent_gateway.presence import session_key_hash
from tests.agent_board.client_handoff_support import AWS_KEY, BASE, _bundle, _headers, board, store  # noqa: F401

GIT = {"last_commits": ["abc123 Fix redirect"], "changed_files": ["src/app.py", "README.md"],
       "excluded_files": [".env"]}


# --- prepare ---------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_resolves_the_items_to_hand_over(client, db, board):  # noqa: F811
    from tests.agent_board.support import agent, seed_item
    from tests.agent_board.work_item_claims_support import _claim

    other = await seed_item(db, board.ws, "BRD-7")
    bens = await seed_item(db, board.ws, "BRD-8")
    await db.commit()
    await _claim(db, await agent(db, board.anna), other)  # Anna's MCP agent, not this session
    await _claim(db, await agent(db, board.ben, grant_id="grant-ben"), bens)  # Ben's: never Anna's to hand over
    await db.commit()
    headers = await _headers(db, board)

    async def keys(body):
        answer = await client.post(f"{BASE}/prepare", json=body, headers=headers)
        assert answer.status_code == 200, answer.text
        return [item["key"] for item in answer.json()["items"]], answer.json()

    by_key, body = await keys({"key": "BRD-7"})
    assert by_key == ["BRD-7"]
    assert body["policy"] == {"push": "branch", "mode": "confirm", "auto_trigger_pct": 99.0}
    assert (await keys({"all": True}))[0] == ["BRD-6", "BRD-7"]  # every item of the user's agents
    assert (await keys({}))[0] == ["BRD-6"]  # the session's own claim
    missing = await client.post(f"{BASE}/prepare", json={"key": "NOPE-1"}, headers=headers)
    assert missing.status_code == 404
    ben_headers = await _headers(db, board, board.ben, board.ben_key)
    created = (await client.post(f"{BASE}/prepare", json={}, headers=ben_headers)).json()["items"]
    assert len(created) == 1 and created[0]["title"].startswith("Handoff from ")
    work_item_headers = {**ben_headers, "x-octryx-work-item": "BRD-7"}
    assert [item["key"] for item in (await client.post(f"{BASE}/prepare", json={},
                                                       headers=work_item_headers)).json()["items"]] == ["BRD-7"]


# --- commit -----------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_writes_the_handoff_with_the_work_state_and_requests_a_takeover(client, db, board, store,  # noqa: F811
                                                                                   tmp_path):
    await board.handoff(db, "agent wrote this")
    await db.commit()
    headers = await _headers(db, board)
    bundle = (await client.post(f"{BASE}/attachments", params={"work_item_id": board.item.id},
                                content=_bundle(tmp_path, {"a.py": "x\n"}), headers=headers)).json()["bundle_id"]
    repo = {"url": "https://git.example.com/acme/app.git", "branch": "octryx-handoff/BRD-6/anna-20261006-1000",
            "base_commit": "a" * 40, "wip_commit": "b" * 40, "bundle_id": bundle}

    answer = await client.post(f"{BASE}/commit", json={"work_item_id": "BRD-6", "repo": repo, "git": GIT,
                                                       "note": "Tests are red on CI"}, headers=headers)
    body = answer.json()
    sections = (await client.get(f"{BASE}/resume", params={"key": "BRD-6"},
                                 headers=await _headers(db, board, board.ben, board.ben_key))).json()

    assert answer.status_code == 200, answer.text
    assert body["handoff"]["version"] == 2 and body["takeover"] is None  # confirm mode: request + nudge
    handoff = sections["handoff"]["sections"]
    assert handoff["repo"] == repo and handoff["state"] == "agent wrote this"
    assert handoff["changed_files"] == GIT["changed_files"] and handoff["excluded_files"] == [".env"]
    assert handoff["notes"] == "Tests are red on CI" and "linked_sessions" in handoff
    assert sections["handoff"]["author"]["type"] == "agent"
    request = (await db.execute(select(AgentBoardMessage).where(AgentBoardMessage.author_type == "system"))).scalar_one()
    assert request.claim_id == board.claim["claim_id"]


@pytest.mark.asyncio
async def test_commit_refusals(client, db, board, store):  # noqa: F811
    headers = await _headers(db, board)
    by_other = await client.post(f"{BASE}/commit", json={"work_item_id": "BRD-6", "repo": {}, "git": {}},
                                 headers=await _headers(db, board, board.ben, board.ben_key))
    no_bundle = await client.post(f"{BASE}/commit", json={"work_item_id": "BRD-6", "repo": {"bundle_id": "x"},
                                                          "git": {}}, headers=headers)
    secret = await client.post(f"{BASE}/commit", json={"work_item_id": "BRD-6", "repo": {}, "git": {},
                                                       "note": f"key {AWS_KEY}"}, headers=headers)
    stranger = await client.post(f"{BASE}/commit", json={"work_item_id": "BRD-6", "repo": {}, "git": {},
                                                         "to_user": "nobody"}, headers=headers)
    from app.models import User

    outsider = (await db.get(User, board.outsider)).username
    not_member = await client.post(f"{BASE}/commit", json={"work_item_id": "BRD-6", "repo": {}, "git": {},
                                                           "to_user": outsider}, headers=headers)
    assert not_member.status_code == 422 and not_member.json()["detail"] == {"code": "to_user_not_member"}
    assert by_other.status_code == 409 and by_other.json()["detail"] == {"code": "claimed_by_other"}
    assert no_bundle.status_code == 422 and no_bundle.json()["detail"] == {"code": "bundle_not_found"}
    assert secret.status_code == 422 and AWS_KEY not in secret.text
    assert stranger.status_code == 422 and stranger.json()["detail"] == {"code": "to_user_not_member"}


@pytest.mark.asyncio
async def test_commit_to_a_named_user_creates_a_pending_takeover(client, db, board):  # noqa: F811
    from app.models import User

    ben = await db.get(User, board.ben)
    answer = await client.post(f"{BASE}/commit", json={"work_item_id": "BRD-6", "repo": {}, "git": {},
                                                       "to_user": ben.username}, headers=await _headers(db, board))
    takeover = answer.json()["takeover"]
    assert (takeover["status"], takeover["to"]["user"]["id"], takeover["to"]["agent_hash"]) == (
        "pending", board.ben, None)


@pytest.mark.asyncio
async def test_commit_in_auto_mode_offers_and_the_offered_agent_takes_over_by_asking(client, db, board):  # noqa: F811
    """On the /handoff and trigger paths: a request plus an offer, never an assignment."""
    from app.models import WorkItemClaim

    project = await db.get(Project, board.ws)
    project.config = {**(project.config or {}), "agent_gateway_policy": {"handoff": {"mode": "auto"}}}
    await db.commit()
    answer = await client.post(f"{BASE}/commit", json={"work_item_id": "BRD-6", "repo": {}, "git": GIT},
                               headers=await _headers(db, board))
    claim = await db.get(WorkItemClaim, board.claim["claim_id"])
    await db.refresh(claim)
    assert answer.json()["takeover"] is None
    assert (await db.execute(select(func.count(WorkItemTakeover.id)))).scalar_one() == 0
    assert claim.released_at is None and claim.offer_agent_hash == session_key_hash(board.ben_key)
    assert claim.handed_off_at is not None
    from tests.agent_board.test_handoffs import Pair

    asked = await Pair.call(board, db, board.ben, "work_item_takeover_request", session_key=board.ben_key,
                            work_item_id=board.item.id)
    # Anna is not at her limit, but she handed over herself: condition 1 holds once Ben asks.
    assert asked["takeover"]["status"] == "confirmed" and asked["takeover"]["decided_by"] == {"kind": "system"}


@pytest.mark.asyncio
async def test_a_bundle_of_another_item_is_refused(client, db, board, store, tmp_path):  # noqa: F811
    from tests.agent_board.support import seed_item

    await seed_item(db, board.ws, "BRD-9")
    await db.commit()
    headers = await _headers(db, board)
    foreign = (await client.post(f"{BASE}/attachments", params={"work_item_id": "BRD-9"},
                                 content=_bundle(tmp_path, {"a": "b\n"}), headers=headers)).json()["bundle_id"]
    refused = await client.post(f"{BASE}/commit", json={"work_item_id": "BRD-6", "repo": {"bundle_id": foreign},
                                                        "git": {}}, headers=headers)
    assert refused.status_code == 422 and refused.json()["detail"] == {"code": "bundle_not_found"}
