"""Closed proposal records refuse aliases, server fields and invalid refs, and the producer's definition, budget values and tool definitions stay bounded and closed."""

import copy

import pytest

from app.services.workflow_runs.specification.lineage import SpecificationUnavailable
from app.services.workflow_runs.specification.records import record_readiness, validate_proposal
from tests.specification_definition_support import BUDGET, specification_definition
from tests.specification_producer_support import BRIEF, IDEA, PLAN, SPEC


@pytest.mark.parametrize("kind,proposal", [("idea_frame", IDEA), ("research_plan", PLAN),
                                           ("research_brief", BRIEF), ("spec", SPEC)])
def test_closed_proposals_do_not_alias_or_accept_server_fields(kind, proposal):
    record, errors = validate_proposal(kind, proposal)
    assert not errors and record == proposal and record is not proposal
    for key in ["evidence", "budget", "idea_frame_ref", "actor", "complete", "verdict", "version"]:
        assert validate_proposal(kind, {**proposal, key: "model-authored"})[1]
    assert validate_proposal(kind, [proposal])[1]
    assert validate_proposal(kind, {**proposal, "schema_version": True})[1]


@pytest.mark.parametrize("mutate", [
    lambda r: r["criteria"][0].update(story_ids=["ST2"]),
    lambda r: r["claims"][0].update(evidence_keys=["https://display.invalid/source"]),
    lambda r: r["claims"][0].update(evidence_keys=["#12:34"]),
    lambda r: r["claims"][0].update(id="CL0"),
    lambda r: r["uncertainty"][0].update(claim_ids=["CL2"]),
    lambda r: r["documentation_audience"].update(semantics="all_users"),
    lambda r: r.update(summary="x" * 1001),
    lambda r: r["criteria"].append(copy.deepcopy(r["criteria"][0])),
    lambda r: r.update(summary="bad\x00text"),
])
def test_invalid_refs_types_bounds_and_identity_are_refused(mutate):
    record = copy.deepcopy(SPEC)
    mutate(record)
    assert validate_proposal("spec", record)[1]


def test_question_ids_and_readiness():
    record = copy.deepcopy(IDEA)
    record["open_questions"] = [{"id": "Q2", "text": "Unclear"}]
    assert validate_proposal("idea_frame", record)[0]["open_questions"][0]["id"] == "Q2"
    assert not record_readiness("idea_frame", record)[0]
    record["deferred_questions"] = [{"id": "Q2", "text": "Same", "reason": "Later"}]
    assert validate_proposal("idea_frame", record)[1]
    assert record_readiness("idea_frame", IDEA)[0]


def test_definition_is_bounded_and_no_external_actions():
    graph = specification_definition()
    assert graph["budget"] == BUDGET
    assert not any(node["type"] in {"platform_action", "handoff", "sub_workflow"} for node in graph["nodes"])
    tools = {tool for node in graph["nodes"] if node["type"] == "phase"
             for tool in node["config"]["tool_policy"]["allowlist"]}
    assert tools == {"submit_idea_frame", "submit_research_plan", "submit_research_brief", "submit_spec",
                     "knowledge_search", "knowledge_read"}
    assert "overshoot" in next(n for n in graph["nodes"] if n["id"] == "plan")["config"]["instructions"]


@pytest.mark.parametrize("bad", [True, 0, -1, float("inf"), float("nan"), "40"])
def test_actual_budget_rejects_non_numeric_nonfinite_and_nonpositive_values(bad):
    from types import SimpleNamespace

    from app.services.workflow_runs.specification.lineage import effective_budget
    with pytest.raises(SpecificationUnavailable):
        effective_budget(SimpleNamespace(limits={"budget": {**BUDGET, "tool_calls": bad}}))


def test_tool_definitions_expose_no_server_fields_and_are_copied():
    from app.services.workflow_runs.specification.records import SERVER_FIELDS
    from app.tools.definitions.specification_outputs import get_specification_output_definitions
    definitions = get_specification_output_definitions()
    for kind, fields in SERVER_FIELDS.items():
        assert not fields.intersection(definitions[f"submit_{kind}"]["function"]["parameters"]["properties"])
    definitions["submit_spec"]["function"]["parameters"]["properties"].clear()
    assert get_specification_output_definitions()["submit_spec"]["function"]["parameters"]["properties"]
