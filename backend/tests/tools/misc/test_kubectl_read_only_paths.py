"""No read-only kubectl path can change the cluster: one closed read-verb table
(``tools/kubernetes_kubectl_argv.py``) decides on every path."""

from __future__ import annotations

import pytest

from app.services.classification_tool_policy import tool_writes
from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.services.security_analyzer.builtins import read_only_command_finding
from app.tools import kubernetes
from app.tools.context import ToolContext
from app.tools.kubernetes_kubectl_argv import (
    KUBECTL_SUBCOMMAND_FORBIDDEN,
    kubectl_is_read_only,
    kubectl_subcommand_refusal,
)
from app.tools.runtime_impl._runtime_kubectl_tool import RunKubectlCommandTool, _validate_kubectl_args

WRITE_ARGS = [
    ["apply", "-f", "x.yaml"],
    ["edit", "deploy/api"],
    ["label", "pod", "api-0", "x=y"],
    ["annotate", "pod", "api-0", "x=y"],
    ["patch", "deploy/api", "-p", "{}"],
    ["delete", "pod", "api-0"],
    ["scale", "deploy/api", "--replicas", "0"],
    ["autoscale", "deploy/api", "--max", "3"],
    ["rollout", "restart", "deploy/api"],
    ["rollout", "undo", "deploy/api"],
    ["create", "ns", "x"],
    ["replace", "-f", "x.yaml"],
    ["set", "image", "deploy/api", "api=evil"],
    ["expose", "deploy/api"],
    ["run", "x", "--image", "busybox"],
    ["cordon", "node-1"],
    ["uncordon", "node-1"],
    ["drain", "node-1"],
    ["taint", "nodes", "node-1", "k=v:NoSchedule"],
    ["exec", "api-0", "--", "sh"],
    ["attach", "api-0"],
    ["cp", "api-0:/etc/passwd", "."],
    ["port-forward", "api-0", "8080"],
    ["proxy"],
    ["debug", "api-0"],
    ["certificate", "approve", "csr-1"],
    ["auth", "reconcile", "-f", "rbac.yaml"],
    ["config", "use-context", "prod"],
    ["config", "view", "--raw"],
    ["cluster-info", "dump", "--output-directory", "/tmp/x"],
    ["diff", "-f", "x.yaml"],
    ["plugin", "list"],
    ["kustomize", "."],
    ["-n", "payments", "delete", "pod", "api-0"],
    [],
]


READ_ARGS = [
    ["get", "pods", "-o", "json"],
    ["describe", "pod", "api-0"],
    ["logs", "api-0", "--tail", "50"],
    ["top", "pods"],
    ["events", "--for", "pod/api-0"],
    ["explain", "deployment.spec"],
    ["api-resources"],
    ["api-versions"],
    ["version", "-o", "json"],
    ["cluster-info"],
    ["auth", "can-i", "list", "pods"],
    ["auth", "whoami"],
]


# Persistent flags may stand between subcommands, so the subcommand path is
# resolved past every flag and the decision falls on the resolved leaf.
FLAG_POSITION_WRITES = [
    ["cluster-info", "--namespace=default", "dump", "--output-directory=/tmp/x"],
    ["cluster-info", "--namespace", "default", "dump", "--output-directory=/tmp/x"],
    ["cluster-info", "-n", "default", "dump"],
    ["cluster-info", "-ndefault", "dump"],
    ["cluster-info", "--request-timeout", "5s", "dump"],
    ["cluster-info", "-v", "6", "dump"],
    ["cluster-info", "--v=6", "dump"],
    ["cluster-info", "--match-server-version", "dump"],
    ["cluster-info", "--unknown-flag", "dump"],
    ["auth", "--namespace", "default", "reconcile", "-f", "rbac.yaml"],
    ["auth", "-n", "x", "reconcile"],
    ["auth", "--unknown", "can-i"],
    ["--namespace", "default", "delete", "pod", "x"],
    ["--namespace=default", "cluster-info", "dump"],
    ["-v", "6", "apply", "-f", "x.yaml"],
    ["--unknown-flag", "get", "pods"],
]


LEAF_READS_WITH_FLAGS = [
    ["cluster-info", "--namespace", "default"],
    ["cluster-info", "--request-timeout=5s"],
    ["auth", "--namespace", "default", "can-i", "list", "pods"],
    ["auth", "-n=x", "whoami", "-o", "json"],
    ["get", "--namespace", "default", "dump"],  # ``get`` has no subcommands: ``dump`` is a resource name
    ["logs", "api-0", "--tail", "50", "-c", "api"],
    ["top", "pod", "--containers"],
    ["--namespace", "default", "get", "pods"],
    ["-v=6", "describe", "pod", "api-0"],
]


CONNECTION_OVERRIDES = [
    ["get", "pods", "--server", "https://evil.example"],
    ["get", "pods", "--server=https://evil.example"],
    ["get", "pods", "-s", "https://evil.example"],
    ["get", "pods", "-shttps://evil.example"],
    ["get", "pods", "--token", "t"],
    ["get", "pods", "--kubeconfig=/tmp/other"],
    ["get", "pods", "--as", "system:admin"],
    ["get", "pods", "--as-group=system:masters"],
    ["get", "pods", "--as-uid", "0"],
    ["get", "pods", "--certificate-authority", "/tmp/ca"],
    ["get", "pods", "--client-certificate=/tmp/c"],
    ["get", "pods", "--client-key", "/tmp/k"],
    ["get", "pods", "--insecure-skip-tls-verify"],
    ["get", "pods", "--insecure-skip-tls-verify=true"],
    ["get", "pods", "--context", "prod"],
    ["get", "pods", "--cluster=prod"],
    ["get", "pods", "--user", "admin"],
    ["get", "pods", "--username=admin"],
    ["get", "pods", "--password", "p"],
    ["get", "pods", "--tls-server-name", "x"],
    ["--context", "prod", "get", "pods"],
    ["get", "pods", "--profile=cpu", "--profile-output=/tmp/x"],
    ["get", "pods", "--cache-dir", "/tmp/x"],
]


