"""Shell composition, platform bash, Workspace prefixes and kubeconfig contexts cannot carry a kubectl write past the read-only rule, and argv tokens stay literal."""

from __future__ import annotations

import pytest

from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.services.security_analyzer.builtins import read_only_command_finding
from app.tools.context import ToolContext
from app.tools.kubernetes_kubectl_argv import kubectl_is_read_only

# A kubectl read followed by a shell operator or a redirect is no plain kubectl read: the operator check comes
# before the kubectl branch. The helper's contract is one simple command: operators, redirects and substitutions are checked first,
# on every path (platform bash and run_cli_command strings, the agent gateway).
SHELL_COMPOSED = [
    "kubectl get pods; touch /tmp/x",
    "kubectl get pods > /tmp/x",
    "kubectl get pods >> /tmp/x",
    "kubectl get pods && kubectl delete pod x",
    "kubectl get pods || rm -rf /tmp/x",
    "kubectl get pods | tee /tmp/x",
    "kubectl get pods | sh",
    "kubectl get pods\ntouch /tmp/x",
    "kubectl get pods $(touch /tmp/x)",
    "kubectl get pods `touch /tmp/x`",
    "kubectl get pods & touch /tmp/x",
    "cat README.md; touch /tmp/x",
    "cat README.md | sh",
    "cat README.md > /tmp/x",
    "ls $(touch /tmp/x)",
    "kubectl get pods 'unbalanced",
]


@pytest.mark.parametrize("command", SHELL_COMPOSED)
def test_the_read_only_rule_checks_shell_composition_first(command):
    assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG).action != "allow"


@pytest.mark.parametrize("command", ["kubectl get pods -o json", "cat README.md", "ls -la",
                                     "kubectl get pods -l 'app in (a,b)'"])
def test_a_simple_read_command_stays_allowed(command):
    assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG).action == "allow"


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["kubectl get pods; touch /tmp/x", "kubectl get pods > /tmp/x"])
async def test_platform_bash_in_a_read_only_run_does_not_allow_a_composed_kubectl_command(monkeypatch, command):
    from app.services.security_analyzer import builtins

    async def config(db, project_id=None):
        return DEFAULT_EXEC_POLICY_CONFIG

    monkeypatch.setattr(builtins, "get_effective_exec_policy_config", config)
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s",
                          project_config={}, run_capability={"enforced": True, "class": "read_only"})

    finding = await builtins._exec_policy_analyzer("bash", command, context)

    assert finding.action != "allow"


@pytest.mark.asyncio
async def test_run_kubectl_keeps_its_own_workspace_prefix_but_not_an_agent_override(monkeypatch):
    from app.services.security_analyzer import builtins

    async def config(db, project_id=None):
        return DEFAULT_EXEC_POLICY_CONFIG

    monkeypatch.setattr(builtins, "get_effective_exec_policy_config", config)
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s",
                          project_config={}, run_capability={"enforced": True, "class": "read_only"})
    prefix = ["kubectl", "--kubeconfig", "/k", "--context", "demo", "-n", "payments"]

    allowed = await builtins._exec_policy_analyzer("run_kubectl", [*prefix, "get", "pods"], context)
    refused = await builtins._exec_policy_analyzer("run_kubectl", [*prefix, "get", "pods", "--server", "x"], context)

    assert allowed.action == "allow"
    assert refused.action != "allow"


def test_only_the_gateway_lets_a_client_name_its_own_kubeconfig_context():
    # The gateway policy requires an explicit context on a client's own kubeconfig (kubectl-requires-context).
    assert read_only_command_finding("kubectl --context=dev get pods", DEFAULT_EXEC_POLICY_CONFIG,
                                     kubectl_context_selectable=True).action == "allow"
    assert read_only_command_finding("kubectl --context dev get pods", DEFAULT_EXEC_POLICY_CONFIG).action != "allow"
    for override in ("--server=https://evil.example", "--token=t", "--kubeconfig=/tmp/x", "--as=admin", "--cluster=x"):
        command = f"kubectl --context=dev get pods {override}"
        assert read_only_command_finding(command, DEFAULT_EXEC_POLICY_CONFIG,
                                         kubectl_context_selectable=True).action != "allow", override
    assert kubectl_is_read_only(["--context", "dev", "cluster-info", "dump"], context_selectable=True) is False


@pytest.mark.asyncio
async def test_argv_tokens_are_literal_arguments_not_shell_operators(monkeypatch):
    # run_kubectl runs its argv without a shell: a ";" token is an argument, the kubectl rules judge it.
    from app.services.security_analyzer import builtins

    async def config(db, project_id=None):
        return DEFAULT_EXEC_POLICY_CONFIG

    monkeypatch.setattr(builtins, "get_effective_exec_policy_config", config)
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s",
                          project_config={}, run_capability={"enforced": True, "class": "read_only"})

    literal = await builtins._exec_policy_analyzer("run_kubectl", ["kubectl", "get", "pods", ";"], context)
    shell = await builtins._exec_policy_analyzer("bash", "kubectl get pods ;", context)

    assert literal.action == "allow"
    assert shell.action != "allow"
