"""under an alert scope every Kubernetes path stays in the mapped target's namespace (and connection).

- ``kubectl_scope_refusal``: ``-A``/``--all-namespaces`` (any spelling), a ``-n``/``--namespace`` other than the
  target's and a Secret read with ``get``/``describe`` (``secret``, ``secrets``, ``Secret.v1``, ``pods,secrets``,
  ``secret/x``, ``-o yaml``) are refused; without a scope nothing changes (D7 a);
- ``run_kubectl`` and the internal runner refuse those before anything runs, and run in the target's namespace;
- the structured tools default to the target's namespace and refuse another one (``namespace_out_of_scope``, a
  ``refused`` envelope, nothing executed); the evidence tools carry an envelope (``empty`` is targeted);
- a refused out-of-scope call is not counted as evidence by the gate.
"""

from __future__ import annotations

import json

import pytest

import app.tools.kubernetes as kubernetes
from app.services.workflow_checks.evidence_families import evaluate_families, records_of
from app.services.workflow_checks.library import ToolUse
from app.tools.alert_scope import AlertScope
from app.tools.kubernetes_kubectl_argv import (
    KUBECTL_ALL_NAMESPACES_OUT_OF_SCOPE,
    NAMESPACE_OUT_OF_SCOPE,
    SECRET_READ_OUT_OF_SCOPE,
    kubectl_scope_refusal,
)
from app.tools.registry import ToolContext
from app.tools.runtime_impl import _runtime_kubectl_tool
from app.tools.runtime_impl._runtime_kubectl_tool import RunKubectlCommandTool

SCOPE = AlertScope(target_id="checkout", namespace="shop", connection_id="k8s-prod")

REFUSED = [
    (["get", "pods", "-A"], KUBECTL_ALL_NAMESPACES_OUT_OF_SCOPE),
    (["get", "pods", "--all-namespaces"], KUBECTL_ALL_NAMESPACES_OUT_OF_SCOPE),
    (["get", "pods", "--all-namespaces=false"], KUBECTL_ALL_NAMESPACES_OUT_OF_SCOPE),
    (["get", "pods", "-oyaml", "-A"], KUBECTL_ALL_NAMESPACES_OUT_OF_SCOPE),
    (["top", "pods", "-A"], KUBECTL_ALL_NAMESPACES_OUT_OF_SCOPE),
    (["get", "pods", "-n", "kube-system"], NAMESPACE_OUT_OF_SCOPE),
    (["get", "pods", "-nkube-system"], NAMESPACE_OUT_OF_SCOPE),
    (["get", "pods", "-n=kube-system"], NAMESPACE_OUT_OF_SCOPE),
    (["--namespace", "kube-system", "get", "pods"], NAMESPACE_OUT_OF_SCOPE),
    (["logs", "api-0", "--namespace=other"], NAMESPACE_OUT_OF_SCOPE),
    (["get", "pods", "-n", "shop", "-n", "other"], NAMESPACE_OUT_OF_SCOPE),
    (["get", "secret", "db", "-o", "yaml"], SECRET_READ_OUT_OF_SCOPE),
    (["get", "secrets"], SECRET_READ_OUT_OF_SCOPE),
    (["get", "Secret.v1", "db"], SECRET_READ_OUT_OF_SCOPE),
    (["get", "pods,secrets"], SECRET_READ_OUT_OF_SCOPE),
    (["get", "secret/db", "-o", "jsonpath={.data}"], SECRET_READ_OUT_OF_SCOPE),
    (["get", "pod/api-0", "secret/db"], SECRET_READ_OUT_OF_SCOPE),
    (["describe", "secret", "db"], SECRET_READ_OUT_OF_SCOPE),
    (["get", "-o", "yaml", "-n", "shop", "secret", "db"], SECRET_READ_OUT_OF_SCOPE),
    (["-o", "yaml", "get", "secret", "db"], "kubectl_args_ambiguous"),
]
ALLOWED = [
    ["get", "pods", "-o", "json"],
    ["get", "pods", "-n", "shop"],
    ["logs", "api-0", "--tail", "50"],
    ["describe", "pod", "api-0"],
    ["get", "events", "--field-selector", "involvedObject.name=secret"],
    ["explain", "secret"],
    ["top", "pods"],
]


