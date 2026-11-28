from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app.services.content_detection.custom_definitions import CustomDetectorDefinition, DetectorDefinitions
from app.services.content_detection.custom_validation import check_detector_set
from app.services.content_routing.tool_results import check_tool_result
from app.services.policy_engine.runtime import set_policy_runtime
from tests.model_gateway.conftest import ALIAS, gateway_config
from tests.policy_engine_support import use_custom_policies

SELF_MATCHING = r"ACME[- #0-9]*"
MASK = ('@id("mask-refs")\n@obligation("mask")\n@mask("{detector}")\n@mask_style("{style}")\n'
        'forbid (principal, action == Action::"{action}", resource)\n'
        'when {{ context.content.detected.contains("{detector}") }};')


def _validated(detector: str, pattern: str) -> DetectorDefinitions:
    return check_detector_set({"detectors": [
        {"id": detector, "label": "Reference", "category": "secrets", "pattern": pattern}]})


def _stored(detector: str, pattern: str) -> DetectorDefinitions:
    return DetectorDefinitions((CustomDetectorDefinition(detector, "Reference", "secrets", pattern),))


def _install(definitions: DetectorDefinitions, action: str, style: str = "type_token") -> None:
    detector = definitions.detectors[0].id
    runtime = use_custom_policies(MASK.format(detector=detector, style=style, action=action), mode="enforce")
    set_policy_runtime(replace(runtime, custom_detectors=definitions))


async def _tool_result(text: str):
    return await check_tool_result({"text": text}, tool_name="t", family=None, origin="connector",
                                   workspace_id="ws-1", session_id=None, conversation="chat")


async def _chat(text: str):
    from app.db import core as db_core
    from app.services.content_routing.chat import apply_chat_content
    from app.services.model_gateway.litellm.alias_catalog import resolve_alias_admission
    from app.services.prompt_catalog import prompt_set_scope, resolve_prompt_set
    from tests.model_gateway.conftest import verified_admission

    entry = resolve_alias_admission(ALIAS, gateway_config()).entry
    async with db_core.async_session_factory() as db:
        prompt_set = await resolve_prompt_set(db, workspace_id=None)
    with prompt_set_scope(prompt_set):
        return await apply_chat_content(verified_admission(ALIAS), entry, [{"role": "user", "content": text}],
                                        admit=lambda alias: (entry, None), tools=True)


CASES = [
    pytest.param(_validated("custom.acme", r"ACME-[0-9]{4}"), "type_token", "ticket ACME-1234 open",
                 "ticket [ACME #1] open", id="plain"),
    pytest.param(_validated("custom.acme", SELF_MATCHING), "type_token", "ticket ACME-1234 open",
                 "ticket [ACME #1]open", id="self-matching"),
    pytest.param(_stored("custom.acme", SELF_MATCHING), "type_token", "ticket ACME-1234 open",
                 "ticket [ACME #1]open", id="stored-self-matching"),
    pytest.param(_validated("custom.zx", r"ZX-[0-9]{4}|\b"), "type_token", "ref ZX-1234 open",
                 "ref [ZX #1] open", id="zero-width-alternative"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("definitions", "style", "text", "masked"), CASES)
async def test_tool_result_mask_repair_succeeds(client, db, definitions, style, text, masked):
    _install(definitions, "receive_tool_result", style)
    outcome = await _tool_result(text)
    assert not outcome.blocked, outcome.reason
    assert outcome.result["text"] == masked
    assert outcome.notice["kind"] == "mask" and outcome.notice["masked"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("definitions", "style", "text", "masked"), CASES)
async def test_governed_chat_mask_repair_succeeds(client, definitions, style, text, masked):
    _install(definitions, "call_model", style)
    result = await _chat(text)
    assert result.messages[0]["content"] == masked
    assert text.split()[1] not in json.dumps(result.messages)
    assert result.notice["reason"] == "content_obligation_applied" and result.notice["masked"] == 1


ADJACENT = ('@id("mask-refs")\n@obligation("mask")\n@mask("{mask}")\n'
            'forbid (principal, action == Action::"receive_tool_result", resource)\n'
            'when {{ context.content.detected.containsAny(["custom.acme", "phone"]) }};')


@pytest.mark.asyncio
async def test_a_phone_right_after_a_placeholder_still_blocks_when_only_the_reference_is_masked(client, db):
    runtime = use_custom_policies(ADJACENT.format(mask="custom.acme"), mode="enforce")
    set_policy_runtime(replace(runtime, custom_detectors=_validated("custom.acme", SELF_MATCHING)))
    outcome = await _tool_result("ticket ACME-1234 +49 30 1234567")
    assert outcome.blocked and outcome.reason == "content_obligation_insufficient"


@pytest.mark.asyncio
async def test_a_phone_right_after_a_placeholder_is_masked_when_both_are_masked(client, db):
    runtime = use_custom_policies(ADJACENT.format(mask="custom.acme,phone"), mode="enforce")
    set_policy_runtime(replace(runtime, custom_detectors=_validated("custom.acme", SELF_MATCHING)))
    outcome = await _tool_result("ticket ACME-1234 +49 30 1234567")
    assert not outcome.blocked, outcome.reason
    assert outcome.result["text"] == "ticket [ACME #1][PHONE #2]"


RETAINED = ('@id("mask-refs")\n@obligation("mask")\n@mask("{mask}")\n@mask_style("last4")\n'
            'forbid (principal, action == Action::"{action}", resource)\n'
            'when {{ context.content.detected.containsAny(["{mask}", "custom.tail"]) }};')
RETAINED_CASES = [
    pytest.param(_validated("custom.zx", r"ZX-[0-9]{6}|0042"), "custom.zx", "ref ZX-120042 open",
                 id="self-matching-last4"),
    pytest.param(check_detector_set({"detectors": [
        {"id": "custom.acme", "label": "Reference", "category": "secrets", "pattern": r"ACME-[0-9]+"},
        {"id": "custom.tail", "label": "Tail", "category": "secrets", "pattern": r"0042"}]}),
        "custom.acme", "ref ACME-120042 open", id="other-detector-on-retained-last4"),
]


def _install_retained(definitions: DetectorDefinitions, mask: str, action: str) -> None:
    runtime = use_custom_policies(RETAINED.format(mask=mask, action=action), mode="enforce")
    set_policy_runtime(replace(runtime, custom_detectors=definitions))


@pytest.mark.asyncio
@pytest.mark.parametrize(("definitions", "mask", "text"), RETAINED_CASES)
async def test_a_finding_on_retained_last4_input_blocks_a_tool_result(client, db, definitions, mask, text):
    _install_retained(definitions, mask, "receive_tool_result")
    outcome = await _tool_result(text)
    assert outcome.blocked and outcome.reason == "content_obligation_insufficient"


@pytest.mark.asyncio
@pytest.mark.parametrize(("definitions", "mask", "text"), RETAINED_CASES)
async def test_a_finding_on_retained_last4_input_blocks_governed_chat(client, definitions, mask, text):
    from app.services.model_gateway.litellm.errors import LiteLLMGatewayError

    _install_retained(definitions, mask, "call_model")
    with pytest.raises(LiteLLMGatewayError) as refused:
        await _chat(text)
    assert refused.value.denial_reason == "content_obligation_insufficient"
