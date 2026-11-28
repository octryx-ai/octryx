"""Contract: a failed knowledge LLM chain re-raises a typed error with code and class only (X6)."""

from __future__ import annotations

import logging

import pytest

from app.services.knowledge_graph import KnowledgeLLMRuntimeFailedError, build_generate_fn

FAKE_TOKEN = "ghp_X6" + "fakeTokenAbcdefghijklmnopqrstuvwxyz0123"
CREDENTIALED_URL = "https://user:tok3n@host/x.git"
INTERNAL_PATH = "/srv/internal/x6-secret-path"
PROVIDER_TEXT = f"upstream said: {CREDENTIALED_URL} {FAKE_TOKEN} {INTERNAL_PATH}"


class ProviderBoomError(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_all_runtimes_failing_raise_closed_facts_with_the_provider_error_as_cause(db, monkeypatch, caplog):
    async def fake_resolve(_db, **_kwargs):
        return [
            {"provider_name": "stub-a", "model": "m-a", "driver": "stub", "use_case_tags": ["extract"]},
            {"provider_name": "stub-b", "model": "m-b", "driver": "stub", "use_case_tags": ["extract"]},
        ]

    class _FailingClient:
        async def chat(self, **_kwargs):
            raise ProviderBoomError(PROVIDER_TEXT)

        async def close(self):
            return None

    import app.services.control_plane_service as cps
    from app.agent import providers as agent_providers

    monkeypatch.setattr(cps, "resolve_control_plane_runtimes", fake_resolve)
    monkeypatch.setattr(agent_providers, "get_provider", lambda **_kwargs: _FailingClient())

    generate = await build_generate_fn(db, project_ids="kg-x6-workspace", role="extract")
    with caplog.at_level(logging.DEBUG), pytest.raises(KnowledgeLLMRuntimeFailedError) as raised:
        await generate("hello")

    error = raised.value
    assert str(error) == "knowledge_runtime_failed role=extract attempts=2 error_type=ProviderBoomError"
    assert (error.error_code, error.error_type, error.attempts) == ("knowledge_runtime_failed", "ProviderBoomError", 2)
    assert isinstance(error.__cause__, ProviderBoomError)
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "error_type=ProviderBoomError" in logged
    for marker in (FAKE_TOKEN, "tok3n", CREDENTIALED_URL, INTERNAL_PATH, "upstream said"):
        assert marker not in str(error)
        assert marker not in repr(error.args)
        assert marker not in logged
