"""Acceptance fixtures for the companion: a question, a gate, a problem and a finished run in a test Workspace.

Only where the deployment sets ``OCTRYX_ENABLE_TEST_FIXTURES=true`` (otherwise the endpoint answers 404),
for an admin, and never with the production runtime profile. The runs use a tiny published workflow without agent phases
(``companion-fixture``: start → "Go on?" confirmation → done), so answering them never starts a model turn:
confirming finishes the run, Continue on the paused one brings it back to the confirmation, Abort ends it. Every
fixture is titled "[companion fixture]" and the generation is audited. A "running" fixture stands in a phase
(``companion-fixture-running``, target terminal, ``context.fixture``) without any model turn, also after a handover
(``server_continuation`` never drives a fixture run); a stub member (no password login) receives handovers.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, ClarificationQuestion, FlowDefinition, User
from ...time_utils import utc_now

FIXTURE_KEY = "companion-fixture"
FIXTURES_FLAG = "OCTRYX_ENABLE_TEST_FIXTURES"
TITLE = "[companion fixture]"
DEFINITION = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "ask", "type": "user_confirmation", "label": "Go on?", "config": {"subject": "advance"}},
              {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
              {"id": "stopped", "type": "outcome", "config": {"outcome": "blocked"}}],
    "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "ask"},
              {"id": "e1", "source_node_id": "ask", "target_node_id": "done", "when": "confirmed"},
              {"id": "e2", "source_node_id": "ask", "target_node_id": "stopped", "when": "changed"},
              {"id": "e3", "source_node_id": "ask", "target_node_id": "stopped", "when": "stopped"}],
}


FIXTURE_CONTEXT_KEY = "fixture"  # the platform never starts a model turn for such a run (server_continuation)
RUNNING_KEY = "companion-fixture-running"
RUNNING_DEFINITION = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "work", "type": "phase", "label": "Fixture phase (no model turn)", "config": {
                  "agent": "engineer", "workflow_id": "knowledge_request", "workflow_class": "knowledge_request",
                  "workflow_contract": {"workflow_id": "knowledge_request", "workflow_class": "knowledge_request",
                                        "capability_class": "read_only", "when_to_use": "Companion fixture.",
                                        "checks": [{"type": "tool_called", "params": {"tools": ["knowledge_search"]},
                                                    "blocking": True, "description": "Never run (fixture)"}]},
                  "tool_policy": {"allowlist": ["knowledge_search"], "denylist": []}}},
              {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
    "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "work"},
              {"id": "e1", "source_node_id": "work", "target_node_id": "done"}],
}
MEMBER_USERNAME = "companion-fixture-member"


class FixtureError(ValueError):
    pass


def fixtures_enabled() -> bool:
    import os

    return str(os.environ.get(FIXTURES_FLAG) or "").strip().lower() == "true"


async def _ensure_workflow(db: AsyncSession, admin: User, key: str = FIXTURE_KEY,
                           definition: dict[str, Any] = DEFINITION) -> None:
    from ..flow_definitions import create_flow_definition, publish_flow_definition_version
    from ..run_admission.phased_catalog import TEST_FIXTURE_FLAG

    existing = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalars().first()
    if existing is not None:
        return
    created = await create_flow_definition(db, current_user=admin, payload={
        "key": key, "name": "Companion acceptance fixture", "definition": definition})
    # The platform's own acceptance fixture (dev only, FIXTURES_FLAG): shipped content, no human author to review.
    await publish_flow_definition_version(db, version_id=created["versions"][0]["id"], current_user=admin,
                                          publish_metadata={TEST_FIXTURE_FLAG: True}, shipped=True)


async def _member(db: AsyncSession, workspace_id: str) -> User:
    """A stub second member of the Workspace (no password login), the receiver for handover acceptance."""
    import secrets

    from ...models import UserProject

    user = (await db.execute(select(User).where(User.username == MEMBER_USERNAME))).scalar_one_or_none()
    if user is None:
        user = User(username=MEMBER_USERNAME, email=f"{MEMBER_USERNAME}@octryx.invalid",
                    display_name="Companion fixture member", password_hash=f"!disabled-{secrets.token_hex(16)}",
                    is_active=True)
        db.add(user)
        await db.flush()
    if await db.get(UserProject, (user.id, workspace_id)) is None:
        db.add(UserProject(user_id=user.id, project_id=workspace_id, role="member"))
        await db.flush()
    return user


async def _run(db: AsyncSession, admin: User, workspace_id: str, *, key: str = FIXTURE_KEY,
               target: str = "server"):
    from ..workflow_runs.records import new_chat_session, start_run

    thread = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, session=thread,
                          runtime_target={"kind": target}, context={FIXTURE_CONTEXT_KEY: True})
    run.title = TITLE
    return run, thread


async def generate(db: AsyncSession, admin: User, *, workspace_id: str) -> dict[str, Any]:
    from ...config import get_settings
    from ..admin.governance.admin_access_service import is_global_admin
    from ..workflow_runs.actions import perform_action
    from ..workflow_runs.limits import pause_run

    if str(get_settings().runtime_profile or "").strip().lower() == "production":
        raise FixtureError("not_in_production")
    if not await is_global_admin(db, admin.id):
        raise FixtureError("admin_only")
    await _ensure_workflow(db, admin)
    gate, _thread = await _run(db, admin, workspace_id)
    problem, _thread = await _run(db, admin, workspace_id)
    await pause_run(db, problem, reason="runtime_failed", actor_id=None, detail={
        "message": "Fixture: the phase's turn ended without finishing it. Continue brings the run back to its "
                   "confirmation; Abort ends it.", "code": "fixture_problem",
        "resume": {"kind": "restart", "node_id": "ask"}})
    done, _thread = await _run(db, admin, workspace_id)
    await perform_action(db, done, user=admin, body={
        "action": "confirm", "payload_hash": done.node_state["waiting"]["payload_hash"]})
    question_thread = (await _run(db, admin, workspace_id))[1]
    question = ClarificationQuestion(
        session_id=question_thread.id, project_id=workspace_id, question_id=f"fixture-{utc_now().timestamp()}",
        question_text=f"{TITLE} Which option should the agent take?",
        context_json={"options": ["Option A", "Option B"]}, requested_by=admin.id, status="open")
    db.add(question)
    await _ensure_workflow(db, admin, RUNNING_KEY, RUNNING_DEFINITION)
    running, _thread = await _run(db, admin, workspace_id, key=RUNNING_KEY, target="terminal")
    member = await _member(db, workspace_id)
    db.add(AuditLog(user_id=admin.id, action="attention.fixtures_generated", resource_type="project",
                    resource_id=workspace_id, details={"runs": [gate.id, problem.id, done.id, running.id],
                                                       "member": member.id}))
    await db.flush()
    return {"gate_run_id": gate.id, "problem_run_id": problem.id, "done_run_id": done.id,
            "running_run_id": running.id, "member": {"id": member.id, "display_name": member.display_name},
            "question_id": question.id,
            "note": "A device approval needs a real device turn; start a run with target auto on your device."}


async def member_handover_response(db: AsyncSession, admin: User, *, run_id: str, action: str) -> dict[str, Any]:
    """Accept or decline, as the stub fixture member, a handover addressed to that member (acceptance only)."""
    from ...models import WorkflowRun
    from ..admin.governance.admin_access_service import is_global_admin
    from ..workflow_runs.run_handover import accept_handover, decline_handover, handover

    if not await is_global_admin(db, admin.id):
        raise FixtureError("admin_only")
    member = (await db.execute(select(User).where(User.username == MEMBER_USERNAME))).scalar_one_or_none()
    run = await db.get(WorkflowRun, run_id) if run_id else None
    if member is None or run is None or handover(run).get("to") != member.id:
        raise FixtureError("not_a_fixture_handover")  # never answers for a real person
    if action == "accept":
        result = await accept_handover(db, run, user=member)
    elif action == "decline":
        await decline_handover(db, run, user=member, reason="declined by the companion fixture member")
        result = handover(run)
    else:
        raise FixtureError("invalid_action")
    db.add(AuditLog(user_id=admin.id, action="attention.fixture_handover_response", resource_type="workflow_run",
                    resource_id=run.id, details={"action": action, "member": member.id}))
    await db.flush()
    return {"handover": result, "owner": member.id if action == "accept" else run.requested_by}


__all__ = ["member_handover_response", "FIXTURES_FLAG", "FIXTURE_KEY", "FixtureError", "fixtures_enabled", "generate"]
