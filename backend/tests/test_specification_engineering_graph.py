"""The new authored engineering graph and its parent template, a start that writes nothing, the accepted spec consumed by Clarify and docs, MCP phase facts, and the offer into the pinned new graph."""

from __future__ import annotations

import copy
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.models import FlowDefinition, WorkflowRun
from app.models.runtime.secure_work import WorkItem
from app.models.runtime.workflow_handoff import WorkflowHandoff
from app.services.workflow_runs.decider import resolve_decider, validate_decider_config
from app.services.workflow_runs.graph import graph_for_run, parse_phased_definition
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.handoff import service
from app.services.workflow_runs.handoff.allocation import allocate_child
from app.services.workflow_runs.handoff.contract import canonical_hash
from app.services.workflow_runs.handoff.permissions import rights_evaluator
from app.services.workflow_runs.phase_contract import phase_definition
from app.services.workflow_runs.records import WorkflowRunError, start_run
from app.services.workflow_runs.seeding import definition_digest
from app.services.workflow_runs.specification.integration import authorized_phase_definition
from app.services.workflow_runs.specification.lineage import SpecificationUnavailable
from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.specification_definition_support import specification_definition
from tests.specification_engineering_graph_support import (
    BASE_DIGEST,
    ENGINEERING_KEY,
    OFFER_NODE,
    SPEC_ORIGIN_NODES,
    base_seed,
    spec_engineering_definition,
    specification_engineering_definition,
)
from tests.specification_engineering_integration_support import (  # noqa: F401
    SPEC_TEXT,
    _server_pipeline,
    mcp_status,
    tables,
)
from tests.specification_engineering_support import SPEC_CRITERIA, engineering_child_case, enter_node
from tests.team_handoff_support import action

pytestmark = pytest.mark.usefixtures("scripted_pool")

# --- The new authored graph and the parent template ---------------------------------------------------------


def _base():
    return base_seed()["definition"]


def test_new_graph_is_valid_and_keeps_every_existing_b_s1_contract():
    base, new = _base(), spec_engineering_definition()
    assert definition_digest(base) == BASE_DIGEST  # the original B seed itself is untouched
    assert validate_phased_definition(new)["valid"], validate_phased_definition(new)["errors"]
    assert new["edges"] == base["edges"]
    assert {key: value for key, value in new.items() if key != "nodes"} == {
        key: value for key, value in base.items() if key != "nodes"}
    allowed = {"start": {"handoff_inputs"}, "clarify": {"inputs", "workflow_contract"},
               "doc_draft": {"inputs", "workflow_contract"}, "doc_final": {"inputs", "workflow_contract"},
               "contract": {"shows"}, **{node: {"decider"} for node in SPEC_ORIGIN_NODES}}
    for old, current in zip(base["nodes"], new["nodes"], strict=True):
        assert (old["id"], old["type"], old.get("label")) == (current["id"], current["type"], current.get("label"))
        before, after = old.get("config") or {}, current.get("config") or {}
        changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        assert changed <= allowed.get(old["id"], set()), (old["id"], changed)
        if "workflow_contract" in changed:
            assert ({k: v for k, v in before["workflow_contract"].items() if k != "when_to_use"}
                    == {k: v for k, v in after["workflow_contract"].items() if k != "when_to_use"})
    graph = parse_phased_definition(new)
    assert graph.start().config == {"handoff_inputs": ["spec"]}
    assert all("spec" in graph.nodes[node].config["inputs"] for node in ("clarify", "doc_draft", "doc_final"))
    assert graph.nodes["contract"].config == {"decider": "requester", "subject": "test_contract",
                                              "documentation_contract": True, "shows": "spec"}
    deciders = {node.id: node.config["decider"] for node in graph.nodes.values() if "decider" in node.config}
    assert {node: policy for node, policy in deciders.items() if policy != "requester"} == dict.fromkeys(
        SPEC_ORIGIN_NODES, "spec_origin")
    assert spec_engineering_definition() == new and spec_engineering_definition() is not new


@pytest.mark.parametrize("change,code", [
    (lambda d: d["nodes"][0].pop("config"), "consumer_without_producer"),
    (lambda d: d["nodes"][0].update(config={"handoff_inputs": ["idea_frame"]}), "handoff_inputs_invalid"),
    (lambda d: d["nodes"][0].update(config={"handoff_inputs": ["spec", "spec"]}), "handoff_inputs_invalid"),
    (lambda d: d["nodes"][0].update(config={"handoff_inputs": "spec"}), "handoff_inputs_invalid"),
    (lambda d: next(n for n in d["nodes"] if n["id"] == "clarify")["config"].update(handoff_inputs=["spec"]),
     "handoff_inputs_invalid"),
])
def test_new_graph_data_flow_needs_the_typed_handoff_input(change, code):
    definition = spec_engineering_definition()
    change(definition)
    errors = validate_phased_definition(definition)["errors"]
    assert code in {error["code"] for error in errors}, errors


