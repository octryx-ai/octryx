"""The llm_risk analyzer passes the sampling choice to its client."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.security_analyzer import llm_risk
from app.tools.context import ToolContext


class _Db:
    def __init__(self, provider, temperatures: dict[str, float]) -> None:
        self.provider = provider
        self.temperatures = temperatures

    async def get(self, _model, _id):
        return self.provider

    async def execute(self, statement):
        params = statement.compile().params
        model_id = next(value for key, value in params.items() if key.startswith("model_id"))
        row = SimpleNamespace(temperature=self.temperatures[model_id]) if model_id in self.temperatures else None
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: row))


class _Client:
    async def chat(self, **_kwargs):
        return {"content": '{"score": 1, "recommended_action": "allow", "risk_level": "low", "reason": "ok"}'}

    async def close(self) -> None:
        return None


@pytest.fixture
def captured(monkeypatch):
    seen: dict = {}

    async def defaults(_db):
        return None

    async def targets(_db, _config, active_only):
        return [seen["target"]]

    async def client_kwargs(_db, _provider):
        return {"provider_name": "bedrock", "region": "region-1"}

    async def admit(_db, runtime, **_kwargs):
        return SimpleNamespace(allowed=True, first_dispatchable_runtime=lambda: dict(runtime))

    async def prompts(_db, workspace_id):
        return SimpleNamespace(render=lambda *_args, **_kwargs: "prompt")

    def provider(**kwargs):
        seen["kwargs"] = kwargs
        return _Client()

    monkeypatch.setattr(llm_risk, "ensure_control_plane_defaults", defaults)
    monkeypatch.setattr(llm_risk, "get_runtime_targets", targets)
    monkeypatch.setattr(llm_risk, "build_provider_client_kwargs_async", client_kwargs)
    monkeypatch.setattr(llm_risk, "admit_client_kwargs_for_dispatch", admit)
    monkeypatch.setattr(llm_risk, "prompt_set_for", prompts)
    monkeypatch.setattr(llm_risk, "get_provider", provider)
    return seen


async def _run(seen: dict, target, project_config: dict | None = None,
               temperatures: dict[str, float] | None = None) -> dict:
    seen["target"] = target
    provider = SimpleNamespace(id="p1", name="bedrock", display_name="Bedrock")
    context = ToolContext(user_id="u", project_ids=["w1"], roles=["viewer"], session_id="s",
                          project_config={"project_id": "w1", **(project_config or {})},
                          db=_Db(provider, temperatures or {}))
    await llm_risk._run_llm_risk_model("bash", "ls", context, runtime_settings={})
    return seen["kwargs"]


def _target(*, accepts_temperature: bool | None):
    return SimpleNamespace(provider_id="p1", model_id="model-a", accepts_temperature=accepts_temperature)


async def test_never_send_reaches_the_client(captured) -> None:
    kwargs = await _run(captured, _target(accepts_temperature=False))
    assert kwargs["accepts_temperature"] is False
    assert kwargs["target_temperature"] is None


async def test_the_models_catalog_value_reaches_the_client(captured) -> None:
    kwargs = await _run(captured, _target(accepts_temperature=None), temperatures={"model-a": 0.7})
    assert kwargs["target_temperature"] == 0.7
    assert kwargs["accepts_temperature"] is None


async def test_another_security_review_model_takes_its_own_catalog_value_not_the_targets_choice(captured) -> None:
    kwargs = await _run(captured, _target(accepts_temperature=False), {"security_review_model": "model-b"},
                        temperatures={"model-a": 0.7, "model-b": 0.2})
    assert kwargs["accepts_temperature"] is None and kwargs["target_temperature"] == 0.2
