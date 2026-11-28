"""A non-gateway owner keeps exactly the kwargs it passed, a gateway owner gains the admission, and the summarizer picks its runtime and records a governed refusal."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.model_gateway.dispatch_admission import admit_client_kwargs_for_dispatch
from app.services.model_gateway.litellm.project_admission import PROJECT_ADMISSION_KWARG
from tests.model_gateway.dispatch_admission_surfaces_support import _project

from .conftest import ALIAS, gateway_runtime, granted_project_config

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




async def test_a_non_gateway_owner_gets_exactly_the_kwargs_it_passed(db: AsyncSession):
    caller_kwargs = {"provider_name": "backup", "driver": "openrouter_api", "api_key": "sk-caller"}

    admission = await admit_client_kwargs_for_dispatch(
        db,
        caller_kwargs,
        model="backup-model",
        # No Workspace at all: a non-gateway chain must not even need one.
        project_ids=None,
        owner="security_analyzer_llm_risk",
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




