"""Tests for the support-request error-signature classifier (S3).

The one allowed matcher: factual error signatures classify the turn intent as
``support_request``. It has its own switch and never selects a workflow.
"""

from __future__ import annotations

import pytest

from app.services.execution_strategy_intent import (
    ROUTING_INTENT_SOURCE_DEFAULT,
    ROUTING_INTENT_SOURCE_SIGNATURE,
    support_request_signature_applies,
)
from app.services.execution_strategy_service import resolve_execution_strategy
from app.services.system_config.values import set_system_config_value
from app.services.workflow_routing.support_signature import (
    SUPPORT_REQUEST_SIGNATURE_CONFIG_KEY,
    SUPPORT_REQUEST_SIGNATURE_DISABLED,
    match_support_request_signature,
    support_request_signature_enabled,
)

ERROR_SIGNATURE_PROMPT = (
    "We have the following support request: the simulation failed with a "
    "SQLServerException and a stack trace after the connection read timed out."
)
PLAIN_PROMPT = "Bitte erstelle die Uebersicht."


def test_signature_pattern_matches_factual_error_evidence_only():
    assert match_support_request_signature(ERROR_SIGNATURE_PROMPT)
    assert match_support_request_signature("I am seeing an error message in the log")
    assert not match_support_request_signature(PLAIN_PROMPT)
    assert not match_support_request_signature("Create an AWS topology architecture diagram.")


async def _decide(db, prompt: str, resolution: dict | None = None):
    """Both entry paths: evaluate the signature for this turn, then resolve the strategy."""
    applies = await support_request_signature_applies(prompt, db=db)
    return resolve_execution_strategy(
        prompt=prompt,
        requested_agent_type="diagnosis",
        support_request_signature=applies,
        workflow_routing_policy_resolution=resolution,
    )


@pytest.mark.asyncio
async def test_classifier_flags_support_request_with_signature_source(db):
    decision = await _decide(db, ERROR_SIGNATURE_PROMPT)

    assert decision.routing_intent == "support_request"
    assert decision.routing_reason == "intent:support_request_signature"
    assert decision.routing_intent_confidence == 1.0
    assert decision.routing_intent_source == ROUTING_INTENT_SOURCE_SIGNATURE


@pytest.mark.asyncio
async def test_classifier_respects_its_own_switch(db):
    assert await support_request_signature_enabled(db) is True

    await set_system_config_value(
        db,
        key=SUPPORT_REQUEST_SIGNATURE_CONFIG_KEY,
        value=SUPPORT_REQUEST_SIGNATURE_DISABLED,
        record_prompt_revision=False,
    )
    assert await support_request_signature_enabled(db) is False

    decision = await _decide(db, ERROR_SIGNATURE_PROMPT)
    # Disabled: no signature classification; the explicit-first default applies.
    assert decision.routing_intent == "diagnosis"
    assert decision.routing_reason == "intent:diagnosis_default"
    assert decision.routing_intent_source == ROUTING_INTENT_SOURCE_DEFAULT


@pytest.mark.asyncio
async def test_classifier_never_fires_without_error_evidence(db):
    decision = await _decide(db, PLAIN_PROMPT)

    assert decision.routing_intent == "diagnosis"
    assert decision.routing_reason == "intent:diagnosis_default"
    assert decision.routing_intent_source == ROUTING_INTENT_SOURCE_DEFAULT


@pytest.mark.asyncio
async def test_matched_policy_resolution_wins_over_signature(db):
    resolution = {
        "source": "db",
        "status": "matched",
        "workflow_contract": {"routing_intent": "knowledge"},
    }
    decision = await _decide(db, ERROR_SIGNATURE_PROMPT, resolution)

    assert decision.routing_intent == "knowledge"
    assert decision.routing_intent_source == "policy"
