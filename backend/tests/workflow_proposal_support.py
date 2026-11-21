"""Shared helpers for the test_workflow_proposal_* modules."""

from __future__ import annotations

import json
import uuid

import pytest

import app.agent.providers as providers_module
import app.services.control_plane_service as control_plane_module
from app.models import Project
from app.services.execution_profile_service import build_execution_profile
from app.services.workflow_routing.explicit_selection import resolve_workflow_selection_for_turn

# The Spring Boot upgrade seeds await four-eyes approval in a fresh database; the code
# structure diagram definition has an unrestricted tool policy, so it is change-capable.
CHANGE_WORKFLOW = "code-structure-diagram-routing"


READ_ONLY_WORKFLOW = "aws-topology-diagram-routing"


MESSAGE = "Please migrate this codebase to Spring Boot 4."


class _FakeProvider:
    """Records every proposal call and answers with the scripted content."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[list[dict]] = []

    def __call__(self, **_kwargs):
        return self

    async def chat(self, *, messages, model, temperature, max_tokens):
        self.calls.append(messages)
        return {"content": self.content, "usage": {"prompt_tokens": 40, "completion_tokens": 12}, "model": model}


def _answer(
    workflow_key: str | None, confidence: str = "high", reason: str = "Matches the request.", requested: bool = True
) -> str:
    return json.dumps({"workflow_key": workflow_key, "confidence": confidence, "requested": requested, "reason": reason})


@pytest.fixture
def proposal_model(monkeypatch):
    """Install one non-gateway runtime and a scripted fake provider for the proposal call."""

    def install(content: str, runtimes: list[dict] | None = None) -> _FakeProvider:
        provider = _FakeProvider(content)

        async def fake_runtimes(_db, runtime_target_id=None, **_kwargs):
            return runtimes if runtimes is not None else [{"provider_name": "fake", "model": "fake-model"}]

        monkeypatch.setattr(control_plane_module, "resolve_control_plane_runtimes", fake_runtimes)
        monkeypatch.setattr(providers_module, "get_provider", provider)
        return provider

    return install


async def _project(db, config: dict | None = None) -> Project:
    project = Project(id=str(uuid.uuid4()), name=f"proposal-{uuid.uuid4().hex[:8]}", config=config or {}, is_active=True)
    db.add(project)
    await db.flush()
    return project


async def _resolve(db, *, workflow_key: str = "", project_id: str | None = None) -> dict:
    return await resolve_workflow_selection_for_turn(
        db,
        workflow_key=workflow_key,
        user_message=MESSAGE,
        project_id=project_id,
    )


def _profile(resolution: dict) -> dict:
    return build_execution_profile(
        prompt=MESSAGE,
        requested_agent_type="diagnosis",
        effective_agent_type="diagnosis",
        execution_strategy="direct",
        execution_strategy_reason="strategy:test",
        routing_intent="diagnosis",
        routing_reason="intent:diagnosis_default",
        routing_intent_confidence=1.0,
        routing_intent_source="policy",
        workflow_id=str(resolution.get("workflow_id") or ""),
        workflow_contract={},
        workflow_routing_policy_resolution=resolution,
    ).to_metadata()
