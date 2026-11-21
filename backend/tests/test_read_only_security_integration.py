"""Integration of read-only run contexts with the runtime security gates.

An enforced read-only run must never run a granted mutating command (a granted ``sort -o out input``). Every
read-only context is strictly read-only: the
Assistant in chat outside a workflow run, a ``read_only`` phase, a read-only programmatic origin. The root fix
(``run_capability.escalation.read_only_rule_refusal`` in ``_policy_block_result``) makes every refusal of the
read-only command rules final there, before any approval grant (old or new), standing rule or approval request.

Real paths: the run capability comes from the real turn routing (``resolve_turn_routing_profile``) for a plain chat
turn and for a read-only workflow-run phase; the commands go through the real bash/CLI tools and
``_policy_block_result``; the approve-and-resume path is the real chat approval API.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.core.context.run_context_routing import resolve_turn_routing_profile
from app.models import Approval, Message, Project, User
from app.models import Session as AgentSession
from app.services.run_capability.escalation import CAPABILITY_REFUSAL_KEY
from app.services.security_analyzer.contract import SecurityAnalyzerFinding
from app.services.standing_approvals.argument_class import command_review_scope
from app.services.standing_approvals.tool_rules import grant_standing_tool_rule
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.tools.context import ToolContext
from app.tools.runtime_impl._runtime_command_policy import _policy_block_result
from tests.conftest import ADMIN_PASSWORD
from tests.shell_expansion_support import _granted_session, _runtime, exec_config  # noqa: F401
from tests.test_standing_tool_approvals import _session, _workspace

pytestmark = pytest.mark.asyncio
WRITES = ["sort -o out input", "python3 manage.py migrate", "git commit -am x", "uniq in out"]


def _phase_resolution(capability_class: str) -> dict:
    """A workflow run's phase as the run binding resolves it (``selection_source: workflow_run``)."""
    return {"source": "db", "status": "matched", "selection_source": "workflow_run", "workflow_key": "probe",
            "workflow_id": "probe", "policy_id": "p", "policy_version_id": "v",
            "workflow_contract": {"workflow_id": "probe", "capability_class": capability_class}}


async def _state(db, resolution: dict | None) -> dict:
    """The ``run_capability`` a turn's tools get, from the real routing (as ``run_context`` sets it)."""
    metadata = {ROUTING_RESOLUTION_KEY: resolution} if resolution else {}
    routing = await resolve_turn_routing_profile(
        db=db, session_metadata=metadata, user_message="Please do it.", agent_type="chat", project_id=None,
        agent_definition=None, runtime_target_id=None)
    return routing.run_capability.tool_context_state()


CONTEXTS = {"assistant outside a run": None, "read_only phase": _phase_resolution("read_only")}


@pytest.mark.parametrize("where", sorted(CONTEXTS))
@pytest.mark.parametrize("command", WRITES)
async def test_an_old_mutating_grant_never_runs_in_a_read_only_context(db, monkeypatch, tmp_path, exec_config,  # noqa: F811
                                                                       where, command):
    state = await _state(db, CONTEXTS[where])
    assert (state["class"], state["enforced"]) == ("read_only", True)
    module, calls = _runtime(monkeypatch)
    key = f"int-{where[:4]}-{uuid.uuid4().hex[:6]}"
    user_id = await _granted_session(db, key, command)  # what an approval (here: an old one) leaves behind
    context = ToolContext(user_id=user_id, project_ids=[], roles=["admin"], session_id=f"r7-{key}", db=db,
                          capability_type="diagnosis", workspace_root=str(tmp_path), project_config={},
                          run_capability=state)
    result = await module.BashTool().execute({"command": command}, context)
    assert calls == [] and CAPABILITY_REFUSAL_KEY in result and "approval_id" not in result, result


@pytest.mark.parametrize("where", sorted(CONTEXTS))
async def test_a_standing_rule_never_covers_a_write_in_a_read_only_context(db, where):
    project, owner, _member = await _workspace(db)
    finding = SecurityAnalyzerFinding("exec_policy", "review", "medium", "write", {})
    await grant_standing_tool_rule(db, project_id=project.id, decider_id=owner.id,
                                   scope=command_review_scope("run_cli_command", "git push", [finding]))
    session = await _session(db, project, owner)
    context = ToolContext(user_id=owner.id, project_ids=[project.id], roles=[], session_id=session.id, db=db,
                          project_config=dict(project.config or {}), run_capability=await _state(db, CONTEXTS[where]))
    result = await _policy_block_result("run_cli_command", "git push", context)
    assert result is not None and CAPABILITY_REFUSAL_KEY in result and "approval_id" not in result


async def test_reads_still_run_and_a_change_phase_keeps_its_grants(db, monkeypatch, tmp_path, exec_config):  # noqa: F811
    """Positive controls: a plain read runs in a read-only context; in a ``change`` phase the granted command runs."""
    module, calls = _runtime(monkeypatch)
    read_only = await _state(db, None)
    user_id = await _granted_session(db, "int-read", "unrelated")
    await module.BashTool().execute({"command": "cat README.md"}, ToolContext(
        user_id=user_id, project_ids=[], roles=["admin"], session_id="r7-int-read", db=db, capability_type="diagnosis",
        workspace_root=str(tmp_path), project_config={}, run_capability=read_only))
    change = await _state(db, _phase_resolution("change"))
    assert (change["class"], change["enforced"]) == ("change", True)
    user_id = await _granted_session(db, "int-change", "sort -o out input")
    await module.BashTool().execute({"command": "sort -o out input"}, ToolContext(
        user_id=user_id, project_ids=[], roles=["admin"], session_id="r7-int-change", db=db,
        capability_type="diagnosis", workspace_root=str(tmp_path), project_config={}, run_capability=change))
    assert calls == [("cat README.md", True), ("sort -o out input", True)]


async def test_approving_a_mutating_command_in_a_read_only_chat_does_not_run_it(client, db, monkeypatch):
    """The real approve path: an approval without a change preview grant resumes nothing, so nothing runs."""
    assert (await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
            ).status_code == 303
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name="Read-only chat", config={}, is_active=True)
    db.add(project)
    await db.flush()
    session = AgentSession(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="chat",
                           status="pending_approval", metadata_={"title": "Old approval"})
    message = Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="Run the migration")
    session.metadata_["current_turn_user_message_id"] = message.id
    approval = Approval(id=str(uuid.uuid4()), task_run_id=None, session_id=session.id, requested_by=admin.id,
                        action="Approve command execution for bash", status="pending",
                        reason="Diagnosis mode requires approval\nCommand: python3 manage.py migrate")
    db.add_all([session, message, approval])
    await db.commit()
    ran = []

    async def fake_shell(command, **kwargs):
        ran.append(command)
        raise AssertionError("a read-only chat never runs an approved write")

    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_shell)
    approved = await client.post(f"/admin/chat/api/approvals/{approval.id}/approve")
    assert approved.status_code == 200 and ran == []
