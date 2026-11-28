"""Process substitution is refused as an expansion on the helper, the gateway, the analyzer chain and platform bash, cannot be approved in a read-only run, and stays a literal file name when quoted."""

from __future__ import annotations

import pytest

from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.services.security_analyzer import builtins
from app.services.security_analyzer.service import analyze_security_risk
from app.tools.context import ToolContext
from tests.shell_expansion_support import _gateway, _granted_session, _runtime, exec_config  # noqa: F401

# Process substitution: ``<(…)``/``>(…)`` (and zsh ``=(…)``) run a command and pass its pipe as a word. It is an
# expansion, so it must be refused on the original text AS an expansion: only then is it the final capability
# refusal in a read-only run, not an approvable review.
PROCESS_SUBSTITUTION = [
    "cat <(printf canary)",
    "cat >(printf canary)",
    "cat a | tee >(sh)",
    "diff <(cat a) <(cat b)",
    "cat =(printf canary)",
    "cat a<(printf canary)",
]


# (A quoted ``'>(sh)'`` is still refused, by the configured operator check, which matches ``>`` anywhere in the
# text: fail closed, unrelated to process substitution.)
PROCESS_SUBSTITUTION_LITERAL = ["cat '<(x)'", 'cat "<(x)"', "cat '=(x)'", "wc -l '<(a)'"]


@pytest.mark.parametrize("command", PROCESS_SUBSTITUTION)
def test_process_substitution_is_refused_as_an_expansion_on_the_helper(command):
    finding = builtins.read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG)

    assert finding.action != "allow", command
    assert finding.details.get("shell_expansion") is True, (command, finding.details)


@pytest.mark.parametrize("command", PROCESS_SUBSTITUTION)
def test_the_gateway_refuses_process_substitution_in_the_original_text(command):
    decision = _gateway(command)

    assert decision is not None and decision.decision == "deny", command


@pytest.mark.asyncio
@pytest.mark.parametrize("command", PROCESS_SUBSTITUTION)
async def test_the_real_analyzer_chain_refuses_process_substitution(exec_config, command):  # noqa: F811
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s",
                          run_capability={"enforced": True, "class": "read_only"}, project_config={})

    assert (await analyze_security_risk("bash", command, context)).action != "allow", command


@pytest.mark.asyncio
@pytest.mark.parametrize("command", PROCESS_SUBSTITUTION)
async def test_platform_bash_refuses_process_substitution_before_runtime(monkeypatch, tmp_path, exec_config, command):  # noqa: F811
    module, calls = _runtime(monkeypatch)
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s",
                          run_capability={"enforced": True, "class": "read_only"}, project_config={},
                          workspace_root=str(tmp_path))

    result = await module.BashTool().execute({"command": command}, context)

    assert calls == [], (command, result)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", PROCESS_SUBSTITUTION)
async def test_in_a_read_only_run_an_approval_cannot_execute_process_substitution(
    db, monkeypatch, tmp_path, exec_config, command  # noqa: F811
):
    from app.services.run_capability.escalation import CAPABILITY_REFUSAL_KEY

    module, calls = _runtime(monkeypatch)
    key = f"ps-{PROCESS_SUBSTITUTION.index(command)}"
    user_id = await _granted_session(db, key, command)
    context = ToolContext(user_id=user_id, project_ids=[], roles=["viewer"], session_id=f"r7-{key}",
                          project_config={}, workspace_root=str(tmp_path), db=db,
                          run_capability={"enforced": True, "class": "read_only"})

    result = await module.BashTool().execute({"command": command}, context)

    assert calls == [], (command, result)
    assert CAPABILITY_REFUSAL_KEY in result, result
    assert "approval_id" not in result


@pytest.mark.parametrize("command", PROCESS_SUBSTITUTION_LITERAL)
def test_a_quoted_process_substitution_is_a_literal_file_name(command):
    assert builtins.read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG).action == "allow", command
    assert _gateway(command) is None, command
