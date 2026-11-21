"""Shell expansion: the words judged are the words bash runs.

Cases:

- globs, brace expansion, variables and ANSI-C quoting that change a command's words; unquoted ``?`` and
  bracket globs, repeated and combined expansions, variables in the PROGRAM NAME and in a FLAG VALUE;
- refused on the helper, the gateway (with the ORIGINAL command, also with a literal ``--context=dev``),
  the real analyzer chain and the real ``BashTool`` before the runtime;
- in a ``read_only`` run the refusal is a capability refusal: a granted approval for exactly that command
  does not turn it back into an execution (and in an unenforced run the same grant still works).

Run by bash, each of the base cases writes or deletes files or (kubectl) prints a file it was not asked to read.
This module asserts decisions and runtime calls only; it runs no shell.
"""

from __future__ import annotations

import pytest

from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.services.security_analyzer import builtins
from app.services.security_analyzer.service import analyze_security_risk
from app.tools.context import ToolContext
from tests.shell_expansion_support import _gateway, _granted_session, _runtime, exec_config  # noqa: F401

# Base cases: each expands into a write, a delete or an unasked read.
BASE_CASES = [
    "uniq glob-*",
    "uniq glob-{a,b}",
    "sort $READ_FLAGS input",
    r"sort $'\x2d\x6foutput' input",
    r"find . $'\x2ddelete'",
    r"kubectl get pods $'\x2d\x6fgo-template-file=/tmp/canary'",
]


# Mandatory additions: ? and bracket globs, repeated/combined forms, variables as program or flag value.
EXTRA_CASES = [
    "uniq glob-?",
    "uniq glob-[ab]",
    "uniq glob-[!c]",
    "sort $A$B input",
    "sort ${A}${B} input",
    "uniq glob-*{a,b}",
    r"sort $'\x2d'$'\x6f'out input",
    "$PROG README.md",
    "${CAT} README.md",
    "$(echo cat) README.md",
    "sort -k $KEY input",
    "head -n $N file",
    "sort -t$SEP input",
    "kubectl get pods -o $FMT",
    "kubectl get pods --output=$FMT",
    "cat =ls",
    "uniq ^a",
]


ALL_CASES = BASE_CASES + EXTRA_CASES


POSITIVE = [
    "find . -name '*.py'",
    "rg --glob '*.py' pattern src",
    "sort -u input",
    "uniq -c input",
    "sort -k2,2 -t, input",
]


@pytest.mark.parametrize("command", ALL_CASES)
def test_expansion_never_passes_the_helper(command):
    assert builtins.read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG).action != "allow", command


@pytest.mark.parametrize("command", ALL_CASES)
def test_the_gateway_refuses_the_original_expansion_text(command):
    decision = _gateway(command)
    assert decision is not None and decision.decision == "deny", command
    if command.startswith("kubectl "):
        with_context = command.replace("kubectl ", "kubectl --context=dev ", 1)
        decision = _gateway(with_context)
        assert decision is not None and decision.decision == "deny", with_context


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ALL_CASES)
async def test_the_real_analyzer_chain_refuses_expansion(exec_config, command):  # noqa: F811
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s",
                          run_capability={"enforced": True, "class": "read_only"}, project_config={})

    report = await analyze_security_risk("bash", command, context)

    assert report.action != "allow", command


@pytest.mark.parametrize("command", POSITIVE)
def test_quoted_patterns_and_plain_reads_remain_reads(command):
    assert builtins.read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG).action == "allow"
    assert _gateway(command) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("argv", [["cat", "glob-*"], ["cat", "$READ_FLAGS"], ["sort", "-u", "$x"]], ids=" ".join)
async def test_literal_argv_with_glob_or_dollar_file_names_stays_a_read(exec_config, argv):  # noqa: F811
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s",
                          run_capability={"enforced": True, "class": "read_only"}, project_config={})

    report = await analyze_security_risk("run_cli_command", list(argv), context)

    assert report.action == "allow", argv


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ALL_CASES)
async def test_platform_bash_refuses_before_runtime(monkeypatch, tmp_path, exec_config, command):  # noqa: F811
    module, calls = _runtime(monkeypatch)
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s",
                          run_capability={"enforced": True, "class": "read_only"}, project_config={},
                          workspace_root=str(tmp_path))

    result = await module.BashTool().execute({"command": command}, context)

    assert calls == [], (command, result)


@pytest.mark.asyncio
async def test_platform_bash_runs_a_quoted_read(monkeypatch, tmp_path, exec_config):  # noqa: F811
    module, calls = _runtime(monkeypatch)
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s",
                          run_capability={"enforced": True, "class": "read_only"}, project_config={},
                          workspace_root=str(tmp_path))

    await module.BashTool().execute({"command": "find . -name '*.py'"}, context)

    assert calls == [("find . -name '*.py'", True)]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["uniq glob-*", r"sort $'\x2d\x6foutput' input", "find . -name x -o -name y"])
async def test_in_a_read_only_run_an_approval_cannot_turn_a_refused_command_into_an_execution(
    db, monkeypatch, tmp_path, exec_config, command  # noqa: F811
):
    from app.services.run_capability.escalation import CAPABILITY_REFUSAL_KEY

    module, calls = _runtime(monkeypatch)
    key = str(abs(hash(command)) % 100000)
    user_id = await _granted_session(db, key, command)
    context = ToolContext(user_id=user_id, project_ids=[], roles=["viewer"], session_id=f"r7-{key}",
                          project_config={}, workspace_root=str(tmp_path), db=db,
                          run_capability={"enforced": True, "class": "read_only"})
    if command.startswith("find"):
        # Control: a plain read in the same read-only run still runs (the grant is irrelevant to it).
        await module.BashTool().execute({"command": command}, context)
        assert len(calls) == 1
        return

    result = await module.BashTool().execute({"command": command}, context)

    assert calls == [], result
    assert CAPABILITY_REFUSAL_KEY in result, result
    assert "approval_id" not in result


@pytest.mark.asyncio
async def test_in_a_change_run_the_read_only_rules_do_not_hold_the_command(
    monkeypatch, tmp_path, exec_config  # noqa: F811
):
    module, calls = _runtime(monkeypatch)
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="r7-change",
                          run_capability={"enforced": True, "class": "change"}, project_config={},
                          workspace_root=str(tmp_path))

    await module.BashTool().execute({"command": "uniq glob-*"}, context)

    assert calls == [("uniq glob-*", True)]


@pytest.mark.asyncio
async def test_a_verbatim_command_has_no_approval_path_in_a_read_only_run(db, monkeypatch, tmp_path, exec_config):  # noqa: F811
    # A read-only context is strictly read-only: a write shown verbatim is refused by capability like shell
    # expansion; a grant (here: a stored one) never runs it.
    module, calls = _runtime(monkeypatch)
    user_id = await _granted_session(db, "verbatim", "sort -o out input")
    context = ToolContext(user_id=user_id, project_ids=[], roles=["viewer"], session_id="r7-verbatim",
                          project_config={}, workspace_root=str(tmp_path), db=db,
                          run_capability={"enforced": True, "class": "read_only"})

    result = await module.BashTool().execute({"command": "sort -o out input"}, context)

    assert calls == [] and result["capability_refusal"]["run_capability"] == "read_only"
    assert "approval_id" not in result
