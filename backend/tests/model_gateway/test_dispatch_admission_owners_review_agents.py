"""Review and agent owners: LLM risk reports the admission state as a finding, an engine-mediated owner records a zero-dispatch attempt, and call_agent raises the typed denial without building a client."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.model_gateway.dispatch_admission import DispatchAdmissionDeniedError
from app.tools.context import ToolContext
from tests.model_gateway.dispatch_admission_owners_support import _ForbiddenProviderFactory, _project

from .conftest import ALIAS, gateway_runtime


async def _llm_risk_runtime() -> tuple[dict[str, Any], str]:
    return {**gateway_runtime(), "provider_id": None}, "LiteLLM Gateway"


# --- risk analysis ----------------------------------------------------------


async def test_llm_risk_reports_the_admission_state_as_a_review_finding(db: AsyncSession, monkeypatch):
    from app.services.security_analyzer import llm_risk

    project = await _project(db, policy={})
    monkeypatch.setattr(
        llm_risk,
        "_resolve_llm_risk_runtime",
        lambda _db, **_kwargs: _llm_risk_runtime(),
    )
    monkeypatch.setattr(llm_risk, "get_provider", _ForbiddenProviderFactory())
    context = ToolContext(
        user_id="u1",
        project_ids=[project.id],
        roles=[],
        session_id="s1",
        project_config={"project_id": project.id},
        db=db,
    )

    finding = await llm_risk._llm_risk_analyzer("run_command", "kubectl delete ns prod", context)

    # Still fails closed to manual review, but for a *stated* reason.
    assert finding.action == "review"
    assert "not admitted for this Workspace" in finding.reason
    assert finding.details["dispatched"] is False
    assert finding.details["dispatch_owner"] == "security_analyzer_llm_risk"


# --- engine-mediated owners --------------------------------------------------


async def test_an_engine_mediated_owner_records_a_zero_dispatch_attempt(db: AsyncSession):
    """The secure-work worker hands the admitted chain to the engine.

    Their contract is the annotated list: the refused gateway target must never be
    constructed, the admitted target must serve, and the refusal must survive into
    the runtime attempts with its reason, evidence and ``dispatched=false``.
    """

    from app.agent.core.runtime.runtime_admission_contract import RUNTIME_ADMISSION_DENIED_STATUS
    from app.agent.engine.runtime._engine_runtime_fallback import _chat_with_runtime_fallback
    from app.services.model_gateway.dispatch_admission import admit_runtimes_for_dispatch

    from .conftest import MESSAGES, RecordingRuntimeFactory, backup_runtime

    project = await _project(db, policy={})
    admission = await admit_runtimes_for_dispatch(
        db,
        [gateway_runtime(), backup_runtime()],
        project_ids=project.id,
        owner="secure_work_plan_worker",
    )
    factory = RecordingRuntimeFactory(forbidden=("litellm",))

    response, used_runtime, attempts = await _chat_with_runtime_fallback(
        list(admission.runtimes),
        messages=MESSAGES,
        tools=None,
        get_provider_func=factory,
        retry_policy={"max_retries": 0, "pause_seconds": 0, "fallback_mode": "all_runtimes"},
    )

    assert factory.constructed == ["backup"]
    assert response["content"] == "backup answer"
    assert used_runtime["target_id"] == "t2"
    denied = [item for item in attempts if item.get("status") == RUNTIME_ADMISSION_DENIED_STATUS]
    assert denied and denied[0]["dispatched"] is False
    assert denied[0]["admission_reason"] == "model_alias_not_granted_for_project"
    assert denied[0]["admission_evidence"]["dispatch_owner"] == "secure_work_plan_worker"


# --- sub-agent / call-agent -------------------------------------------------


async def test_call_agent_raises_the_typed_denial_and_builds_no_client(db: AsyncSession, monkeypatch):
    from types import SimpleNamespace

    from app.models import LLMProvider
    from app.services import control_plane_service
    from app.services.call_agent.service import CallAgentService

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
        db, SimpleNamespace(project_id=project.id, llm_model=ALIAS, enabled_tools=[])
    )

    with pytest.raises(DispatchAdmissionDeniedError) as denied:
        await service._get_llm_provider()

    result = denied.value.to_result()
    assert result["dispatch_owner"] == "call_agent"
    assert result["dispatched"] is False
