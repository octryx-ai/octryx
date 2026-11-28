"""S2c-1 attempt race on a disposable migrated PostgreSQL, never Acceptance."""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC

import pytest
from sqlalchemy import delete, update

from app.models import (
    FlowDefinition,
    FlowDefinitionVersion,
    Project,
    Session,
    ToolCall,
    User,
    UserProject,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunSession,
)
from app.models.project.knowledge_evidence import (
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeSourceHead,
    KnowledgeSourceRevision,
)
from app.services.workflow_runs.graph import graph_for_run
from app.services.workflow_runs.phase_outputs import output_hash
from app.services.workflow_runs.records import lock_run, record_event
from app.services.workflow_runs.review.artefact_contract import ArtefactUnavailableError
from app.services.workflow_runs.review.artefact_evidence import resolve_snapshot
from app.services.workflow_runs.review.attempts import _claim_attempt
from app.time_utils import utc_now
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.knowledge_retention_postgres_support import (
    UNGRANTED_ROW_WAIT,
    postgres_sessions,
    requires_postgres,
    until,
)
from tests.workflow_artefact_review_support import definition


@requires_postgres
@pytest.mark.asyncio
async def test_two_review_workers_claim_exactly_one_attempt_postgres():
    engine, factory = postgres_sessions()
    workspace_id = user_id = run_id = None
    try:
        async with factory() as seed:
            workspace_id = await seed_workspace(seed)
            user_id = await seed_member(seed, workspace_id=workspace_id)
            run = WorkflowRun(workflow_kind="phased", workflow_key="artefact-review-claim", project_id=workspace_id,
                requested_by=user_id, status="waiting", waiting_kind="awaiting_review", current_node_id="review",
                node_state={"entry": 3, "waiting": {}}, context={})
            seed.add(run)
            await seed.commit()
            run_id = run.id
        ready = asyncio.Event()
        arrived = 0

        async def contender():
            nonlocal arrived
            async with factory() as db:
                run = await db.get(WorkflowRun, run_id)
                arrived += 1
                if arrived == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), timeout=10)
                return await _claim_attempt(db, run)

        attempts = await asyncio.wait_for(asyncio.gather(contender(), contender()), timeout=20)
        assert sum(value is not None for value in attempts) == 1
        async with factory() as verify:
            run = await verify.get(WorkflowRun, run_id)
            assert run.node_state["waiting"]["attempt"] == next(value for value in attempts if value is not None)
    finally:
        async with factory() as cleanup:
            if run_id:
                await cleanup.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
            if user_id:
                await cleanup.execute(delete(UserProject).where(UserProject.user_id == user_id))
                await cleanup.execute(delete(User).where(User.id == user_id))
            if workspace_id:
                await cleanup.execute(delete(Project).where(Project.id == workspace_id))
            await cleanup.commit()
        await engine.dispose()


async def _seed_flow_session_source(seed, ids: dict):
    flow = FlowDefinition(key=f"artifact-lock-{uuid.uuid4().hex}", name="Artifact source lock",
        project_id=ids["workspace"], created_by=ids["user"], status="published")
    seed.add(flow)
    await seed.flush()
    ids["flow"] = flow.id
    version = FlowDefinitionVersion(flow_id=flow.id, version=1, status="published",
        definition_json=definition(), created_by=ids["user"])
    session = Session(user_id=ids["user"], project_id=ids["workspace"], origin="chat")
    source = KnowledgeEvidenceSource(project_id=ids["workspace"], source_key=f"lock-{uuid.uuid4().hex}",
                                     display_title="Snapshot lock fixture")
    seed.add_all([version, session, source])
    await seed.flush()
    ids.update(version=version.id, session=session.id, source=source.id)
    return flow, version, session, source


async def _seed_revision_and_read_call(seed, ids: dict, session, source):
    revision = KnowledgeSourceRevision(source_id=source.id, project_id=ids["workspace"],
        revision_ordinal=1, content_sha256="b" * 64, byte_size=10, media_type="text/plain",
        object_bucket="acceptance", object_key="lock-fixture", parser_name="plain", parser_version="1",
        parser_sandbox="none", state="projected")
    seed.add(revision)
    await seed.flush()
    ids["revision"] = revision.id
    key = revision.id.replace("-", "") + ":1"
    entered_at = utc_now().isoformat()
    call = ToolCall(session_id=session.id, tool_name="knowledge_read", status="success",
                    parameters={"evidence_key": key}, result={"state": "ok"})
    seed.add_all([call, KnowledgeSourceHead(source_id=source.id, project_id=ids["workspace"],
        current_revision_id=revision.id, wanted_revision_id=revision.id), KnowledgeEvidenceSpan(
        project_id=ids["workspace"], revision_id=revision.id, evidence_key=key, span_ordinal=1,
        char_start=0, char_end=10, text="Actual observation", citation="Lock fixture")])
    await seed.flush()
    ids["call"] = call.id
    return key, entered_at, call


