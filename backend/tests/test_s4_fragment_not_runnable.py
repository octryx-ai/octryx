"""S4.2: a fragment is part of a workflow — never a run, never a tool, and its nodes are edited in the fragment.

A fragment version refuses a DAG run (409 ``flow_version_fragment``), is never the published phased flow a
workflow run starts on, is hidden from the capability catalog (and so from every LLM tool list), and the phased
editor refuses to edit a composite's fragment-origin node (409 ``fragment_node_read_only``) while an own node of the
composite is edited through its source, so the new draft keeps the same pins and provenance.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.flow_capabilities import list_flow_capabilities
from app.services.workflow_runs.engine import published_phased_flow
from app.services.workflow_runs.phased_editor import phase_graph_view, save_phase_graph
from app.services.workflow_runs.records import WorkflowRunError, new_chat_session, start_run
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.policy_engine_support import bearer
from tests.s4_fragment_support import (
    FLOWS,
    create,
    make_admin,
    probe_fragment,
    published_fragment,
    unique_key,
    version_row,
    work_composite,
    work_fragment,
)


def test_the_literal_markers_equal_the_compiler_and_seeder_constants():
    """``flow_version_state`` and ``fragments.store`` spell the fragment kind and the seed marker as literals."""
    from app.services import flow_version_state
    from app.services.workflow_runs import seeding
    from app.services.workflow_runs.fragments import format as fragment_format
    from app.services.workflow_runs.fragments import store

    assert flow_version_state.FRAGMENT_EXECUTION_KIND == fragment_format.FRAGMENT_KIND
    assert store.FRAGMENT_SEED_MARKER == seeding.FRAGMENT_SEED_MARKER


@pytest.mark.asyncio
async def test_a_fragment_version_never_runs_as_a_dag(client, db):
    author, reviewer = await make_admin(db), await make_admin(db)
    draft = await create(db, author, unique_key("s4-draft-fragment"), probe_fragment())
    _key, _flow_id, published_id, _pin = await published_fragment(db, author, reviewer)
    workspace = {"project_id": await seed_workspace(db)}  # a DAG run needs one before anything else is judged
    await db.commit()
    for version_id in (draft["versions"][0]["id"], published_id):
        for action in ("run", "partial-run"):
            response = await client.post(f"{FLOWS}/versions/{version_id}/{action}", headers=bearer(author.id),
                                         json={"node_id": "confirm", **workspace} if action == "partial-run"
                                         else workspace)
            assert response.status_code in (400, 409), response.text
            assert "flow_version_fragment" in response.text or "fragment" in response.text, response.text
        run = await client.post(f"{FLOWS}/versions/{version_id}/run", headers=bearer(author.id), json=workspace)
        assert run.status_code == 409 and run.json()["detail"]["reason"] == "flow_version_fragment"


@pytest.mark.asyncio
async def test_a_fragment_is_never_started_as_a_workflow_run(db):
    author, reviewer = await make_admin(db), await make_admin(db)
    key, _flow_id, _version_id, _pin = await published_fragment(db, author, reviewer)
    workspace_id = await seed_workspace(db)

    assert await published_phased_flow(db, key, None) is None
    assert await published_phased_flow(db, key, workspace_id) is None
    with pytest.raises(WorkflowRunError) as refused:
        await start_run(db, user=author, workflow_key=key, project_id=workspace_id,
                        session=await new_chat_session(db, author, workspace_id))
    assert refused.value.code == "unknown_workflow"


@pytest.mark.asyncio
async def test_a_fragment_is_hidden_from_the_capabilities(client, db):
    author, reviewer = await make_admin(db), await make_admin(db)
    key, _flow_id, version_id, _pin = await published_fragment(db, author, reviewer)
    await db.commit()

    listed = await list_flow_capabilities(db, include_hidden=True)
    [item] = [item for item in listed if item["flow_key"] == key]
    assert item["available"] is False and item["hidden_reason"] == "A fragment is part of a workflow, not a tool."
    assert key not in {item["flow_key"] for item in await list_flow_capabilities(db)}

    # Even a publish that asks for a visible capability stays hidden.
    row = await version_row(db, version_id)
    assert row.publish_metadata["capability_enabled"] is False and row.publish_metadata["llm_visible"] is False
    api = await client.get(f"{FLOWS}/capabilities", headers=bearer(author.id))
    assert api.status_code == 200 and key not in {item["flow_key"] for item in api.json()["items"]}
    run = await client.post(f"{FLOWS}/capabilities/{item['tool_name']}/run", headers=bearer(author.id), json={})
    assert run.json().get("error") == f"Workflow capability is not available: {item['tool_name']}", run.text


@pytest.mark.asyncio
async def test_the_phased_editor_refuses_a_fragment_origin_node_and_keeps_the_pins_for_own_nodes(db):
    author, reviewer = await make_admin(db), await make_admin(db)
    key, _flow_id, fragment_version_id, pin = await published_fragment(db, author, reviewer, definition=work_fragment(),
                                                                       key=unique_key("s4-work"))
    created = await create(db, author, unique_key("s4-work-composite"), work_composite(key, fragment_version_id, pin))
    flow_id, version_id = created["id"], created["versions"][0]["id"]
    assert set(created["versions"][0]["runtime_settings"]["composition"]["provenance"]) == {"w.work"}

    view = await phase_graph_view(db, flow_id, "w.work")
    with pytest.raises(HTTPException) as refused:
        await save_phase_graph(db, flow_id, "w.work", user=author,
                               body={"base_version_id": version_id, "graph": view["graph"]})
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "fragment_node_read_only"

    own = await phase_graph_view(db, flow_id, "own")
    saved = await save_phase_graph(db, flow_id, "own", user=author,
                                   body={"base_version_id": version_id, "graph": own["graph"]})
    assert saved["version"] == 2
    new = await version_row(db, saved["version_id"])
    composition = new.runtime_settings["composition"]
    assert composition["fragments"][0]["version_id"] == fragment_version_id
    assert composition["fragments"][0]["checksum"] == pin
    assert set(composition["provenance"]) == {"w.work"}
    assert "fragment" not in {node["type"] for node in new.definition_json["nodes"]}
    assert "fragment" in {node["type"] for node in composition["source"]["nodes"]}
