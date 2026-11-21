"""Contract: the Coding session list carries the coding audit's reviewer verdict.

- the list's ``review_summary`` equals the ``reviewer_approval`` gate of ``coding-audit`` for the same
  Work Item (same evaluator, same inputs), bound to the latest plan id and version;
- decisions on a replaced plan or on a since-changed unit do not block the new state;
- an approved work review is not pull-request readiness;
- inputs are loaded once for all listed, workspace-scoped items: the query count is the same for 1
  and 20 items, and no foreign item's review events are read;
- an evaluation failure fails the request; it is never turned into an empty or passing summary.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.engine import Engine

from app.models import WorkChangePlan, WorkItemChangeUnit
from app.services.secure_work.coding import coding_review_summary
from app.time_utils import utc_now
from tests.secure_work_coding_review_evidence_support import BASE, _auth, _decision, _gate, _post, _user, _world

pytestmark = pytest.mark.asyncio


async def _listed(client, headers, item):
    response = await client.get(f"{BASE}/coding-sessions?limit=5000", headers=headers)
    assert response.status_code == 200, response.text
    entry = next(entry for entry in response.json()["items"] if entry["work_item"]["id"] == item.id)
    return entry["review_summary"]


def _same_verdict(summary, gate):
    assert summary["basis"] == "reviewer_approval"
    assert (summary["status"], summary["reason"]) == (gate["status"], gate["reason"])
    # The list flag is "current negative review"; the gate flag is PR-readiness blocking.
    assert summary["blocking"] is (gate["status"] == "block")
    assert (summary["plan_id"], summary["plan_version"]) == (gate["evidence"].get("plan_id"), gate["evidence"].get("plan_version"))


async def test_root_negative_fixture_list_equals_the_audit_gate(client, auth_headers, db):
    alice = await _user(db, "alice")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username], members=[alice])
    created = await _post(client, _auth(alice), item, _decision(plan, unit, decision="changes_requested"))
    assert created.status_code in (200, 201), created.text

    summary = await _listed(client, auth_headers, item)
    gate, report = await _gate(client, auth_headers, item)
    assert gate["status"] == "block"
    _same_verdict(summary, gate)
    assert summary["plan_id"] == plan.id and summary["plan_version"] == 1
    assert report["pr_summary"]["ready_to_open_pr"] is False


@pytest.mark.parametrize("status", ["missing", "pass", "block", "review_required"])
async def test_real_gate_and_list_blocking_flags_differ_only_for_missing(client, auth_headers, db, status):
    """The audit gate's ``blocking`` is PR-readiness (BLOCKING_GATE_STATUSES includes missing); the
    list's ``blocking`` is a current negative review only. The frontend readers rely on both."""
    alice, bob = await _user(db, "alice"), await _user(db, "bob")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username], members=[alice, bob])
    if status == "pass":
        await _post(client, _auth(alice), item, _decision(plan, unit))
    elif status == "block":
        await _post(client, _auth(alice), item, _decision(plan, unit, decision="changes_requested"))
    elif status == "review_required":
        await _post(client, _auth(bob), item, _decision(plan, unit))
    gate, _ = await _gate(client, auth_headers, item)
    summary = await _listed(client, auth_headers, item)
    assert (gate["status"], gate["blocking"]) == (status, status in {"block", "missing"})
    assert (summary["status"], summary["blocking"]) == (status, status == "block")
    assert set(gate["evidence"]) >= {"plan_id", "plan_version", "scopes", "requirement_gaps", "activity_count", "limit"}


async def test_an_approved_review_passes_but_is_not_pr_readiness(client, auth_headers, db):
    alice = await _user(db, "alice")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username], members=[alice])
    await _post(client, _auth(alice), item, _decision(plan, unit))
    summary = await _listed(client, auth_headers, item)
    gate, report = await _gate(client, auth_headers, item)
    _same_verdict(summary, gate)
    assert summary["status"] == "pass"
    assert report["pr_summary"]["ready_to_open_pr"] is False, "other audit gates are still missing"


async def test_a_negative_decision_on_a_replaced_plan_does_not_block_the_new_version(client, auth_headers, db):
    alice = await _user(db, "alice")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username], members=[alice])
    await _post(client, _auth(alice), item, _decision(plan, unit, decision="changes_requested"))
    plan.status = "superseded"
    db.add(WorkChangePlan(work_item_id=item.id, version=2, status="approved", title="Plan v2", created_by=plan.created_by))
    await db.commit()

    summary = await _listed(client, auth_headers, item)
    gate, _ = await _gate(client, auth_headers, item)
    _same_verdict(summary, gate)
    assert summary["status"] != "block" and summary["plan_version"] == 2


