"""DevOps workflows acceptance: Feature delivery (B) end to end, and Incident analysis (E) from a signed test alert.

B against the Jira work stub and a local bare git remote (the GitHub stub): the ticket is created (the Work item has
none) → feature branch → clarify submits the test contract → the server drafts the Work item's change plan from it →
the plan confirmed (the payload rebuilt at decision time) → tests written and red → two slices delegated to sub-agents in their own worktrees,
merged → green → independent review → the read-only documentation draft (the reviewed tree proven unchanged) → push →
PR with the requester as reviewer → CI watched on the pushed SHA (a green run of another commit does not count) →
merge watched (signed webhook) → the final documentation → functional acceptance (a) → publication card (b) → the page
published on the Confluence Cloud v2 fake → audience and outsider proofs → "go to deployment" → four-eyes approval by
another admin → the Workspace's deploy job → its result watched (signed Jenkins webhook) → done check → done.

E: a signed test alert starts the Action that names the workflow; its session becomes the run's first phase, the
alert is data on the run; evidence → the hypothesis submitted as data → the owner confirms it → a bug ticket written
from it → Bug fix (C) as sub-workflow, which receives the hypothesis.
"""


from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, Session, WorkflowRun
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.documentation import s1_graph
from app.services.workflow_runs.platform import deploy
from app.services.workflow_runs.review.runner import run_due_reviews
from app.services.workflow_runs.slices import delegate as delegate_module
from app.services.workflow_runs.slices.delegate import delegate_slices
from app.services.workflow_runs.slices.results import merge_slices
from app.services.workflow_runs.watch import poll_watching_runs
from tests.device_job_session_parity_support import B_KEY
from tests.documentation_acceptance_support import DOCUMENTATION
from tests.phased_workflow_fixtures import admin_user
from tests.policy_engine_support import bearer
from tests.prompt_catalog_publish_support import second_admin
from tests.test_workflow_run_tdd_evidence import phase_turn_with_history
from tests.workflow_acceptance_b_e_support import _server_pipeline  # noqa: F401
from tests.workflow_acceptance_b_support import (
    CONFIRMED,
    EDIT,
    FEES_TEST,
    TOTALS_TEST,
    _act,
    _pytest,
    _signed,
    _view,
    s1_publication_systems,
)
from tests.workflow_acceptance_support import (  # noqa: F401 - the stubbed Jira and GitHub fixture
    _phase_turn,
    _settle,
    _workspace,
    jira_stub,
    scm_stub,
    submitted,
    systems,
)
from tests.workflow_run_review_support import ScriptedReviewer


def _stub_jenkins_and_children(monkeypatch):
    """Stub the deploy's Jenkins client and the sub-agent launcher; return the Jenkins class (it records triggers)."""

    class Jenkins:
        triggered: list[str] = []

        async def trigger_build(self, job):
            self.triggered.append(job)
            return {"queued": True, "queue_url": "https://ci.invalid/queue/item/1/"}

        async def queued_build_number(self, queue_url):  # the deploy's queue item started build 7
            return "7" if queue_url.endswith("/queue/item/1/") else None

        async def get_build_status(self, job, number):
            return {"status": "running", "build_url": f"https://ci.invalid/job/{job}/{number}/"}

    async def jenkins(_db, _run):
        return Jenkins()

    monkeypatch.setattr(deploy, "jenkins_client", jenkins)

    async def no_children(_db, **_kwargs):  # the sub-agents' turns are played below, in their worktrees
        return None

    monkeypatch.setattr(delegate_module, "launch_children", no_children)
    return Jenkins


