"""Each enforcement entry point keeps the rules ``content_security.enforcement`` names for its surface: where the
platform's provider call and the coding-agent gateway differ on purpose."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from app.services.content_detection import scanner
from app.services.content_detection.builtin import CandidateLimitError
from app.services.content_detection.examination import RequestBudget
from app.services.content_security import enforcement_inbound
from app.services.content_security.enforcement import (
    CEDAR_READS_AS_FOUND,
    CEDAR_READS_PROBED,
    GATEWAY,
    INJECTION_ANYWHERE,
    INJECTION_NEWEST_TURN,
    PLATFORM,
    SHADOW_WOULD_DENY,
    SHADOW_WOULD_REMEDY,
)
from app.services.content_security.format_request_body import examine_request_body
from tests.content_detection.content_obligations_support import DATA_TEXT, ROUTED
from tests.content_detection.test_content_admission import _records
from tests.content_detection.test_examination_boundaries import _chat
from tests.content_detection.test_tool_results import ASSIGNMENT, _history_body
from tests.content_security.gateway_route_support import messages_body, responses_body
from tests.content_security.model_call_driver_support import DRIVERS, Reply
from tests.content_security.test_model_call_whole_request import INJECTION, _plan, _refused
from tests.model_gateway.conftest import ALIAS
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture
from tests.model_gateway.test_inbound_anthropic_gateway import ROUTE, _request_body
from tests.policy_engine_support import use_custom_policies

MARKER = "unreadable-older-notes"
MASKING_ASSIGNMENTS = ('@id("mask-assignments")\n@obligation("mask")\n@mask("credential_assignment")\n'
                       'forbid (principal, action == Action::"call_model", resource)\n'
                       'when { context.content.detected.contains("credential_assignment") };')


def _captured(monkeypatch, module: Any, name: str) -> list[tuple[tuple, dict]]:
    calls: list[tuple[tuple, dict]] = []
    original = getattr(module, name)

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, spy)
    return calls


@pytest.mark.usefixtures("platform_model_call")
@pytest.mark.asyncio
async def test_injection_refuses_anywhere_on_the_platform(monkeypatch):
    assert PLATFORM.injection == INJECTION_ANYWHERE
    _plan(monkeypatch, {})
    await _refused(monkeypatch, [{"role": "user", "content": INJECTION}, {"role": "assistant", "content": "Done."},
                                 {"role": "user", "content": "thanks"}])


def test_injection_refuses_only_in_the_newest_turn_on_the_gateway():
    assert GATEWAY.injection == INJECTION_NEWEST_TURN
    for build in (messages_body, responses_body):
        assert examine_request_body(build("m", result=INJECTION), "ws-1", RequestBudget()).injection == 1
        older = examine_request_body(build("m", result=INJECTION, answered=True), "ws-1", RequestBudget())
        assert older.injection == 0, build.__name__


@pytest.mark.usefixtures("platform_model_call")
@pytest.mark.asyncio
async def test_cedar_reads_the_platform_call_with_what_the_probe_withheld(monkeypatch):
    from app.services.content_routing import chat

    assert PLATFORM.cedar_reads == CEDAR_READS_PROBED
    seen = _captured(monkeypatch, chat, "apply_chat_content")
    real = scanner._find

    def find(text, found_by):
        if MARKER in text:
            raise CandidateLimitError()
        return real(text, found_by)

    monkeypatch.setattr(scanner, "_find", find)
    harness = DRIVERS["litellm_gateway"](monkeypatch, Reply("ok"))
    try:
        await harness.driver.chat(messages=[{"role": "user", "content": f"{MARKER} from last week"},
                                            {"role": "assistant", "content": "Done."},
                                            {"role": "user", "content": "thanks"}], model=harness.model)
    finally:
        await harness.driver.close()
    ((args, _kwargs),) = seen
    assert MARKER not in json.dumps(args[2]), "Cedar reads the messages with the unfinished part withheld"


@pytest.mark.asyncio
async def test_cedar_reads_the_gateway_request_as_found(client, db, gateway_setup, monkeypatch):  # noqa: F811
    assert GATEWAY.cedar_reads == CEDAR_READS_AS_FOUND
    fake, build = gateway_setup
    headers = await build()
    seen = _captured(monkeypatch, enforcement_inbound, "decide_model_content")
    body = {**_history_body(f"login {ASSIGNMENT} failed"), "model": ALIAS}
    assert (await client.post(ROUTE, json=body, headers=headers)).status_code == 200
    assert "Hunter2024x" not in fake.requests[0].content.decode(), "the Workspace's default masks it before sending"
    assert "credential_assignment" in seen[0][1]["scans"].live.detected, "Cedar read it before the mask"


@pytest.mark.asyncio
async def test_a_platform_shadow_denial_records_the_obligation_that_would_apply(client):
    assert PLATFORM.shadow == SHADOW_WOULD_REMEDY
    use_custom_policies(ROUTED.replace(f'@reroute_to("{ALIAS}")', '@reroute_to("approved-model")'), mode="shadow")
    content = await _chat([{"role": "user", "content": DATA_TEXT}])
    assert content.evidence["outcome"] == SHADOW_WOULD_REMEDY and content.evidence["obligation"]["applied"] is False


@pytest.mark.asyncio
async def test_a_gateway_shadow_denial_records_only_that_cedar_would_deny(client, db, gateway_setup):  # noqa: F811
    assert GATEWAY.shadow == SHADOW_WOULD_DENY
    fake, build = gateway_setup
    use_custom_policies(MASKING_ASSIGNMENTS, mode="shadow")
    response = await client.post(ROUTE, json=_request_body(newest_text=f"login {ASSIGNMENT} failed"),
                                 headers=await build())
    assert response.status_code == 200 and len(fake.requests) == 1
    [record] = await _records(db)
    assert record.obligation["cedar"] == {"policies": ["mask-assignments"], "would": "deny", "applied": "none"}


@pytest.mark.asyncio
async def test_the_gateway_checks_client_tool_results_by_its_rule(client, db, gateway_setup, monkeypatch):  # noqa: F811
    assert GATEWAY.client_tool_check and not PLATFORM.client_tool_check
    fake, build = gateway_setup
    headers = await build()
    body = {**_history_body("3 passed"), "model": ALIAS}
    checked = _captured(monkeypatch, enforcement_inbound, "client_tool_result_denial")
    assert (await client.post(ROUTE, json=body, headers=headers)).status_code == 200
    monkeypatch.setattr(enforcement_inbound, "GATEWAY", replace(GATEWAY, client_tool_check=False))
    assert (await client.post(ROUTE, json=body, headers=headers)).status_code == 200
    assert len(checked) == 1, "only while the gateway's rule names the check"
