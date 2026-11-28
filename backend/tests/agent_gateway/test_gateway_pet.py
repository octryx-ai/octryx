"""``GET /api/v1/agent-gateway/pet``: the Octryx pet's state, a view over the attention queue."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import UserProject, WorkflowRun
from app.services.attention.pet_view import MAX_ITEMS, pet_view, view_etag
from app.time_utils import utc_now
from tests.agent_gateway.seat_presence_support import _workspace
from tests.agent_gateway.test_gateway_workspaces import _token
from tests.knowledge_evidence_seed_support import seed_member

PATH = "/api/v1/agent-gateway/pet"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_gateway" / "pet_v1.json"
WS_A = {"id": "ws-a", "name": "Acme Orders"}
WS_B = {"id": "ws-b", "name": "Alpha"}
QUIET_OFF = {"active": False, "until": None}


def _entry(key: str, kind: str, severity: str, *, workspace=WS_A, created_at="2026-11-06T10:00:00+00:00",
           href="/chat?session_id=s-1", title: str = "", **extra) -> dict:
    return {"key": key, "kind": kind, "id": key.split(":")[1], "title": title or f"{kind} {key}", "subtitle": "",
            "text": "free text never leaves the queue", "created_at": created_at, "severity": severity,
            "workspace": workspace, "run": None, "work_item": None, "session_id": "s-1",
            "link": {"href": href, "label": "Open"}, "actions": [], **extra}


def _run(run_id: str, state: str, *, workspace=WS_A, updated_at="2026-11-06T09:00:00+00:00", title: str = "") -> dict:
    return {"id": run_id, "workflow_key": "coding", "title": title or f"Run {run_id}", "status": "running", "state": state,
            "workspace": workspace, "session_id": f"s-{run_id}", "updated_at": updated_at}


def _queue(items=(), running=(), quiet=QUIET_OFF) -> dict:
    return {"items": list(items), "running": list(running), "count": len(items), "quiet": quiet,
            "needs_you": sum(1 for item in items if item["severity"] == "action"), "cursor": None}


CASES = {
    "resting": _queue(running=[_run("r-done", "done")]),
    "working": _queue(running=[_run("r-1", "working", title="RIVER-412 Rule import keeps decimals"),
                               _run("r-2", "needs_you"),
                               _run("r-3", "working", updated_at="2026-11-06T09:30:00+00:00",
                                    title="RIVER-415 Faster tenant export")]),
    "needs_you": _queue(items=[
        _entry("clarification:q-1", "question", "action", created_at="2026-11-06T11:00:00+00:00",
               title="Which branch should the import fix go to?"),
        _entry("device_approval:a-1", "device_approval", "action", title="Run tests on MacBook Pro (owner)"),
        _entry("run:p-1:2026-11-06T08:00:00", "problem", "warning", code="loop_limit",
               title="RIVER-409 Retry policy for the scorer"),
        _entry("allowance:5h:2026-11-06T13:00:00+00:00", "allowance", "warning", workspace=None, created_at=None,
               href="/chat?area=operations&tab=usage", title="Seat allowance 5h at 96 %"),
        _entry("done:d-1", "done", "info", href="https://bitbucket.org/team/repo/pull-requests/7",
               title="RIVER-401 Tenant reference export"),
    ], running=[_run("r-1", "working")]),
    "threshold_only": _queue(items=[
        _entry("budget:ws-a:2026-11-07T00:00:00Z", "budget", "warning", created_at=None,
               href="/chat?area=operations&tab=usage", title="Daily budget 41.20 / 50.00 USD"),
    ]),
    "problem": _queue(items=[
        _entry("run:p-1:2026-11-06T08:00:00", "problem", "warning", code="loop_limit",
               title="RIVER-409 Retry policy for the scorer"),
        _entry("done:d-1", "done", "info"),
    ], running=[_run("r-1", "working")]),
    "problem_free_text_code": _queue(items=[
        _entry("run:p-2:2026-11-06T08:00:00", "problem", "warning", code="Paused: something odd happened"),
    ]),
    "done": _queue(items=[_entry("done:d-1", "done", "info", href="https://bitbucket.org/team/repo/pull-requests/7",
                                 title="RIVER-401 Tenant reference export")]),
    "quiet": _queue(items=[_entry("done:d-1", "done", "info")],
                    quiet={"active": True, "until": "2026-11-07T08:00:00+01:00"}),
}


def test_each_case_matches_the_shared_example():
    examples = json.loads(FIXTURE.read_text(encoding="utf-8"))["examples"]
    assert set(examples) == set(CASES)
    for name, queue in CASES.items():
        assert pet_view(queue) == examples[name], name


def test_the_order_and_what_never_leaves_the_queue():
    needs = pet_view(CASES["needs_you"])
    assert needs["state"] == "needs_you" and needs["count"] == 3 and needs["reason"] is None
    assert [item["id"] for item in needs["items"]] == [
        "clarification:q-1", "device_approval:a-1", "allowance:5h:2026-11-06T13:00:00+00:00"]
    assert all(set(item) == {"id", "kind", "title", "url"} for item in needs["items"])
    assert "free text" not in json.dumps(needs)
    assert pet_view(CASES["threshold_only"])["state"] == "needs_you"
    assert pet_view(CASES["problem"])["reason"] == "loop_limit"
    assert pet_view(CASES["problem_free_text_code"])["reason"] is None
    working = pet_view(CASES["working"])
    assert working["count"] == 2 and working["since"] == "2026-11-06T09:30:00+00:00"
    many = pet_view(_queue(items=[_entry(f"clarification:q-{n}", "question", "action") for n in range(9)]))
    assert many["count"] == 9 and len(many["items"]) == MAX_ITEMS
    assert pet_view(CASES["quiet"])["poll_after_seconds"] == 300


def test_a_bound_login_sees_only_its_workspaces_and_the_seat_allowance():
    queue = _queue(items=[
        _entry("clarification:q-b", "question", "action", workspace=WS_B),
        _entry("clarification:q-none", "question", "action", workspace=None),
        _entry("allowance:7d:x", "allowance", "warning", workspace=None),
        _entry("done:d-a", "done", "info"),
    ], running=[_run("r-b", "working", workspace=WS_B)])
    bound = pet_view(queue, workspaces={"ws-a"})
    assert bound["state"] == "needs_you" and [item["id"] for item in bound["items"]] == ["allowance:7d:x"]
    only_done = pet_view(_queue(items=queue["items"][3:], running=queue["running"]), workspaces={"ws-a"})
    assert only_done["state"] == "done"


def test_the_etag_follows_the_view():
    assert view_etag(pet_view(CASES["done"])) == view_etag(pet_view(CASES["done"]))
    assert view_etag(pet_view(CASES["done"])) != view_etag(pet_view(CASES["quiet"]))


@pytest.mark.asyncio
async def test_the_launcher_login_reads_the_pet_state(client, db):
    first, second, foreign = await _workspace(db), await _workspace(db), await _workspace(db)
    user = await seed_member(db, workspace_id=first, role="member")
    db.add(UserProject(user_id=user, project_id=second, role="member"))
    db.add(WorkflowRun(project_id=first, workflow_kind="phased", workflow_key="x", title="Done run",
                       requested_by=user, status="completed", outcome="delivered", completed_at=utc_now()))
    db.add(WorkflowRun(project_id=second, workflow_kind="phased", workflow_key="x", title="Paused run",
                       requested_by=user, status="paused", pause_reason="loop_limit"))
    await db.commit()

    whole = await client.get(PATH, headers=await _token(db, user))
    bound = await client.get(PATH, headers=await _token(db, user, bound=[first]))
    narrowed = await client.get(PATH, params={"project_id": first}, headers=await _token(db, user))
    refused = await client.get(PATH, params={"project_id": foreign}, headers=await _token(db, user))
    missing = await client.get(PATH)

    assert whole.status_code == 200 and whole.json()["state"] == "problem"
    assert whole.json()["reason"] == "loop_limit" and whole.json()["headline"] == "Paused run"
    assert bound.json()["state"] == "done" and narrowed.json()["state"] == "done"
    assert refused.status_code == 403 and refused.json()["reason"] == "workspace_not_authorized"
    assert missing.status_code == 401

    etag = whole.headers["etag"]
    again = await client.get(PATH, headers={**await _token(db, user), "if-none-match": etag})
    assert again.status_code == 304 and again.headers["etag"] == etag and not again.content


def write_fixture() -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["examples"] = {name: pet_view(queue) for name, queue in CASES.items()}
    FIXTURE.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
