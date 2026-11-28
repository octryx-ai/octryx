"""Shared harness of the publication tests: a Confluence Cloud REST v2 fake behind an injected
``httpx.MockTransport`` (no network), a documented run, and the (b) confirmation. No tests live here."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import (
    BuiltInToolConfig,
    FlowDefinition,
    Project,
    Session,
    User,
    WorkflowRun,
    WorkflowRunDecision,
    WorkflowRunSession,
    WorkItem,
)
from app.models.security.user import UserProject
from app.services.workflow_runs.documentation.page import page_title, recorded_output, render_storage
from app.services.workflow_runs.documentation.publication_recovery import reconcile_publication_intent
from app.services.workflow_runs.documentation.publication_v2 import publish_documentation_v2
from app.services.workflow_runs.documentation.record import validate_feature_documentation
from app.services.workflow_runs.documentation.write_intent import (
    approve_publication_intent,
    publication_body_hash,
    reserve_publication_intent,
)
from app.services.workflow_runs.pause import payload_hash
from app.services.workflow_runs.phase_outputs import output_hash
from app.services.workflow_runs.records import lock_run
from tests.s1_publish_cloud_support import PARENT, SITE, SPACE_KEY, FakeCloudV2

DOCUMENTATION = {"title": "Totals", "what": "Shows the totals.", "why": "Users asked for it.",
                 "how_to_use": "Open the report.", "notes": ""}


class Crash(BaseException):  # noqa: N818 - a simulated process death, not an error the code may handle
    ...


async def documented_run(db, *, parent: str = PARENT, url: str = SITE) -> WorkflowRun:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name=f"s1-{uuid.uuid4().hex[:6]}", is_active=True, config={
        "feature_documentation": {"confluence_space_key": SPACE_KEY, "parent_page_id": parent,
            "audience_proof": {"semantics": "workspace_readers", "principal_user_id": "reader-fixture",
                               "outsider_user_id": "outsider-fixture", "source_key": "docs"}},
        "tool_policy": {"allowlist": ["create_confluence_page", "update_confluence_page", "get_confluence_page"]}})
    db.add(project)
    await db.flush()
    # The run's requester decides its "requester" nodes only as a current Workspace member.
    db.add(UserProject(user_id=admin.id, project_id=project.id, role="admin"))
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=project.id, is_active=True, config={
        "confluence_auth_mode": "basic",
        "confluence_url": url, "confluence_username": "docs-bot", "confluence_password": "docs-pw",
        "confluence_allowed_spaces": [{"space_key": SPACE_KEY, "enabled": True}]}))
    item = WorkItem(source_type="platform", source_instance="octryx", source_key=f"OCX-{uuid.uuid4().hex[:4]}",
                    title="Totals", project_id=project.id, work_state="intake")
    db.add(item)
    await db.flush()
    record, _problems = validate_feature_documentation(DOCUMENTATION)
    output = {"kind": "feature_documentation", "version": 1, "hash": output_hash(record), "record": record,
              "at": "2026-10-13T12:00:00+00:00"}
    from tests.phased_workflow_fixtures import publish_phased
    graph = {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"},
        {"id": "confirm_publication", "type": "user_confirmation", "config": {"subject": "publication"}},
        {"id": "done", "type": "outcome", "config": {"outcome": "done"}}], "edges": [
        {"id": "first", "source_node_id": "start", "target_node_id": "confirm_publication"},
        {"id": "final", "source_node_id": "confirm_publication", "target_node_id": "done", "when": "confirmed"}]}
    key = await publish_phased(db, graph)
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    run = WorkflowRun(flow_definition_version_id=flow.current_version_id, workflow_kind="phased", workflow_key=key, requested_by=admin.id, project_id=project.id,
                      status="running", current_node_id="reserve_publication", node_state={"entry": 1},
                      work_item_id=item.id, ticket_key=item.source_key,
                      context={"outputs": {"feature_documentation": output}})
    db.add(run)
    await db.flush()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="chat", status="active")
    db.add(session)
    await db.flush()
    db.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role="main", active=True))
    await db.commit()
    return run


def card_body(run: WorkflowRun, marker: str, *, what: str | None = None) -> str:
    record = dict(recorded_output(run)["record"])
    if what is not None:
        record["what"] = what
    links = {"ticket": {"key": run.ticket_key or "", "url": ""}, "pull_request": {"id": "", "url": ""}}
    return render_storage(record, [], links, run_id=run.id, run_marker=marker)


async def reserve(db, run: WorkflowRun, fake: FakeCloudV2, *, entry: int = 1):
    await lock_run(db, run)
    run.current_node_id, run.node_state = "reserve_publication", {"entry": entry}
    intent = await reserve_publication_intent(db, run, transport=fake.transport())
    await db.commit()
    return intent


async def confirm(db, run: WorkflowRun, intent, *, body: str | None = None, action: str = "confirmed",
                  approve: bool = True) -> WorkflowRunDecision:
    output = recorded_output(run)
    body = body if body is not None else card_body(run, intent.marker)
    payload = {"subject": "publication", "title": intent.title, "body": body, "marker": intent.marker,
               "output_hash": output["hash"], "target": {"workspace_id": run.project_id, **{
                   key: getattr(intent, key) for key in ("operation", "operation_id", "marker", "connection_id",
                        "instance", "space_id", "space_key", "parent_id", "page_id", "base_version", "expected_version")}}}
    from app.services.project.service import get_project_config
    from app.services.workflow_runs.documentation.audience_binding import audience_snapshot
    payload["audience"] = audience_snapshot(await get_project_config(run.project_id, db), run.project_id)
    decision = WorkflowRunDecision(run_id=run.id, node_id="confirm_publication", kind="confirmation",
                                   subject="publication", action=action, payload=payload,
                                   payload_hash=payload_hash(payload), decided_by=run.requested_by)
    db.add(decision)
    await db.flush()
    if approve:
        await approve_publication_intent(db, run, decision_id=decision.id, card_hash=decision.payload_hash,
                                         output_hash=output["hash"], body_hash=publication_body_hash(body))
    await db.commit()
    return decision


async def publish(db, run: WorkflowRun, fake: FakeCloudV2, *, entry: int = 1, worker: str | None = None,
                  reconcile: bool = False):
    await lock_run(db, run)
    run.current_node_id, run.node_state = "publish_docs", {"entry": entry}
    handler = reconcile_publication_intent if reconcile else publish_documentation_v2
    outcome = await handler(db, run, transport=fake.transport(), worker_id=worker)
    await db.commit()
    return outcome


async def crashed(db, call) -> None:
    try:
        await call
    except Crash:
        await db.rollback()
    else:  # pragma: no cover - the crash must happen
        raise AssertionError("the call was expected to crash")


async def published_ready(db, fake: FakeCloudV2, **run_options):
    run = await documented_run(db, **run_options)
    intent = await reserve(db, run, fake)
    await confirm(db, run, intent)
    return run, intent


def title_of(run: WorkflowRun) -> str:
    return page_title(run, dict(recorded_output(run)["record"]))
