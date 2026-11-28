"""Environment wrappers, path manipulation, log masking, dash-dash and missing values, quoted and escaping read commands fail closed."""

from __future__ import annotations

import pytest

# The log-masking classification must not judge ``args[0]`` only, or leading flags that the parser
# accepts (``-n payments logs …``) slip past it. It uses the resolved command path;
# an ambiguous argv counts as a log read (fail closed).
from app.services.classification_tool_policy import (  # noqa: E402
    CLASSIFICATION_TOOL_POLICY_KEY,
    builtin_tool_decision,
    tool_reads_logs,
)
from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.tools import kubernetes

# --- Flag-scanning counterexamples ------------------------------------------------------------------------
# ``--`` consumed as a flag VALUE must not end flag scanning; a standalone ``--`` is ambiguous here
# (fail closed). Packed short flags are parsed per character like pflag (``-As…`` hides ``-s``).
# Leading environment assignments, wrappers and path-qualified binaries on read-only paths.
from app.tools.kubernetes_kubectl_argv import kubectl_is_read_only  # noqa: E402
from app.tools.runtime_impl._runtime_kubectl_tool import RunKubectlCommandTool
from tests.support.security_acceptance_support import _context, _diagnosis_report, _gateway, runtime  # noqa: F401

ENV_AND_WRAPPER_FORMS = [
    "HOME=/tmp/other kubectl --context=dev get pods",
    "env HOME=/tmp/other kubectl --context=dev get pods",
    "PATH=/tmp/other kubectl --context=dev get pods",
    "env PATH=/tmp/other kubectl --context=dev get pods",
    "KUBECONFIG=/tmp/evil kubectl --context=dev get pods",
    "env -i kubectl --context=dev get pods",
    "command kubectl --context=dev get pods",
    "exec kubectl --context=dev get pods",
    "nice kubectl --context=dev get pods",
    "nohup kubectl --context=dev get pods",
    "time kubectl --context=dev get pods",
    "timeout 5 kubectl --context=dev get pods",
    "sudo kubectl --context=dev get pods",
    "/tmp/other/kubectl --context=dev get pods",
    "./kubectl --context=dev get pods",
    "HOME=/tmp/other cat README.md",
    "env cat README.md",
    "LC_ALL=C ls",
]


_MASKING = {"level": "restricted", "log_masking_required": True, "connectors": {"kubernetes": "read"}}


LOG_FORMS = [
    ["logs", "api-0"],
    ["--namespace", "payments", "logs", "api-0"],
    ["-n", "payments", "logs", "api-0"],
    ["-npayments", "logs", "api-0"],
    ["--namespace=payments", "logs", "api-0", "--tail", "5"],
    ["-v", "6", "logs", "api-0"],
    ["--unknown", "logs", "api-0"],
]


# --- '--' and missing values --------------------------------------------------------------------------
# '--' as a VALUE before, between and after command words, and missing values, on every path.
DASHDASH_AND_MISSING = [
    ["--namespace", "--", "get", "pods", "--server=https://evil.example"],
    ["auth", "--namespace", "--", "can-i", "list", "pods", "--token=t"],
    ["get", "pods", "--request-timeout", "--", "--token=t"],
    ["cluster-info", "--namespace", "--", "dump"],
    ["get", "pods", "--namespace"],
    ["get", "pods", "-n"],
    ["--namespace"],
    ["get", "pods", "-o"],
]


# The original shell semantics are judged before normalization; quoted assignments and quoted
# wrappers stay refused; programs outside the read-only list (unknown wrappers) fail closed.
QUOTED_AND_UNKNOWN = [
    '"HOME=/tmp/x" kubectl --context=dev get pods',
    "HOME='/tmp/x' kubectl --context=dev get pods",
    "'env' HOME=/tmp/x kubectl --context=dev get pods",
    "\\env HOME=/tmp/x kubectl --context=dev get pods",
    'e"nv" PATH=/tmp/x kubectl --context=dev get pods',
    "firejail kubectl --context=dev get pods",
    "busybox kubectl --context=dev get pods",
]


# Allowed read-only commands are bound to their reading options: an option that writes a file or runs
# another program is refused on both paths.
READ_COMMAND_ESCAPES = [
    "find . -delete",
    "find . -exec rm {} +",
    "find . -execdir sh -c x {} ;",
    "find . -fprint /tmp/x",
    "find . -ok rm {} ;",
    "sort -o /tmp/x a",
    "sort -uo /tmp/x a",
    "sort --output=/tmp/x a",
    "sort --compress-program=sh a",
    "uniq a /tmp/x",
    "rg --pre sh pattern",
    "rg --pre=sh pattern",
    "rg -z pattern",
    "sed 'w /tmp/x' a",
    "sed -n '1e touch /tmp/x' a",
    "sed 's/a/b/w /tmp/x' a",
    "sed 's/a/b/e' a",
    "sed -i 's/a/b/' a",
    "sed -ni 1p a",
    "sed -f script.sed a",
]


