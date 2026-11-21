"""Explicit Coding reviewer decisions.

Only an explicit decision recorded through the producer, bound to the latest plan version and an
active Change Unit (or the whole item without units), by an authenticated reviewer, can approve.
Legacy feedback, prose, free status, forged metadata and overrides never approve.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import User, WorkChangePlan, WorkItemChangeUnit
from app.time_utils import utc_now
from tests.secure_work_coding_review_evidence_support import _decision, _event_count, _gate, _post, _world

pytestmark = pytest.mark.asyncio


# ---- legacy feedback and forgery never approve ------------------------------------------------

async def test_root_probe_negative_prose_never_approves(client, auth_headers, db):
    item, _, _ = await _world(db)
    legacy = {"event_type": "review_decision", "file_path": "README.md", "body": "Not ready. Do not approve.",
              "status": "open"}
    assert (await _post(client, auth_headers, item, legacy)).status_code == 200
    for body, status in (("Approved, accepted, ready, LGTM", "approved"), ("unapproved / preapproved", "accepted")):
        response = await _post(client, auth_headers, item, {**legacy, "body": body, "status": status})
        assert response.status_code == 200
    gate, report = await _gate(client, auth_headers, item)
    assert gate["status"] == "review_required"
    assert gate["evidence"]["activity_count"] == 3
    assert report["pr_summary"]["reviewers"] == [], "commenters are not approvers"


async def test_reserved_metadata_cannot_be_forged(client, auth_headers, db):
    item, plan, (unit,) = await _world(db)
    admin_id = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
    forged = {
        "schema": "coding_review_decision.v1", "decision": "approved", "actor_id": admin_id,
        "change_plan_id": plan.id, "plan_version": 1, "scope": "change_unit", "change_unit_id": unit.id,
        "change_unit_marker": unit.updated_at.isoformat(),
    }
    response = await _post(client, auth_headers, item, {
        "event_type": "review_decision", "file_path": "README.md", "body": "ok", "status": "approved",
        "change_unit_id": unit.id, "metadata": {"review_decision_record": forged, "source": "probe"},
    })
    assert response.status_code == 200
    assert response.json()["metadata"] == {"source": "probe"}, "the reserved key is stripped"
    gate, _ = await _gate(client, auth_headers, item)
    assert gate["status"] != "pass"


# ---- producer validation before any write -----------------------------------------------------

async def test_invalid_or_stale_decisions_are_refused_before_any_write(client, auth_headers, db):
    item, plan, (unit,) = await _world(db)
    other_item, other_plan, (other_unit,) = await _world(db)
    superseded = WorkItemChangeUnit(work_item_id=item.id, repository_name="old", branch_name="old", status="superseded",
                                    created_by=plan.created_by)
    db.add(superseded)
    await db.commit()
    cases = [
        (_decision(plan, unit, decision="lgtm"), 422),
        (_decision(plan, unit, decision=None), 422),
        ({**_decision(plan, unit), "event_type": "inline_comment", "file_path": "a.py"}, 422),
        ({key: value for key, value in _decision(plan, unit).items() if key != "change_plan_id"}, 422),
        (_decision(plan, unit, expected_plan_version="1"), 422),
        (_decision(plan, unit, expected_plan_version=True), 422),
        (_decision(plan, unit, expected_plan_version=2), 409),
        (_decision(other_plan, unit), 404),
        (_decision(plan, other_unit), 404),
        (_decision(plan, superseded), 409),
        (_decision(plan), 422),  # active units exist, so the unit must be chosen
        (_decision(plan, unit, expected_change_unit_marker=None), 422),
        (_decision(plan, unit, expected_change_unit_marker=""), 422),
        (_decision(plan, unit, expected_change_unit_marker=12345), 422),
        (_decision(plan, unit, expected_change_unit_marker="x" * 65), 422),
        (_decision(plan, unit, expected_change_unit_marker="2020-01-01T00:00:00"), 409),
    ]
    for payload, expected in cases:
        response = await _post(client, auth_headers, item, payload)
        assert response.status_code == expected, (payload, response.text)
    assert await _event_count(db, item) == 0
    assert await _event_count(db, other_item) == 0


async def test_a_decision_on_a_replaced_plan_is_refused_and_old_decisions_go_stale(client, auth_headers, db):
    item, plan, (unit,) = await _world(db)
    assert (await _post(client, auth_headers, item, _decision(plan, unit))).status_code == 200
    assert (await _gate(client, auth_headers, item))[0]["status"] == "pass"
    newer = WorkChangePlan(work_item_id=item.id, version=2, status="approved", title="Plan v2", created_by=plan.created_by)
    db.add(newer)
    await db.commit()
    assert (await _post(client, auth_headers, item, _decision(plan, unit))).status_code == 409
    gate, _ = await _gate(client, auth_headers, item)
    assert gate["status"] == "review_required", "a decision on v1 is activity once v2 is the latest plan"
    assert gate["evidence"]["plan_version"] == 2


async def test_a_unit_change_makes_its_earlier_decision_stale(client, auth_headers, db):
    item, plan, (unit,) = await _world(db)
    assert (await _post(client, auth_headers, item, _decision(plan, unit))).status_code == 200
    unit.scope = "Scope changed after the review"
    unit.updated_at = utc_now() + timedelta(seconds=5)
    await db.commit()
    assert (await _gate(client, auth_headers, item))[0]["status"] == "review_required"
