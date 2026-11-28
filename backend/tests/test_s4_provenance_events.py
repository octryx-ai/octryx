"""Fragment provenance in a composite run's graph, events and run view."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import FlowDefinition, Project, User, UserProject, WorkflowRun, WorkflowRunEvent
from app.models.runtime.flow_definition import FlowDefinitionVersion
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.fragments.provenance import (
    node_provenance,
    reader_fragment,
    redact_event_detail,
    run_composition,
    version_provenance,
)
from app.services.workflow_runs.graph import graph_for_run, parse_phased_definition
from app.services.workflow_runs.records import record_event, start_run
from app.services.workflow_runs.run_lists import run_events
from app.services.workflow_runs.run_sessions import new_bound_session
from app.services.workflow_runs.seeding import definition_digest
from app.services.workflow_runs.views import run_nodes
from tests.phased_workflow_fixtures import admin_user, phase_turn, phased_definition, publish_phased, run_workspace
from tests.policy_engine_support import bearer, make_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

FRAGMENT_KEY = "sf-probe"
CHECKSUM = "sha256:" + "ab" * 32
FRAGMENT_NODES = ("work", "verify")
FRAGMENT_EDGES = ("e2", "rework")


def composition_block(definition: dict, *, version_id: str) -> dict:
    pin = {"ref": "probe", "key": FRAGMENT_KEY, "version": 1, "version_id": version_id, "checksum": CHECKSUM}
    return {
        "schema": "composition/v1",
        "source": {"execution_kind": "phased", "nodes": [], "edges": []},
        "source_hash": "sha256:" + "cd" * 32,
        "compiled_digest": definition_digest(definition),
        "fragments": [{**pin, "namespace": "", "nodes": list(FRAGMENT_NODES), "edges": list(FRAGMENT_EDGES)}],
        "provenance": {node_id: {**pin, "node": node_id} for node_id in FRAGMENT_NODES},
    }


async def _composite(db, *, project_id: str | None = None) -> tuple[str, FlowDefinitionVersion, str]:
    definition = phased_definition()
    key = await publish_phased(db, definition)
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    version = await db.get(FlowDefinitionVersion, flow.current_version_id)
    fragment_version_id = str(uuid.uuid4())
    version.runtime_settings = {**dict(version.runtime_settings or {}),
                                "composition": composition_block(definition, version_id=fragment_version_id)}
    if project_id:
        flow.project_id = project_id
    await db.flush()
    return key, version, fragment_version_id


async def _member(db) -> tuple[User, Project]:
    project = Project(name=f"S4 {uuid.uuid4().hex[:6]}", description="", is_active=True)
    db.add(project)
    await db.flush()
    user = await db.get(User, await make_user(db, admin=False))
    db.add(UserProject(user_id=user.id, project_id=project.id, role="member"))
    await db.flush()
    return user, project


async def _events(db, run: WorkflowRun, kind: str) -> list[WorkflowRunEvent]:
    return list((await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == kind)
        .order_by(WorkflowRunEvent.created_at.asc(), WorkflowRunEvent.id.asc()))).scalars().all())


async def _finish(db, run: WorkflowRun, user: User) -> None:
    session = await new_bound_session(db, run, user)
    resolution = await run_turn_resolution(db, session, user_message="Collect it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search", "knowledge_read"])
    assert (run.status, run.outcome) == ("completed", "done")


def test_the_provenance_readers_return_the_contract_shapes_and_never_guess():
    version = FlowDefinitionVersion(runtime_settings={"composition": composition_block(phased_definition(),
                                                                                       version_id="v-1")})
    provenance = version_provenance(version)
    assert sorted(provenance) == sorted(FRAGMENT_NODES)
    graph = parse_phased_definition(phased_definition())
    assert graph.provenance == {}
    graph.provenance = provenance
    assert node_provenance(graph, "work") == {"key": FRAGMENT_KEY, "version": 1, "checksum": CHECKSUM, "ref": "probe"}
    assert node_provenance(graph, "start") is None and node_provenance(graph, "done") is None
    assert run_composition(version) == [{"key": FRAGMENT_KEY, "version": 1, "checksum": CHECKSUM}]
    assert reader_fragment(provenance["work"], admin=False) == {"key": FRAGMENT_KEY, "version": 1, "ref": "probe"}
    assert reader_fragment(provenance["work"], admin=True) == {
        "key": FRAGMENT_KEY, "version": 1, "ref": "probe", "version_id": "v-1", "checksum": CHECKSUM}
    for settings in ({}, {"composition": "x"}, {"composition": {"provenance": [1]}},
                     {"composition": {"provenance": {"work": {"key": ""}}, "fragments": [{"version": 1}]}}):
        plain = FlowDefinitionVersion(runtime_settings=settings)
        assert version_provenance(plain) == {} and run_composition(plain) == []
    assert version_provenance(None) == {} and run_composition(None) == []


def test_a_run_reader_never_gets_the_checksum_in_an_event_detail():
    detail = {"kind": "phase", "iteration": 1, "entry": 2,
              "fragment": {"key": FRAGMENT_KEY, "version": 1, "checksum": CHECKSUM, "ref": "probe"}}
    assert redact_event_detail("node_entered", detail, admin=True) == detail
    assert redact_event_detail("node_entered", detail, admin=False) == {
        "kind": "phase", "iteration": 1, "entry": 2, "fragment": {"key": FRAGMENT_KEY, "version": 1, "ref": "probe"}}
    started = {"workflow_key": "k", "composition": [{"key": FRAGMENT_KEY, "version": 1, "checksum": CHECKSUM}]}
    assert redact_event_detail("run_started", started, admin=False)["composition"] == [
        {"key": FRAGMENT_KEY, "version": 1}]
    plain = {"kind": "phase", "iteration": 1, "entry": 1}
    assert redact_event_detail("node_entered", plain, admin=False) is plain


@pytest.mark.asyncio
async def test_graph_for_run_carries_the_versions_provenance(db):
    admin = await admin_user(db)
    key, version, fragment_version_id = await _composite(db)
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id)
    assert run.flow_definition_version_id == version.id
    graph = await graph_for_run(db, run)
    assert sorted(graph.provenance) == sorted(FRAGMENT_NODES)
    assert graph.provenance["verify"]["version_id"] == fragment_version_id


@pytest.mark.asyncio
async def test_run_nodes_show_key_version_ref_to_every_reader_and_the_pin_only_to_an_admin(client, db):
    member, project = await _member(db)
    key, _version, fragment_version_id = await _composite(db, project_id=None)
    admin = await admin_user(db)
    run = await start_run(db, user=member, workflow_key=key, project_id=project.id)
    assert run.requested_by == member.id

    as_member = {node["id"]: node for node in await run_nodes(db, run, user=member)}
    as_admin = {node["id"]: node for node in await run_nodes(db, run, user=admin)}
    for node_id in FRAGMENT_NODES:
        assert as_member[node_id]["fragment"] == {"key": FRAGMENT_KEY, "version": 1, "ref": "probe"}
        assert as_admin[node_id]["fragment"] == {"key": FRAGMENT_KEY, "version": 1, "ref": "probe",
                                                 "version_id": fragment_version_id, "checksum": CHECKSUM}
    for node_id in ("start", "done"):
        assert as_member[node_id] == as_admin[node_id] and set(as_member[node_id]) == {"id", "title", "kind"}
    anonymous = {node["id"]: node for node in await run_nodes(db, run)}
    assert "checksum" not in anonymous["work"]["fragment"]

    await db.commit()
    member_view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=bearer(member.id))).json()["run"]
    admin_view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=bearer(admin.id))).json()["run"]
    assert member_view["current_node"]["fragment"] == {"key": FRAGMENT_KEY, "version": 1, "ref": "probe"}
    assert admin_view["current_node"]["fragment"]["checksum"] == CHECKSUM
    assert admin_view["current_node"]["fragment"]["version_id"] == fragment_version_id
    assert "version_id" not in str(member_view["nodes"]) and CHECKSUM not in str(member_view)


@pytest.mark.asyncio
async def test_run_events_withhold_the_checksum_from_the_requester_and_show_it_to_an_admin(db):
    member, project = await _member(db)
    key, _version, _vid = await _composite(db)
    admin = await admin_user(db)
    run = await start_run(db, user=member, workflow_key=key, project_id=project.id)
    record_event(db, run, "node_entered", node_id="verify", detail={
        "kind": "gate", "iteration": 1, "entry": 3,
        "fragment": {"key": FRAGMENT_KEY, "version": 1, "checksum": CHECKSUM, "ref": "probe"}})
    await db.flush()
    as_member = [item["detail"] for item in (await run_events(db, run, user=member))["events"]
                 if item["node_id"] == "verify"]
    as_admin = [item["detail"] for item in (await run_events(db, run, user=admin))["events"]
                if item["node_id"] == "verify"]
    assert as_member[-1]["fragment"] == {"key": FRAGMENT_KEY, "version": 1, "ref": "probe"}
    assert as_admin[-1]["fragment"]["checksum"] == CHECKSUM
    assert "checksum" not in [item["detail"] for item in (await run_events(db, run))["events"]
                              if item["node_id"] == "verify"][-1]["fragment"]


@pytest.mark.asyncio
async def test_the_events_route_passes_its_reader_so_only_an_admin_sees_the_checksum(client, db):
    member, project = await _member(db)
    key, _version, fragment_version_id = await _composite(db)
    admin = await admin_user(db)
    run = await start_run(db, user=member, workflow_key=key, project_id=project.id)
    await db.commit()
    url = f"/api/v1/workflow-runs/{run.id}/events"
    as_member = (await client.get(url, headers=bearer(member.id))).json()["events"]
    as_admin = (await client.get(url, headers=bearer(admin.id))).json()["events"]

    def entered(events: list[dict]) -> dict:
        return next(item for item in events if item["kind"] == "node_entered" and item["node_id"] == "work")

    assert entered(as_member)["detail"]["fragment"] == {"key": FRAGMENT_KEY, "version": 1, "ref": "probe"}
    assert entered(as_admin)["detail"]["fragment"]["checksum"] == CHECKSUM
    started = [next(item for item in events if item["kind"] == "run_started") for events in (as_member, as_admin)]
    assert started[0]["detail"]["composition"] == [{"key": FRAGMENT_KEY, "version": 1}]
    assert started[1]["detail"]["composition"] == [{"key": FRAGMENT_KEY, "version": 1, "checksum": CHECKSUM}]
    assert CHECKSUM not in str(as_member)
    assert fragment_version_id not in str(as_member) + str(as_admin)


@pytest.mark.asyncio
async def test_node_entered_carries_the_fragment_exactly_for_fragment_nodes(db):
    admin = await admin_user(db)
    key, _version, fragment_version_id = await _composite(db)
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id)
    await _finish(db, run, admin)

    entered = await _events(db, run, "node_entered")
    assert [event.node_id for event in entered] == ["start", "work", "verify", "done"]
    for event in entered:
        if event.node_id in FRAGMENT_NODES:
            assert event.detail["fragment"] == {"key": FRAGMENT_KEY, "version": 1, "checksum": CHECKSUM,
                                                "ref": "probe"}
        else:
            assert "fragment" not in event.detail
        assert fragment_version_id not in str(event.detail)
    started = await _events(db, run, "run_started")
    assert started[0].detail["composition"] == [{"key": FRAGMENT_KEY, "version": 1, "checksum": CHECKSUM}]


@pytest.mark.asyncio
async def test_run_started_composition_lists_the_pins_for_the_requester_without_the_checksum(db):
    member, project = await _member(db)
    key, _version, _vid = await _composite(db)
    run = await start_run(db, user=member, workflow_key=key, project_id=project.id)
    events = (await run_events(db, run, user=member))["events"]
    started = next(item for item in events if item["kind"] == "run_started")
    assert started["detail"]["composition"] == [{"key": FRAGMENT_KEY, "version": 1}]
    entered = [item for item in events if item["kind"] == "node_entered"]
    assert [item["node_id"] for item in entered] == ["start", "work"]
    assert entered[1]["detail"]["fragment"] == {"key": FRAGMENT_KEY, "version": 1, "ref": "probe"}


@pytest.mark.asyncio
async def test_a_plain_run_has_no_fragment_keys_and_byte_compatible_events(db):
    admin = await admin_user(db)
    key = await publish_phased(db, phased_definition())
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id)
    await _finish(db, run, admin)
    assert (await graph_for_run(db, run)).provenance == {}
    assert all(set(node) == {"id", "title", "kind"} for node in await run_nodes(db, run, user=admin))
    for event in await _events(db, run, "node_entered"):
        assert set(event.detail) == {"kind", "iteration", "entry"}
    started = (await _events(db, run, "run_started"))[0]
    assert set(started.detail) == {"workflow_key", "version", "runtime_target"}
    listed = (await run_events(db, run, user=admin))["events"]
    assert all("fragment" not in item["detail"] and "composition" not in item["detail"] for item in listed)
