"""S4.2: a fragment is part of a workflow, never a run or a tool, and its nodes are edited only in the
fragment."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.workflow_runs.engine import published_phased_flow
from app.services.workflow_runs.phased_editor import phase_graph_view, save_phase_graph
from app.services.workflow_runs.records import WorkflowRunError, new_chat_session, start_run
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.s4_fragment_support import (
    create,
    make_admin,
    published_fragment,
    unique_key,
    version_row,
    work_composite,
    work_fragment,
)
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


def test_the_literal_markers_equal_the_compiler_and_seeder_constants():
    from app.services import flow_version_state
    from app.services.workflow_runs import seeding
    from app.services.workflow_runs.fragments import format as fragment_format
    from app.services.workflow_runs.fragments import store

    assert flow_version_state.FRAGMENT_EXECUTION_KIND == fragment_format.FRAGMENT_KIND
    assert store.FRAGMENT_SEED_MARKER == seeding.FRAGMENT_SEED_MARKER




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
