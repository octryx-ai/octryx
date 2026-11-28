"""Plan requirements and their configuration, reviewer overrides, the workspace scope of the review routes and the bounded report queries."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.models import Project, UserProject, WorkItem, WorkReviewerOverride
from tests.services.secure_work.secure_work_coding_review_evidence_support import (
    BASE,
    _auth,
    _decision,
    _event_count,
    _gate,
    _post,
    _user,
    _world,
)

pytestmark = pytest.mark.asyncio


# ---- requirements and configuration ------------------------------------------------------------

async def test_missing_plan_and_malformed_or_unmatched_requirements_never_pass(client, auth_headers, db):
    item = WorkItem(source_type="jira", source_instance="review-decision-test", source_key="OCX-1131-NOPLAN",
                    title="No plan", work_state="intake", sync_state="imported")
    db.add(item)
    await db.commit()
    assert (await _gate(client, auth_headers, item))[0]["status"] == "missing"

    malformed, plan, (unit,) = await _world(db)
    unit.reviewer_policy_json = {"required_reviewers": "alice"}
    await db.commit()
    await _post(client, auth_headers, malformed, _decision(plan, unit))
    gate, _ = await _gate(client, auth_headers, malformed)
    assert gate["status"] == "review_required" and "not readable" in gate["reason"]

    unmatched, plan2, (unit2,) = await _world(db)
    plan2.required_approvals_json = [{"type": "code_review", "repository_name": "payments", "required": True,
                                      "reviewers": []}]
    await db.commit()
    await _post(client, auth_headers, unmatched, _decision(plan2, unit2))
    gate, _ = await _gate(client, auth_headers, unmatched)
    assert gate["status"] == "review_required" and "payments" in gate["reason"]


async def test_plan_code_review_reviewers_are_required_too(client, auth_headers, db):
    alice, bob = await _user(db, "alice"), await _user(db, "bob")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username], members=[alice, bob])
    plan.required_approvals_json = [{"type": "code_review", "repository_name": unit.repository_name, "required": True,
                                     "reviewers": [bob.username]}]
    await db.commit()
    await _post(client, _auth(alice), item, _decision(plan, unit))
    assert (await _gate(client, auth_headers, item))[0]["status"] == "review_required"
    await _post(client, _auth(bob), item, _decision(plan, unit))
    assert (await _gate(client, auth_headers, item))[0]["status"] == "pass"


async def test_overrides_record_assignment_but_never_approve(client, auth_headers, db):
    alice = await _user(db, "alice")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username], members=[alice])
    response = await client.post(f"{BASE}/work-items/{item.id}/reviewer-overrides", headers=auth_headers,
                                 json={"change_unit_id": unit.id, "selected_reviewer": alice.username})
    assert response.status_code == 200, response.text
    gate, report = await _gate(client, auth_headers, item)
    assert gate["status"] == "review_required" and gate["evidence"]["overrides"] == 1
    assert report["pr_summary"]["reviewers"] == []


async def test_override_refuses_another_items_unit_without_writing(client, auth_headers, db):
    item, _, _ = await _world(db)
    _, _, (foreign_unit,) = await _world(db)
    response = await client.post(f"{BASE}/work-items/{item.id}/reviewer-overrides", headers=auth_headers,
                                 json={"change_unit_id": foreign_unit.id, "selected_reviewer": "alice"})
    assert response.status_code == 404
    rows = (await db.execute(select(func.count(WorkReviewerOverride.id))
                             .where(WorkReviewerOverride.work_item_id == item.id))).scalar_one()
    assert rows == 0


# ---- workspace scope on the review routes --------------------------------------------------------

async def test_review_routes_refuse_items_outside_the_workspace(client, db):
    own = Project(name=f"Review Own {uuid.uuid4().hex[:6]}")
    db.add(own)
    await db.flush()
    member, outsider = await _user(db, "member"), await _user(db, "outsider")
    db.add(UserProject(user_id=member.id, project_id=own.id))
    await db.commit()
    item, plan, (unit,) = await _world(db, project_id=own.id)
    for path, method, body in (
        ("coding-review-events", "get", None),
        ("coding-review-events", "post", _decision(plan, unit)),
        ("agent-feedback-context", "get", None),
        ("reviewer-overrides", "get", None),
        ("reviewer-overrides", "post", {"change_unit_id": unit.id, "selected_reviewer": "x"}),
    ):
        url = f"{BASE}/work-items/{item.id}/{path}"
        call = getattr(client, method)
        response = await (call(url, headers=_auth(outsider), json=body) if body else call(url, headers=_auth(outsider)))
        assert response.status_code == 404, (path, method, response.text)  # the answer of a missing item
    assert await _event_count(db, item) == 0
    allowed = await _post(client, _auth(member), item, _decision(plan, unit))
    assert allowed.status_code == 200, allowed.text


# ---- bounded queries -------------------------------------------------------------------------------

async def test_report_query_count_does_not_grow_with_decisions(client, auth_headers, db):
    alice = await _user(db, "alice")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username], members=[alice])
    statements: list[str] = []

    def _count(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    async def _selects() -> int:
        statements.clear()
        sa_event.listen(Engine, "before_cursor_execute", _count)
        try:
            await _gate(client, auth_headers, item)
        finally:
            sa_event.remove(Engine, "before_cursor_execute", _count)
        return len(statements)

    await _post(client, _auth(alice), item, _decision(plan, unit))
    await _selects()  # the suite's shared session looks up the viewer's hidden Workspaces once
    one = await _selects()
    for _ in range(6):
        await _post(client, _auth(alice), item, _decision(plan, unit))
    await _selects()  # a commit forgets the hidden Workspaces; the next read looks them up again
    assert await _selects() == one


async def test_a_repository_requirement_covers_every_matching_unit(client, auth_headers, db):
    alice = await _user(db, "alice")
    item, plan, units = await _world(db, units=2, members=[alice])
    for unit in units:
        unit.repository_name = "shared-repository"
    plan.required_approvals_json = [{"type": "code_review", "repository_name": "shared-repository",
                                     "reviewers": [alice.username], "required": True}]
    await db.commit()
    await _post(client, _auth(alice), item, _decision(plan, units[0]))
    gate, _ = await _gate(client, auth_headers, item)
    assert gate["status"] == "review_required"
    assert [scope["missing_reviewers"] for scope in gate["evidence"]["scopes"]].count([alice.username]) == 1
    await _post(client, _auth(alice), item, _decision(plan, units[1]))
    assert (await _gate(client, auth_headers, item))[0]["status"] == "pass"


@pytest.mark.parametrize(
    "requirements",
    [{"type": "code_review"}, "code_review", [None], [{"reviewers": ["x"]}], [42]],
)
async def test_unreadable_plan_requirements_keep_the_gate_open(client, auth_headers, db, requirements):
    item, plan, (unit,) = await _world(db)
    plan.required_approvals_json = requirements
    await db.commit()
    await _post(client, auth_headers, item, _decision(plan, unit))
    gate, _ = await _gate(client, auth_headers, item)
    assert gate["status"] == "review_required"
    assert gate["evidence"]["requirement_gaps"], "the unreadable requirement is reported, not dropped"
