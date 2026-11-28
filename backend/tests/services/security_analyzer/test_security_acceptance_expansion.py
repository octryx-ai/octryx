"""Argv option semantics and shell expansion refused on the helper, gateway, analyzer chain and the real bash tool."""

from __future__ import annotations

import pytest

from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.tools.context import ToolContext
from tests.support.security_acceptance_support import _diagnosis_report, _gateway, runtime  # noqa: F401

# The argv form: the diagnosis analyzer applied the invocation/option rules to strings only, so argv
# lists like ['find', '.', '-delete'] passed. The same option semantics now apply to argv; shell
# operator tokens in an argv list are literal arguments (no shell runs it).
ARGV_ESCAPES = [
    ["find", ".", "-delete"],
    ["find", ".", "-exec", "rm", "{}", "+"],
    ["sort", "-o", "out", "in"],
    ["sort", "--out=out", "in"],
    ["uniq", "in", "out"],
    ["uniq", "--", "in", "-out"],
    ["sed", "w /tmp/x", "a"],
    ["date", "-s", "2020-01-01"],
    ["env", "HOME=/tmp/x", "cat", "a"],
    ["HOME=/tmp/x", "cat", "a"],
    ["/tmp/x/cat", "a"],
    ["rg", "--pre", "sh", "x"],
]


ARGV_READS = [
    ["cat", "README.md", ";"],
    ["cat", "a", ">", "b"],
    ["sort", "-u", "in"],
    ["uniq", "-c", "in"],
    ["find", ".", "-name", "*.py"],
    ["ls", "-la"],
]


# --- Shell expansion ----------------------------------------------------------------------------------
# Shell expansion changes the argv bash runs after the check: the ORIGINAL text is judged with its quote and
# escape state, and every expansion not proven safe fails closed, before any normalization or re-quoting.
EXPANSIONS = [
    "uniq glob-*",
    "uniq glob-?",
    "uniq glob-[ab]",
    "uniq glob-{a,b}",
    "uniq glob-{1..2}",
    "sort $READ_FLAGS input",
    "sort ${READ_FLAGS} input",
    'sort "$READ_FLAGS" input',
    "sort $(echo -o) out input",
    "sort `echo -o` out input",
    "sort $((1)) input",
    r"sort $'\x2d\x6foutput' input",
    r"find . $'\x2ddelete'",
    'sort $"-ooutput" input',
    "cat ~/.kube/config",
    "cat ~root/x",
    "cat !$",
    "cat a # -o",
    r'sort "\$x" input',
    r"kubectl --context=dev get pods $'\x2d\x6fgo-template-file=/tmp/canary'",
]


EXPANSION_SAFE = [
    "find . -name '*.py'",
    "rg --glob '*.py' pattern src",
    "find . -name \\*.py",
    "sed -n '$p' a",
    "sort -u input",
    "uniq -c input",
    "cat 'a b'",
    'cat "a b"',
    "kubectl --context=dev get pods -o 'jsonpath={.items[*].metadata.name}'",
    "head -5 a",
]


async def _bash_tool(monkeypatch, tmp_path, command):

    from app.services.execution_runtime import ExecutionRuntimeResult
    from app.services.security_analyzer import builtins
    from app.tools.runtime_impl import _runtime_bash_web as module

    async def config(db, project_id=None):
        return DEFAULT_EXEC_POLICY_CONFIG

    calls: list = []

    async def execute(**kwargs):
        calls.append(kwargs["command"])
        return ExecutionRuntimeResult(exit_code=0, stdout="", stderr="", timed_out=False, metadata={})

    monkeypatch.setattr(builtins, "get_effective_exec_policy_config", config)
    monkeypatch.setattr("app.services.execution_runtime.service.execute_with_runtime", execute)
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s", project_config={},
                          run_capability={"enforced": True, "class": "read_only"}, workspace_root=str(tmp_path))
    result = await module.BashTool().execute({"command": command}, context)
    return result, calls


@pytest.mark.asyncio
@pytest.mark.parametrize("argv", ARGV_ESCAPES, ids=" ".join)
async def test_argv_lists_get_the_same_option_semantics(monkeypatch, argv):
    assert (await _diagnosis_report(monkeypatch, "run_cli_command", list(argv))).action != "allow"


@pytest.mark.asyncio
@pytest.mark.parametrize("argv", ARGV_READS, ids=" ".join)
async def test_argv_reads_stay_allowed_and_operator_tokens_stay_literal(monkeypatch, argv):
    assert (await _diagnosis_report(monkeypatch, "run_cli_command", list(argv))).action == "allow"


@pytest.mark.parametrize("command", EXPANSIONS)
def test_r7_1_expansion_is_refused_on_helper_and_gateway(command):
    from app.services.security_analyzer.builtins import read_only_command_finding

    assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG,
                                     kubectl_context_selectable=True).action != "allow", command
    decision = _gateway(command)
    assert decision is not None and decision.decision == "deny", command


@pytest.mark.asyncio
@pytest.mark.parametrize("command", EXPANSIONS)
async def test_r7_1_expansion_is_refused_on_the_platform_analyzer_chain(monkeypatch, command):
    assert (await _diagnosis_report(monkeypatch, "bash", command)).action != "allow"


@pytest.mark.parametrize("command", EXPANSION_SAFE)
def test_r7_1_quote_literal_forms_stay_allowed(command):
    from app.services.security_analyzer.builtins import read_only_command_finding

    assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG,
                                     kubectl_context_selectable=True).action == "allow", command
    assert _gateway(command) is None, command


@pytest.mark.asyncio
@pytest.mark.parametrize("argv", [["uniq", "glob-*"], ["sort", "$READ_FLAGS", "input"], ["find", ".", "-name", "*.py"]],
                         ids=" ".join)
async def test_r7_1_argv_lists_stay_literal(monkeypatch, argv):
    # No shell runs an argv list: '*' and '$' are literal characters of one argument.
    assert (await _diagnosis_report(monkeypatch, "run_cli_command", list(argv))).action == "allow"


@pytest.mark.asyncio
@pytest.mark.parametrize("command", EXPANSIONS[:14])
async def test_r7_1_the_real_bash_tool_never_runs_an_expanding_command(monkeypatch, tmp_path, command):
    result, calls = await _bash_tool(monkeypatch, tmp_path, command)

    assert calls == [], (command, result)


@pytest.mark.asyncio
async def test_r7_1_the_real_bash_tool_runs_a_quote_literal_read(monkeypatch, tmp_path):
    result, calls = await _bash_tool(monkeypatch, tmp_path, "find . -name '*.py'")

    assert len(calls) == 1, result
