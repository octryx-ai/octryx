"""An unfinished scan never yields clean, is never cached, and is withheld before anything goes on
(inbound gateway and ``check_tool_result``; the model-call wrapper is covered in ``tests/content_security``)."""

from __future__ import annotations

import json

import pytest

from app.services.content_detection.examination import RequestBudget
from app.services.content_detection.masking import WITHHELD_TEXT
from app.services.content_routing.tool_results import MAX_DEPTH, check_tool_result
from app.tools.result_content import mcp_result_checked
from tests.content_detection.test_tool_results import MASK_RESULTS, _history_body
from tests.model_gateway.test_inbound_anthropic_gateway import ROUTE
from tests.policy_engine_support import use_custom_policies

# More internal-address candidates than a detector examines in one text: its scan cannot finish.
FRAGMENT = "10.3.0.1 "
UNFINISHED = " ".join(f"10.3.{index // 250}.{index % 250}" for index in range(5200))
#: The same for the gateway, whose built-in kinds are credentials and credential assignments only.
GATEWAY_FRAGMENT = "password=Value0x"
GATEWAY_UNFINISHED = " ".join(f"password=Value{index}x" for index in range(5200))


@pytest.mark.asyncio
async def test_the_gateway_refuses_an_unfinished_re_sent_tool_result_on_every_attempt(client, db, gateway_setup):
    from app.services.content_security import format_request_body
    from tests.model_gateway.conftest import ALIAS

    fake, build = gateway_setup
    headers = await build()
    use_custom_policies(MASK_RESULTS, mode="enforce")
    body = {**_history_body(GATEWAY_UNFINISHED), "model": ALIAS}
    for _attempt in range(2):
        response = await client.post(ROUTE, json=body, headers=headers)
        assert response.status_code == 400 and "content_scan_unfinished" in response.text
    assert fake.requests == [], "nothing was forwarded"
    scanned = format_request_body.examine_request_body(body, headers["X-Octryx-Workspace"], RequestBudget())
    assert not scanned.finished and GATEWAY_FRAGMENT not in str(scanned.body.live.report.summary())


@pytest.mark.parametrize("mode", ["enforce", "shadow"])
@pytest.mark.asyncio
async def test_a_tool_result_part_the_scan_cannot_finish_is_withheld_in_every_mode(mode):
    use_custom_policies(MASK_RESULTS, mode=mode)
    deep: object = "deep text"
    for _ in range(MAX_DEPTH + 2):
        deep = {"inner": deep}
    outcome = await check_tool_result({"log": UNFINISHED, "status": "ok", "nested": deep}, tool_name="t",
                                      family=None, origin="connector", workspace_id="ws-1", session_id=None,
                                      conversation="chat")

    assert not outcome.blocked
    assert outcome.result["log"] == WITHHELD_TEXT and outcome.result["status"] == "ok"
    assert "deep text" not in json.dumps(outcome.result)
    assert outcome.notice["withheld"] == 2 and outcome.notice["reason"] == "content_scan_unfinished"


@pytest.mark.asyncio
async def test_an_mcp_result_never_leaves_with_an_unfinished_part():
    use_custom_policies(MASK_RESULTS, mode="enforce")
    result = await mcp_result_checked("search_logs", {"text": UNFINISHED}, "ws-1")

    assert result["text"] == WITHHELD_TEXT and result["content_policy"]["withheld"] == 1


@pytest.mark.asyncio
async def test_the_gateway_refuses_an_unfinished_newest_turn_before_forwarding(client, db, gateway_setup):
    from tests.model_gateway.conftest import ALIAS

    fake, build = gateway_setup
    headers = await build()
    body = {"model": ALIAS, "max_tokens": 64, "messages": [{"role": "user", "content": GATEWAY_UNFINISHED}]}
    response = await client.post(ROUTE, json=body, headers=headers)

    assert response.status_code == 400 and "content_scan_unfinished" in response.text
    assert fake.requests == [], "nothing was forwarded"


def test_the_detector_preview_never_shows_an_unfinished_sample_as_checked(monkeypatch):
    from app.services.content_detection import builtin
    from app.services.content_detection.preview import preview
    from app.services.content_detection.scanner import DetectorSet

    monkeypatch.setattr(builtin, "MAX_CANDIDATES", 3)
    answer = preview("a@example.org b@example.org c@example.org d@example.org", DetectorSet())

    assert answer["unfinished"] is True and answer["masked_text"] == WITHHELD_TEXT and answer["parts"] == []