async def _start_run(client, auth_headers, db, project, item):
    # The Workspace deploys with its own job and lets runs read their CI (its tool allow rules).
    policy = dict(project.config["tool_policy"])
    project.config = {**project.config, "deploy_job": "deploy-pay",
                      "tool_policy": {**policy, "allowlist": [*policy["allowlist"], "list_github_action_runs"]}}
    await db.commit()

    started = await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                json={"workflow_key": B_KEY, "work_item_id": item.id})
    assert started.status_code == 200, started.text
    run_id, session_id = started.json()["run"]["id"], started.json()["session_id"]
    view = await _settle(client, auth_headers, run_id)
    ticket = view["ticket_key"]
    assert jira_stub.ISSUES[ticket]["fields"]["issuetype"] == {"name": "Story"}  # created: the item had none
    assert (view["repository"], view["branch"]) == ("github:acme/pay", f"feature/{ticket}-totals-round-down-instead-of-half-up")
    assert view["current_node"]["id"] == "clarify"
    run = await db.get(WorkflowRun, run_id)
    return run_id, session_id, ticket, Path(run.context["local_path"])


async def _clarify_and_confirm_plan(client, auth_headers, db, run_id, session_id):
    # Clarify submits the test contract as data; the server drafts the change plan; the person confirms that plan.
    read = {"tool_name": "read_workspace_file", "status": "success", "result": {}}
    await _phase_turn(db, session_id, [read])
    assert (await _view(client, auth_headers, run_id))["current_node"]["id"] == "clarify"  # chat text is not enough
    contract = {"criteria": [{"id": "AC1", "text": "Totals round half up", "tests": [CONFIRMED[0]],
                              "command": f"pytest {CONFIRMED[0]}"},
                             {"id": "AC2", "text": "The fee is two percent", "tests": [CONFIRMED[1]],
                              "command": f"pytest {CONFIRMED[1]}"}]}
    await _phase_turn(db, session_id, [read, await submitted(db, session_id, "submit_test_contract", contract)])
    stale = (await _view(client, auth_headers, run_id))["waiting"]
    assert [criterion["tests"] for criterion in stale["payload"]["acceptance_criteria"]] == [[CONFIRMED[0]],
                                                                                           [CONFIRMED[1]]]
    run = await db.get(WorkflowRun, run_id)
    from app.models.runtime.secure_work import WorkChangePlan

    plan = await db.get(WorkChangePlan, run.context["change_plan"]["id"])
    plan.understood_request = "Edited in Work while the run waits."
    plan.validation_plan_json = [*plan.validation_plan_json, {"command": "pytest tests", "source": "plan"}]
    await db.commit()
    changed = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                json={"action": "confirm", "payload_hash": stale["payload_hash"]})
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "payload_changed"
    contract = (await _view(client, auth_headers, run_id))["waiting"]
    view = await _act(client, auth_headers, run_id, action="confirm", payload_hash=contract["payload_hash"])
    assert view["current_node"]["id"] == "tests_first"


async def _tests_first_then_merged_slices(client, auth_headers, db, run_id, session_id, working_copy):
    # Tests first: written and red on their assertions.
    (working_copy / "tests" / "test_totals.py").write_text(TOTALS_TEST)
    (working_copy / "tests" / "test_fees.py").write_text(FEES_TEST)
    await _phase_turn(db, session_id, [EDIT, _pytest(working_copy)])
    assert (await _view(client, auth_headers, run_id))["current_node"]["id"] == "implement"

    # Implement: two slices for two sub-agents, each in its own worktree branch, then merged.
    session = await db.get(Session, session_id)
    delegated = await delegate_slices(db, parent_session=session, slices=[
        {"key": "totals", "title": "Round half up", "task": "Fix round_total.", "tests": [CONFIRMED[0]]},
        {"key": "fees", "title": "Two percent fee", "task": "Fix fee.", "tests": [CONFIRMED[1]]}])
    assert [item_["status"] for item_ in delegated["slices"]] == ["running", "running"]
    await db.commit()
    run = await db.get(WorkflowRun, run_id)
    fixes = {"totals": ("pay/totals.py", "def round_total(value: float) -> int:\n    return int(value + 0.5)\n",
                        "tests/test_totals.py"),
             "fees": ("pay/fees.py", "def fee(amount: int) -> int:\n    return amount * 2 // 100\n", "tests/test_fees.py")}
    for key, (path, code, test) in fixes.items():
        slice_ = run.context["slices"][key]
        worktree = Path(slice_["path"])
        (worktree / path).write_text(code)
        child = await db.get(Session, slice_["child_session_id"])
        resolution = await run_turn_resolution(db, child, user_message="Work on the slice.")
        assert resolution["phase_agent"]["key"] == "engineer"  # a slice child runs as its phase's agent
        await phase_turn_with_history(db, child.id, resolution, [EDIT, _pytest(worktree, test)])
    assert {key: item_["status"] for key, item_ in run.context["slices"].items()} == {"totals": "completed",
                                                                                     "fees": "completed"}
    merged = await merge_slices(db, parent_session=session)
    assert {item_["key"]: item_["status"] for item_ in merged["slices"]} == {"totals": "merged", "fees": "merged"}
    await db.commit()
    await _phase_turn(db, session_id, [EDIT, _pytest(working_copy)])
    run = await db.get(WorkflowRun, run_id)
    assert run.gate_results["green"]["state"] == "passed", run.gate_results["green"]


