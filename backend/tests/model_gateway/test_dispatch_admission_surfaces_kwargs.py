"""A non-gateway owner keeps exactly the kwargs it passed, a gateway owner gains the admission, and the summarizer picks its runtime and records a governed refusal."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.model_gateway.dispatch_admission import admit_client_kwargs_for_dispatch
from app.services.model_gateway.litellm.project_admission import PROJECT_ADMISSION_KWARG
from tests.model_gateway.dispatch_admission_surfaces_support import _ForbiddenProviderFactory, _mixed_chain, _project

from .conftest import ALIAS, backup_runtime, gateway_runtime, granted_project_config

# The kwargs ``_provider_client_kwargs`` builds for a non-gateway runtime.
NON_GATEWAY_LLM_RISK_KEYS = {
    "provider_name",
    "api_key",
    "region",
    "role_arn",
    "copilot_token",
    "auth_mode",
    # The catalog row's sampling choice travels with every target.
    "accepts_temperature",
    "target_temperature",
}


async def _summarize_tagged_chain() -> list[dict[str, Any]]:
    return [gateway_runtime(use_case_tags=["summarize"])]


# --- nothing else changes ----------------------------------------------------


async def test_a_non_gateway_owner_gets_exactly_the_kwargs_it_passed(db: AsyncSession):
    caller_kwargs = {"provider_name": "backup", "driver": "openrouter_api", "api_key": "sk-caller"}

    admission = await admit_client_kwargs_for_dispatch(
        db,
        caller_kwargs,
        model="backup-model",
        # No Workspace at all: a non-gateway chain must not even need one.
        project_ids=None,
        owner="session_summarizer",
    )

    assert admission.allowed is True
    assert admission.first_dispatchable_runtime() == caller_kwargs


async def test_a_gateway_owner_gets_the_admission_and_keeps_its_own_model_key(db: AsyncSession):
    project = await _project(db, policy=granted_project_config(ALIAS)["model_policy"])

    admission = await admit_client_kwargs_for_dispatch(
        db,
        # An owner whose kwargs mapping legitimately carries the model keeps it.
        {"provider_name": "litellm", "driver": "litellm_gateway", "model": ALIAS},
        model=ALIAS,
        project_ids=project.id,
        owner="security_analyzer_llm_risk",
    )

    runtime = admission.first_dispatchable_runtime()
    assert runtime["model"] == ALIAS
    assert runtime[PROJECT_ADMISSION_KWARG].verified is True


def test_llm_risk_adds_the_gateway_fields_only_for_the_gateway():
    from app.services.security_analyzer.llm_risk import _provider_client_kwargs

    other = _provider_client_kwargs(
        {
            "provider_name": "bedrock",
            "driver": "bedrock_api",
            "api_key": None,
            "region": "eu-central-1",
            "config_json": {"inference_profile": "must-not-be-forwarded"},
            "endpoint_url": "https://bedrock.example/v1",
        }
    )
    assert set(other) == NON_GATEWAY_LLM_RISK_KEYS

    gateway = _provider_client_kwargs(
        {**gateway_runtime(), "endpoint_url": "https://litellm.internal.test/v1", "config_json": {}}
    )
    assert set(gateway) == NON_GATEWAY_LLM_RISK_KEYS | {
        "driver",
        "endpoint_url",
        "config_json",
        PROJECT_ADMISSION_KWARG,
    }


# --- the summarizer seam -----------------------------------------------------


async def test_the_summarizer_uses_the_platform_default_when_no_task_model_is_set(
    db: AsyncSession, monkeypatch
):
    # No hard-coded summary model. Without a "Conversation summaries" Task model the platform default
    # (first in the order) summarizes, through the same Workspace admission.
    from app.agent.core.runtime._summarizer_runtime import resolve_summarizer_runtime
    from app.services import control_plane_service

    project = await _project(db, policy={})

    async def backup_first(_db, **_kwargs):
        return [backup_runtime(), gateway_runtime()]

    monkeypatch.setattr(control_plane_service, "resolve_control_plane_runtimes", backup_first)
    runtime = await resolve_summarizer_runtime(db, project_id=project.id)
    assert runtime.admitted is True
    assert runtime.model == backup_runtime()["model"]

    # A platform default this Workspace may not use is refused visibly, never swapped for another model.
    monkeypatch.setattr(
        control_plane_service, "resolve_control_plane_runtimes", lambda _db, **_kwargs: _mixed_chain()
    )
    refused = await resolve_summarizer_runtime(db, project_id=project.id)
    assert refused.admitted is False and refused.model == ""


async def test_the_summarizer_records_the_refusal_of_a_tagged_governed_runtime(
    db: AsyncSession, monkeypatch
):
    """The seam that makes ``session_summarizer`` a real owner rather than a claim.

    An operator tags a control-plane target ``summarize``; from then on the
    Workspace's ``model_policy`` decides, and a refusal is written to the session
    instead of leaving a summary silently missing.
    """

    from sqlalchemy import select

    from app.agent.core.runtime.summarizer import _update_summary
    from app.models import Message, Session, User
    from app.services import control_plane_service

    project = await _project(db, policy={})
    monkeypatch.setattr(
        control_plane_service,
        "resolve_control_plane_runtimes",
        lambda _db, **_kwargs: _summarize_tagged_chain(),
    )
    monkeypatch.setattr("app.agent.providers.get_provider", _ForbiddenProviderFactory())
    user = (await db.execute(select(User).limit(1))).scalars().first()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        agent_type="chat",
        status="active",
        metadata_={},
    )
    db.add(session)
    for index in range(12):
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session.id,
                role="user" if index % 2 == 0 else "assistant",
                content=f"Message {index} about the deployment window.",
            )
        )
    await db.commit()

    await _update_summary(session.id, db)
    await db.refresh(session)

    admission = dict(session.metadata_ or {})["summary_admission"]
    assert admission["dispatch_owner"] == "session_summarizer"
    assert admission["dispatched"] is False
    assert "summary" not in dict(session.metadata_ or {})