@pytest.mark.parametrize(("args", "code"), REFUSED, ids=lambda value: " ".join(value) if isinstance(value, list)
                         else value)
def test_scope_refusals(args, code):
    assert kubectl_scope_refusal(args, namespace="shop") == code
    # Without a scope nothing changes here (the read-only rule decides).
    assert kubectl_scope_refusal(args, namespace=None) is None


@pytest.mark.parametrize("args", ALLOWED, ids=" ".join)
def test_reads_in_the_target_namespace_pass(args):
    assert kubectl_scope_refusal(args, namespace="shop") is None


def _context(**config) -> ToolContext:
    return ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s",
                       project_config={"k8s_use_kubectl": True, "k8s_namespace": "default", **config},
                       connection_id="k8s-prod")


def _scoped(monkeypatch, scope, *modules):
    async def run_alert_scope(_context):
        return scope

    for module in modules:
        monkeypatch.setattr(module, "run_alert_scope", run_alert_scope)


class _Runtime:
    def __init__(self, stdout: str = "{}"):
        self.commands: list[list[str]] = []
        self.stdout = stdout

    async def __call__(self, **kwargs):
        from types import SimpleNamespace

        self.commands.append(list(kwargs["command"]))
        return SimpleNamespace(timed_out=False, exit_code=0, stdout=self.stdout, stderr="", metadata={})


async def _local_runtime(*_args, **_kwargs):
    from types import SimpleNamespace

    return SimpleNamespace(provider="local")


@pytest.fixture
def runtime(monkeypatch):
    fake = _Runtime(json.dumps({"items": []}))
    monkeypatch.setattr(kubernetes, "execute_with_runtime", fake)
    monkeypatch.setattr(kubernetes, "resolve_execution_runtime_config", _local_runtime)
    monkeypatch.setattr("app.services.execution_runtime.service.execute_with_runtime", fake)
    monkeypatch.setattr("app.services.execution_runtime.config.resolve_execution_runtime_config", _local_runtime)

    async def no_policy_block(*_args, **_kwargs):
        return None

    monkeypatch.setattr(_runtime_kubectl_tool, "_policy_block_result", no_policy_block)
    return fake


@pytest.mark.asyncio
@pytest.mark.parametrize("args", ["get pods -A", "get pods -n kube-system", "get secret db -o yaml",
                                  "describe secrets"])
async def test_run_kubectl_refuses_out_of_scope_before_anything_runs(monkeypatch, runtime, args):
    import app.tools.alert_scope as alert_scope

    _scoped(monkeypatch, SCOPE, alert_scope)
    result = await RunKubectlCommandTool().execute({"args": args}, _context())
    if "secret" in args:  # Secret reads are refused everywhere now, before the scope is consulted
        assert result["error"] == "kubectl_secret_read_refused"
    else:
        assert result["error"].endswith("_out_of_scope") and result["scope_namespace"] == "shop"
    assert runtime.commands == []


@pytest.mark.asyncio
async def test_run_kubectl_refuses_another_namespace_param_and_runs_in_the_target_namespace(monkeypatch, runtime):
    import app.tools.alert_scope as alert_scope

    _scoped(monkeypatch, SCOPE, alert_scope)
    refused = await RunKubectlCommandTool().execute({"args": "get pods", "namespace": "kube-system"}, _context())
    assert refused["error"] == NAMESPACE_OUT_OF_SCOPE and runtime.commands == []
    ran = await RunKubectlCommandTool().execute({"args": "get pods -o json"}, _context())
    assert "error" not in ran
    assert runtime.commands[-1][runtime.commands[-1].index("-n") + 1] == "shop"  # not the Workspace default


@pytest.mark.asyncio
async def test_without_a_scope_run_kubectl_behaves_as_before(monkeypatch, runtime):
    import app.tools.alert_scope as alert_scope

    _scoped(monkeypatch, None, alert_scope)
    ran = await RunKubectlCommandTool().execute({"args": "get pods -A"}, _context())
    assert "error" not in ran and runtime.commands[-1][-1] == "-A"
    secret = await RunKubectlCommandTool().execute({"args": "get secret db -n kube-system"}, _context())
    assert secret["error"] == "kubectl_secret_read_refused"  # the global Secret refusal
    assert runtime.commands[-1][-1] == "-A"  # the Secret read never ran