def test_spec_origin_is_an_authored_closed_decider_value_only():
    assert validate_decider_config({"decider": "spec_origin"}) == ""
    for config in ({"deputy": "spec_origin"}, {"decider": "spec_origin:pm"}, {"decider": ["spec_origin"]}):
        assert validate_decider_config(config)
    base = copy.deepcopy(_base())
    next(n for n in base["nodes"] if n["id"] == "accept_functional")["config"]["decider"] = "spec_origin"
    codes = {error["code"] for error in validate_phased_definition(base)["errors"]}
    assert "spec_origin_without_handoff" in codes  # never on a graph without its accepted spec
    assert validate_phased_definition(_base())["valid"]  # a node without an authored decider uses the requester


def test_parent_template_offers_the_exact_pinned_child_before_its_terminal_done():
    child = spec_engineering_definition()
    ids = [str(uuid.uuid4()) for _ in range(6)]
    parent = specification_engineering_definition(
        child_version_id=ids[0], child_checksum=canonical_hash(child), workspace_id=ids[1], work_item_id=ids[2],
        repository="bitbucket:demo-team/test", connection_ids=[ids[3]], source_ids=[ids[4]], engineer_id=ids[5])
    assert validate_phased_definition(parent)["valid"], validate_phased_definition(parent)["errors"]
    graph = parse_phased_definition(parent)
    offer = graph.nodes[OFFER_NODE]
    assert offer.kind == "sub_workflow" and offer.config["workflow_key"] == ENGINEERING_KEY
    assert (offer.config["child_version_id"], offer.config["child_checksum"]) == (ids[0], canonical_hash(child))
    handoff = offer.config["handoff"]
    assert handoff["owner"] == f"person:{ids[5]}" and handoff["artefacts"] == ["spec"] and not handoff["detach"]
    assert handoff["scope"] == {"workspace_id": ids[1], "work_item_id": ids[2], "repository": "bitbucket:demo-team/test",
                                "service_ids": [], "connection_ids": [ids[3]], "source_ids": [ids[4]]}
    assert [edge.target for edge in graph.exits("confirm-spec") if edge.when == "confirmed"] == [OFFER_NODE]
    assert {edge.when: edge.target for edge in graph.exits(OFFER_NODE)}["done"] == "done"
    # Connective only: no ticket, link, notification or other platform write in the parent.
    assert not [node for node in graph.nodes.values() if node.kind == "platform_action"]
    assert [edge["target"] for edge in specification_definition()["edges"] if edge["id"] == "accepted"] == ["done"]
    for bad in ({"child_checksum": "sha256:short"}, {"child_version_id": ""}):
        broken = copy.deepcopy(parent)
        next(n for n in broken["nodes"] if n["id"] == OFFER_NODE)["config"].update(bad)
        assert "invalid_child_pin" in {error["code"] for error in validate_phased_definition(broken)["errors"]}


# --- Start, Clarify input, documentation context ----------------------------------------------------------


@pytest.mark.asyncio
async def test_new_graph_never_starts_directly_and_writes_nothing(db):
    key = await publish_phased(db, spec_engineering_definition())
    before = await db.scalar(select(func.count()).select_from(WorkflowRun))
    with pytest.raises(WorkflowRunError) as error:
        admin = await admin_user(db)
        await start_run(db, user=admin, workflow_key=key, project_id=await run_workspace(db, admin))
    assert error.value.code == "needs_configuration"
    assert await db.scalar(select(func.count()).select_from(WorkflowRun)) == before


@pytest.mark.asyncio
async def test_clarify_and_docs_consume_only_the_actual_callers_accepted_spec(db):
    case = await engineering_child_case(db)
    await enter_node(db, case.child, "clarify")
    graph = await graph_for_run(db, case.child)
    assert case.child.context["handoff"]["spec"]["criteria"] == SPEC_CRITERIA  # the copy exists, and is never used
    raw = phase_definition(case.child, graph.nodes["clarify"])["workflow_contract"]["workflow_run_phase"]
    assert "spec" not in raw.get("inputs", {})
    for node in ("clarify", "doc_draft", "doc_final"):
        definition = await authorized_phase_definition(db, case.child, graph.nodes[node], principal=case.engineer)
        inputs = definition["workflow_contract"]["workflow_run_phase"]["inputs"]
        assert inputs["spec"] == case.row.envelopes["spec"]["envelope"]["record"]
        assert [row["id"] for row in inputs["spec"]["criteria"]] == ["AC7", "AC2"]
    # The PM may read it as themself; a denied member, a missing caller and the requester fallback may not.
    assert await authorized_phase_definition(db, case.child, graph.nodes["clarify"], principal=case.pm)
    for principal in (case.denied, None):
        with pytest.raises(SpecificationUnavailable):
            await authorized_phase_definition(db, case.child, graph.nodes["clarify"], principal=principal)
    assert not case.child.context.get("outputs", {}).get("spec")


