"""Workflow C "Bug fix with a reproduction test", end to end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, Session, WorkflowRun
from app.models.integration.webhook import Webhook
from app.models.runtime.secure_work import WorkPullRequest
from app.services.inbound_alerts.signature import sign_body
from app.services.webhook_secret import issue_webhook_secret
from app.services.workflow_runs.review.runner import run_due_reviews
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_acceptance_support import (  # noqa: F401
    GITHUB_API,
    KEY,
    REPRO_TEST,
    REPRODUCTION,
    _git,
    _phase_turn,
    _pytest,
    _server_pipeline,
    _settle,
    _workspace,
    jira_stub,
    scm_stub,
    submitted,
    systems,
)
from tests.workflow_run_review_support import ScriptedReviewer

pytestmark = pytest.mark.usefixtures("scripted_pool")

FIXED = "def round_total(value: float) -> int:\n    return int(value + 0.5)\n"


async def _assert_bug_ticket_and_branch(db, systems, run_view: dict, run_id) -> tuple[WorkflowRun, Path]:  # noqa: F811
    ticket = run_view["ticket_key"]
    assert jira_stub.ISSUES[ticket]["fields"]["issuetype"] == {"name": "Bug"}
    assert run_view["branch"] == f"bugfix/{ticket}-totals-round-down-instead-of-half-up"
    assert _git(systems["bare"].parent, "--git-dir", str(systems["bare"]), "branch", "--list", run_view["branch"])
    assert run_view["current_node"]["id"] == "reproduce"
    run = await db.get(WorkflowRun, run_id)
    working_copy = Path(run.context["local_path"])
    return run, working_copy


async def _reproduce_and_confirm(client, auth_headers, db, run_id, session_id, working_copy: Path) -> None:
    from app.services.workflow_runs.binding import run_turn_resolution

    reproduce = await run_turn_resolution(db, await db.get(Session, session_id), user_message="Hi.")
    assert reproduce["phase_agent"]["key"] == "engineer"

    (working_copy / "tests" / "test_totals.py").write_text(REPRO_TEST)
    await _phase_turn(db, session_id, [_pytest(working_copy), await submitted(db, session_id, "submit_reproduction",
                                                                               REPRODUCTION)])
    waiting = (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=auth_headers)).json()["run"]["waiting"]
    assert waiting["subject"] == "reproduction"
    assert [item["id"] for item in waiting["payload"]["failing_tests"]] == ["tests/test_totals.py::test_rounds_half_up"]
    assert (waiting["payload"]["tests"], waiting["payload"]["symptom"]) == (REPRODUCTION["tests"], "assert 2 == 3")
    confirmed = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                  json={"action": "confirm", "payload_hash": waiting["payload_hash"]})
    assert confirmed.json()["run"]["current_node"]["id"] == "fix"


async def _fix_and_pass_review(client, auth_headers, db, run_id, session_id, working_copy: Path):
    (working_copy / "pay" / "totals.py").write_text(FIXED)
    edit = {"tool_name": "edit_workspace_file", "status": "success", "result": {}}
    await _phase_turn(db, session_id, [edit, _pytest(working_copy)])
    reviewer = ScriptedReviewer({"verdict": "pass", "summary": "Rounds half up.", "findings": []})
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    assert "pay/totals.py" in reviewer.tasks[0][1] and "+    return int(value + 0.5)" in reviewer.tasks[0][1]
    run_view = await _settle(client, auth_headers, run_id)
    assert run_view["current_node"]["id"] == "ci", run_view
    return reviewer


async def _watch_ci_until_merge_gate(client, auth_headers, db, systems, project, run, run_id) -> dict:  # noqa: F811
    admin = await admin_user(db)
    ci_hook = Webhook(project_id=project.id, owner_id=admin.id, name="CI acceptance", source_type="ci_build",
                      is_active=True, accept_untimestamped=True)
    db.add(ci_hook)
    await db.flush()
    ci_secret = await issue_webhook_secret(db, ci_hook)
    await db.flush()
    await db.refresh(run)
    ci_body = json.dumps({"action": "completed", "repository": {"full_name": "acme/pay"},
                          "workflow_run": {"name": "Tests and lint", "conclusion": "success",
                                           "head_branch": run.branch, "head_sha": run.context["head_sha"]}}).encode()
    ci_delivered = await client.post(f"/api/v1/webhooks/{ci_hook.id}/trigger", content=ci_body, headers={
        "X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "ci-acceptance-1",
        "X-Hub-Signature-256": sign_body(ci_secret, ci_body)})
    assert ci_delivered.status_code == 202 and ci_delivered.json()["workflow_runs"] == []
    # One success event cannot prove the aggregate. The governed provider reader owns green.
    from app.services.workflow_runs.watch import poll_watching_runs
    systems["ci_runs"].extend([
        {"id": 101, "name": "Tests", "head_sha": run.context["head_sha"], "status": "completed",
         "conclusion": "success", "html_url": GITHUB_API + "/actions/runs/101"},
        {"id": 102, "name": "Lint", "head_sha": run.context["head_sha"], "status": "in_progress"},
    ])
    await poll_watching_runs(db)
    assert (await _settle(client, auth_headers, run_id))["current_node"]["id"] == "ci"
    systems["ci_runs"][1].update(status="completed", conclusion="success")
    await poll_watching_runs(db)
    run_view = await _settle(client, auth_headers, run_id)
    assert run_view["current_node"]["id"] == "merged", run_view
    return run_view


async def _assert_reviewed_push_and_pull_request(db, systems, run, run_view: dict, reviewer, item) -> None:  # noqa: F811
    reviewer_row = (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == "reviewer"))
                    ).scalar_one()
    assert reviewer.reviewer.definition_id == reviewer_row.id and reviewer_row.system_prompt in reviewer.tasks[0][0]
    gates = run.gate_results
    assert gates["reproduces"]["state"] == gates["green"]["state"] == gates["review"]["state"] == "passed"
    pushed = _git(systems["bare"].parent, "--git-dir", str(systems["bare"]), "show",
                  f"{run_view['branch']}:pay/totals.py")
    assert pushed.strip() == FIXED.strip()
    pull = scm_stub.PULLS["acme/pay#1"]
    assert [user["login"] for user in pull["requested_reviewers"]] == ["requester-gh", "pay-lead"]
    recorded = (await db.execute(select(WorkPullRequest).where(WorkPullRequest.work_item_id == item.id))).scalar_one()
    assert (recorded.provider, recorded.pr_id) == ("github", "1")
    await db.refresh(item)
    assert item.work_state == "review"


async def _merge_and_go_on(client, auth_headers, db, project, run_id, item) -> None:
    admin = await admin_user(db)
    webhook = Webhook(project_id=project.id, owner_id=admin.id, name="pull requests", source_type="scm_pull_request",
                      is_active=True, accept_untimestamped=True)
    db.add(webhook)
    await db.flush()
    scm_secret = await issue_webhook_secret(db, webhook)
    await db.flush()
    scm_stub.merge("acme", "pay", 1)
    body = json.dumps({"action": "closed", "repository": {"full_name": "acme/pay"},
                       "pull_request": {"number": 1, "merged": True,  # GitHub always sends the PR's web URL
                                        "html_url": scm_stub.PULLS["acme/pay#1"]["html_url"]}}).encode()
    delivered = await client.post(f"/api/v1/webhooks/{webhook.id}/trigger", content=body, headers={
        "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "merge-1",
        "X-Hub-Signature-256": sign_body(scm_secret, body)})
    assert delivered.status_code == 202 and delivered.json()["workflow_runs"] == [run_id]
    go_on = (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=auth_headers)).json()["run"]["waiting"]
    done = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                             json={"action": "confirm", "payload_hash": go_on["payload_hash"]})
    assert (done.json()["run"]["status"], done.json()["run"]["outcome"]) == ("completed", "done")
    await db.refresh(item)
    assert item.work_state == "done"


@pytest.mark.asyncio
async def test_bug_fix_from_ticket_to_merged_pull_request(client, auth_headers, db, systems):  # noqa: F811
    project, item = await _workspace(db, systems)
    started = await client.post("/api/v1/workflow-runs", headers=auth_headers, json={
        "workflow_key": KEY, "work_item_id": item.id, "project_id": project.id, "repository": "github:acme/pay"})
    assert started.status_code == 200, started.text
    run_id, session_id = started.json()["run"]["id"], started.json()["session_id"]
    run_view = await _settle(client, auth_headers, run_id)

    run, working_copy = await _assert_bug_ticket_and_branch(db, systems, run_view, run_id)

    await _reproduce_and_confirm(client, auth_headers, db, run_id, session_id, working_copy)

    reviewer = await _fix_and_pass_review(client, auth_headers, db, run_id, session_id, working_copy)
    run_view = await _watch_ci_until_merge_gate(client, auth_headers, db, systems, project, run, run_id)
    await _assert_reviewed_push_and_pull_request(db, systems, run, run_view, reviewer, item)

    await _merge_and_go_on(client, auth_headers, db, project, run_id, item)


@pytest.mark.asyncio
async def test_a_reproduction_that_never_fails_pauses_at_n_with_one_follow_up(client, auth_headers, db, systems):  # noqa: F811
    project, item = await _workspace(db, systems)
    started = await client.post("/api/v1/workflow-runs", headers=auth_headers, json={
        "workflow_key": KEY, "work_item_id": item.id, "project_id": project.id, "repository": "github:acme/pay"})
    run_id, session_id = started.json()["run"]["id"], started.json()["session_id"]
    run_view = await _settle(client, auth_headers, run_id)
    ticket = run_view["ticket_key"]
    run = await db.get(WorkflowRun, run_id)
    working_copy = Path(run.context["local_path"])
    for _ in range(3):
        await _phase_turn(db, session_id, [_pytest(working_copy), await submitted(
            db, session_id, "submit_reproduction", REPRODUCTION)])
        changed = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                    json={"action": "change"})
        assert changed.status_code == 200, changed.text
    run_view = (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=auth_headers)).json()["run"]
    assert (run_view["status"], run_view["pause_reason"]) == ("paused", "loop_limit")
    follow_ups = [key for key, issue in jira_stub.ISSUES.items() if "follow-up" in issue["fields"].get("labels", [])]
    assert len(follow_ups) == 1 and run_view["failure"]["follow_up_issue"] == follow_ups[0]
    assert len(jira_stub.ISSUES[ticket]["comments"]) >= 3
    assert {action["key"] for action in run_view["actions"]} >= {"continue", "change_plan", "abort"}
