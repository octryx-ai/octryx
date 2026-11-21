"""spec-writing's decisions gate waits for the product owner in the Spec Studio by default.
auto_accept=review_passed is only an explicit opt-in (benchmarks/unattended runs). While waiting, the product owner
gets a notification and the run is visible as 'waiting for spec approval'."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Notification
from app.services.workflow_runs.auto_accept import auto_accept
from tests import test_spec_studio_flow as flow


def _gate(monkeypatch, **config) -> None:
    """The flow test's definition with the decisions node configured like the seed (or the opt-in)."""
    original = flow._definition

    def definition() -> dict:
        found = original()
        for node in found["nodes"]:
            if node["id"] == "decisions":
                node["config"].update(config)
        return found

    monkeypatch.setattr(flow, "_definition", definition)


async def _notifications(db, run) -> list[Notification]:
    return list((await db.execute(select(Notification).where(Notification.user_id == run.requested_by))).scalars())


@pytest.mark.asyncio
async def test_a_passed_spec_waits_for_the_product_owner_who_is_told_once_where_to_approve(
        client, auth_headers, db, tmp_path, monkeypatch):
    from app.services.workflow_runs.attention import inbox_items
    from app.services.workflow_runs.views import run_row

    _gate(monkeypatch, auto_accept="product_owner", auto_revise=2, tasks=False)
    run = await flow._waiting_run(db, tmp_path)
    assert await auto_accept(db, run) is False
    assert await auto_accept(db, run) is False  # a second check (another review event) tells nobody again
    await db.commit()
    await db.refresh(run)
    assert (run.status, run.current_node_id) == ("waiting", "decisions")
    waiting = run.node_state["waiting"]
    assert (waiting["reason"], waiting["title"]) == ("spec_approval", "Waiting for spec approval")
    assert not dict(run.context.get("spec_studio") or {}).get("approved")  # nothing frozen without the person

    sent = await _notifications(db, run)
    assert len(sent) == 1
    assert sent[0].link == f"/chat?area=work&work_view=spec_studio&run_id={run.id}"
    assert sent[0].title.startswith("Spec ready for your approval")
    assert run_row(run)["waiting_reason"] == "spec_approval"
    item = next(item for item in await inbox_items(db, run.requested_by) if item["id"] == run.id)
    assert (item["kind"], item["link"]["href"]) == ("workflow_run_spec_approval", sent[0].link)
    events = (await client.get(f"/api/v1/workflow-runs/{run.id}/events", headers=auth_headers)).json()["events"]
    assert [event["kind"] for event in events].count("waiting_for_product_owner") == 1

    # The product owner approves in the Studio: frozen as their approval, the run goes on.
    approved = await client.post(f"/api/v1/workflow-runs/{run.id}/spec-studio/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    await db.refresh(run)
    assert run.context["spec_studio"]["approved"][-1]["how"] == "product_owner"


@pytest.mark.asyncio
async def test_findings_still_go_back_to_the_agent_and_after_the_revisions_the_product_owner_decides(
        db, tmp_path, monkeypatch):
    _gate(monkeypatch, auto_accept="product_owner", auto_revise=1, tasks=False)
    run = await flow._waiting_run(db, tmp_path)
    finding = {"severity": "high", "text": "R4 has no worked example."}
    run.context = {**run.context, "review": {**run.context["review"], "verdict": "changes", "findings": [finding]}}
    assert await auto_accept(db, run) is True  # revision 1 of 1: back to the draft
    assert run.current_node_id == "draft" and run.context["auto_revisions"] == {"decisions": 1}

    # The draft comes back with the same finding: no more revisions, no automatic accept, the person decides.
    run.status, run.waiting_kind, run.current_node_id = "waiting", "awaiting_confirmation", "decisions"
    run.node_state = {**dict(run.node_state or {}), "waiting": {"subject": "decisions"}}
    assert await auto_accept(db, run) is False
    assert run.node_state["waiting"]["reason"] == "spec_approval"
    assert len(await _notifications(db, run)) == 1


@pytest.mark.asyncio
async def test_review_passed_stays_the_explicit_opt_in_for_unattended_runs(db, tmp_path, monkeypatch):
    _gate(monkeypatch, auto_accept="review_passed", auto_revise=2, tasks=False)
    run = await flow._waiting_run(db, tmp_path)
    assert await auto_accept(db, run) is True
    assert run.status != "waiting" or run.current_node_id != "decisions"
    assert await _notifications(db, run) == []


def test_the_spec_writing_seed_waits_for_the_product_owner_and_records_the_studio():
    from tests.research_phases_support import _seed

    nodes = {node["id"]: node for node in _seed("spec-writing")["nodes"]}
    assert nodes["decisions"]["config"]["auto_accept"] == "product_owner"
    draft = nodes["draft"]["config"]
    assert draft["output"] == "spec_studio" and "submit_spec_studio" in draft["tool_policy"]["allowlist"]
    assert {"type": "tool_called", "params": {"tools": ["submit_spec_studio"]}, "blocking": True,
            "description": "The Spec Studio was submitted"} in draft["workflow_contract"]["checks"]


@pytest.mark.asyncio
async def test_a_workspace_opts_out_of_the_wait_with_one_audited_setting(
        client, auth_headers, db, tmp_path, monkeypatch):
    """Benchmarks: the shipped spec-writing stays as it is, its Workspace says
    ``spec_approval: review_passed`` and a passed spec is accepted without a product owner and without a
    notification. A Workspace copy of the workflow would need a second admin to publish it (four-eyes)."""
    from app.models import AuditLog

    _gate(monkeypatch, auto_accept="product_owner", auto_revise=2, tasks=False)
    created = await client.post("/api/v1/projects", headers=auth_headers, json={"name": "Coffee Bench Codex"})
    assert created.status_code in (200, 201), created.text
    project_id = created.json()["id"]
    refused = await client.put(f"/api/v1/projects/{project_id}/config", headers=auth_headers,
                               json={"spec_approval": "always"})
    assert refused.status_code == 400 and "spec_approval_invalid" in refused.text
    saved = await client.put(f"/api/v1/projects/{project_id}/config", headers=auth_headers,
                             json={"spec_approval": "review_passed"})
    assert saved.status_code == 200, saved.text
    audits = (await db.execute(select(AuditLog))).scalars().all()
    assert any("spec_approval" in str(audit.__dict__) for audit in audits)

    run = await flow._waiting_run(db, tmp_path)
    run.project_id = project_id
    assert await auto_accept(db, run) is True
    assert await _notifications(db, run) == []
    await db.commit()
    events = (await client.get(f"/api/v1/workflow-runs/{run.id}/events", headers=auth_headers)).json()["events"]
    accepted = next(event for event in events if event["kind"] == "auto_accepted")
    assert "Workspace setting spec_approval: review_passed" in accepted["detail"]["reason"]

    # Set back to the default: the next run of the Workspace waits for the product owner again.
    await client.put(f"/api/v1/projects/{project_id}/config", headers=auth_headers,
                     json={"spec_approval": "product_owner"})
    again = await flow._waiting_run(db, tmp_path / "again")
    again.project_id = project_id
    assert await auto_accept(db, again) is False
    assert again.node_state["waiting"]["reason"] == "spec_approval"
