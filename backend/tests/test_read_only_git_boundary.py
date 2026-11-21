"""Git on read-only paths: only closed git read forms run.

On a strictly read-only path (the Assistant outside a run, a ``read_only`` phase) the shared read-only boundary
(``security_analyzer.read_only_git``) admits only closed git read forms, so ``git remote add``, ``git branch probe``
and ``git log --output=out`` never reach the runtime. Proven on: the real turn routing + bash tool (also with a
stored grant), the tool registry dispatch, the device gateway's
PreToolUse decision and the chat approve-and-resume path. Positive controls: the git reads a phase or the Assistant
uses still run, and a ``change`` phase keeps its git writes.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, Message, Project, User
from app.models import Session as AgentSession
from app.services.agent_gateway.capability import capability_decision
from app.services.agent_gateway.capability_session import EffectiveCapability
from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.services.run_capability.escalation import CAPABILITY_REFUSAL_KEY
from app.services.security_analyzer.builtins import read_only_command_finding
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.conftest import ADMIN_PASSWORD
from tests.shell_expansion_support import _granted_session, _runtime, exec_config  # noqa: F401
from tests.test_read_only_security_integration import CONTEXTS, _phase_resolution, _state

pytestmark = pytest.mark.asyncio
WRITES = [
    "git remote add probe https://example.test/probe", "git remote set-url origin https://example.test/x",
    "git remote remove origin", "git branch probe", "git branch -d main", "git branch -m a b",
    "git log --output=out", "git diff --output=out", "git diff --ext-diff", "git log --textconv -p",
    "git -c core.pager=sh log", "git --exec-path=/tmp log", "git -p log", "git --git-dir=/tmp/x log",
    "git config user.name x", "git ls-files", "git log --out=x",
]
READS = [
    "git status", "git status --porcelain", "git diff --stat main", "git diff --cached", "git log --oneline -n 5",
    "git log -5 --format=%H", "git show --stat HEAD", "git show HEAD:README.md", "git branch -a",
    "git branch --show-current", "git branch --list 'feat*'", "git rev-parse --abbrev-ref HEAD", "git remote -v",
    "git remote get-url origin", "git --no-pager log -1", "git -C repo status",
]


def _finding(command: str):
    return read_only_command_finding(command, dict(DEFAULT_EXEC_POLICY_CONFIG))


@pytest.mark.parametrize("command", WRITES)
async def test_the_shared_read_only_rule_refuses_every_git_write_or_unknown_form(command):
    assert _finding(command).action != "allow", command


@pytest.mark.parametrize("command", READS)
async def test_the_shared_read_only_rule_admits_the_git_reads_phases_use(command):
    assert _finding(command).action == "allow", command


# --- Regression cases for the read-only git command boundary ---------------------------------------------------


@pytest.mark.parametrize("where", sorted(CONTEXTS))
@pytest.mark.parametrize("command", ["git remote add probe https://example.test/probe", "git branch probe",
                                     "git log --output=out"])
async def test_known_git_mutations_do_not_run_in_strict_read_only(db, monkeypatch, tmp_path, exec_config,  # noqa: F811
                                                                    where, command):
    state = await _state(db, CONTEXTS[where])
    assert state["enforced"] and state["class"] == "read_only"
    module, calls = _runtime(monkeypatch)
    key = where.replace(" ", "-") + command.split()[1] + uuid.uuid4().hex[:4]
    user_id = await _granted_session(db, key, command)
    context = ToolContext(user_id=user_id, project_ids=[], roles=["admin"], session_id="r7-" + key, db=db,
                          capability_type="diagnosis", workspace_root=str(tmp_path), project_config={},
                          run_capability=state)
    result = await module.BashTool().execute({"command": command}, context)
    assert calls == [] and CAPABILITY_REFUSAL_KEY in result, (result, calls)


# --- reachability beyond the tool itself and positive controls ----------------------------------------------------


@pytest.mark.parametrize("where", sorted(CONTEXTS))
async def test_the_registry_dispatch_refuses_and_reads_still_run(db, monkeypatch, tmp_path, exec_config, where):  # noqa: F811
    _module, calls = _runtime(monkeypatch)
    context = ToolContext(user_id="", project_ids=[], roles=["admin"], session_id=f"git-{uuid.uuid4().hex[:6]}",
                          db=db, capability_type="diagnosis", workspace_root=str(tmp_path), project_config={},
                          run_capability=await _state(db, CONTEXTS[where]))
    refused = await execute_tool("bash", {"command": "git remote add probe https://example.test/probe"}, context)
    assert calls == [] and CAPABILITY_REFUSAL_KEY in refused
    await execute_tool("bash", {"command": "git log --oneline -n 5"}, context)
    assert calls == [("git log --oneline -n 5", True)]


async def test_a_change_phase_keeps_its_git_writes(db, monkeypatch, tmp_path, exec_config):  # noqa: F811
    _module, calls = _runtime(monkeypatch)
    state = await _state(db, _phase_resolution("change"))
    context = ToolContext(user_id="", project_ids=[], roles=["admin"], session_id=f"git-{uuid.uuid4().hex[:6]}",
                          db=db, capability_type="change", workspace_root=str(tmp_path), project_config={},
                          run_capability=state)
    await execute_tool("bash", {"command": "git branch feature/x"}, context)
    assert calls == [("git branch feature/x", True)]


@pytest.mark.parametrize(("command", "denied"), [("git remote add probe https://example.test/probe", True),
                                                 ("git branch probe", True), ("git log --output=out", True),
                                                 ("git status", False), ("git log --oneline -n 5", False)])
async def test_the_device_gateway_decides_the_same_way_outside_a_run(command, denied):
    """octryx-claude outside a run is read-only (D2): Claude Code's native Bash gets the same verdict."""
    decision = capability_decision(EffectiveCapability("read_only", None, None, None),
                                   {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/repo"},
                                   dict(DEFAULT_EXEC_POLICY_CONFIG))
    assert (decision is not None) is denied, (command, decision)


async def test_approving_a_git_write_in_a_read_only_chat_does_not_run_it(client, db, monkeypatch):
    assert (await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
            ).status_code == 303
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name="Read-only git chat", config={}, is_active=True)
    db.add(project)
    await db.flush()
    session = AgentSession(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="chat",
                           status="pending_approval", metadata_={"title": "Old git approval"})
    message = Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="Add the probe remote")
    session.metadata_["current_turn_user_message_id"] = message.id
    approval = Approval(id=str(uuid.uuid4()), task_run_id=None, session_id=session.id, requested_by=admin.id,
                        action="Approve command execution for bash", status="pending",
                        reason="Diagnosis mode requires approval\nCommand: git remote add probe https://example.test/p")
    db.add_all([session, message, approval])
    await db.commit()
    ran = []

    async def fake_shell(command, **kwargs):
        ran.append(command)
        raise AssertionError("a read-only chat never runs an approved git write")

    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_shell)
    approved = await client.post(f"/admin/chat/api/approvals/{approval.id}/approve")
    # An approval without a change preview grant resumes nothing: no command runs.
    assert approved.status_code == 200 and ran == []


@pytest.mark.parametrize(("argv", "refused"), [
    (["git", "remote", "add", "probe", "https://example.test/probe"], True), (["git", "branch", "probe"], True),
    (["git", "log", "--output=out"], True), (["git", "-c", "core.pager=sh", "log"], True),
    (["git", "status"], False), (["git", "log", "--oneline", "-n", "5"], False)])
async def test_an_argv_git_call_gets_the_same_verdict(db, tmp_path, exec_config, argv, refused):  # noqa: F811
    """The argument-list form (no shell) is judged by the same closed git forms."""
    from app.tools.runtime_impl._runtime_command_policy import _policy_block_result

    context = ToolContext(user_id="", project_ids=[], roles=["admin"], session_id=f"git-{uuid.uuid4().hex[:6]}",
                          db=db, capability_type="diagnosis", workspace_root=str(tmp_path), project_config={},
                          run_capability=await _state(db, None))
    result = await _policy_block_result("run_cli_command", argv, context)
    assert (result is not None and CAPABILITY_REFUSAL_KEY in result) is refused, (argv, result)
