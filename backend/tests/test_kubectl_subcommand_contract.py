"""The kubectl path of the Kubernetes tools: subcommand first, namespace as an option, deny by default.

The fake runner replaces the execution runtime, so the real ``_run_kubectl`` builds the argv and
applies the allow-list with the first argument as the subcommand; the namespace follows as an option.
"""

from __future__ import annotations

import json

import pytest

from app.services.execution_runtime import ExecutionRuntimeConfig, ExecutionRuntimeResult
from app.tools import kubernetes
from app.tools.context import ToolContext
from app.tools.kubernetes import GetK8sEvents, GetPodLogs, ListPods
from app.tools.kubernetes_kubectl_argv import (
    KUBECTL_SUBCOMMAND_FORBIDDEN,
    KUBECTL_SUBCOMMAND_MISSING,
    kubectl_subcommand_refusal,
)

_EVENTS = {
    "items": [
        {
            "type": "Warning",
            "reason": "BackOff",
            "message": "Back-off restarting failed container",
            "involvedObject": {"name": "api-0"},
            "count": 4,
        }
    ]
}


class _FakeKubectl:
    """Records every argv the runtime would execute and answers with a fixed stdout."""

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.commands: list[list[str]] = []

    async def execute(self, **kwargs) -> ExecutionRuntimeResult:
        self.commands.append(list(kwargs["command"]))
        return ExecutionRuntimeResult(exit_code=0, stdout=self.stdout, stderr="", timed_out=False, metadata={})


@pytest.fixture
def fake_kubectl(monkeypatch):
    def install(stdout: str) -> _FakeKubectl:
        fake = _FakeKubectl(stdout)

        async def resolve_config(db, *, project_config=None):
            return ExecutionRuntimeConfig()

        monkeypatch.setattr(kubernetes, "resolve_execution_runtime_config", resolve_config)
        monkeypatch.setattr(kubernetes, "execute_with_runtime", fake.execute)
        return fake

    return install


def _context(**project_config) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["viewer"],
        session_id="session-1",
        project_config={"k8s_use_kubectl": True, "k8s_context": "demo", **project_config},
    )


def _after_global_options(command: list[str]) -> list[str]:
    """The argv after ``kubectl [--kubeconfig K] [--context C] [-n NS]``."""
    index = 1
    while index < len(command) and command[index] in {"--kubeconfig", "--context", "-n"}:
        index += 2
    return command[index:]


@pytest.mark.asyncio
async def test_get_k8s_events_runs_on_the_kubectl_path(fake_kubectl):
    fake = fake_kubectl(json.dumps(_EVENTS))

    result = await GetK8sEvents().execute({"namespace": "payments", "pod": "api-0"}, _context())

    assert result["source"] == "kubectl"
    assert result["total_events"] == 1
    assert result["events"][0]["reason"] == "BackOff"
    (command,) = fake.commands
    assert command[:5] == ["kubectl", "--context", "demo", "-n", "payments"]
    assert _after_global_options(command) == [
        "get", "events", "-o", "json", "--field-selector", "involvedObject.name=api-0",
    ]


@pytest.mark.asyncio
async def test_get_pod_logs_runs_on_the_kubectl_path(fake_kubectl):
    fake = fake_kubectl("GET /ready 200\n")

    result = await GetPodLogs().execute(
        {"namespace": "payments", "pod": "api-0", "container": "api", "tail_lines": 50}, _context()
    )

    assert result["source"] == "kubectl"
    assert result["logs"] == "GET /ready 200\n"
    (command,) = fake.commands
    assert command[:5] == ["kubectl", "--context", "demo", "-n", "payments"]
    assert _after_global_options(command) == ["logs", "api-0", "--tail", "50", "-c", "api"]


@pytest.mark.asyncio
async def test_tool_namespace_replaces_the_project_default_namespace(fake_kubectl):
    fake = fake_kubectl(json.dumps({"items": []}))

    result = await ListPods().execute({"namespace": "payments"}, _context(k8s_namespace="default"))

    assert result["source"] == "kubectl"
    (command,) = fake.commands
    assert command.count("-n") == 1
    assert command[command.index("-n") + 1] == "payments"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("args", "code"),
    [
        (["exec", "api-0", "--", "sh"], KUBECTL_SUBCOMMAND_FORBIDDEN),
        (["delete", "pod", "api-0"], KUBECTL_SUBCOMMAND_FORBIDDEN),
        (["-n", "payments", "get", "pods"], KUBECTL_SUBCOMMAND_FORBIDDEN),
        (["--kubeconfig", "/tmp/other", "get", "pods"], KUBECTL_SUBCOMMAND_FORBIDDEN),
        ([], KUBECTL_SUBCOMMAND_MISSING),
    ],
)
async def test_disallowed_subcommand_is_refused_before_anything_runs(fake_kubectl, args, code):
    fake = fake_kubectl("")

    returncode, stdout, stderr = await kubernetes._run_kubectl(_context(), args)

    assert (returncode, stdout, stderr) == (1, "", code)
    assert fake.commands == []
    assert kubectl_subcommand_refusal(args) == code


def test_allowed_subcommands_pass_the_check():
    for args in (["get", "pods"], ["logs", "api-0"], ["version", "-o", "json"]):
        assert kubectl_subcommand_refusal(args) is None
