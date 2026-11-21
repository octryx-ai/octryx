"""Fake kubectl runtime, tool contexts, diagnosis and gateway decision helpers shared by the security acceptance tests."""

from __future__ import annotations

import pytest

from app.services.agent_gateway.capability import capability_decision
from app.services.agent_gateway.capability_session import EffectiveCapability
from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.services.execution_runtime import ExecutionRuntimeConfig, ExecutionRuntimeResult
from app.tools import kubernetes
from app.tools.context import ToolContext


class _Runtime:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    async def execute(self, **kwargs) -> ExecutionRuntimeResult:
        self.commands.append(list(kwargs["command"]))
        return ExecutionRuntimeResult(exit_code=0, stdout="{}", stderr="", timed_out=False, metadata={})


async def _host_config(db, *, project_config=None):
    return ExecutionRuntimeConfig()


@pytest.fixture
def runtime(monkeypatch):
    fake = _Runtime()
    monkeypatch.setattr(kubernetes, "execute_with_runtime", fake.execute)
    monkeypatch.setattr(kubernetes, "resolve_execution_runtime_config", _host_config)
    monkeypatch.setattr("app.services.execution_runtime.service.execute_with_runtime", fake.execute)
    monkeypatch.setattr("app.services.execution_runtime.config.resolve_execution_runtime_config", _host_config)
    return fake


def _context(**overrides) -> ToolContext:
    values = {
        "user_id": "u", "project_ids": [], "roles": ["viewer"], "session_id": "s",
        "project_config": {"k8s_use_kubectl": True, "kubeconfig_path": "/srv/kube/config", "k8s_context": "demo"},
    }
    values.update(overrides)
    return ToolContext(**values)


async def _diagnosis_report(monkeypatch, tool_name, command):
    from app.services.security_analyzer import builtins
    from app.services.security_analyzer.service import analyze_security_risk

    async def config(db, project_id=None):
        return DEFAULT_EXEC_POLICY_CONFIG

    monkeypatch.setattr(builtins, "get_effective_exec_policy_config", config)
    return await analyze_security_risk(tool_name, command, _context(run_capability={"enforced": True, "class": "read_only"}))


def _gateway(command: str):
    return capability_decision(
        EffectiveCapability(capability_class="read_only"),
        {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/work"},
        DEFAULT_EXEC_POLICY_CONFIG,
    )