@pytest.mark.asyncio
async def test_mcp_phase_facts_are_projected_for_the_actual_caller(db):
    from app.services.workflow_runs.octryx.contract import run_contract

    case = await engineering_child_case(db)
    await enter_node(db, case.child, "clarify")
    owner = await mcp_status(db, case.child, case.engineer)
    assert owner["phase"]["inputs"]["spec"]["criteria"] == SPEC_CRITERIA
    assert "submit_test_contract" in owner["phase"]["tools"]["allow"]
    for contract in (await mcp_status(db, case.child, case.denied), await run_contract(db, case.child)):
        assert not contract["phase"]["inputs"] and not contract["phase"]["tools"]["allow"]
        assert SPEC_TEXT not in json.dumps(contract)


# --- How a run reaches the new B from the spec parent -----------------------------------------------------------


@pytest.mark.asyncio
async def test_spec_parent_offers_into_the_exact_pinned_new_b_and_the_named_engineer_accepts(db):
    from tests.test_specification_handoff_authority import prepared_spec_case

    case = await prepared_spec_case(db, criteria=copy.deepcopy(SPEC_CRITERIA))
    child_key = await publish_phased(db, spec_engineering_definition(), key=ENGINEERING_KEY)
    child_flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == child_key))).scalar_one()
    from app.models import FlowDefinitionVersion

    child_version = await db.get(FlowDefinitionVersion, child_flow.current_version_id)
    item = WorkItem(source_type="jira", source_instance="t", source_key="SPEC-1", source_project_key="SPEC",
                    title="The specified feature", project_id=case.parent.project_id, work_state="development")
    db.add(item)
    await db.flush()
    scope = {"workspace_id": case.parent.project_id, "work_item_id": item.id, "repository": None,
             "connection_ids": [], "source_ids": [case.source.id], "engineer_id": case.receiver.id}
    parent_key = await publish_phased(db, specification_engineering_definition(
        child_version_id=child_version.id, child_checksum=canonical_hash(child_version.definition_json), **scope))
    parent_flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == parent_key))).scalar_one()
    case.parent.flow_definition_version_id, case.parent.workflow_key = parent_flow.current_version_id, parent_key
    case.parent.work_item_id = item.id
    case.parent.current_node_id = OFFER_NODE
    await db.flush()
    from app.services.workflow_runs.sub_workflows import start_sub_workflow

    node = (await graph_for_run(db, case.parent)).nodes[OFFER_NODE]
    stale = copy.deepcopy(node.config)
    stale["child_checksum"] = "sha256:" + "0" * 64
    with pytest.raises(WorkflowRunError) as error:
        await start_sub_workflow(db, case.parent, type(node)(node.id, node.kind, node.title, stale), actor_id=None)
    assert error.value.code == "needs_configuration"
    assert not (await db.execute(select(WorkflowHandoff))).scalars().all()
    await start_sub_workflow(db, case.parent, node, actor_id=None)
    row = (await db.execute(select(WorkflowHandoff).where(WorkflowHandoff.parent_run_id == case.parent.id))).scalar_one()
    assert row.child_descriptor == {"workflow_key": ENGINEERING_KEY, "version_id": child_version.id,
                                    "checksum": canonical_hash(child_version.definition_json)}
    assert (row.target_kind, row.target_key) == ("person", case.receiver.id) and row.envelopes["spec"]
    assert (case.parent.status, case.parent.waiting_kind) == ("waiting", "handoff")
    binding = await service.accept_handoff(db, row.id, case.receiver, action(row),
                                           rights_evaluator=rights_evaluator, allocator=allocate_child)
    child = await db.get(WorkflowRun, binding["child_run_id"])
    assert (child.workflow_key, child.flow_definition_version_id) == (ENGINEERING_KEY, child_version.id)
    assert child.requested_by == case.receiver.id and child.work_item_id == item.id and child.ticket_key == "SPEC-1"
    node = (await graph_for_run(db, child)).nodes["confirm_publication"]
    assert (await resolve_decider(db, child, node)).user_ids == (case.sender.id,)  # the producer confirmed this spec
