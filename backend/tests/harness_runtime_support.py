"""The harness parity world: a deterministic tool, the governed closure and a scripted provider."""

from __future__ import annotations

from typing import Any

import pytest

import app.agent.engine as engine_module
import app.agent.providers as providers_module
from app.tools.definitions import get_all_definitions
from app.tools.registry import TOOL_REGISTRY

TOOL = "get_current_time"


@pytest.fixture
def fake_world(monkeypatch):
    """Deterministic tool, injected governed closure and a scripted provider."""

    async def fixed_time(params, context):
        return {"utc_time_iso": "2026-09-30T00:00:00+00:00", "timezone_name": "UTC"}

    monkeypatch.setattr(TOOL_REGISTRY[TOOL], "execute", fixed_time)
    world: dict[str, Any] = {"project_config": {}, "script": [], "calls": []}
    original_prepare = engine_module._prepare_agent_run

    async def prepare_with_governed_closure(**kwargs):
        prepared = await original_prepare(**kwargs)
        prepared.tool_definitions = [get_all_definitions()[TOOL]]
        prepared.tool_context.project_config = {**(prepared.tool_context.project_config or {}), **world["project_config"]}
        return prepared

    def provider_factory(**_kwargs):
        class _ScriptedProvider:
            async def chat(self, messages, model=None, tools=None, **_ignored):
                world["calls"].append({"messages": [dict(message) for message in messages], "tools": tools})
                step = world["script"].pop(0)
                if isinstance(step, Exception):
                    raise step
                return {**step, "model": model or ""}

            async def close(self):
                return None

        return _ScriptedProvider()

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare_with_governed_closure)
    monkeypatch.setattr(providers_module, "get_provider", provider_factory)
    monkeypatch.setattr(engine_module, "get_provider", provider_factory)
    return world
