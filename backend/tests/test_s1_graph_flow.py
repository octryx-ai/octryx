"""Human statements and recovery through the real graph/decision service."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.workflow_runs import platform_actions
from app.services.workflow_runs.actions import perform_action
from app.services.workflow_runs.documentation import acceptance, publication_card, s1_graph
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.platform import catalog
from app.services.workflow_runs.platform.dispatch import ToolOutcome
from app.services.workflow_runs.records import WorkflowRunError, start_run
from tests.agent_definition_revision_fixtures import make_project
from tests.phased_seed_definitions import seed_definitions
from tests.phased_workflow_fixtures import member_admin, publish_phased

FIXTURE = Path(__file__).parent / "fixtures/s1_graph/b_vnext_definition.json"
PUBLICATION_PAYLOAD = publication_card.publication_payload

@pytest.fixture
def integrated(monkeypatch):
    for key, capability in s1_graph.S1_ACTION_CLASSES.items():
        choices = s1_graph.S1_ACTION_PARAMS.get(key, ())
        monkeypatch.setitem(catalog.ACTIONS, key, catalog.ActionSpec(
            key, capability, frozenset(name for name, _ in choices), choices=choices, requestable=False))
        monkeypatch.setitem(catalog.ACTION_ROUTES, key, s1_graph.S1_ACTION_ROUTES[key])
    original = platform_actions._typed
    async def typed(db, run, key, params, node=None):
        if s1_graph.is_s1_action(key):
            return await s1_graph.run_s1_action(db, run, key, params, node)
        return await original(db, run, key, params, node)
    monkeypatch.setattr(platform_actions, "_typed", typed)
    monkeypatch.setattr(s1_graph, "OVERRIDES", {})

def tail():
    graph = json.loads(FIXTURE.read_text())
    keep = {"accept_functional", "reserve_publication", "confirm_publication", "publish_docs", "docs_in_knowledge",
            "audience_proof", "outsider_proof", "acceptance_open", "done_check", "done", "blocked", "stopped",
            "followup_intent", "followup_create", "followup_readback", "confirm_exception", "done_with_exception",
            "action_failed"}
    nodes = [{"id": "start", "type": "start"}] + [node for node in graph["nodes"] if node["id"] in keep]
    edges = [{"id": "start", "source_node_id": "start", "target_node_id": "accept_functional"}]
    edges.extend(edge for edge in graph["edges"] if edge["source_node_id"] in keep and edge["target_node_id"] in keep)
    edges.extend([
        {"id": "accepted", "source_node_id": "acceptance_open", "target_node_id": "done_check", "when": "accepted"},
        {"id": "change", "source_node_id": "confirm_publication", "target_node_id": "reserve_publication",
         "when": "changed", "kind": "loop", "max_iterations": 2},
    ])
    return {"execution_kind": "phased", "nodes": nodes, "edges": edges}

async def prepared(db, monkeypatch):
    project = await make_project(db)
    project.config = {"feature_documentation": {"acceptance_environment": {"name": "Acceptance", "kind": "test"}}}
    user = await member_admin(db, project.id)
    key = await publish_phased(db, tail())
    run = await start_run(db, user=user, workflow_key=key, project_id=project.id)
    run.context = {**dict(run.context or {}), "head_sha": "pushed", "ci": {"sha": "pushed", "state": "succeeded"}}
    from app.services.workflow_runs.pause import record_decision
    record_decision(db, run, kind="confirmation", subject="test_contract", action="confirmed", user_id=user.id,
                    payload={"acceptance_criteria": [{"id": "AC1", "text": "Feature works", "tests": ["t::test_new"]}]})
    await db.flush()
    payload = await acceptance.acceptance_payload(db, run)
    from app.services.workflow_runs.pause import payload_hash
    run.node_state = {**run.node_state, "waiting": {**run.node_state["waiting"], "payload": payload,
                                                   "payload_hash": payload_hash(payload)}}
    intent = SimpleNamespace(id="intent", run_id=run.id, slot="feature_documentation", superseded_by_id=None,
                             operation_id="operation", marker="marker", state="sent_confirmed", result_page_id="17",
                             result_version=1)
    async def newest(*args): return intent
    async def no_active(*args): return None
    monkeypatch.setattr(s1_graph, "latest_intent", newest)
    monkeypatch.setattr(s1_graph, "active_intent", no_active)
    async def reserve(*args): return intent
    async def approve(*args, **kwargs): assert kwargs["card_hash"]
    async def publish(*args):
        return ToolOutcome("succeeded", {"page_id": "17", "version": 1, "storage_digest": "digest"})
    async def sync(*args): return ToolOutcome("succeeded", {"page_version": 1, "revision_id": "rev"})
    async def challenge(*args, principal_role):
        return SimpleNamespace(id=principal_role, challenge_id=principal_role, expected_principal_id=principal_role,
                               page_id="17", page_version=1, source_key="confluence.test.17", expires_at=None)
    async def consume(*args, principal_role):
        return ToolOutcome("succeeded", {"page_id": "17", "page_version": 1, "result_digest": "digest"})
    async def current_proof(*args): return ToolOutcome("succeeded")
    s1_graph.OVERRIDES.update(reserve_publication_intent=reserve, approve_publication_intent=approve,
                             publish_documentation_v2=publish, sync_published_version=sync,
                             issue_audience_challenge=challenge, consume_audience_receipt=consume,
                             validate_current_publication_proof=current_proof)
    async def publication(_db, _run):
        pending = acceptance.acceptance_state(_run)["state"] == "pending"
        return {"subject": "publication", "output_hash": "output", "canonical_hash": "body", "body": "approved",
                "acceptance_pending": pending, "acceptance": acceptance.acceptance_state(_run),
                "target": {"operation_id": "operation", "marker": "marker"}}
    monkeypatch.setattr(publication_card, "publication_payload", publication)
    return run, user, intent

async def choose(db, run, user, action, **body):
    await perform_action(db, run, user=user, body={"action": action,
        "payload_hash": run.node_state["waiting"].get("payload_hash"), **body})

def test_new_graph_is_closed_and_is_the_engineering_base_seed(integrated):
    graph = json.loads(FIXTURE.read_text())
    assert validate_phased_definition(graph)["valid"]
    subjects = {node["id"]: node.get("config", {}).get("subject") for node in graph["nodes"]}
    assert subjects["accept_functional"] == "functional_acceptance"
    assert subjects["confirm_publication"] == "publication"
    actions = {node["id"]: node.get("config", {}).get("action") for node in graph["nodes"]}
    assert actions["tree_check"] == "documentation.tree_unchanged"
    assert actions["audience_proof"] == actions["outsider_proof"] == "documentation.audience_proof"
    assert actions["done_check"] == "documentation.done_check"
    assert not {"document", "confirm_docs"} & set(actions)  # the pre-S1 documentation path is gone
    assert "handed_over" not in json.dumps(graph)
    shipped = next(seed for seed in seed_definitions() if seed["key"] == "feature-delivery-tdd")
    assert shipped["definition"] == graph


def test_pending_timestamp_and_no_invented_tested_sha():
    assert publication_card._later(datetime(2026, 10, 13), "2026-10-13T18:00:00Z") == "2026-10-13T18:00:00Z"
    build, problems = acceptance._build(SimpleNamespace(context={"head_sha": "new", "ci": {"state": "succeeded"}}))
    assert build["tested_sha"] == "" and problems
    _, problems = acceptance._build(SimpleNamespace(context={"head_sha": "new", "ci": {
        "sha": "old", "state": "succeeded"}}))
    assert "CI evidence is not bound to the pushed commit" in problems

@pytest.mark.asyncio
async def test_confirmed_send_recovery_then_deferred_acceptance_still_waits(db, monkeypatch, integrated):
    run, user, _ = await prepared(db, monkeypatch)
    await choose(db, run, user, "not_testable_yet")
    assert run.current_node_id == "confirm_publication"
    await choose(db, run, user, "confirm")
    assert run.current_node_id == "audience_proof" and run.waiting_kind == "audience_receipt"
    await choose(db, run, user, "check_audience_receipt")
    assert run.current_node_id == "outsider_proof"
    await choose(db, run, user, "check_audience_receipt")
    assert run.current_node_id == "acceptance_open" and run.waiting_kind == "functional_acceptance"
    published = dict(s1_graph.facts(run)["publication"])
    assert published["acceptance_as_published"] == "pending"
    await choose(db, run, user, "accept")
    assert (run.status, run.outcome) == ("completed", "done")
    assert s1_graph.facts(run)["publication"] == published

@pytest.mark.asyncio
async def test_late_acceptance_rechecks_proof_before_completion(db, monkeypatch, integrated):
    run, user, _ = await prepared(db, monkeypatch)
    await choose(db, run, user, "not_testable_yet")
    await choose(db, run, user, "confirm")
    await choose(db, run, user, "check_audience_receipt")
    await choose(db, run, user, "check_audience_receipt")
    async def revoked(*args):
        return ToolOutcome("failed", reason="audience access was revoked", failure_class="audience_unproven")
    s1_graph.OVERRIDES["validate_current_publication_proof"] = revoked
    await choose(db, run, user, "accept")
    assert run.status == "paused" and run.pause_reason == "audience_unproven" and run.outcome is None

@pytest.mark.asyncio
async def test_latest_intent_follows_successors_and_refuses_foreign_run():
    old = SimpleNamespace(id="old", run_id="run", slot="feature_documentation", superseded_by_id="new")
    new = SimpleNamespace(id="new", run_id="run", slot="feature_documentation", superseded_by_id=None)
    class DB:
        async def get(self, model, key): return {"old": old, "new": new}[key]
    run = SimpleNamespace(id="run", context={"publish_prove": {"intent_id": "old"}})
    assert (await s1_graph.latest_intent(DB(), run)).id == "new"
    new.run_id = "foreign"
    assert await s1_graph.latest_intent(DB(), run) is None

@pytest.mark.asyncio
async def test_late_rejection_creates_nothing_until_its_exact_followup_is_authorised(db, monkeypatch, integrated):
    run, user, _ = await prepared(db, monkeypatch)
    run.ticket_key = "BRD-16"
    await choose(db, run, user, "not_testable_yet")
    await choose(db, run, user, "confirm")
    await choose(db, run, user, "check_audience_receipt")
    await choose(db, run, user, "check_audience_receipt")
    calls = []

    async def dispatch(_db, _run, tool, args, **kwargs):
        calls.append((tool, args))
        if tool == "create_jira_ticket":
            return ToolOutcome("succeeded", {"ticket_id": "BRD-99"})
        authorised = s1_graph.facts(_run)["followup"]["authorised"]
        return ToolOutcome("succeeded", {"ticket_id": "BRD-99", "summary": authorised["summary"],
                                         "description": authorised["description"], "issue_type": "Task"})

    from importlib import import_module

    from app.services.workflow_runs.platform import dispatch as dispatch_module

    # Load its function import before patching dispatch; otherwise the lazy module keeps the fake forever.
    import_module("app.services.workflow_runs.platform.jira")
    monkeypatch.setattr(dispatch_module, "dispatch_tool", dispatch)
    await choose(db, run, user, "reject_acceptance", reason="The named preview did not meet AC1")
    assert run.current_node_id == "followup_intent" and not calls
    await choose(db, run, user, "confirm")
    assert [tool for tool, _ in calls] == ["create_jira_ticket", "get_jira_ticket"]
    assert run.status == "completed" and run.outcome == "blocked"
    assert s1_graph.facts(run)["followup"]["readback"]["key"] == "BRD-99"


@pytest.mark.asyncio
async def test_missing_actor_configuration_fails_before_publication_and_missing_environment_cannot_accept(
        db, monkeypatch, integrated):
    from app.services.workflow_runs.documentation import preflight
    project = await make_project(db)
    user = await member_admin(db, project.id)
    key = await publish_phased(db, tail())
    run = await start_run(db, user=user, workflow_key=key, project_id=project.id)
    outcome = await preflight.preflight(db, run)
    assert not outcome.ok and outcome.failure_class == "needs_configuration"
    with pytest.raises(WorkflowRunError) as error:
        await choose(db, run, user, "accept")
    assert getattr(error.value, "code", None) == "nothing_to_confirm"
    assert not s1_graph.facts(run).get("publication")

@pytest.mark.asyncio
async def test_publication_card_contains_exact_reserved_marker_and_immutable_pending_banner(db, monkeypatch, integrated):
    run, user, _ = await prepared(db, monkeypatch)
    await choose(db, run, user, "not_testable_yet")
    intent = SimpleNamespace(id="intent", title=run.title, created_at=datetime(2026, 10, 13), marker="stable-marker",
                             operation="create", operation_id="operation", connection_id="named", instance="https://c/wiki",
                             space_id="1", space_key="DEMO", parent_id="17", page_id=None, base_version=None,
                             expected_version=1)
    async def active(*args): return intent
    async def output(*args):
        return {"version": 1, "hash": "output", "record": {"what": "A feature", "why": "A reason",
                                                             "how_to_use": "Use the feature"}}
    monkeypatch.setattr(s1_graph, "active_intent", active)
    monkeypatch.setattr(publication_card, "_final_output", output)
    from app.services.workflow_runs.documentation import preflight
    monkeypatch.setattr(preflight, "run_link", lambda _: "https://platform.invalid/run")
    payload = await PUBLICATION_PAYLOAD(db, run)
    assert "Functional acceptance pending as of" in payload["body"]
    assert "stable-marker" in payload["body"] and "https://platform.invalid/run" in payload["body"]
    assert payload["acceptance_pending"] and payload["target"]["connection_id"] == "named"
    assert payload["canonical_hash"]

@pytest.mark.asyncio
async def test_confirmed_criteria_do_not_adopt_a_same_named_draft_or_newer_changed_contract(db, monkeypatch, integrated):
    run, _, _ = await prepared(db, monkeypatch)
    run.context = {**run.context, "outputs": {"test_contract": {"record": {"criteria": [{
        "id": "AC1", "text": "Contradictory draft", "tests": ["t::test_new"]}]}}}}
    assert (await acceptance.confirmed_criteria(db, run))[0]["text"] == "Feature works"
    from app.services.workflow_runs.pause import record_decision
    record_decision(db, run, kind="confirmation", subject="test_contract", action="changed", payload={},
                    user_id=run.requested_by)
    await db.flush()
    assert await acceptance.confirmed_criteria(db, run) == []


@pytest.mark.asyncio
async def test_missing_actor_service_error_keeps_its_explicit_configuration_class(monkeypatch):
    class ActorError(Exception):
        code = "principal_refused"
        failure_class = "needs_configuration"
    async def refuse(*args, **kwargs):
        raise ActorError("the configured proof actor is unusable")
    monkeypatch.setattr(s1_graph, "OVERRIDES", {"issue_audience_challenge": refuse})
    outcome = await s1_graph._call("issue_audience_challenge", None, None, principal_role="audience")
    assert not outcome.ok and outcome.failure_class == "needs_configuration"

@pytest.mark.asyncio
async def test_sync_preserves_all_four_representation_digests_from_the_real_service_shape(monkeypatch):
    run = SimpleNamespace(context={"publish_prove": {"publication": {"version": 3}}})
    digests = {key: key for key in ("storage_digest", "view_raw_digest", "document_html_digest", "index_refs_digest")}
    async def sync(*args):
        return ToolOutcome("succeeded", {"page_version": 3, "revision_id": "revision", "digests": digests})
    monkeypatch.setattr(s1_graph, "OVERRIDES", {"sync_published_version": sync})
    outcome, route = await s1_graph._sync(None, run)
    assert outcome.ok and route == "succeeded"
    assert all(s1_graph.facts(run)["sync"][key] == value for key, value in digests.items())
    assert s1_graph.INTERFACES["reconcile_publication_intent"] == "publication_recovery"
