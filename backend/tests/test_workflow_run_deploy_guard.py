"""Four-eyes before a deploy is structural (publish and runtime), and the deploy watch follows exactly the
build its own queue item started."""

from __future__ import annotations

import copy

import pytest

from app.models import Approval
from app.services.secure_work.cicd.jenkins_client import JenkinsClient, JenkinsRuntimeConfig
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.platform import ci, deploy
from app.services.workflow_runs.records import start_run
from tests.phased_seed_definitions import seed_definitions
from tests.phased_workflow_fixtures import admin_user
from tests.prompt_catalog_publish_support import second_admin
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


async def approve(db, run, approver=None, *, node_id: str = "approve_deploy") -> Approval:
    from app.services.workflow_runs.deploy_four_eyes import record_approval

    approver = approver or await second_admin(db)
    approval = Approval(requested_by=run.requested_by, workspace_id=run.project_id, status="approved",
                        approved_by=approver.id, action="Workflow run: deploy")
    db.add(approval)
    await db.flush()
    record_approval(run, approval_id=approval.id, approved_by=approver.id, node_id=node_id)
    return approval


def deploy_definition(*, other_approval: bool = False) -> dict:
    nodes = [{"id": "start", "type": "start"},
             {"id": "approve_merge", "type": "approval", "label": "Approve the merge", "config": {"unlocks": "merge"}},
             {"id": "confirm", "type": "user_confirmation", "label": "Go on", "config": {"subject": "advance"}},
             {"id": "approve_deploy", "type": "approval", "label": "Approve the deploy", "config": {"unlocks": "x"}},
             {"id": "deploy", "type": "platform_action", "label": "Deploy", "config": {"action": "deploy.run"}},
             {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
             {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}]
    edges = [("start", "approve_merge", None), ("approve_merge", "confirm", "approved"),
             ("approve_merge", "blocked", "rejected"), ("confirm", "blocked", "changed"),
             ("confirm", "blocked", "stopped"), ("deploy", "done", "succeeded"), ("deploy", "blocked", "failed"),
             ("approve_deploy", "deploy", "approved"), ("approve_deploy", "blocked", "rejected")]
    edges.append(("confirm", "deploy" if other_approval else "approve_deploy", "confirmed"))
    if other_approval:
        nodes = [node for node in nodes if node["id"] != "approve_deploy"]
        edges = [edge for edge in edges if "approve_deploy" not in edge[:2]]
    return {"execution_kind": "phased", "nodes": nodes,
            "edges": [{"id": f"e{index}", "source_node_id": source, "target_node_id": target,
                       **({"when": when} if when else {})} for index, (source, target, when) in enumerate(edges)]}


async def at_deploy(db, project_id: str):
    from tests.phased_workflow_fixtures import publish_phased

    run = await start_run(db, user=await admin_user(db), workflow_key=await publish_phased(db, deploy_definition()),
                          project_id=project_id, repository="github:acme/pay")
    run.current_node_id = "deploy"
    return run


def _b() -> dict:
    return copy.deepcopy(next(seed for seed in seed_definitions() if seed["key"] == "feature-delivery-tdd")["definition"])


def test_a_workflow_that_can_deploy_without_an_approval_is_refused_at_publish():
    assert validate_phased_definition(_b())["valid"] and validate_phased_definition(deploy_definition())["valid"]
    # Any approval is not enough: an approval of another subject before the deploy is refused.
    other = deploy_definition(other_approval=True)
    assert "deploy_without_four_eyes" in {error["code"] for error in validate_phased_definition(other)["errors"]}
    other["nodes"][1]["config"]["subject"] = "deploy"  # unless it says it approves the deploy
    assert validate_phased_definition(other)["valid"]
    shortcut = _b()  # an edited Feature delivery: the merge watch goes straight to the deploy
    for edge in shortcut["edges"]:
        if edge["target_node_id"] == "approve_deploy":
            edge["target_node_id"] = "deploy"
    codes = {error["code"] for error in validate_phased_definition(shortcut)["errors"]}
    assert "deploy_without_four_eyes" in codes


class Jenkins:
    def __init__(self):
        self.triggered: list[str] = []

    async def trigger_build(self, job):
        self.triggered.append(job)
        return {"queued": True, "queue_url": "https://ci.invalid/queue/item/41/"}


@pytest.mark.asyncio
async def test_a_deploy_starts_only_with_an_unused_four_eyes_approval_of_this_pass(db, monkeypatch):
    from app.models import Project
    from tests.agent_definition_revision_fixtures import make_project

    jenkins = Jenkins()

    async def client(_db, _run):
        return jenkins

    monkeypatch.setattr(deploy, "jenkins_client", client)
    project = await make_project(db)
    (await db.get(Project, project.id)).config = {"deploy_job": "deploy-prod"}
    run = await at_deploy(db, project.id)
    refused = await deploy.run_deploy(db, run, {})  # before the fix: the job started without any approval
    assert refused.state == "failed" and "four-eyes approval" in refused.reason and jenkins.triggered == []

    approval = await approve(db, run)
    approval.status = "rejected"
    await db.flush()
    assert "not decided approved" in (await deploy.run_deploy(db, run, {})).reason

    await approve(db, run, node_id="approve_merge")  # an approval of another subject in this pass
    assert "not the deploy's approval" in (await deploy.run_deploy(db, run, {})).reason
    await approve(db, run)
    assert (await deploy.run_deploy(db, run, {})).ok and jenkins.triggered == ["deploy-prod"]
    again = await deploy.run_deploy(db, run, {})
    assert again.state == "failed" and "already started a deploy" in again.reason


class QueueClient(JenkinsClient):
    def __init__(self):
        super().__init__(JenkinsRuntimeConfig(base_url="https://ci.invalid", username=None, token=None))

    async def _get_json(self, path, *, params=None):
        if path == "/queue/item/41/api/json":
            return {"executable": {"number": 7}}
        if path.endswith("/7/api/json"):
            return {"number": 7, "result": "FAILURE", "building": False, "url": "https://ci.invalid/job/d/7/"}
        return {"number": 8, "result": "SUCCESS", "building": False, "builds": [
            {"number": 8, "result": "SUCCESS", "building": False, "timestamp": 9_999_999_999_999}]}


@pytest.mark.asyncio
async def test_the_deploy_watch_reads_exactly_the_build_its_queue_item_started():
    result = await ci._deploy_build(QueueClient(), "deploy-prod", "https://ci.invalid/queue/item/41/")
    assert (result.state, result.url) == ("failed", "https://ci.invalid/job/d/7/")  # not the concurrent green 8

    class Queued(QueueClient):
        async def _get_json(self, path, *, params=None):
            return {"why": "Waiting for next available executor"}

    waiting = await ci._deploy_build(Queued(), "deploy-prod", "https://ci.invalid/queue/item/41/")
    assert waiting.state == "running"


@pytest.mark.asyncio
async def test_a_jenkins_notification_satisfies_a_deploy_watch_only_for_the_deploys_own_build(db):
    from app.models import WorkflowRun
    from app.services.workflow_runs.graph import parse_phased_definition
    from app.services.workflow_runs.watch import matches, watch_target
    from app.services.workflow_runs.watch_events import ci_event

    run = WorkflowRun(context={"deploy": {"job": "deploy-prod", "queue_url": "https://ci.invalid/queue/item/41/"}})
    node = parse_phased_definition(_b()).nodes["deployed"]

    def notified(number):
        build = {"phase": "COMPLETED", "status": "SUCCESS", **({"number": number} if number else {})}
        return ci_event({"name": "deploy-prod", "build": build}, {})

    # Before the build number is resolved nothing counts — before the fix any finished build did.
    assert not matches(notified(8), watch_target(run, node))
    ci.record_ci(run, await ci._deploy_build(QueueClient(), "deploy-prod", "https://ci.invalid/queue/item/41/"))
    assert run.context["deploy"]["build_number"] == "7"
    target = watch_target(run, node)
    assert not matches(notified(8), target) and not matches(notified(None), target)  # a concurrent build, or none
    assert matches(notified(7), target)

    class Forgotten(QueueClient):  # Jenkins dropped the queue item: the kept build number still reads the build
        async def queued_build_number(self, queue_url):
            raise AssertionError("the queue item is not asked again")

    again = await ci._deploy_build(Forgotten(), "deploy-prod", "https://ci.invalid/queue/item/41/", "7")
    assert again.state == "failed" and again.build == "7"
