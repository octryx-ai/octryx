"""A model-admission refusal ends the turn in an explicit governance state.

A turn whose model alias the project has not granted (zero provider requests) must not end as ``failed`` /
``provider_error``. The run ends ``needs_configuration`` / ``model_alias_not_admitted`` (``denied`` /
``model_data_policy_denied`` for a data-policy refusal), decided from the typed
runtime attempts, never from message text; the Turn Execution Summary agrees.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.core.runtime.runtime_admission_contract import (
    admission_refusal_of_attempts,
    build_admission_denied_attempt,
)
from app.agent.core.runtime.runtime_errors import (
    RUNTIME_ERROR_ALIAS_DENIED,
    RUNTIME_ERROR_DATA_POLICY_DENIED,
    RUNTIME_ERROR_TRANSIENT,
)
from app.models import TurnTrace
from app.services.model_gateway.litellm.errors import GATEWAY_STATE_ALIAS_DENIED, LiteLLMGatewayError
from app.services.model_gateway.litellm.runtime_admission import (
    ALIAS_DENIED_MESSAGE,
    apply_model_policy_to_runtimes,
)
from app.services.product_run.turn_outcome import FinalTraceFacts, RunMove, turn_end_move
from app.services.session.turn_execution_summary_service import load_user_turn_execution_summary
from tests import product_run_chat_support
from tests.product_run_chat_binding_support import (
    OPENED,
    TRANSIENT,
    _attempt,
    _audit,
    _drain,
    _session,
    _turn,
)

# The scripted provider world of the binding tests (no network, call counter).
world = product_run_chat_support.world

ALIAS = "octryx-alias-not-granted"


def _refused(error_class: str) -> dict:
    runtime = {"provider_name": "litellm_gateway", "driver": "litellm_gateway", "model": ALIAS}
    denial = {"error_class": error_class, "reason": "alias_not_granted", "message": ALIAS_DENIED_MESSAGE}
    return build_admission_denied_attempt(runtime, denial, retry_cycle_index=0)


@pytest.fixture
def ungranted_alias(monkeypatch):
    """Every runtime target becomes a gateway alias the project did not grant (real admission producer)."""
    prepare = engine_module._prepare_agent_run

    async def prepare_with_ungranted_alias(**kwargs):
        prepared = await prepare(**kwargs)
        prepared.runtimes = apply_model_policy_to_runtimes(
            [{**runtime, "driver": "litellm_gateway", "model": ALIAS} for runtime in prepared.runtimes],
            project_config={"model_policy": {"allowed_aliases": []}},
            project_id=kwargs["project_id"],
        )
        return prepared

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare_with_ungranted_alias)


async def _summary_of_failure(db, session):
    trace = (
        await db.execute(
            select(TurnTrace).where(TurnTrace.session_id == session.id, TurnTrace.provider == "runtime-fallback")
        )
    ).scalar_one()
    return trace, await load_user_turn_execution_summary(db, user_id=session.user_id, trace_id=trace.id)


@pytest.mark.asyncio
async def test_an_alias_the_project_did_not_grant_ends_in_needs_configuration_without_a_provider_call(
    db, monkeypatch, world, ungranted_alias
) -> None:
    world["script"] = [AssertionError("a refused alias must not reach a provider")]
    session = await _session(db)

    await _drain(_turn(db, session))

    assert world["calls"] == 0
    attempt = await _attempt(db, session.id)
    assert (attempt.state, attempt.end_reason) == ("needs_configuration", "model_alias_not_admitted")
    assert await _audit(db, attempt.run_id) == [*OPENED, ("running", "needs_configuration", "model_alias_not_admitted")]
    trace, summary = await _summary_of_failure(db, session)
    assert {a["status"] for a in trace.raw_output["runtime_attempts"]} == {"admission_denied"}
    assert summary["state"] == "needs_configuration"
    assert summary["state_reason"]["code"] == "model_alias_not_admitted"
    assert summary["next_action"]["kind"] == "complete_configuration"
    assert summary["run_identity"]["attempt"]["state"] == "needs_configuration"
    assert summary["run_identity"]["attempt"]["end_reason"] == "model_alias_not_admitted"


@pytest.mark.asyncio
async def test_a_driver_side_alias_refusal_is_the_same_governance_outcome(db, world) -> None:
    """The governed driver re-checks the grant and refuses with a typed error before any request."""
    world["script"] = [LiteLLMGatewayError(GATEWAY_STATE_ALIAS_DENIED, denial_reason="alias_not_granted")]
    session = await _session(db)

    await _drain(_turn(db, session))

    attempt = await _attempt(db, session.id)
    assert (attempt.state, attempt.end_reason) == ("needs_configuration", "model_alias_not_admitted")


@pytest.mark.asyncio
async def test_a_provider_error_is_still_a_provider_error(db, world) -> None:
    """Negative control: a dispatched request that failed keeps ``failed`` / ``provider_error``."""
    world["script"] = [TRANSIENT, TRANSIENT]
    session = await _session(db)

    await _drain(_turn(db, session))

    attempt = await _attempt(db, session.id)
    assert (attempt.state, attempt.end_reason) == ("failed", "provider_error")
    _trace, summary = await _summary_of_failure(db, session)
    assert (summary["state"], summary["state_reason"]["code"]) == ("failed", "runtime_failed")


def test_the_refusal_is_decided_from_typed_attempts_only() -> None:
    alias, data = _refused(RUNTIME_ERROR_ALIAS_DENIED), _refused(RUNTIME_ERROR_DATA_POLICY_DENIED)
    dispatched = {"status": "error", "error_class": RUNTIME_ERROR_TRANSIENT, "error_class_source": "explicit"}
    assert admission_refusal_of_attempts([alias, alias]) == RUNTIME_ERROR_ALIAS_DENIED
    assert admission_refusal_of_attempts([alias, data]) == RUNTIME_ERROR_DATA_POLICY_DENIED
    # A target that was dispatched, an unexplained class, a truncated record, or nothing at all: not a refusal.
    assert admission_refusal_of_attempts([alias, dispatched]) is None
    assert admission_refusal_of_attempts([{**alias, "error_class_source": "message_pattern"}]) is None
    assert admission_refusal_of_attempts([alias, "...[3 more items truncated]"]) is None
    assert admission_refusal_of_attempts([]) is None
    assert admission_refusal_of_attempts(None) is None
    # The message text is never read: the refusal survives any wording.
    assert admission_refusal_of_attempts([{**alias, "error": "provider returned 503"}]) == RUNTIME_ERROR_ALIAS_DENIED


@pytest.mark.parametrize(
    ("provider", "refusal", "move"),
    [
        ("runtime-fallback", RUNTIME_ERROR_ALIAS_DENIED, RunMove("needs_configuration", "model_alias_not_admitted")),
        ("runtime-fallback", RUNTIME_ERROR_DATA_POLICY_DENIED, RunMove("denied", "model_data_policy_denied")),
        ("runtime-fallback", None, RunMove("failed", "provider_error")),
        ("harness", RUNTIME_ERROR_ALIAS_DENIED, RunMove("failed", "runtime_error")),
    ],
)
def test_turn_end_mapping_of_admission_refusals(provider, refusal, move) -> None:
    facts = FinalTraceFacts(provider=provider, failed=True, finished=False, admission_refusal=refusal)
    assert turn_end_move(facts, "running") == move
