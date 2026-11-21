"""Shared helpers for the shell-expansion and read-only boundary tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.services.agent_gateway.capability import capability_decision
from app.services.agent_gateway.capability_session import EffectiveCapability
from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.services.security_analyzer import builtins


def _gateway(command: str):
    return capability_decision(
        EffectiveCapability(capability_class="read_only"),
        {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/work"},
        DEFAULT_EXEC_POLICY_CONFIG,
    )


@pytest.fixture
def exec_config(monkeypatch):
    async def config(db, project_id=None):
        return DEFAULT_EXEC_POLICY_CONFIG

    monkeypatch.setattr(builtins, "get_effective_exec_policy_config", config)


def _runtime(monkeypatch):
    from app.services.execution_runtime import ExecutionRuntimeResult
    from app.tools.runtime_impl import _runtime_bash_web as module

    calls: list = []

    async def execute(**kwargs):
        calls.append((kwargs["command"], kwargs.get("shell")))
        return ExecutionRuntimeResult(exit_code=0, stdout="", stderr="", timed_out=False, metadata={})

    monkeypatch.setattr("app.services.execution_runtime.service.execute_with_runtime", execute)
    return module, calls


async def _granted_session(db, key: str, command: str) -> str:
    """A session holding an approval grant for exactly ``bash`` + ``command`` (what an approval leaves)."""
    from app.models import Session as AgentSession
    from app.models import User
    from app.services.change_preview import build_change_request_fingerprint

    user = (await db.execute(select(User))).scalars().first()
    grant = {"tool_name": "bash", "approval_id": f"appr-{key}",
             "request_fingerprint": build_change_request_fingerprint("bash", {"command": command})}
    db.add(AgentSession(id=f"r7-{key}", user_id=user.id, agent_type="chat", status="active",
                        metadata_={"approval_grants": [grant]}))
    await db.flush()
    return user.id
