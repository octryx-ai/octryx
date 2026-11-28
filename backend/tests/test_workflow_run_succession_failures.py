"""A transient platform failure pauses and a retry succeeds, a non-recoverable one ends blocked, one run is active per work item and workflow, an earlier pull request or change plan is reused, and every platform action routes its failure."""

from __future__ import annotations

import pytest

from app.services.flow_definitions import validate_flow_definition
from app.services.secure_work.pull_requests.record_identity import pull_request_identity
from app.services.workflow_runs.actions import perform_action
from app.services.workflow_runs.records import WorkflowRunError
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_succession_support import BRANCH, Tools, _definition, _item, _origin, _start

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_a_transient_failure_pauses_and_a_retry_succeeds(db, monkeypatch):
    tools = Tools(monkeypatch, {"create_jira_ticket": [{"error": "Service Unavailable", "status_code": 503},
                                                       {"ticket_id": "BRD-77", "status": "created"}]})
    key = await publish_phased(db, _definition(("ticket", "jira.create_issue", {"issue_type": "Task"})))
    item = await _item(db, source_type="manual")
    run = await _start(db, key, item)
    assert (run.status, run.pause_reason) == ("paused", "action_failed")
    assert run.node_state["pause"]["failure_class"] == "transient"
    admin = await admin_user(db)
    await perform_action(db, run, user=admin, body={"action": "retry_action"})
    assert (run.status, run.ticket_key) == ("waiting", "BRD-77")
    assert tools.tools() == ["create_jira_ticket", "create_jira_ticket"]
    # The next run of the item adopts that ticket instead of creating another.
    await perform_action(db, run, user=admin, body={"action": "abort", "reason": "done with it"})
    again = await _start(db, key, item)
    assert (again.ticket_key, again.context["ticket_adopted_from_run"]) == ("BRD-77", run.id)
    assert tools.tools().count("create_jira_ticket") == 2


@pytest.mark.asyncio
async def test_a_non_recoverable_failure_still_ends_blocked(db, monkeypatch):
    Tools(monkeypatch, {})
    key = await publish_phased(db, BRANCH)
    item = await _item(db, source_type="manual")  # no ticket, no platform key: the branch cannot be named, retrying cannot help
    run = await _start(db, key, item)
    assert (run.status, run.outcome) == ("completed", "blocked")
    assert run.context["failed_action"]["failure_class"] == "invalid"


@pytest.mark.asyncio
async def test_one_active_run_per_work_item_and_workflow(db, monkeypatch, tmp_path):
    _seed, work = _origin(tmp_path)
    Tools(monkeypatch, {"prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}]})
    key = await publish_phased(db, BRANCH)
    item = await _item(db)
    first = await _start(db, key, item)
    with pytest.raises(WorkflowRunError) as refused:
        await _start(db, key, item)
    assert refused.value.code == "run_already_active" and first.id in str(refused.value)
    other = await publish_phased(db, _definition(("ticket", "jira.create_issue", {"issue_type": "Task"})))
    assert (await _start(db, other, item)).status == "waiting"  # another workflow on the item may run


@pytest.mark.asyncio
async def test_an_earlier_open_pull_request_is_reused_and_one_on_another_branch_refuses(db, monkeypatch, tmp_path):
    _seed, work = _origin(tmp_path)
    tools = Tools(monkeypatch, {"prepare_github_repository": [{"local_path": str(work), "base_branch": "main"}],
                                "get_github_pull_request": [{"number": 12, "state": "open"}]})
    key = await publish_phased(db, _definition(("branch", "scm.create_branch", {}), ("pr", "scm.open_pr", {})))
    item = await _item(db)
    admin = await admin_user(db)
    first = await _start(db, key, item, branch="feature/brd-pr")
    opened = tools.tools().count("create_github_pull_request")
    url = "https://github.com/acme/payments/pull/12"  # as scm.open_pr stores it: with the identity of its URL
    first.pull_request = {"provider": "github", "repository": "acme/payments", "id": "12", "branch": "feature/brd-pr",
                          "url": url, "state": "open",
                          "identity": pull_request_identity("github", url, "acme/payments", "12")}
    await perform_action(db, first, user=admin, body={"action": "abort", "reason": "again"})
    second = await _start(db, key, item, branch="feature/brd-pr")
    assert second.status == "waiting" and second.pull_request["adopted_from_run"] == first.id
    assert tools.tools().count("create_github_pull_request") == opened  # reused: no second pull request

    await perform_action(db, second, user=admin, body={"action": "abort", "reason": "new branch"})
    third = await _start(db, key, item, branch="feature/brd-pr-2")
    assert (third.pause_reason, third.node_state["pause"]["failure_class"]) == ("action_failed", "pr_conflict")
    tools.answers["get_github_pull_request"] = [{"number": 12, "state": "closed", "merged": False}]
    tools.answers["create_github_pull_request"] = [{"number": 13, "html_url": "https://scm.test/pr/13"}]
    await perform_action(db, third, user=admin, body={"action": "retry_action"})  # closed in the SCM, then retried
    assert third.status == "waiting" and third.pull_request["id"] == "13"


@pytest.mark.asyncio
async def test_the_same_contracts_open_change_plan_is_adopted_never_a_decided_one(db):
    from app.models import WorkChangePlan
    from app.services.secure_work.plans.run_plan import draft_run_plan
    from tests.agent_definition_revision_fixtures import make_project

    project = await make_project(db)
    admin = await admin_user(db)
    item = await _item(db)
    item.project_id = project.id
    envelope = {"hash": "sha256:contract", "version": 1,
                "record": {"summary": "slugify", "criteria": [{"id": "AC1", "text": "slugifies", "command": "pytest",
                                                               "tests": ["t1"]}]}}
    first = await draft_run_plan(db, item=item, requester=admin, run_id="run-a", node_id="draft", envelope=envelope)
    adopted = await draft_run_plan(db, item=item, requester=admin, run_id="run-b", node_id="draft", envelope=envelope,
                                   earlier_run_ids=["run-a"])
    assert adopted.id == first.id
    first.status = "approved"  # a decided plan belongs to the run that confirmed it
    await db.flush()
    fresh = await draft_run_plan(db, item=item, requester=admin, run_id="run-c", node_id="draft", envelope=envelope,
                                 earlier_run_ids=["run-a"])
    assert fresh.id != first.id and isinstance(fresh, WorkChangePlan)


def test_every_platform_action_routes_its_failure_and_a_pause_is_entered_only_by_failures():
    assert validate_flow_definition(BRANCH)["valid"]
    codes = lambda definition: [error["code"] for error in validate_flow_definition(definition)["errors"]]  # noqa: E731
    unrouted = _definition(("branch", "scm.create_branch", {}))
    unrouted["edges"] = [edge for edge in unrouted["edges"] if edge["id"] != "branch-ko"]
    unrouted["edges"].append({"id": "orphan", "source_node_id": "hold", "target_node_id": "action_failed"})
    unrouted["edges"] = [edge for edge in unrouted["edges"] if edge["id"] != "hold-done"]
    assert {"missing_failure_route", "pause_entry"} <= set(codes(unrouted))
    wrong_reason = _definition(("branch", "scm.create_branch", {}))
    wrong_reason["nodes"][-3]["config"] = {"reason": "loop_limit"}
    assert "pause_reason" in codes(wrong_reason)
