"""Shared helpers for the test_pre_turn_model_call_boundary_* modules."""

from __future__ import annotations

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
import app.agent.providers as providers_module
import app.agent.providers.factory as provider_factory_module
import app.services.control_plane_service as control_plane_service
from app.agent.providers.base import BaseLLMProvider
from app.models import ControlPlaneRuntimeTarget, User
from app.services.workflow_routing.proposal_contract import proposal_system_prompt

# AWS documentation example key, assembled at runtime so static secret scanners stay quiet.
FAKE_AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"


FAKE_EMAIL = "alice" + "@example.com"


SECRET_PROMPT = f"Reply with exactly PONG-775. Context: contact {FAKE_EMAIL}, key {FAKE_AWS_KEY}"


class _ProviderRecorder:
    """Counting stand-in for the provider factory and every client it builds."""

    def __init__(self) -> None:
        self.constructions: list[dict] = []
        self.chat_calls: list[dict] = []

    def factory(self, **kwargs):
        self.constructions.append(dict(kwargs))
        recorder = self

        class _Client(BaseLLMProvider):
            # A real driver subclass: its chat passes the same content-security point every driver passes.
            async def chat(self, messages, model=None, tools=None, max_tokens=4096, **_kwargs):
                recorder.chat_calls.append({"messages": [dict(message) for message in messages], "model": model})
                return {
                    "content": "PONG-775",
                    "tool_calls": None,
                    "model": model or "",
                    "usage": {"prompt_tokens": 21, "completion_tokens": 4, "total_tokens": 25},
                }

            async def list_models(self):
                return []

            async def close(self):
                return None

        return _Client()

    def sent_text(self, call: dict) -> str:
        return "\n".join(str(message.get("content") or "") for message in call["messages"])

    def is_proposal(self, call: dict) -> bool:
        first = call["messages"][0] if call["messages"] else {}
        return str(first.get("content") or "").startswith(proposal_system_prompt())

    def proposal_calls(self) -> list[dict]:
        return [call for call in self.chat_calls if self.is_proposal(call)]

    def turn_calls(self) -> list[dict]:
        return [call for call in self.chat_calls if not self.is_proposal(call)]


class _RuntimeResolutionCounter:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        return await self.delegate(*args, **kwargs)


@pytest.fixture
def provider_recorder(monkeypatch) -> _ProviderRecorder:
    recorder = _ProviderRecorder()
    # Every provider construction path: the package export (late imports), the factory
    # module, and the engine's module-level binding used by the runtime fallback.
    monkeypatch.setattr(providers_module, "get_provider", recorder.factory)
    monkeypatch.setattr(provider_factory_module, "get_provider", recorder.factory)
    monkeypatch.setattr(engine_module, "get_provider", recorder.factory)
    return recorder


@pytest.fixture
def runtime_resolutions(monkeypatch) -> _RuntimeResolutionCounter:
    # Every resolve_control_plane_runtimes call, however it was imported, ends here.
    counter = _RuntimeResolutionCounter(control_plane_service._resolve_control_plane_runtimes_impl)
    monkeypatch.setattr(control_plane_service, "_resolve_control_plane_runtimes_impl", counter)
    return counter


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _first_active_target(db) -> ControlPlaneRuntimeTarget:
    target = (
        await db.execute(
            select(ControlPlaneRuntimeTarget)
            .where(ControlPlaneRuntimeTarget.is_active.is_(True))
            .order_by(ControlPlaneRuntimeTarget.priority)
        )
    ).scalars().first()
    assert target is not None
    return target
