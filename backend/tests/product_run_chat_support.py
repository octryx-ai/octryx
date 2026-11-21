"""Product runs of chat turns: a scripted provider (no network) and a deterministic single tool.

``world`` is the fixture; a test module imports it by name.
"""

from __future__ import annotations

from typing import Any

import pytest

import app.agent.engine as engine_module
import app.agent.providers as providers_module
from app.tools.definitions import get_all_definitions
from app.tools.registry import TOOL_REGISTRY

TOOL = "get_current_time"


@pytest.fixture
def world(monkeypatch):
    """A scripted provider (no network) and a deterministic single tool, as in the harness parity proof."""

    async def fixed_time(params, context):
        return {"utc_time_iso": "2026-09-30T00:00:00+00:00", "timezone_name": "UTC"}

    monkeypatch.setattr(TOOL_REGISTRY[TOOL], "execute", fixed_time)
    state: dict[str, Any] = {"project_config": {}, "script": [], "calls": 0}
    original_prepare = engine_module._prepare_agent_run

    async def prepare(**kwargs):
        prepared = await original_prepare(**kwargs)
        prepared.tool_definitions = [get_all_definitions()[TOOL]]
        prepared.tool_context.project_config = {
            **(prepared.tool_context.project_config or {}),
            **state["project_config"],
        }
        return prepared

    def provider_factory(**_kwargs):
        class _ScriptedProvider:
            async def chat(self, messages, model=None, tools=None, **_ignored):
                state["calls"] += 1
                step = state["script"].pop(0)
                if isinstance(step, BaseException):
                    raise step
                if callable(step):
                    return await step()
                return {**step, "model": model or ""}

            async def close(self):
                return None

        return _ScriptedProvider()

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare)
    monkeypatch.setattr(providers_module, "get_provider", provider_factory)
    monkeypatch.setattr(engine_module, "get_provider", provider_factory)
    return state