async def test_a_unit_changed_after_the_decision_voids_it(client, auth_headers, db):
    alice = await _user(db, "alice")
    item, plan, (unit,) = await _world(db, reviewers=[alice.username], members=[alice])
    await _post(client, _auth(alice), item, _decision(plan, unit, decision="rejected"))
    assert (await _listed(client, auth_headers, item))["status"] == "block"
    row = await db.get(WorkItemChangeUnit, unit.id)
    row.scope = "changed after the review"
    row.updated_at = utc_now()
    await db.commit()

    summary = await _listed(client, auth_headers, item)
    gate, _ = await _gate(client, auth_headers, item)
    _same_verdict(summary, gate)
    assert summary["status"] != "block"


async def test_an_item_without_a_plan_is_missing_without_plan_binding(client, auth_headers, db):
    item, plan, _ = await _world(db, units=0)
    await db.delete(await db.get(WorkChangePlan, plan.id))
    await db.commit()
    summary = await _listed(client, auth_headers, item)
    gate, _ = await _gate(client, auth_headers, item)
    _same_verdict(summary, gate)
    assert (summary["status"], summary["plan_id"], summary["plan_version"]) == ("missing", None, None)


async def test_scoped_list_queries_are_constant_and_never_read_foreign_review_events(client, db):
    member = await _user(db, "member")
    foreign_reviewer = await _user(db, "foreign")
    own_item, own_plan, (own_unit,) = await _world(db, reviewers=[member.username], members=[member])
    project_id = own_item.project_id
    foreign_item, foreign_plan, (foreign_unit,) = await _world(db, reviewers=[foreign_reviewer.username],
                                                                members=[foreign_reviewer])
    await _post(client, _auth(foreign_reviewer), foreign_item, _decision(foreign_plan, foreign_unit, decision="rejected"))
    await _post(client, _auth(member), own_item, _decision(own_plan, own_unit, decision="changes_requested"))

    statements: list[tuple[str, object]] = []

    def _record(_conn, _cursor, statement, parameters, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, parameters))

    async def _list_selects():
        statements.clear()
        sa_event.listen(Engine, "before_cursor_execute", _record)
        try:
            response = await client.get(f"{BASE}/coding-sessions", headers=_auth(member))
        finally:
            sa_event.remove(Engine, "before_cursor_execute", _record)
        assert response.status_code == 200, response.text
        return response.json()["items"], list(statements)

    items, one = await _list_selects()
    assert [entry["work_item"]["id"] for entry in items] == [own_item.id]
    assert items[0]["review_summary"]["status"] == "block"
    review_reads = [params for sql, params in one if "work_coding_review_events" in sql]
    assert review_reads and all(foreign_item.id not in str(params) for params in review_reads)
    # The foreign reviewer has no engineering profile, so no query names them. Users linked to active
    # profiles are read platform-wide (the canonical identity directory), not per workspace.
    assert all(foreign_reviewer.id not in str(params) for sql, params in one if "FROM users" in sql)

    for _ in range(19):
        extra, extra_plan, (extra_unit,) = await _world(db, reviewers=[member.username], project_id=project_id)
        await _post(client, _auth(member), extra, _decision(extra_plan, extra_unit))
    items, twenty = await _list_selects()
    assert len(items) == 20
    assert len(twenty) == len(one), "the list's query count does not grow with the rows"


async def test_an_evaluation_failure_fails_the_list_instead_of_hiding_the_verdict(client, auth_headers, db, monkeypatch):
    await _world(db)

    def _broken(*_args, **_kwargs):
        raise RuntimeError("evaluator failure")

    monkeypatch.setattr(coding_review_summary, "evaluate_reviewer_gate", _broken)
    with pytest.raises(RuntimeError, match="evaluator failure"):
        await client.get(f"{BASE}/coding-sessions", headers=auth_headers)


async def test_project_id_lists_only_that_workspace_and_refuses_one_outside_the_callers_scope(client, auth_headers, db):
    """Coding shows the selected Workspace only; an unknown Workspace is 404."""
    member = await _user(db, "member")
    own_item, _, _ = await _world(db, members=[member])
    other_item, _, _ = await _world(db)

    response = await client.get(f"{BASE}/coding-sessions?project_id={own_item.project_id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert [entry["work_item"]["id"] for entry in response.json()["items"]] == [own_item.id]

    response = await client.get(f"{BASE}/coding-sessions?project_id={other_item.project_id}", headers=_auth(member))
    assert response.status_code == 403, "a Workspace outside the member's scope is refused by the scope guard"

    # an id that names no Workspace is the 404 of an unknown Workspace, for a platform admin too
    response = await client.get(f"{BASE}/coding-sessions?project_id=no-such-workspace", headers=auth_headers)
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "project_not_found")