async def _review_draft_push_and_watch_ci(client, auth_headers, db, run_id, session_id, reviewer):
    # Independent review → documentation draft (read-only) → push → PR (you review) → Work item in review → CI.
    await db.commit()
    assert await run_due_reviews(db, model_factory=ScriptedReviewer(
        {"verdict": "pass", "summary": "Both fixes are minimal.", "findings": []}).factory) == 1
    assert (await _settle(client, auth_headers, run_id))["current_node"]["id"] == "doc_draft"
    await _phase_turn(db, session_id, [await submitted(db, session_id, "submit_feature_documentation",
                                                       DOCUMENTATION)])
    view = await _settle(client, auth_headers, run_id)
    assert view["current_node"]["id"] == "ci", view
    run = await db.get(WorkflowRun, run_id)
    await db.refresh(run)
    assert s1_graph.facts(run)["tree_check"]["tree"] == run.context["review"]["tree"]  # the draft changed nothing
    assert run.context["review"]["reviewer_agent"] == reviewer.id  # the review node ran as the Reviewer agent
    head = run.context["head_sha"]
    assert scm_stub.PULLS["acme/pay#1"]["requested_reviewers"][0]["login"] == "requester-gh"
    scm_stub.report_run("acme", "pay", name="tests", head_sha="0" * 40, conclusion="success")  # another commit
    assert await poll_watching_runs(db) == 0
    scm_stub.report_run("acme", "pay", name="tests", head_sha=head, conclusion="success")
    assert await poll_watching_runs(db) == 1
    assert (await _view(client, auth_headers, run_id))["current_node"]["id"] == "merged"


