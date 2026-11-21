"""A governed research context guard runs before each actual provider and retry."""

import pytest

import app.agent.engine.runtime._engine_runtime_fallback as fallback_module
from app.agent.core.runtime.runtime_errors import ProviderRuntimeError
from app.agent.engine.pre_dispatch._research_evidence_context import ResearchEvidenceContextError
from app.agent.engine.runtime._engine_runtime_fallback import _chat_with_runtime_fallback
from tests.test_runtime_error_taxonomy import _FakeClient, _runtimes


@pytest.mark.asyncio
async def test_context_refusal_never_constructs_a_provider_or_tries_another_runtime():
    spawned = []

    def factory(**kwargs):
        spawned.append(kwargs)
        pytest.fail("context refusal must precede provider initialization")

    def guard(runtime, messages):
        raise ResearchEvidenceContextError("research_context_capacity_unavailable")

    with pytest.raises(ResearchEvidenceContextError) as error:
        await _chat_with_runtime_fallback(_runtimes(), messages=[{"role": "user", "content": "Research."}],
                                          tools=[], get_provider_func=factory, context_guard=guard)
    assert spawned == [] and error.value.runtime_attempts == []


@pytest.mark.asyncio
async def test_unused_unknown_fallback_does_not_block_known_primary_but_reached_unknown_does():
    spawned = []
    succeeds = True

    def factory(**kwargs):
        spawned.append(kwargs["provider_name"])
        return _FakeClient(lambda: {"content": "ok", "tool_calls": []} if succeeds else
                           ProviderRuntimeError("primary failed", error_class="permanent"))

    def guard(runtime, messages):
        if runtime["provider_name"] != "primary":
            raise ResearchEvidenceContextError("research_context_capacity_unavailable")

    args = dict(messages=[{"role": "user", "content": "Research."}], tools=[],
                get_provider_func=factory, context_guard=guard)
    reply, served, _ = await _chat_with_runtime_fallback(_runtimes(), **args)
    assert reply["content"] == "ok" and served["provider_name"] == "primary" and spawned == ["primary"]
    succeeds = False
    with pytest.raises(ResearchEvidenceContextError) as error:
        await _chat_with_runtime_fallback(_runtimes(), **args)
    assert spawned == ["primary", "primary"]  # Never initializes the unknown-capacity secondary.
    assert error.value.runtime_attempts[-1]["status"] == "error"


@pytest.mark.asyncio
async def test_context_pressure_retry_cannot_remove_the_protected_working_set(monkeypatch):
    calls = []
    original = [{"role": "user", "content": "Research."}, {"role": "assistant", "content": "protected source"}]

    def factory(**kwargs):
        calls.append(kwargs["provider_name"])
        return _FakeClient(lambda: ProviderRuntimeError("too much context", error_class="context_pressure"))

    def guard(runtime, messages):
        if messages != original:
            raise ResearchEvidenceContextError("current_read_pair_changed")

    monkeypatch.setattr(fallback_module, "_context_pressure_retry_messages", lambda messages: messages[:1])
    runtime = {**_runtimes()[0], "max_context_retries": 1}
    with pytest.raises(ResearchEvidenceContextError):
        await _chat_with_runtime_fallback([runtime], messages=original, tools=[], max_tokens=2048,
                                          get_provider_func=factory, context_guard=guard)
    assert calls == ["primary"]
