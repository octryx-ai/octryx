"""Unfinished examinations inside structures: the disposition and the record agree."""

from __future__ import annotations

import json

import pytest

from app.services.content_detection import scanner
from app.services.content_detection.builtin import CandidateLimitError
from app.services.content_detection.masking import WITHHELD_TEXT
from app.services.content_routing import gateway_outcome
from app.services.policy_engine.runtime import PolicyRuntime, set_policy_runtime
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture
from tests.model_gateway.model_gateway_openai_responses_support import responses_setup  # noqa: F401 - fixture

LEAF = "rotation notes for host 10.12.0.1"
STRUCTURE = {"note": LEAF, "owner": "platform team"}


@pytest.fixture
def unfinished_structure(monkeypatch):
    real = scanner._find

    def find(text, detectors):
        if LEAF in text:
            raise CandidateLimitError()
        return real(text, detectors)

    monkeypatch.setattr(scanner, "_find", find)
    set_policy_runtime(PolicyRuntime())
    entries: list[dict] = []
    monkeypatch.setattr(gateway_outcome, "record_decision", entries.append)
    return entries


def _refused(response, sent: list, entries: list[dict], reason: str) -> None:
    assert reason == "content_scan_unfinished", response.text
    assert sent == []
    (entry,) = entries
    assert entry["obligation"]["fixed"] == "unfinished"
    assert entry["content"] == {"scanned": True, "complete": False, "unfinished": True}


@pytest.mark.asyncio
async def test_the_anthropic_route_refuses_an_unfinished_re_sent_structure(client, db, gateway_setup,  # noqa: F811
                                                                           unfinished_structure):
    from tests.model_gateway.conftest import ALIAS
    from tests.model_gateway.test_inbound_anthropic_gateway import ROUTE

    fake, build = gateway_setup
    body = {"model": ALIAS, "max_tokens": 64, "stream": True, "messages": [
        {"role": "user", "content": "rotate the keys"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "note", "input": STRUCTURE}]},
        {"role": "user", "content": "next"}]}
    response = await client.post(ROUTE, json=body, headers=await build())
    _refused(response, fake.requests, unfinished_structure, response.headers["x-octryx-gateway-reason"])


@pytest.mark.asyncio
async def test_the_responses_route_refuses_an_unfinished_re_sent_structure(client, responses_setup,  # noqa: F811
                                                                           unfinished_structure):
    from tests.model_gateway import model_gateway_openai_responses_support as openai_support

    fake, build = responses_setup
    body = openai_support._body()
    body["input"][1:1] = [{"type": "local_shell_call", "call_id": "c2", "action": STRUCTURE}]
    for item in body["input"]:
        if item.get("type") == "function_call":
            item["arguments"] = json.dumps(STRUCTURE)
    response = await client.post(openai_support.ROUTE, json=body, headers=await build())
    _refused(response, fake.requests, unfinished_structure, response.json()["error"]["code"])


@pytest.mark.asyncio
async def test_a_part_the_mask_obligation_withholds_is_in_the_obligation_record(client, monkeypatch):
    from app.services.content_detection.request_examination import RequestExaminer
    from app.services.content_security import transport
    from tests.content_detection.content_obligations_support import DATA_TEXT, EMAIL, ROUTED
    from tests.content_detection.test_examination_boundaries import _chat
    from tests.model_gateway.conftest import ALIAS
    from tests.policy_engine_support import use_custom_policies

    use_custom_policies(ROUTED.replace(f'@reroute_to("{ALIAS}")', '@reroute_to("approved-model")'), mode="enforce")
    real = scanner._find

    class UnfinishedMasking(RequestExaminer):
        def examine(self, text, source="history"):
            def find(text, found_by):
                raise CandidateLimitError()

            monkeypatch.setattr(scanner, "_find", find)
            try:
                return super().examine(text, source)
            finally:
                monkeypatch.setattr(scanner, "_find", real)

    monkeypatch.setattr(transport, "RequestExaminer", UnfinishedMasking)
    content = await _chat([{"role": "user", "content": DATA_TEXT}])
    assert EMAIL not in json.dumps(content.messages) and WITHHELD_TEXT in json.dumps(content.messages)
    assert content.evidence["outcome"] == "remedied"
    assert content.evidence["obligation"]["withheld"] == 1 and content.evidence["obligation"]["masked"] == 0