async def _seed_review_run(seed, ids: dict, flow, version, session, call, key: str, entered_at: str) -> None:
    record = {"summary": "Uncertain", "cause": "Insufficient evidence", "sources": [key]}
    envelope = {"kind": "incident_hypothesis", "version": 1, "hash": output_hash(record),
                "node_id": "hypothesis", "entry": 2, "record": record}
    run = WorkflowRun(workflow_kind="phased", workflow_key=flow.key, project_id=ids["workspace"],
        requested_by=ids["user"], flow_definition_version_id=version.id, current_node_id="review",
        status="waiting", waiting_kind="awaiting_review", node_state={"entry": 3},
        context={"outputs": {"incident_hypothesis": envelope}})
    seed.add(run)
    await seed.flush()
    ids["run"] = run.id
    seed.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role="main", active=True))
    record_event(seed, run, "node_entered", node_id="hypothesis", detail={"entry": 2})
    record_event(seed, run, "artefact_phase_provenance", node_id="hypothesis", detail={
        "entry": 2, "version": 1, "session_id": session.id, "envelope_hash": envelope["hash"],
        "call_ids": [call.id], "entered_at": entered_at})


async def _assert_snapshot_blocks_withdrawal(factory, ids: dict) -> None:
    async with factory() as reviewer, factory() as writer, factory() as observer:
        run = await reviewer.get(WorkflowRun, ids["run"])
        await lock_run(reviewer, run)
        node = (await graph_for_run(reviewer, run)).nodes["review"]
        snapshot = await resolve_snapshot(reviewer, run, node)
        assert snapshot["evidence"][0]["revision_id"] == ids["revision"]

        async def withdraw():
            await writer.execute(update(KnowledgeSourceHead).where(
                KnowledgeSourceHead.source_id == ids["source"]).values(wanted_revision_id=None))
            await writer.commit()

        withdrawing = asyncio.create_task(withdraw())
        await until(observer, UNGRANTED_ROW_WAIT, 1)
        assert not withdrawing.done()
        await reviewer.commit()
        await asyncio.wait_for(withdrawing, timeout=10)
        await lock_run(reviewer, run)
        with pytest.raises(ArtefactUnavailableError, match="source_head_changed"):
            await resolve_snapshot(reviewer, run, node)
        await reviewer.rollback()


async def _cleanup_snapshot_rows(factory, ids: dict) -> None:
    async with factory() as cleanup:
        if "run" in ids:
            for model in (WorkflowRunSession, WorkflowRunEvent):
                await cleanup.execute(delete(model).where(model.run_id == ids["run"]))
            await cleanup.execute(delete(WorkflowRun).where(WorkflowRun.id == ids["run"]))
        if "call" in ids:
            await cleanup.execute(delete(ToolCall).where(ToolCall.id == ids["call"]))
        if "session" in ids:
            await cleanup.execute(delete(Session).where(Session.id == ids["session"]))
        if "source" in ids:
            await cleanup.execute(delete(KnowledgeSourceHead).where(KnowledgeSourceHead.source_id == ids["source"]))
        if "revision" in ids:
            await cleanup.execute(delete(KnowledgeEvidenceSpan).where(
                KnowledgeEvidenceSpan.revision_id == ids["revision"]))
            await cleanup.execute(delete(KnowledgeSourceRevision).where(
                KnowledgeSourceRevision.id == ids["revision"]))
        if "source" in ids:
            await cleanup.execute(delete(KnowledgeEvidenceSource).where(KnowledgeEvidenceSource.id == ids["source"]))
        if "version" in ids:
            await cleanup.execute(delete(FlowDefinitionVersion).where(FlowDefinitionVersion.id == ids["version"]))
        if "flow" in ids:
            await cleanup.execute(delete(FlowDefinition).where(FlowDefinition.id == ids["flow"]))
        if "user" in ids:
            await cleanup.execute(delete(UserProject).where(UserProject.user_id == ids["user"]))
            await cleanup.execute(delete(User).where(User.id == ids["user"]))
        if "workspace" in ids:
            await cleanup.execute(delete(Project).where(Project.id == ids["workspace"]))
        await cleanup.commit()


@requires_postgres
@pytest.mark.asyncio
async def test_final_snapshot_blocks_source_head_writer_then_refuses_withdrawal_postgres():
    engine, factory = postgres_sessions()
    ids = {}
    try:
        async with factory() as seed:
            ids["workspace"] = await seed_workspace(seed)
            ids["user"] = await seed_member(seed, workspace_id=ids["workspace"])
            flow, version, session, source = await _seed_flow_session_source(seed, ids)
            key, entered_at, call = await _seed_revision_and_read_call(seed, ids, session, source)
            await _seed_review_run(seed, ids, flow, version, session, call, key, entered_at)
            await seed.commit()
        await _assert_snapshot_blocks_withdrawal(factory, ids)
    finally:
        await _cleanup_snapshot_rows(factory, ids)
        await engine.dispose()


@pytest.mark.parametrize("aware_now", [False, True])
@pytest.mark.parametrize("aware_started", [False, True])
@pytest.mark.parametrize("age_minutes,expected", [(0, False), (5, False), (6, True), (16, True)])
def test_review_attempt_active_and_stale_times_accept_naive_and_aware_utc(aware_now, aware_started,
                                                                        age_minutes, expected):
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from app.services.workflow_runs.review.attempts import _due

    now = datetime(2026, 10, 14, 20, 0, 0, tzinfo=UTC)
    started = now - timedelta(minutes=age_minutes)
    if not aware_now:
        now = now.replace(tzinfo=None)
    if not aware_started:
        started = started.replace(tzinfo=None)
    run = SimpleNamespace(status="waiting", waiting_kind="awaiting_review",
                          node_state={"waiting": {"started_at": started.isoformat()}})
    assert _due(run, now) is expected