async def _merge_publish_and_prove_documentation(client, auth_headers, db, monkeypatch, project, run_id, session_id,
                                                 ticket):
    # The person merges; the Engineer finalises the documentation as data; the requester accepts the feature (a) and
    # confirms the exact publication card (b); the platform publishes the page and proves its audience.
    cloud = await s1_publication_systems(db, project, monkeypatch, requester=await admin_user(db))
    scm_stub.merge("acme", "pay", 1)
    await _signed(client, db, project.id, "scm_pull_request",
                  {"action": "closed", "repository": {"full_name": "acme/pay"},
                   "pull_request": {"number": 1, "merged": True,  # GitHub always sends the PR's web URL
                                    "html_url": scm_stub.PULLS["acme/pay#1"]["html_url"]}},
                  {"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "merge-b"})
    assert (await _view(client, auth_headers, run_id))["current_node"]["id"] == "doc_final"
    await _phase_turn(db, session_id, [await submitted(db, session_id, "submit_feature_documentation",
                                                       DOCUMENTATION)])
    accept = (await _settle(client, auth_headers, run_id))["waiting"]
    assert accept["subject"] == "functional_acceptance", accept
    view = await _act(client, auth_headers, run_id, action="accept", payload_hash=accept["payload_hash"])
    card = (await _settle(client, auth_headers, run_id))["waiting"]
    assert card["subject"] == "publication", card
    view = await _act(client, auth_headers, run_id, action="confirm", payload_hash=card["payload_hash"])
    for role in ("audience", "outsider"):
        view = await _settle(client, auth_headers, run_id)
        assert view["waiting"]["principal_role"] == role, view
        view = await _act(client, auth_headers, run_id, action="check_audience_receipt")
    view = await _settle(client, auth_headers, run_id)
    assert view["current_node"]["id"] == "confirm_deploy", view
    run = await db.get(WorkflowRun, run_id)
    await db.refresh(run)
    published = s1_graph.facts(run)["publication"]
    page = cloud.pages[published["page_id"]]
    stored = page["versions"][-1]
    assert (stored["title"], page["parentId"], published["version"]) == (
        f"{ticket}: {DOCUMENTATION['title']}", "100001", 1)
    assert CONFIRMED[0] in stored["storage"] and scm_stub.PULLS["acme/pay#1"]["html_url"] in stored["storage"]
    assert published["acceptance_as_published"] == "accepted"
    assert {role: proof["consumed"] for role, proof in s1_graph.facts(run)["audience"].items()} == {
        "audience": True, "outsider": True}
    return published


async def _approve_and_watch_deploy(client, auth_headers, db, project, item, run_id, jenkins):
    view = await _view(client, auth_headers, run_id)
    assert view["current_node"]["id"] == "confirm_deploy"
    view = await _act(client, auth_headers, run_id, action="confirm", payload_hash=view["waiting"]["payload_hash"])
    assert view["waiting_kind"] == "awaiting_approval" and jenkins.triggered == []
    refused = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                json={"action": "approve"})
    assert refused.status_code == 403  # four-eyes: not the requester
    approver = await second_admin(db)
    await db.commit()
    view = await _act(client, bearer(approver.id), run_id, action="approve")
    assert jenkins.triggered == ["deploy-pay"] and view["current_node"]["id"] == "deployed"
    await poll_watching_runs(db)  # resolves the deploy's queue item to its build (still running)
    await db.commit()
    await _signed(client, db, project.id, "ci_build",  # a concurrent build of the job: not ours
                  {"name": "deploy-pay", "build": {"phase": "FINALIZED", "status": "SUCCESS", "number": 8}}, {})
    assert (await _view(client, auth_headers, run_id))["current_node"]["id"] == "deployed"
    await _signed(client, db, project.id, "ci_build",
                  {"name": "deploy-pay", "build": {"phase": "FINALIZED", "status": "SUCCESS", "number": 7}}, {})
    view = await _view(client, auth_headers, run_id)
    assert (view["status"], view["outcome"]) == ("completed", "done")
    await db.refresh(item)
    assert item.work_state == "done"


@pytest.mark.asyncio
async def test_feature_delivery_from_a_missing_ticket_to_a_watched_deployment(client, auth_headers, db, systems,  # noqa: F811
                                                                              monkeypatch):
    project, item = await _workspace(db, systems)
    jenkins = _stub_jenkins_and_children(monkeypatch)
    run_id, session_id, ticket, working_copy = await _start_run(client, auth_headers, db, project, item)

    # The phases run as the Engineer (whatever the composer picked).
    engineer, reviewer = [(await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == key))
                           ).scalar_one() for key in ("engineer", "reviewer")]
    clarify = await run_turn_resolution(db, await db.get(Session, session_id), user_message="Hi.")
    assert (clarify["phase_agent"]["key"], clarify["phase_agent"]["definition_id"]) == ("engineer", engineer.id)

    await _clarify_and_confirm_plan(client, auth_headers, db, run_id, session_id)
    await _tests_first_then_merged_slices(client, auth_headers, db, run_id, session_id, working_copy)
    await _review_draft_push_and_watch_ci(client, auth_headers, db, run_id, session_id, reviewer)
    await _merge_publish_and_prove_documentation(client, auth_headers, db, monkeypatch, project, run_id, session_id,
                                                 ticket)
    await _approve_and_watch_deploy(client, auth_headers, db, project, item, run_id, jenkins)
