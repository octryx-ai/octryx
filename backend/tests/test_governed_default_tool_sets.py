"""The governed default is a curated, versioned tool set per capability class.

A turn without a selected workflow never gets the capability's whole catalog (hundreds of visible tools): the default
is a closed set per class, filtered by visibility and the Workspace policy; a workflow brings its own tools, and a provider cap cuts by the set's declared
order instead of catalog order.
"""

from __future__ import annotations

import random

import pytest

from app.agent.core.context.context_planner import build_context_section_decisions, plan_turn_context
from app.agent.core.context.turn_tool_surface import resolve_turn_tool_surface
from app.agent.runtime_defaults import CODING_WRITE_TOOLS, VALID_CAPABILITY_TYPES
from app.services.governed_default_tool_sets import GOVERNED_DEFAULT_TOOL_SETS, governed_default_tool_set
from app.services.policy_lists.default_tool_sets import catalog_tool_names
from app.services.tool_surface_budget_policy import budget_tool_definitions_for_runtime
from tests.conftest import ADMIN_PASSWORD
from tests.governed_default_tool_sets_support import _definition

# The smallest provider cap (Copilot). Every set must sit well under it.
_SMALLEST_PROVIDER_CAP = 96


_EXPECTED_COUNTS = {"diagnosis": 110, "plan": 39, "change": 55, "admin": 45}
# admin.v3: the settings tools that read a model which never existed are gone.
_EXPECTED_VERSIONS = {"diagnosis": 10, "plan": 2, "change": 2, "admin": 3}


def _governed_surface(capability_type: str):
    return resolve_turn_tool_surface(
        plan_turn_context(project_id="p1", agent_definition=None, session_metadata={}, history_count=0),
        capability_type=capability_type,
        workflow_id=None,
        workflow_contract=None,
        routing_resolution=None,
        agent_definition=None,
        project_config={},
    )


@pytest.mark.parametrize("capability_type", sorted(VALID_CAPABILITY_TYPES))
def test_each_capability_class_gets_exactly_its_versioned_set(capability_type):
    tool_set = governed_default_tool_set(capability_type)
    plan = _governed_surface(capability_type)

    assert plan.tool_surface_source == "governed_default"
    # diagnosis.v3/v4: the Octryx client's tools in the chat.
    assert plan.tool_surface_set == tool_set.key == f"{capability_type}.v{_EXPECTED_VERSIONS[capability_type]}"
    # Declared order is kept: it is the set's priority under a provider cap.
    assert plan.tool_allowlist == list(tool_set.tools)
    assert len(tool_set.tools) == _EXPECTED_COUNTS[capability_type]
    # The chat set (diagnosis, tool_search in it) sends only its core in full and the rest by name; the
    # provider cap applies to what a request sends (``_loop_request_messages``), so only the other sets must fit it.
    if "tool_search" not in tool_set.tools:
        assert len(tool_set.tools) < _SMALLEST_PROVIDER_CAP
    # Every set reaches any workflow's tools explicitly.
    assert "select_workflow" in tool_set.tools
    assert build_context_section_decisions(plan)["tools"]["source"] == f"tool_surface:governed_default:{tool_set.key}"


def test_every_set_names_only_tools_its_capability_catalog_offers():
    assert set(GOVERNED_DEFAULT_TOOL_SETS) == set(VALID_CAPABILITY_TYPES)
    for capability_type in VALID_CAPABILITY_TYPES:
        assert set(governed_default_tool_set(capability_type).tools) <= catalog_tool_names(capability_type)


def test_the_chat_set_is_read_only_with_knowledge_and_the_change_set_carries_the_coding_core():
    chat = set(governed_default_tool_set("diagnosis").tools)
    change = set(governed_default_tool_set("change").tools)

    assert {"select_workflow", "knowledge_search", "knowledge_read", "memory_recall", "web_search"} <= chat
    assert not chat & CODING_WRITE_TOOLS
    assert "bash" not in chat | change
    assert CODING_WRITE_TOOLS <= change
    assert {"read_workspace_file", "grep_workspace", "code_search", "run_test_suite", "get_git_diff"} <= change
    assert {"knowledge_search", "knowledge_read"} <= change


def test_an_unknown_capability_has_no_default_set():
    with pytest.raises(ValueError):
        governed_default_tool_set("operations")


def test_the_cap_cuts_by_the_declared_order_never_by_catalog_order():
    tool_set = GOVERNED_DEFAULT_TOOL_SETS["diagnosis"]
    offered = [_definition(name) for name in [*tool_set.tools, *(f"extra_tool_{index:03d}" for index in range(80))]]
    shuffled = list(offered)
    random.Random(7).shuffle(shuffled)

    def _budget(definitions):
        return [
            definition["function"]["name"]
            for definition in budget_tool_definitions_for_runtime(
                definitions,
                runtimes=[{"provider_name": "copilot", "model": "gpt-4o"}],
                capability_type="diagnosis",
                coding_discipline="planning",
                priority_tool_names=tool_set.tools,
            )
        ]

    kept = _budget(offered)
    assert kept == _budget(shuffled)
    assert len(kept) == _SMALLEST_PROVIDER_CAP
    seated = min(len(tool_set.tools), _SMALLEST_PROVIDER_CAP)
    assert kept[:seated] == list(tool_set.tools)[:seated]
    assert kept[seated:] == sorted(kept[seated:])


def test_a_set_under_the_cap_is_not_cut():
    offered = [_definition(name) for name in GOVERNED_DEFAULT_TOOL_SETS["change"].tools]
    kept = budget_tool_definitions_for_runtime(
        offered,
        runtimes=[{"provider_name": "copilot", "model": "gpt-4o"}],
        capability_type="change",
        coding_discipline="edit",
        priority_tool_names=GOVERNED_DEFAULT_TOOL_SETS["change"].tools,
    )
    assert kept == offered


@pytest.mark.asyncio
async def test_the_admin_panel_lists_the_seeded_default_sets_as_editable(client) -> None:
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303

    response = await client.get("/admin/chat/api/panel/default-tool-sets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["override"] == "supported"
    by_capability = {entry["capability_type"]: entry for entry in payload["sets"]}
    assert set(by_capability) == set(VALID_CAPABILITY_TYPES)
    assert all(entry["unregistered_tools"] == [] for entry in payload["sets"])
    assert by_capability["diagnosis"]["key"] == by_capability["diagnosis"]["seed_key"] == "diagnosis.v10"
    assert by_capability["diagnosis"]["origin"] == "seed" and by_capability["diagnosis"]["matches_seed"]
    assert by_capability["diagnosis"]["tool_count"] == _EXPECTED_COUNTS["diagnosis"]
    assert by_capability["diagnosis"]["families"][0] == {
        "name": "workflow_selection",
        "tools": ["select_workflow", "list_available_workflows", "start_workflow"],
    }


def test_every_knowledge_answer_set_offers_the_read_only_knowledge_evidence():
    # A1 answers a plain chat turn from governed Knowledge evidence, including code impact.
    from app.services.governed_default_tool_sets import GOVERNED_DEFAULT_TOOL_SETS

    evidence = {"knowledge_search", "knowledge_read", "knowledge_changes", "knowledge_code_impact", "web_search"}
    for capability in ("diagnosis", "plan", "change"):
        assert evidence <= set(GOVERNED_DEFAULT_TOOL_SETS[capability].tools), capability
