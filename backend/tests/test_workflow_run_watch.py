"""DevOps workflows S4b: a run watches an external state; the server observes it (webhook, poll, Jira, approval)."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest

from app.models import UserLinkedAccount
from app.models.integration.webhook import Webhook
from app.models.runtime.secure_work import WorkItem, WorkItemWorkflowDefinition
from app.services.flow_definitions import validate_flow_definition
from app.services.inbound_alerts.signature import sign_body
from app.services.secure_work.pull_requests.record_identity import pull_request_identity
from app.services.webhook_secret import issue_webhook_secret
from app.services.workflow_runs import watch_events as events
from app.services.workflow_runs.sweep import sweep_waiting_runs
from app.services.workflow_runs.watch import deliver_event, deliver_jira_change, poll_watching_runs
from app.time_utils import utc_now
from tests.agent_definition_revision_fixtures import make_project
from tests.phased_workflow_fixtures import admin_user
from tests.test_workflow_run_platform_actions import FakeTools, _repository, _run

PR_URL = "https://github.com/acme/pay/pull/4"


def _opened(url: str = PR_URL, repository: str = "acme/pay") -> dict:
    """The run's pull request as ``scm.open_pr`` stores it: with the identity derived from the provider's URL."""
    return {"provider": "github", "repository": repository, "id": "4", "url": url,
            "identity": pull_request_identity("github", url, repository, "4")}


def _merged(url: str, repository: str = "acme/pay") -> bytes:
    return json.dumps({"action": "closed", "repository": {"full_name": repository},
                       "pull_request": {"number": 4, "merged": True, "html_url": url}}).encode()


def _watching(conditions: list[str], *, advance: str = "confirm", params: dict | None = None,
              open_pr: bool = True) -> dict:
    nodes = [{"id": "start", "type": "start"},
             {"id": "pr", "type": "platform_action", "config": {"action": "scm.open_pr"}},
             {"id": "watch", "type": "watch", "label": "Merged",
              "config": {"conditions": conditions, "advance": advance, **({"params": params} if params else {})}},
             {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
             {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}]
    edges = [{"id": "s", "source_node_id": "start", "target_node_id": "pr" if open_pr else "watch"},
             {"id": "p1", "source_node_id": "pr", "target_node_id": "watch", "when": "succeeded"},
             {"id": "p2", "source_node_id": "pr", "target_node_id": "blocked", "when": "failed"}]
    if not open_pr:
        nodes.pop(1)
        edges = [edges[0]]
    for index, condition in enumerate(conditions):
        target = "blocked" if condition in ("pr.declined", "ci.failed") else "done"
        edges.append({"id": f"w{index}", "source_node_id": "watch", "target_node_id": target, "when": condition})
    return {"execution_kind": "phased", "nodes": nodes, "edges": edges}


def test_provider_events_are_read_into_closed_conditions():
    github = {"action": "closed", "repository": {"full_name": "acme/pay"}, "pull_request": {"number": 4, "merged": True}}
    assert events.scm_event(github, {"X-GitHub-Event": "pull_request"}) == events.WatchEvent(
        "pr.merged", "github", "acme/pay", "4")
    review = {"review": {"state": "APPROVED"}, "repository": {"full_name": "acme/pay"}, "pull_request": {"number": 4}}
    assert events.scm_event(review, {"X-GitHub-Event": "pull_request_review"}).condition == "pr.approved"
    gitlab = {"object_kind": "merge_request", "project": {"path_with_namespace": "acme/pay"},
              "object_attributes": {"action": "close", "iid": 2}}
    assert events.scm_event(gitlab, {}).condition == "pr.declined"
    bitbucket = {"eventKey": "pr:merged", "pullRequest": {"id": 7, "toRef": {"repository": {
        "slug": "pay", "project": {"key": "PAY"}}}}}
    assert events.scm_event(bitbucket, {}) == events.WatchEvent("pr.merged", "bitbucket", "PAY/pay", "7")
    assert events.scm_event({"action": "opened"}, {"X-GitHub-Event": "pull_request"}) is None
    run = {"action": "completed", "repository": {"full_name": "acme/pay"},
           "workflow_run": {"conclusion": "failure", "head_branch": "bugfix/PAY-1-x"}}
    assert events.ci_event(run, {"X-GitHub-Event": "workflow_run"}).condition == "ci.failed"
    assert events.ci_event({"name": "pay-ci", "build": {"phase": "COMPLETED", "status": "SUCCESS"}}, {}) == (
        events.WatchEvent("ci.succeeded", "jenkins", job="pay-ci"))


def test_auto_advance_never_enters_a_higher_class_or_deliver():
    assert validate_flow_definition(_watching(["pr.merged"], advance="auto", open_pr=False))["valid"]
    into_deploy = _watching(["pr.merged"], advance="auto", open_pr=False)
    into_deploy["nodes"].append({"id": "deploy", "type": "platform_action",
                                 "config": {"action": "jira.transition", "params": {"work_state": "done"}}})
    into_deploy["edges"] = [edge for edge in into_deploy["edges"] if edge["id"] != "w0"] + [
        {"id": "w0", "source_node_id": "watch", "target_node_id": "deploy", "when": "pr.merged"},
        {"id": "d1", "source_node_id": "deploy", "target_node_id": "done", "when": "succeeded"},
        {"id": "d2", "source_node_id": "deploy", "target_node_id": "blocked", "when": "failed"}]
    codes = [error["code"] for error in validate_flow_definition(into_deploy)["errors"]]
    assert "auto_advance_into_higher_class" in codes
    jira = _watching(["jira.status"], open_pr=False)
    assert "watch_work_state" in [error["code"] for error in validate_flow_definition(jira)["errors"]]


async def _pr_run(db, monkeypatch, definition: dict):
    tools = FakeTools(monkeypatch, {"create_github_pull_request": [
        {"number": 4, "html_url": "https://scm.test/pr/4", "status": "created", "reviewers_unresolved": []}]})
    admin = await admin_user(db)
    project = await make_project(db)
    await _repository(db, project.id, "github", "pay", owners=[])
    db.add(UserLinkedAccount(user_id=admin.id, platform="github", username="admin-scm"))
    item = WorkItem(source_type="jira", source_instance="t", source_key=f"PAY-{uuid.uuid4().hex[:4]}",
                    title="Totals", project_id=project.id)
    db.add(item)
    await db.flush()
    run = await _run(db, definition, work_item_id=item.id, project_id=project.id, repository="github:acme/pay")
    run.branch = "bugfix/x"
    return run, tools, project


@pytest.mark.asyncio
async def test_a_signed_pr_webhook_moves_the_watching_run_after_the_requesters_go_on(client, auth_headers, db,
                                                                                    monkeypatch):
    definition = _watching(["pr.merged", "pr.declined"])
    definition["nodes"][1]["config"] = {"action": "scm.open_pr"}
    # The run needs a branch before its PR: give the definition's run one through the PR facts directly.
    run, _tools, project = await _pr_run(db, monkeypatch, definition)
    assert run.outcome == "blocked"  # no branch yet: the PR step fails explicitly
    admin = await admin_user(db)
    run = await _run(db, definition, project_id=project.id, repository="github:acme/pay")
    run.status, run.waiting_kind, run.current_node_id = "waiting", "watching", "watch"
    run.pull_request = _opened()
    run.node_state = {"waiting": {"kind": "watching", "since": utc_now().isoformat(),
                                  "target": {"pr": run.pull_request["identity"], "repository": run.repository}}}
    webhook = Webhook(project_id=project.id, owner_id=admin.id, name="scm", source_type="scm_pull_request",
                      is_active=True, accept_untimestamped=True)
    db.add(webhook)
    await db.flush()
    secret = await issue_webhook_secret(db, webhook)
    await db.flush()
    body = _merged(PR_URL)
    # Signed events of the same path and number on another host, or of another owner's same-named repository, never
    # match: the event is bound to the host of the pull request URL in its signed payload first.
    for index, other in enumerate((_merged("https://ghe.example.test/acme/pay/pull/4"),
                                   _merged("https://github.com/other/pay/pull/4", "other/pay"),
                                   json.dumps({"action": "closed", "repository": {"full_name": "acme/pay"},
                                               "pull_request": {"number": 4, "merged": True}}).encode())):
        missed = await client.post(f"/api/v1/webhooks/{webhook.id}/trigger", content=other, headers={
            "X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sign_body(secret, other),
            "X-GitHub-Delivery": f"other-{index}"})
        assert missed.status_code == 202 and missed.json()["workflow_runs"] == []
    assert run.waiting_kind == "watching"
    forged = await client.post(f"/api/v1/webhooks/{webhook.id}/trigger", content=body,
                               headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=00"})
    assert forged.status_code == 401
    signed = await client.post(f"/api/v1/webhooks/{webhook.id}/trigger", content=body, headers={
        "X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sign_body(secret, body),
        "X-GitHub-Delivery": "d-1"})
    assert signed.status_code == 202 and signed.json()["workflow_runs"] == [run.id]
    assert (run.waiting_kind, run.node_state["waiting"]["watched"]) == ("awaiting_confirmation", "pr.merged")
    view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=auth_headers)).json()["run"]
    confirmed = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                                  json={"action": "confirm", "payload_hash": view["waiting"]["payload_hash"]})
    assert confirmed.json()["run"]["outcome"] == "done"


@pytest.mark.asyncio
async def test_the_poll_fallback_jira_changes_approvals_and_the_timeout(db, monkeypatch):
    run, tools, project = await _pr_run(db, monkeypatch, _watching(["pr.merged"], advance="auto", open_pr=False))
    run.status, run.waiting_kind = "waiting", "watching"
    tools.answers["get_github_pull_request"] = [{"number": 4, "state": "closed", "merged": True}]
    # Recorded on another host than the repository's connection (github.com) serves: never read, never moves.
    run.pull_request = _opened("https://ghe.example.test/acme/pay/pull/4")
    assert await poll_watching_runs(db) == 0 and "get_github_pull_request" not in tools.tools()
    run.pull_request = _opened()
    assert await poll_watching_runs(db) == 1
    assert tools.calls[-1][:2] == ("get_github_pull_request", {"repository": "acme/pay", "pr_number": "4"})
    assert (run.status, run.outcome) == ("completed", "done")  # auto: a read-only outcome needs no "go on"

    admin = await admin_user(db)
    db.add(WorkItemWorkflowDefinition(name="wb", states_json=[], mappings_json={"review": {"source_status": "In Review"}},
                                      is_default=True, is_active=True, created_by=admin.id, updated_by=admin.id))
    jira_run = await _run(db, _watching(["jira.status"], advance="auto", params={"work_state": "review"},
                                        open_pr=False), project_id=project.id)
    jira_run.ticket_key = "PAY-77"
    jira_run.node_state["waiting"]["target"]["ticket_key"] = "PAY-77"
    db.add(WorkItem(source_type="jira", source_instance="t", source_key="PAY-77", title="x", project_id=project.id))
    await db.flush()
    assert await deliver_jira_change(db, {"key": "PAY-77", "status": "Done"}, project_id=project.id) == []
    # A change source of another Workspace never moves this Workspace's runs (review: Workspace scoping).
    assert await deliver_jira_change(db, {"key": "PAY-77", "status": "In Review"}, project_id="other") == []
    assert await deliver_jira_change(db, {"key": "PAY-77", "status": "In Review"}, project_id=project.id) == [
        jira_run.id]

    approval_run = await _run(db, _watching(["approval.decided"], advance="auto", open_pr=False),
                              project_id=project.id)
    approval_run.node_state["waiting"]["target"]["approval_id"] = "appr-1"
    assert await deliver_event(db, events.WatchEvent("approval.decided", approval_id="appr-2"), source="t") == []
    assert await deliver_event(db, events.WatchEvent("approval.decided", approval_id="appr-1"), source="t") == [
        approval_run.id]

    late = await _run(db, _watching(["pr.merged"], open_pr=False), project_id=project.id)
    await sweep_waiting_runs(db, now=utc_now() + timedelta(hours=121))
    assert (late.status, late.pause_reason) == ("paused", "watch_timeout")


@pytest.mark.asyncio
async def test_succession_adoption_reads_only_the_stored_identity_on_the_repositorys_host(db, monkeypatch):
    from app.models import WorkflowRun
    from app.services.workflow_runs.platform.pr_adoption import earlier_pull_request
    from app.services.workflow_runs.platform.repo_ref import parse_repository

    run, tools, project = await _pr_run(db, monkeypatch, _watching(["pr.merged"], open_pr=False))
    admin = await admin_user(db)

    def earlier(title: str, pull_request: dict, branch: str) -> WorkflowRun:
        return WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="k", title=title,
                           requested_by=admin.id, status="completed", work_item_id=run.work_item_id,
                           repository=run.repository, branch=branch, pull_request={**pull_request, "branch": branch})

    # Same path and number on another host, open on another branch: another repository's pull request, so it neither
    # blocks (pr_conflict) nor is read.
    elsewhere = earlier("elsewhere", _opened("https://ghe.example.test/acme/pay/pull/4"), "feature/other")
    db.add(elsewhere)
    await db.flush()
    tools.answers["get_github_pull_request"] = [{"number": 4, "state": "open"}]
    assert await earlier_pull_request(db, run, parse_repository(run.repository)) is None
    assert "get_github_pull_request" not in tools.tools()

    own = earlier("own", _opened(), run.branch)
    db.add(own)
    await db.flush()
    adopted = await earlier_pull_request(db, run, parse_repository(run.repository))
    assert adopted.ok and adopted.result["adopted_from_run"] == own.id
    assert run.pull_request["identity"] == own.pull_request["identity"]
    assert [call[:2] for call in tools.calls if call[0] == "get_github_pull_request"] == [
        ("get_github_pull_request", {"repository": "acme/pay", "pr_number": "4"})]