@pytest.mark.asyncio
async def test_the_internal_runner_refuses_out_of_scope_arguments(monkeypatch, runtime):
    _scoped(monkeypatch, SCOPE, kubernetes)
    assert await kubernetes._run_kubectl(_context(), ["get", "pods", "-A"]) == (
        1, "", KUBECTL_ALL_NAMESPACES_OUT_OF_SCOPE)
    assert await kubernetes._run_kubectl(_context(), ["get", "pods"], namespace="kube-system") == (
        1, "", NAMESPACE_OUT_OF_SCOPE)
    assert runtime.commands == []
    await kubernetes._run_kubectl(_context(), ["get", "pods"])
    assert runtime.commands[-1][runtime.commands[-1].index("-n") + 1] == "shop"


@pytest.mark.asyncio
async def test_structured_tools_default_to_the_target_namespace_and_refuse_another(monkeypatch, runtime):
    _scoped(monkeypatch, SCOPE, kubernetes)
    refused = await kubernetes.GetPodLogs().execute({"namespace": "kube-system", "pod": "coredns"}, _context())
    assert refused["error"] == NAMESPACE_OUT_OF_SCOPE
    assert (refused["evidence"]["status"], refused["evidence"]["reason"]) == ("refused", NAMESPACE_OUT_OF_SCOPE)
    other = await kubernetes.ListSecrets().execute({"namespace": "kube-system"}, _context())
    assert other["error"] == NAMESPACE_OUT_OF_SCOPE and "evidence" not in other  # not a family tool
    assert runtime.commands == []

    pods = await kubernetes.ListFailedPods().execute({}, _context())
    assert runtime.commands[-1][runtime.commands[-1].index("-n") + 1] == "shop"
    assert pods["namespace"] == "shop" and next(iter(pods)) == "evidence"
    assert pods["evidence"] | {"window": None} == {"v": 1, "family": "kubernetes", "status": "empty",
                                                   "target_id": "checkout", "namespace": "shop", "window": None,
                                                   "count": 0, "reason": ""}
    # Another connection than the target's is refused too.
    elsewhere = ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s",
                            project_config={"k8s_use_kubectl": True}, connection_id="k8s-staging")
    assert (await kubernetes.GetK8sEvents().execute({"namespace": "shop"}, elsewhere))["error"] == (
        "connection_out_of_scope")


@pytest.mark.asyncio
async def test_the_topology_snapshot_stays_in_the_target_namespace(monkeypatch, runtime):
    _scoped(monkeypatch, SCOPE, kubernetes)
    await kubernetes.KubernetesTopologySnapshotTool().execute({"all_namespaces": True}, _context())
    assert runtime.commands and all("-A" not in command for command in runtime.commands)
    assert {command[command.index("-n") + 1] for command in runtime.commands} == {"shop"}


@pytest.mark.asyncio
async def test_a_refused_call_is_not_counted_as_evidence(monkeypatch, runtime):
    _scoped(monkeypatch, SCOPE, kubernetes)
    refused = await kubernetes.GetPodLogs().execute({"namespace": "kube-system", "pod": "x"}, _context())
    records = records_of([ToolUse("get_pod_logs", False, refused)])
    outcome, detail, unresolved, statuses = evaluate_families(
        records, required=["kubernetes"], scope={"target_id": "checkout", "namespace": "shop"})
    assert (outcome, unresolved, statuses) == ("failed", False, {"kubernetes": "refused"}), detail


@pytest.mark.asyncio
async def test_without_a_scope_the_structured_tools_are_unchanged_but_carry_an_envelope(monkeypatch, runtime):
    _scoped(monkeypatch, None, kubernetes)
    result = await kubernetes.ListFailedPods().execute({"namespace": "kube-system"}, _context())
    assert result["namespace"] == "kube-system" and result["evidence"]["target_id"] is None
    assert runtime.commands[-1][runtime.commands[-1].index("-n") + 1] == "kube-system"
