"""Git's optional-argument options (``-U[<n>]``, ``--unified[=<n>]``, ...) never swallow the next word, so a hidden
``--output`` cannot be admitted."""

from __future__ import annotations

import uuid

import pytest

from app.services.agent_gateway.capability import capability_decision
from app.services.agent_gateway.capability_session import EffectiveCapability
from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.services.run_capability.escalation import CAPABILITY_REFUSAL_KEY
from app.services.security_analyzer.builtins import read_only_command_finding
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from app.tools.runtime_impl._runtime_command_policy import _policy_block_result
from tests.shell_expansion_support import _granted_session, _runtime, exec_config  # noqa: F401
from tests.test_read_only_security_integration import CONTEXTS, _state

pytestmark = pytest.mark.asyncio
CASES = ["git diff --unified --output=out", "git diff -U --output=out"]
HIDING = [
    *CASES, "git diff -U --output out", "git diff -M --output=out", "git diff --stat --output=out",
    "git log --author --output=out", "git log -n --output=out", "git log --format --output=out",
    "git log -S --output=out", "git diff --diff-filter --output=out", "git show --date --output=out",
    "git diff -C", "git diff -B", "git diff --find-copies",
]
SAFE = [
    "git diff -U3", "git diff --unified=3", "git diff -U", "git diff -M50", "git diff --find-renames=40",
    "git diff --stat=80", "git log -n 5", "git log -n5", "git log --author bob", "git log --format=%H",
    "git log --date=iso", "git diff --diff-filter ACM", "git show --stat HEAD", "git branch --sort=-committerdate",
]


def _finding(command: str):
    return read_only_command_finding(command, dict(DEFAULT_EXEC_POLICY_CONFIG))


@pytest.mark.parametrize("command", CASES)
async def test_an_optional_git_patch_flag_cannot_swallow_a_write_option(command):
    assert _finding(command).action != "allow"


@pytest.mark.parametrize("where", sorted(CONTEXTS))
@pytest.mark.parametrize("command", CASES)
async def test_the_option_arity_bypass_never_reaches_the_read_only_runtime(db, monkeypatch, tmp_path, exec_config,  # noqa: F811
                                                                           where, command):
    state = await _state(db, CONTEXTS[where])
    module, calls = _runtime(monkeypatch)
    key = where.replace(" ", "-") + str(CASES.index(command)) + uuid.uuid4().hex[:4]
    user = await _granted_session(db, key, command)
    context = ToolContext(user_id=user, project_ids=[], roles=["admin"], session_id="r7-" + key, db=db,
                          capability_type="diagnosis", workspace_root=str(tmp_path), project_config={},
                          run_capability=state)
    result = await module.BashTool().execute({"command": command}, context)
    assert calls == [], (result, calls)


@pytest.mark.parametrize("command", HIDING)
async def test_no_option_is_hidden_as_a_value(command):
    assert _finding(command).action != "allow", command


@pytest.mark.parametrize("command", SAFE)
async def test_attached_values_and_required_values_still_read(command):
    assert _finding(command).action == "allow", command


@pytest.mark.parametrize("granted", [False, True])
@pytest.mark.parametrize("command", CASES)
async def test_string_and_argv_with_and_without_a_grant(db, monkeypatch, tmp_path, exec_config, granted, command):  # noqa: F811
    key = f"arity-{granted}-{uuid.uuid4().hex[:6]}"
    user = await _granted_session(db, key, command if granted else "unrelated")
    context = ToolContext(user_id=user, project_ids=[], roles=["admin"], session_id=f"r7-{key}", db=db,
                          capability_type="diagnosis", workspace_root=str(tmp_path), project_config={},
                          run_capability=await _state(db, None))
    for form in (command, command.split()):
        result = await _policy_block_result("run_cli_command", form, context)
        assert result is not None and CAPABILITY_REFUSAL_KEY in result, (form, result)


@pytest.mark.parametrize("where", sorted(CONTEXTS))
async def test_the_registry_and_the_gateway_refuse_and_attached_values_run(db, monkeypatch, tmp_path, exec_config,  # noqa: F811
                                                                           where):
    _module, calls = _runtime(monkeypatch)
    context = ToolContext(user_id="", project_ids=[], roles=["admin"], session_id=f"arity-{uuid.uuid4().hex[:6]}",
                          db=db, capability_type="diagnosis", workspace_root=str(tmp_path), project_config={},
                          run_capability=await _state(db, CONTEXTS[where]))
    for command in CASES:
        assert CAPABILITY_REFUSAL_KEY in await execute_tool("bash", {"command": command}, context)
    await execute_tool("bash", {"command": "git diff -U3 --stat"}, context)
    assert calls == [("git diff -U3 --stat", True)]
    for command, denied in [*((case, True) for case in CASES), ("git diff --unified=3", False)]:
        decision = capability_decision(EffectiveCapability("read_only"), {
            "tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/repo"}, dict(DEFAULT_EXEC_POLICY_CONFIG))
        assert (decision is not None) is denied, command