@pytest.mark.parametrize("args", WRITE_ARGS, ids=lambda args: " ".join(args) or "empty")
def test_write_and_unknown_kubectl_commands_are_never_read_only(args):
    assert kubectl_is_read_only(args) is False
    assert kubectl_subcommand_refusal(args) is not None
    ok, _ = _validate_kubectl_args(args)
    assert ok is False
    if args:
        assert tool_writes("run_kubectl", {"args": args}) is True


@pytest.mark.parametrize("args", READ_ARGS, ids=" ".join)
def test_read_kubectl_commands_pass_every_path(args):
    assert kubectl_is_read_only(args) is True
    assert kubectl_subcommand_refusal(args) is None
    assert _validate_kubectl_args(args) == (True, "")
    assert tool_writes("run_kubectl", {"args": args}) is False
    finding = read_only_command_finding("kubectl " + " ".join(args), DEFAULT_EXEC_POLICY_CONFIG)
    assert finding.action == "allow", finding.reason


@pytest.mark.parametrize(
    "command",
    [
        "kubectl config use-context prod",
        "kubectl config view --raw",
        "kubectl --context prod delete pod api-0",
        "kubectl auth reconcile -f rbac.yaml",
        "kubectl cluster-info dump --output-directory /tmp/x",
    ],
)
def test_the_read_only_command_rule_refuses_kubectl_writes(command):
    config = {**DEFAULT_EXEC_POLICY_CONFIG, "diagnosis_kubectl_verbs": [
        *DEFAULT_EXEC_POLICY_CONFIG["diagnosis_kubectl_verbs"], "auth", "cluster-info",
    ]}

    assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG).action != "allow"
    assert read_only_command_finding(command, config).action != "allow"


def test_a_configured_write_verb_cannot_widen_the_read_only_rule():
    config = {**DEFAULT_EXEC_POLICY_CONFIG, "diagnosis_kubectl_verbs": ["get", "delete", "apply", "scale"]}

    assert read_only_command_finding("kubectl get pods", config).action == "allow"
    for command in ("kubectl delete pod x", "kubectl apply -f x.yaml", "kubectl scale deploy/x --replicas 0"):
        assert read_only_command_finding(command, config).action != "allow", command


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [["apply", "-f", "x.yaml"], ["edit", "deploy/api"], ["label", "pod", "a", "x=y"]])
async def test_internal_kubectl_runner_refuses_writes_before_anything_runs(monkeypatch, args):
    calls = []

    async def execute(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(kubernetes, "execute_with_runtime", execute)
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s",
                          project_config={"k8s_use_kubectl": True})

    assert await kubernetes._run_kubectl(context, args) == (1, "", KUBECTL_SUBCOMMAND_FORBIDDEN)
    assert calls == []


@pytest.mark.asyncio
async def test_run_kubectl_tool_refuses_a_write_before_anything_runs(monkeypatch):
    calls = []

    async def execute(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("app.services.execution_runtime.service.execute_with_runtime", execute)
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s", project_config={})

    result = await RunKubectlCommandTool().execute({"args": "label pod api-0 x=y"}, context)

    assert "error" in result
    assert calls == []


@pytest.mark.parametrize("args", FLAG_POSITION_WRITES, ids=" ".join)
def test_flags_between_subcommands_do_not_hide_a_write(args):
    assert kubectl_is_read_only(args) is False
    assert _validate_kubectl_args(args)[0] is False
    assert tool_writes("run_kubectl", {"args": args}) is True
    command = "kubectl " + " ".join(args)
    configured = {**DEFAULT_EXEC_POLICY_CONFIG, "diagnosis_kubectl_verbs": ["get", "auth", "cluster-info", "delete"]}
    assert read_only_command_finding(command, configured).action != "allow"


@pytest.mark.parametrize("args", LEAF_READS_WITH_FLAGS, ids=" ".join)
def test_leaf_reads_with_flags_stay_allowed(args):
    assert kubectl_is_read_only(args) is True
    assert _validate_kubectl_args(args) == (True, "")
    assert read_only_command_finding("kubectl " + " ".join(args), DEFAULT_EXEC_POLICY_CONFIG).action == "allow"


@pytest.mark.parametrize("args", CONNECTION_OVERRIDES, ids=" ".join)
def test_connection_override_flags_are_refused_in_read_only_contexts(args):
    assert kubectl_is_read_only(args) is False
    assert _validate_kubectl_args(args)[0] is False
    assert tool_writes("run_kubectl", {"args": args}) is True
    assert read_only_command_finding("kubectl " + " ".join(args), DEFAULT_EXEC_POLICY_CONFIG).action != "allow"


def test_the_internal_runner_keeps_the_subcommand_first_contract():
    # The Kubernetes tools place the namespace themselves: a leading flag is never theirs.
    assert kubectl_subcommand_refusal(["--namespace", "default", "get", "pods"]) == KUBECTL_SUBCOMMAND_FORBIDDEN
    assert kubectl_subcommand_refusal(["get", "pods", "-o", "json"]) is None
