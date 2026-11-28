"""The governed default is a curated, versioned tool set per capability class, never the whole catalog; the coding
surface cap cuts by the set's declared order."""

from __future__ import annotations

import pytest

from app.agent.runtime_defaults import CODING_WRITE_TOOLS, VALID_CAPABILITY_TYPES
from app.services.governed_default_tool_sets import GOVERNED_DEFAULT_TOOL_SETS, governed_default_tool_set
from app.services.policy_lists.default_tool_sets import catalog_tool_names
from tests.conftest import ADMIN_PASSWORD

_CODING_SURFACE_CAP = 96


_EXPECTED_COUNTS = {"diagnosis": 108, "plan": 39, "change": 53, "admin": 45}
_EXPECTED_VERSIONS = {"diagnosis": 11, "plan": 2, "change": 3, "admin": 3}






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
    assert by_capability["diagnosis"]["key"] == by_capability["diagnosis"]["seed_key"] == "diagnosis.v11"
    assert by_capability["diagnosis"]["origin"] == "seed" and by_capability["diagnosis"]["matches_seed"]
    assert by_capability["diagnosis"]["tool_count"] == _EXPECTED_COUNTS["diagnosis"]
    assert by_capability["diagnosis"]["families"][0] == {
        "name": "workflow_selection",
        "tools": ["select_workflow", "list_available_workflows", "start_workflow"],
    }


def test_every_knowledge_answer_set_offers_the_read_only_knowledge_evidence():
    from app.services.governed_default_tool_sets import GOVERNED_DEFAULT_TOOL_SETS

    evidence = {"knowledge_search", "knowledge_read", "knowledge_changes", "knowledge_code_impact", "web_search"}
    for capability in ("diagnosis", "plan", "change"):
        assert evidence <= set(GOVERNED_DEFAULT_TOOL_SETS[capability].tools), capability
