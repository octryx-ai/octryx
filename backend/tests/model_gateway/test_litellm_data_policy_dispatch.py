"""Dispatch records the comparison for a permitted classification and creates zero requests otherwise, whatever the caller or session tries."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.runtime.runtime_admission_contract import RUNTIME_ADMISSION_DENIAL_KEY
from app.agent.runtime.runtime_errors import RUNTIME_ERROR_DATA_POLICY_DENIED, classify_runtime_error
from app.models import Project
from app.services.model_gateway.data_policy import (
    CLASSIFICATION_SOURCE_PROJECT_CONFIG,
    DENIAL_CLASS_INSUFFICIENT,
    DENIAL_WORKSPACE_CLASS_MISSING,
    DENIAL_WORKSPACE_CLASS_UNKNOWN,
    data_policy_decision,
    resolve_data_classification,
)
from app.services.model_gateway.litellm import (
    UNVERIFIED_PROJECT_ADMISSION,
    LiteLLMGatewayError,
    admit_gateway_runtimes,
    apply_model_policy_to_runtimes,
)
from app.services.model_gateway.litellm.errors import GATEWAY_STATE_DATA_POLICY_DENIED
from app.services.model_gateway.litellm.evidence import CALL_EVIDENCE_KEYS
from tests.model_gateway.conftest import (
    ALIAS,
    MESSAGES,
    PROJECT_ID,
    VIRTUAL_KEY,
    gateway_runtime,
    granted_project_config,
    verified_admission,
    workspace_classification,
)
from tests.model_gateway.litellm_data_policy_support import EXCESSIVE_CLASSIFICATIONS, _alias_section

#: These tests call provider drivers directly: they run as the platform (``tests/support/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


def _project_config_with_classification(classification: Any) -> dict[str, Any]:
    return {**granted_project_config(), "data_policy": {"classification": classification}}


async def test_a_permitted_classification_dispatches_and_records_the_comparison(gateway, build_gateway_client) -> None:
    client = build_gateway_client(gateway, project_admission=verified_admission(ALIAS, classification="public"))

    response = await client.chat(MESSAGES, ALIAS)

    assert len(gateway.chat_requests) == 1
    evidence = response["usage"]["gateway_evidence"]
    assert evidence["workspace_data_classification"] == "public"
    assert evidence["workspace_data_classification_source"] == CLASSIFICATION_SOURCE_PROJECT_CONFIG
    assert evidence["data_policy_class"] == "internal"
    # Closed by allowlist, and the virtual key never travels with it.
    assert set(evidence) <= set(CALL_EVIDENCE_KEYS)
    assert VIRTUAL_KEY not in repr(evidence)


@pytest.mark.parametrize("classification", EXCESSIVE_CLASSIFICATIONS)
async def test_an_excessive_classification_creates_zero_requests(classification, gateway, build_gateway_client) -> None:
    client = build_gateway_client(
        gateway,
        project_admission=verified_admission(ALIAS, classification=classification),
    )

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, ALIAS)

    assert gateway.chat_requests == []
    assert excinfo.value.gateway_state == GATEWAY_STATE_DATA_POLICY_DENIED
    assert excinfo.value.denial_reason == DENIAL_CLASS_INSUFFICIENT
    assert classify_runtime_error(excinfo.value).error_class == RUNTIME_ERROR_DATA_POLICY_DENIED
    assert str(excinfo.value).endswith(f"[reason={DENIAL_CLASS_INSUFFICIENT}]")
    assert classification not in str(excinfo.value)


@pytest.mark.parametrize(
    ("project_config", "expected_reason"),
    (
        ({}, DENIAL_WORKSPACE_CLASS_MISSING),
        ({"classification": ""}, DENIAL_WORKSPACE_CLASS_MISSING),
        ({"classification": "  "}, DENIAL_WORKSPACE_CLASS_MISSING),
        ({"classification": "internal-ish"}, DENIAL_WORKSPACE_CLASS_UNKNOWN),
        ({"classification": ["internal"]}, DENIAL_WORKSPACE_CLASS_UNKNOWN),
    ),
)
async def test_an_unusable_classification_creates_zero_requests(
    project_config, expected_reason, gateway, build_gateway_client
) -> None:
    from app.services.model_gateway.litellm import build_project_model_admission

    admission = build_project_model_admission(
        project_id=PROJECT_ID,
        project_config=granted_project_config(),
        source="test_boundary",
        data_classification=resolve_data_classification(project_data_policy=project_config),
    )
    client = build_gateway_client(gateway, project_admission=admission)

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, ALIAS)

    assert gateway.chat_requests == []
    assert excinfo.value.gateway_state == GATEWAY_STATE_DATA_POLICY_DENIED
    assert excinfo.value.denial_reason == expected_reason


def test_an_alias_declaring_secret_is_refused_before_a_client_exists(gateway, build_gateway_client) -> None:
    with pytest.raises(LiteLLMGatewayError) as excinfo:
        build_gateway_client(gateway, config_json=_alias_section("secret"))

    assert gateway.requests == []
    assert excinfo.value.denial_reason == "alias_catalog_has_no_admitted_alias"
    assert data_policy_decision(workspace_classification("secret"), "restricted").reason == DENIAL_CLASS_INSUFFICIENT


async def test_a_model_argument_cannot_carry_a_classification(gateway, build_gateway_client) -> None:
    client = build_gateway_client(
        gateway,
        project_admission=verified_admission(ALIAS, classification="restricted"),
    )

    for model_argument in (ALIAS, f"{ALIAS}:public", "public", f"{ALIAS}?data_policy_class=restricted"):
        with pytest.raises(LiteLLMGatewayError):
            await client.chat(MESSAGES, model_argument)

    assert gateway.chat_requests == []


async def test_a_caller_shaped_admission_cannot_reach_the_gate(gateway, build_gateway_client) -> None:
    class LookAlikeAdmission:
        verified = True
        project_id = PROJECT_ID
        data_classification = workspace_classification("public")

        def decide(self, alias: str) -> Any:  # pragma: no cover - must never run
            raise AssertionError("a look-alike admission must never be consulted")

        def decide_data_policy(self, alias_class: str) -> Any:  # pragma: no cover - must never run
            raise AssertionError("a look-alike admission must never be consulted")

    forgeries = (
        LookAlikeAdmission(),
        {"project_id": PROJECT_ID, "data_classification": "public", "verified": True},
        UNVERIFIED_PROJECT_ADMISSION,
    )

    for forgery in forgeries:
        with pytest.raises(LiteLLMGatewayError):
            client = build_gateway_client(gateway, project_admission=forgery)
            await client.chat(MESSAGES, ALIAS)

    assert gateway.requests == []


def test_a_classification_in_the_turn_project_config_is_never_read() -> None:
    admitted = apply_model_policy_to_runtimes(
        [gateway_runtime()],
        # Exactly what a knowledge-injected or session-patched turn config looks
        # like: a permissive classification sitting in the merged mapping.
        project_config=_project_config_with_classification("public"),
        project_id=PROJECT_ID,
        data_classification=workspace_classification("restricted"),
    )

    assert admitted[0][RUNTIME_ADMISSION_DENIAL_KEY]["reason"] == DENIAL_CLASS_INSUFFICIENT
    assert admitted[0][RUNTIME_ADMISSION_DENIAL_KEY]["evidence"]["workspace_data_classification"] == "restricted"


async def test_a_session_write_cannot_lower_the_project_floor_at_run_preparation(db) -> None:
    project = Project(
        id="project-session-downgrade",
        name="session-downgrade-project",
        config={"data_policy": {"classification": "restricted"}},
    )
    db.add(project)
    await db.commit()

    admitted = await admit_gateway_runtimes(
        db,
        [gateway_runtime()],
        project_config=granted_project_config(),
        project_id=project.id,
        session_metadata={"data_policy": {"classification": "public"}},
    )

    denial = admitted[0][RUNTIME_ADMISSION_DENIAL_KEY]
    assert denial["reason"] == DENIAL_CLASS_INSUFFICIENT
    assert denial["evidence"]["workspace_data_classification"] == "restricted"