READ_COMMAND_READS = [
    "find . -name '*.py' -type f",
    "sort -u a",
    "sort -k2,2 -t, a",
    "uniq -c a",
    "rg -n pattern src",
    "sed -n 1,5p a",
    "sed -n '$p' a",
    "sed 's/a/b/g' a",
    "sed -E -e 's/x+/y/' a",
    "cat README.md",
    "env",
]


@pytest.mark.parametrize("command", ENV_AND_WRAPPER_FORMS)
def test_the_gateway_refuses_environment_wrapper_and_path_manipulation(command):
    decision = _gateway(command)

    assert decision is not None and decision.decision == "deny", command


@pytest.mark.parametrize("command", ENV_AND_WRAPPER_FORMS)
def test_the_helper_refuses_the_same_forms(command):
    from app.services.security_analyzer.builtins import read_only_command_finding

    assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG,
                                     kubectl_context_selectable=True).action != "allow"


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ENV_AND_WRAPPER_FORMS)
async def test_platform_bash_refuses_the_same_forms(monkeypatch, command):
    assert (await _diagnosis_report(monkeypatch, "bash", command)).action != "allow"


def test_a_pipe_of_plain_reads_still_passes_the_gateway():
    assert _gateway("kubectl --context=dev get pods -o json | head -5") is None


@pytest.mark.parametrize("args", LOG_FORMS, ids=" ".join)
def test_log_reads_are_classified_whatever_flags_lead(args):
    assert tool_reads_logs("run_kubectl", {"args": args}) is True
    assert builtin_tool_decision("run_kubectl", _MASKING, {"args": args}).reason == "log_masking_not_available"


@pytest.mark.asyncio
@pytest.mark.parametrize("args", LOG_FORMS[:5], ids=" ".join)
async def test_masking_required_log_reads_never_reach_the_runtime(runtime, args):  # noqa: F811
    from app.tools.registry_governance import _run_governed_tool_checks

    context = _context(project_config={**_context().project_config, CLASSIFICATION_TOOL_POLICY_KEY: _MASKING})

    refused = await _run_governed_tool_checks("run_kubectl", {"args": list(args)}, context)

    assert refused is not None and refused.get("reason") == "log_masking_not_available"
    assert runtime.commands == []


@pytest.mark.parametrize("args", [["-n", "payments", "get", "pods"], ["--namespace=payments", "describe", "pod", "x"]],
                         ids=" ".join)
def test_namespaced_non_log_reads_stay_admitted_under_masking(args):
    assert tool_reads_logs("run_kubectl", {"args": args}) is False
    assert builtin_tool_decision("run_kubectl", _MASKING, {"args": args}).allowed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("args", DASHDASH_AND_MISSING, ids=" ".join)
async def test_dashdash_values_and_missing_values_fail_closed_on_every_path(monkeypatch, runtime, args):  # noqa: F811
    import shlex

    from app.services.classification_tool_policy import tool_writes as writes

    assert kubectl_is_read_only(args) is False
    assert writes("run_kubectl", {"args": args}) is True
    returncode, _, _ = await kubernetes._run_kubectl(_context(), args)
    tool = await RunKubectlCommandTool().execute({"args": list(args)}, _context())
    assert returncode == 1 and tool.get("error") and runtime.commands == []
    report = await _diagnosis_report(monkeypatch, "run_kubectl", ["kubectl", "--context", "demo", *args])
    assert report.action != "allow"
    decision = _gateway("kubectl --context=dev " + shlex.join(args))
    assert decision is not None and decision.decision == "deny"


@pytest.mark.parametrize("command", QUOTED_AND_UNKNOWN + READ_COMMAND_ESCAPES)
def test_quoted_unknown_and_escaping_forms_are_refused_on_helper_and_gateway(command):
    from app.services.security_analyzer.builtins import read_only_command_finding

    assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG,
                                     kubectl_context_selectable=True).action != "allow", command
    decision = _gateway(command)
    assert decision is not None and decision.decision == "deny", command


@pytest.mark.asyncio
@pytest.mark.parametrize("command", READ_COMMAND_ESCAPES)
async def test_platform_bash_refuses_escaping_read_commands(monkeypatch, command):
    assert (await _diagnosis_report(monkeypatch, "bash", command)).action != "allow"


@pytest.mark.parametrize("command", READ_COMMAND_READS)
def test_bound_read_forms_stay_allowed(command):
    from app.services.security_analyzer.builtins import read_only_command_finding

    if command != "env":  # bare env prints the environment (secret analyzer reviews it); not a plain read here
        assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG).action == "allow", command
    assert _gateway(command) is None, command
