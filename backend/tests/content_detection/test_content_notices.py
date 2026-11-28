"""The chat notices of content policies: from the chat driver through the engine into the turn summary."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.agent.runtime.runtime_fallback import _chat_with_runtime_fallback
from app.services.content_routing.notices import closed_notice, turn_content_obligations
from app.services.model_gateway.litellm.errors import LiteLLMGatewayError
from app.services.session.turn_execution_summary import TurnExecutionEvidence, build_turn_execution_summary
from tests.content_detection.content_obligations_support import DATA_TEXT, EMAIL, PHONE, ROUTED
from tests.model_gateway.conftest import ALIAS, gateway_config
from tests.policy_engine_support import use_custom_policies

BLOCK = ('@id("no-mail")\nforbid (principal, action == Action::"call_model", resource)\n'
         'when { context.content.detected.contains("email") };')
RUNTIME = {"provider_name": "gateway", "model": ALIAS, "target_id": "t", "priority": 1, "max_runtime_retries": 0,
           "max_context_retries": 0, "max_malformed_retries": 0}


class _Client:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome

    async def chat(self, **_kwargs):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    async def close(self) -> None:
        return None


async def _chat(policy: str) -> Any:
    from app.db import core as db_core
    from app.services.content_routing.chat import apply_chat_content
    from app.services.model_gateway.litellm.alias_catalog import resolve_alias_admission
    from app.services.prompt_catalog import prompt_set_scope, resolve_prompt_set
    from tests.model_gateway.conftest import verified_admission

    config = gateway_config()
    config["litellm_gateway"]["aliases"]["approved-model"] = dict(
        config["litellm_gateway"]["aliases"][ALIAS], approved_data_categories=["pii"])
    admits = {name: resolve_alias_admission(name, config).entry for name in (ALIAS, "approved-model")}
    use_custom_policies(policy, mode="enforce")
    async with db_core.async_session_factory() as db:
        prompt_set = await resolve_prompt_set(db, workspace_id=None)
    with prompt_set_scope(prompt_set):
        try:
            return await apply_chat_content(verified_admission(ALIAS, "approved-model"), admits[ALIAS],
                                            [{"role": "user", "content": DATA_TEXT}],
                                            admit=lambda alias: (admits[alias], None), tools=False)
        except LiteLLMGatewayError as refused:
            return refused


async def _attempts(outcome: Any) -> list[dict[str, Any]]:
    try:
        _response, _runtime, attempts = await _chat_with_runtime_fallback(
            [RUNTIME], messages=[], tools=None, get_provider_func=lambda **_kwargs: _Client(outcome),
            retry_policy={"max_retries": 0, "pause_seconds": 0})
    except RuntimeError as failed:
        attempts = failed.runtime_attempts
    return attempts


@pytest.mark.asyncio
async def test_masked_routed_and_refused_chat_turns_reach_the_summary_without_the_data(client):
    routed = await _chat(ROUTED.replace(f'@reroute_to("{ALIAS}")', '@reroute_to("approved-model")'))
    served = await _attempts({"content": "ok", "tool_calls": [], "content_obligation": dict(routed.notice)})
    refused = await _chat(BLOCK)
    assert isinstance(refused, LiteLLMGatewayError) and refused.content_notice["reason"] == "content_policy_denied"
    failed = await _attempts(refused)
    tool = {"content_policy": {"kind": "mask", "found": {"secrets": 14}, "masked": 14, "policies": ["mask-tool-results"],
                               "decision_id": "d-tool-1", "reason": "content_obligation_applied"}}
    notices = turn_content_obligations([{"runtime_attempts": served}, {"runtime_attempts": failed}],
                                       [("logs_tail", tool)])
    summary = build_turn_execution_summary(TurnExecutionEvidence(
        trace_id="t1", session_id="s1", message_id=None, provider="gateway", model=ALIAS, context_snapshot={},
        runtime_outcome="finished", content_obligations=tuple(notices)))

    applied, block, masked_tool = summary["content_obligations"]
    assert (applied["kind"], applied["model_from"], applied["model_to"]) == ("mask_reroute", ALIAS, "approved-model")
    # The model-call boundary names the call's one record in both (``model_call``); Cedar writes none of its own.
    assert applied["found"] == {"email": 1, "phone": 1} and applied["masked"] == 2 and applied["decision_id"] is None
    assert (block["reason"], block["policies"], block["applied"]) == ("content_policy_denied", ["no-mail"], False)
    assert block["decision_id"] is None and block["found"] == {"email": 1, "phone": 1}
    assert (masked_tool["source"], masked_tool["tool"], masked_tool["found"]) == ("tool_result", "logs_tail",
                                                                                  {"secrets": 14})
    for evidence in (summary, served, failed, str(refused)):
        assert EMAIL not in json.dumps(evidence, default=str) and PHONE not in json.dumps(evidence, default=str)


def test_notices_are_closed_deduplicated_and_quiet_for_a_sticky_route_without_findings():
    number = "".join(char for char in PHONE if char.isdigit())
    hostile = {"kind": "mask", "found": {number: 1, "email": 2}, "masked": 2, "policies": [f"x {number}", "p"],
               "decision_id": number, "model_to": number, "reason": "content_obligation_applied"}
    notice = closed_notice(hostile, source="model")
    assert number not in json.dumps(notice) and notice["found"] == {"email": 2} and notice["policies"] == ["p"]
    assert notice["decision_id"] is None and notice["model_to"] is None
    assert closed_notice({**hostile, "kind": "leak"}, source="model") is None
    assert closed_notice({**hostile, "reason": "anything"}, source="model") is None
    sticky = {"kind": "reroute", "found": {}, "masked": 0, "model_to": "approved-model"}
    repeated = {"runtime_attempts": [{"content_obligation": hostile}, {"content_obligation": hostile},
                                     {"content_obligation": sticky}]}
    assert len(turn_content_obligations([repeated, repeated], [])) == 1


def test_a_chat_content_refusal_is_terminal_and_never_falls_back():
    from app.agent.runtime.retry_policy import plan_exception_retry
    from app.agent.runtime.runtime_admission_contract import admission_refusal_of_attempts
    from app.agent.runtime.runtime_errors import RUNTIME_ERROR_CONTENT_POLICY_DENIED, classify_runtime_error
    from app.services.content_routing.chat import _refuse

    error_class = classify_runtime_error(_refuse("content_policy_denied")).error_class
    assert error_class == RUNTIME_ERROR_CONTENT_POLICY_DENIED
    plan = plan_exception_retry(error_class=error_class, has_additional_runtimes=True,
                                transient_retries_remaining=2, context_retries_remaining=1,
                                malformed_retries_remaining=1, attempt_messages=[], attempt_max_tokens=100,
                                default_max_tokens=100, retry_index=0, context_pressure_retry_messages=list)
    assert plan.retry_decision == "final_error" and not plan.should_retry
    attempts = [{"error_class": "alias_denied", "error_class_source": "explicit"},
                {"error_class": error_class, "error_class_source": "explicit"}]
    assert admission_refusal_of_attempts(attempts) == RUNTIME_ERROR_CONTENT_POLICY_DENIED
