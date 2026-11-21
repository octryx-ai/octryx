"""DevOps workflows A (triage), B (feature delivery), D (review & PR), E (incident) as seeds.

The seeds publish with their loop defaults and the deploy phase behind four-eyes; A's Definition of Ready is the
clarification gate (no regex); the deploy actions use the Workspace's deploy job only; D posts the
independent reviewer's verdict on the ticket after a person confirms.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import FlowDefinition, Project
from app.services.secure_work.coding_run import definition_of_ready_gate
from app.services.workflow_runs.actions import perform_action
from app.services.workflow_runs.definition_of_ready import validate_record
from app.services.workflow_runs.graph import parse_phased_definition
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.phase_outputs import submit_output
from app.services.workflow_runs.platform import deploy
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.watch import ci_params, watch_target
from tests.phased_seed_definitions import seed_definitions
from tests.phased_workflow_fixtures import admin_user, run_workspace
from tests.test_workflow_run_pause import _turn
from tests.test_workflow_run_platform_actions import FakeTools, _item

KEYS = ["bug-fix-reproduction", "jira-intake-triage", "feature-delivery-tdd", "incident-analysis"]


def _seed(key: str) -> dict:
    return next(seed for seed in seed_definitions() if seed["key"] == key)


@pytest.mark.asyncio
async def test_the_shipped_workflows_are_published_generic_seeds_with_the_o5_defaults(db):
    published = {row.key for row in (await db.execute(select(FlowDefinition).where(
        FlowDefinition.key.in_(KEYS), FlowDefinition.status == "published"))).scalars()}
    assert published == set(KEYS)
    for key in KEYS:
        assert validate_phased_definition(_seed(key)["definition"])["valid"], key
    graph = parse_phased_definition(_seed("feature-delivery-tdd")["definition"])
    limits = {edge.id: edge.max_iterations for edge in graph.loop_edges()}
    assert (limits["loop-implement"], limits["loop-review"], limits["loop-ci"], limits["loop-retry"]) == (3, 2, 2, 1)
    # Slice children run as the phase's own agent (the Engineer).
    assert graph.nodes["implement"].config["sub_agents"] == {"max_parallel": 5, "iterations": 3}
    assert graph.nodes["implement"].config["agent"] == "engineer"
    # The deploy job only after a person's "go" and a four-eyes approval; its result is watched.
    order = [edge.target for edge in graph.edges if edge.source in ("confirm_deploy", "approve_deploy")
             and edge.when in ("confirmed", "approved")]
    assert order == ["approve_deploy", "deploy"] and graph.nodes["deployed"].config["params"] == {"target": "deploy"}


def test_a_definition_of_ready_is_complete_only_with_its_facts_and_no_open_question():
    feature = {"type": "feature", "summary": "x", "acceptance_criteria": ["Totals round half up"],
               "repository": "github:acme/pay"}
    assert validate_record(feature)["complete"]
    assert validate_record({**feature, "acceptance_criteria": []})["missing"] == ["acceptance criteria"]
    bug = validate_record({"type": "bug", "summary": "x", "repository": "nowhere", "open_questions": ["Which API?"]})
    assert bug["missing"] == ["reproduction steps", "expected behaviour", "actual behaviour",
                              "affected repository (<provider>:<owner>/<repo>)", "open question: Which API?"]


async def _triage(db, monkeypatch, record: dict):
    tools = FakeTools(monkeypatch, {"get_jira_ticket": [{"key": "PAY-1"}]})
    admin = await admin_user(db)
    item = await _item(db)
    workspace_id = await run_workspace(db, admin, item.id)
    run = await start_run(db, user=admin, workflow_key="jira-intake-triage", work_item_id=item.id,
                          project_id=workspace_id, session=await new_chat_session(db, admin, workspace_id))
    await submit_output(db, run, "submit_definition_of_ready", record)
    from app.services.workflow_runs.records import main_session_id

    await _turn(db, await main_session_id(db, run), ["submit_definition_of_ready"])
    return run, item, admin, tools


@pytest.mark.asyncio
async def test_triage_asks_the_confirmed_questions_or_confirms_ready_which_unblocks_coding_runs(db, monkeypatch):
    run, item, admin, tools = await _triage(db, monkeypatch, {"type": "feature", "summary": "x",
                                                              "repository": "github:acme/pay"})
    waiting = run.node_state["waiting"]
    assert (run.current_node_id, waiting["payload"]["questions"]) == ("confirm_questions", ["acceptance criteria"])
    await perform_action(db, run, user=admin, body={"action": "confirm", "payload_hash": waiting["payload_hash"]})
    comment = next(call for call in tools.calls if call[0] == "add_jira_comment")
    assert "- acceptance criteria" in comment[1]["body"] and run.outcome == "blocked"
    assert (await definition_of_ready_gate(db, item))["readiness"] == "blocked"

    ready, item, admin, _tools = await _triage(db, monkeypatch, {
        "type": "feature", "summary": "x", "acceptance_criteria": ["Totals round half up"],
        "repository": "github:acme/pay"})
    assert ready.current_node_id == "confirm_ready" and ready.repository == "github:acme/pay"
    await perform_action(db, ready, user=admin, body={"action": "confirm",
                                                      "payload_hash": ready.node_state["waiting"]["payload_hash"]})
    assert (ready.status, ready.outcome) == ("completed", "done")
    assert (await definition_of_ready_gate(db, item))["readiness"] == "ready"  # N2: the confirmed DoR decides
    from app.services.workflow_runs.definition_of_ready import default_repository

    assert await default_repository(db, item.id, None) == "github:acme/pay"  # a later run starts on it


@pytest.mark.asyncio
async def test_the_deploy_phase_uses_only_the_workspaces_deploy_job_and_watches_its_next_build(db, monkeypatch):
    from tests.agent_definition_revision_fixtures import make_project

    project = await make_project(db)
    admin = await admin_user(db)
    run = await start_run(db, user=admin, workflow_key="incident-analysis", project_id=project.id,
                          repository="github:acme/pay")
    assert (await deploy.configured(db, run))[1] == "not_configured"

    class Jenkins:
        triggered: list[str] = []

        async def trigger_build(self, job):
            self.triggered.append(job)
            return {"queued": True, "queue_url": "https://ci.invalid/queue/item/41/"}

    async def client(_db, _run):
        return Jenkins()

    monkeypatch.setattr(deploy, "jenkins_client", client)
    (await db.get(Project, project.id)).config = {"deploy_job": "deploy-prod"}
    await db.flush()
    from tests.test_workflow_run_deploy_guard import approve, at_deploy

    run = await at_deploy(db, project.id)  # at a deploy node, after its own four-eyes approval
    await approve(db, run)
    assert (await deploy.configured(db, run))[1] == "configured"
    assert (await deploy.run_deploy(db, run, {})).ok and Jenkins.triggered == ["deploy-prod"]
    node = parse_phased_definition(_seed("feature-delivery-tdd")["definition"]).nodes["deployed"]
    target = watch_target(run, node)
    assert (target["job"], target["head_sha"]) == ("deploy-prod", None)  # the deploy builds main, not the run's push
    assert ci_params(run, {"target": "deploy"})["queue_url"] == "https://ci.invalid/queue/item/41/"


