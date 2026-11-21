"""What a refused dispatch owner actually surfaces, and what it still passes.

Two properties that admission propagation can silently get wrong:

- **the refusal survives.** A typed, bounded denial has to reach the owner's own
  result — a spoken CallAgent answer, a knowledge tool payload, a session row, a
  pre-turn HTTP detail — instead of being flattened into a generic failure. And it
  must not be lost when something *else* fails afterwards.
- **nothing else changes.** The admission argument is an alias decision, not a
  constructor field, so a non-gateway driver is built from its own kwargs only.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.model_gateway.dispatch_admission_surfaces_support import _ForbiddenProviderFactory, _mixed_chain, _project

from .conftest import ALIAS, gateway_runtime


class _FailingClient:
    async def chat(self, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("upstream timeout")

    async def close(self) -> None:
        return None


async def _gateway_chain() -> list[dict[str, Any]]:
    return [gateway_runtime()]


# --- the refusal survives ----------------------------------------------------


async def test_call_agent_run_keeps_the_typed_denial_instead_of_a_generic_apology(
    db: AsyncSession, monkeypatch
):
    from app.models import LLMProvider
    from app.services import control_plane_service
    from app.services.call_agent.service import ADMISSION_DENIED_ERROR, CallAgentService

    project = await _project(db, policy={})
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="litellm",
        provider_family="litellm",
        driver="litellm_gateway",
        runtime_kind="api",
        auth_mode="api_key",
        is_active=True,
        endpoint_url="https://litellm.internal.test/v1",
        config_json={"litellm_gateway": {}},
    )
    db.add(provider)
    await db.flush()

    async def _targets(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [SimpleNamespace(provider_id=provider.id, model_id=ALIAS)]

    async def _client_kwargs(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"provider_name": "litellm", "driver": "litellm_gateway"}

    monkeypatch.setattr(control_plane_service, "get_runtime_targets", _targets)
    monkeypatch.setattr(control_plane_service, "build_provider_client_kwargs_async", _client_kwargs)
    monkeypatch.setattr("app.agent.providers.get_provider", _ForbiddenProviderFactory())
    service = CallAgentService(
        db,
        SimpleNamespace(
            id="call-agent-1",
            project_id=project.id,
            llm_model=ALIAS,
            enabled_tools=[],
            system_prompt="",
            thinking_message=None,
            max_tool_calls=0,
        ),
    )

    response = await service.run("what is the status")

    assert response.error == ADMISSION_DENIED_ERROR
    assert response.admission["dispatch_owner"] == "call_agent"
    assert response.admission["dispatched"] is False
    assert "an error occurred" not in response.final_response


async def test_the_pre_turn_denial_is_not_lost_behind_a_later_provider_failure():
    from app.web._helpers.chat_turn_start import _pre_turn_dispatch_failure

    denial = {"status": "denied", "dispatch_owner": "chat_turn_task_extraction", "dispatched": False}

    only_denied = _pre_turn_dispatch_failure(denial, None)
    assert only_denied.status_code == 409
    assert only_denied.detail["runtime_failure"] is False

    # A second candidate failed for a provider reason. The policy refusal stays
    # in the payload.
    also_failed = _pre_turn_dispatch_failure(denial, RuntimeError("upstream timeout"))
    assert also_failed.status_code == 502
    assert also_failed.detail["dispatch_owner"] == "chat_turn_task_extraction"
    assert also_failed.detail["runtime_failure"] is True

    # Provider-only errors return a plain-text detail.
    plain = _pre_turn_dispatch_failure(None, RuntimeError("upstream timeout"))
    assert plain.status_code == 502
    assert isinstance(plain.detail, str)


async def test_knowledge_retrieval_keeps_the_graph_denial_as_a_typed_payload(
    db: AsyncSession, monkeypatch
):
    """``global_answer_error`` keeps the typed refusal, never a free-text string."""

    from app.services import control_plane_service
    from app.tools.context import ToolContext
    from app.tools.knowledge_impl._knowledge_retrieve import KnowledgeRetrieveTool

    project = await _project(db, policy={})
    monkeypatch.setattr(
        control_plane_service, "resolve_control_plane_runtimes", lambda _db, **_kwargs: _gateway_chain()
    )
    monkeypatch.setattr("app.agent.providers.get_provider", _ForbiddenProviderFactory())
    context = ToolContext(
        user_id="u1",
        project_ids=[project.id],
        roles=[],
        session_id="s1",
        project_config={"project_id": project.id},
        db=db,
    )

    result = await KnowledgeRetrieveTool().execute(
        {"project_id": project.id, "query": "how does deployment work", "mode": "global"}, context
    )

    admission = result["global_answer_admission"]
    assert admission["dispatch_owner"] == "knowledge_graph_runtime"
    assert admission["dispatched"] is False
    # The closed-vocabulary label, not an exception repr.
    assert result["global_answer_error"] == f"{admission['status']}:{admission['admission_reason']}"


async def test_a_partial_refusal_is_not_lost_when_the_admitted_runtime_fails(
    db: AsyncSession, monkeypatch
):
    """One gateway target refused, the fallback dispatched and failed.

    The chain error has to carry the refusal too; otherwise an operator reading
    "all runtimes failed" cannot see that one of them was a policy decision.
    """

    from app.services import control_plane_service
    from app.services.knowledge_graph.llm_runtime import (
        KnowledgeLLMUnavailableError,
        build_generate_fn,
    )

    project = await _project(db, policy={})
    monkeypatch.setattr(
        control_plane_service,
        "resolve_control_plane_runtimes",
        lambda _db, **_kwargs: _mixed_chain(),
    )
    monkeypatch.setattr("app.agent.providers.get_provider", lambda **_kwargs: _FailingClient())

    generate = await build_generate_fn(db, project_ids=project.id)
    with pytest.raises(KnowledgeLLMUnavailableError) as failed:
        await generate("summarize this")

    refusal = failed.value.to_result()
    assert refusal["dispatch_owner"] == "knowledge_graph_runtime"
    assert refusal["admission_evidence"]["gateway_state"] == "alias_denied"
