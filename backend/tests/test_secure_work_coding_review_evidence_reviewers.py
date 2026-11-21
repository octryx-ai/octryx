"""Named reviewer decisions: an exact positive decision passes, partial or ambiguous reviewers stay unapproved, and later decisions and timestamp ties resolve towards the negative one."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import User, UserLinkedAccount, WorkCodingReviewEvent
from app.time_utils import utc_now
from tests.secure_work_coding_review_evidence_support import _auth, _decision, _gate, _post, _user, _world

pytestmark = pytest.mark.asyncio


async def _linked(db, user: User, external_username: str) -> None:
    """A linked GitHub account of ``user`` (``user_linked_accounts`` is the sole store of platform usernames)."""
    db.add(UserLinkedAccount(user_id=user.id, platform="github", username=external_username))
    await db.flush()


# ---- positive, partial, identities -------------------------------------------------------------

async def test_exact_positive_named_reviewer_decision_passes(client, auth_headers, db):
    alice = await _user(db, "alice", display_name="Alice Reviewer")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username], members=[alice])
    response = await _post(client, _auth(alice), item, _decision(plan, unit, body="Reviewed the whole unit."))
    assert response.status_code == 200, response.text
    record = response.json()["metadata"]["review_decision_record"]
    assert record["actor_id"] == alice.id and record["plan_version"] == 1 and record["change_unit_id"] == unit.id
    assert record["actor_label"] == "Alice Reviewer", "the server records a readable reviewer label"
    await db.refresh(unit)
    assert record["change_unit_marker"] == unit.updated_at.isoformat()
    assert response.json()["file_path"] == "", "a decision needs no invented file path"
    gate, report = await _gate(client, auth_headers, item)
    assert gate["status"] == "pass"
    assert "not to a pull-request head commit" in gate["reason"] and "not merge readiness" in gate["reason"]
    assert report["pr_summary"]["reviewers"] == ["Alice Reviewer"]


async def test_item_level_decision_without_units_and_without_a_file(client, auth_headers, db):
    item, plan, _ = await _world(db, units=0)
    marked = await _post(client, auth_headers, item, _decision(plan, expected_change_unit_marker="2026-10-04T00:00:00"))
    assert marked.status_code == 422, "a whole-item decision takes no unit marker"
    response = await _post(client, auth_headers, item, _decision(plan))
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["review_decision_record"]["scope"] == "work_item"
    assert (await _gate(client, auth_headers, item))[0]["status"] == "pass"


async def test_partial_required_reviewers_stay_unapproved(client, auth_headers, db):
    alice, bob = await _user(db, "alice"), await _user(db, "bob")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username, bob.username], members=[alice, bob])
    await _post(client, _auth(alice), item, _decision(plan, unit))
    gate, report = await _gate(client, auth_headers, item)
    assert gate["status"] == "review_required"
    assert bob.username in gate["reason"]
    assert report["pr_summary"]["reviewers"] == [], "no scope is complete yet"


async def test_a_linked_account_resolves_but_an_ambiguous_name_never_satisfies(client, auth_headers, db):
    alice = await _user(db, "alice")
    await _linked(db, alice, "alice.jira")
    item, plan, (unit,) = await _world(db, reviewers=["alice.jira"], members=[alice])
    await _post(client, _auth(alice), item, _decision(plan, unit))
    assert (await _gate(client, auth_headers, item))[0]["status"] == "pass"

    sam_one, sam_two = await _user(db, "sam-one"), await _user(db, "sam-two")
    sam_one.display_name = sam_two.display_name = "Sam"
    await db.flush()
    other, other_plan, (other_unit,) = await _world(db, reviewers=["Sam"], members=[sam_one, sam_two])
    await _post(client, _auth(sam_one), other, _decision(other_plan, other_unit))
    gate, _ = await _gate(client, auth_headers, other)
    assert gate["status"] == "review_required"
    assert gate["evidence"]["scopes"][0]["ambiguous_reviewers"] == ["Sam"]


async def test_a_name_without_a_user_cannot_satisfy_it(client, auth_headers, db):
    alice = await _user(db, "alice")
    item, plan, (unit,) = await _world(db, reviewers=["Unlinked Reviewer"], members=[alice])
    await _post(client, _auth(alice), item, _decision(plan, unit))
    assert (await _gate(client, auth_headers, item))[0]["status"] == "review_required"


# ---- supersession and ties ---------------------------------------------------------------------

async def test_later_rejection_blocks_and_a_later_approval_by_the_same_reviewer_supersedes(client, auth_headers, db):
    alice, bob = await _user(db, "alice"), await _user(db, "bob")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username], members=[alice, bob])
    await _post(client, _auth(alice), item, _decision(plan, unit))
    await _post(client, _auth(alice), item, _decision(plan, unit, decision="changes_requested"))
    assert (await _gate(client, auth_headers, item))[0]["status"] == "block"
    await _post(client, _auth(alice), item, _decision(plan, unit))
    assert (await _gate(client, auth_headers, item))[0]["status"] == "pass"
    await _post(client, _auth(bob), item, _decision(plan, unit, decision="rejected"))
    assert (await _gate(client, auth_headers, item))[0]["status"] == "block", "another reviewer's rejection blocks"


async def test_a_timestamp_tie_lets_the_negative_decision_win(client, auth_headers, db):
    alice = await _user(db, "alice")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username], members=[alice])
    await _post(client, _auth(alice), item, _decision(plan, unit))
    await _post(client, _auth(alice), item, _decision(plan, unit, decision="rejected"))
    tie = utc_now()
    for row in (await db.execute(select(WorkCodingReviewEvent).where(WorkCodingReviewEvent.work_item_id == item.id))).scalars():
        row.created_at = tie
    await db.commit()
    assert (await _gate(client, auth_headers, item))[0]["status"] == "block"
