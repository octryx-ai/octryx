"""The provider wrapper's decision record per surface, and partial findings of an unfinished examination choosing
nothing."""

from __future__ import annotations

import json
from typing import Any

import pytest

import app.services.content_security.model_call_outcome as model_call_module
import app.services.content_security.model_call_scope as model_call_scope_module
from app.services.content_detection.masking import WITHHELD_TEXT
from app.services.content_security.handling import plan_for
from tests.content_security.model_call_driver_support import DIRECT, DRIVERS, Reply
from tests.model_gateway.conftest import ALIAS

pytestmark = pytest.mark.usefixtures("platform_model_call")

EMAIL = "jane.doe@example.org"
#: A text whose examination cannot finish (candidate limit), with an email found before it stopped.
UNFINISHED = f"mail {EMAIL} " + " ".join(f"10.9.{index // 250}.{index % 250}" for index in range(5200))


def _plan(monkeypatch, settings: dict[str, str], alias: str | None = ALIAS) -> list[dict[str, Any]]:
    async def plan(_scope, surface):
        return plan_for(settings, surface, alias)

    monkeypatch.setattr(model_call_scope_module, "content_handling_isolated", plan)
    entries: list[dict[str, Any]] = []
    monkeypatch.setattr(model_call_module, "record_decision", entries.append)
    return entries


async def _call(monkeypatch, messages, *, tools=None, reply: str = "ok", driver: str = DIRECT):
    harness = DRIVERS[driver](monkeypatch, Reply(reply))
    try:
        result = await harness.driver.chat(messages=messages, model=harness.model,
                                           **({"tools": tools} if tools is not None else {}))
    finally:
        await harness.driver.close()
    return result, harness.sent()


def _tool(description: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": "notify", "description": description,
                                             "parameters": {"type": "object", "properties": {}}}}


async def test_a_mask_applied_only_to_offered_tool_metadata_is_recorded(monkeypatch):
    entries = _plan(monkeypatch, {"email": "mask"})
    result, [sent] = await _call(monkeypatch, [{"role": "user", "content": "who is on call?"}],
                                 tools=[_tool(f"Notify {EMAIL}.")])
    assert EMAIL not in sent
    (entry,) = entries
    assert entry["outcome"] == "remedied"
    assert entry["obligation"]["surfaces"] == [{"surface": "offered_tools", "kind": "email", "requested": "mask",
                                                "applied": "mask"}]
    assert entry["obligation"]["applied"] == {"email": "mask"}
    assert result["content_obligation"]["masked"] >= 1 and result["content_obligation"]["decision_id"] == entry["id"]


async def test_a_mask_applied_only_to_replayed_arguments_is_recorded(monkeypatch):
    entries = _plan(monkeypatch, {"email": "refuse"})
    replayed = {"id": "call-1", "type": "function",
                "function": {"name": "notify", "arguments": json.dumps({"to": EMAIL})}}
    messages = [{"role": "user", "content": "notify the owner"},
                {"role": "assistant", "content": "", "tool_calls": [replayed]},
                {"role": "tool", "tool_call_id": "call-1", "content": "sent"},
                {"role": "assistant", "content": "Done."}, {"role": "user", "content": "thanks"}]
    _result, [sent] = await _call(monkeypatch, messages)
    assert EMAIL not in sent
    (entry,) = entries
    assert entry["obligation"]["surfaces"] == [{"surface": "replay_arguments", "kind": "email",
                                                "requested": "refuse", "applied": "mask",
                                                "reason": "refused_kind_masked"}]
    assert entry["obligation"]["requested"] == {"email": "refuse"} and entry["obligation"]["applied"] == {
        "email": "mask"}, "the record names the mask it applied, not the refusal it asked for"


async def test_a_governed_reroute_records_every_surface_it_was_found_on(monkeypatch):
    entries = _plan(monkeypatch, {"email": "mask_reroute"})
    result, [sent] = await _call(monkeypatch, [{"role": "user", "content": f"mail {EMAIL}"}],
                                 tools=[_tool(f"Notify {EMAIL}.")], reply=f"sent to {EMAIL}", driver="litellm_gateway")
    assert EMAIL not in sent and EMAIL not in result["content"]
    (entry,) = entries
    surfaces = {(item["surface"], item["applied"], item.get("reason", "")) for item in entry["obligation"]["surfaces"]}
    assert surfaces == {("messages", "mask_reroute", ""), ("offered_tools", "mask_reroute", "")}, "no reply evidence"
    assert entry["obligation"]["applied"] == {"email": "mask_reroute"} and entry["obligation"]["target"]["handling"] == ALIAS


@pytest.mark.parametrize("action", ["refuse", "reroute", "mask_reroute", "mask", "report"])
async def test_partial_findings_of_an_unfinished_text_select_no_action(action, monkeypatch):
    entries = _plan(monkeypatch, {"email": action})
    _result, [sent] = await _call(monkeypatch, [{"role": "user", "content": UNFINISHED}])
    assert EMAIL not in sent and WITHHELD_TEXT in sent, "the unfinished text keeps its fixed disposition"
    (entry,) = entries  # not refused, not rerouted (a direct driver would refuse a reroute)
    assert entry["outcome"] == "remedied"
    assert entry["obligation"]["surfaces"] == [] and entry["obligation"]["withheld"] == {"messages": 1}
    assert entry["determining"] == ["platform:unscanned-content-withheld"]


async def test_an_unfinished_tool_definition_chooses_no_reroute_target(monkeypatch):
    entries = _plan(monkeypatch, {"email": "reroute"})
    _result, [sent] = await _call(monkeypatch, [{"role": "user", "content": "hello"}], tools=[_tool(UNFINISHED)])
    assert EMAIL not in sent and "notify" not in sent, "the unfinished definition is not offered"
    (entry,) = entries
    assert entry["obligation"]["withheld"] == {"offered_tools": 1} and entry["obligation"]["surfaces"] == []


async def test_partial_findings_in_the_reply_refuse_nothing(monkeypatch):
    entries = _plan(monkeypatch, {"email": "refuse"})
    result, _sent = await _call(monkeypatch, [{"role": "user", "content": "hello"}], reply=UNFINISHED)
    assert result["content"] == WITHHELD_TEXT, "withheld (its fixed disposition), not refused on a partial finding"
    assert entries == [], "the reply writes no evidence; the clean request has no record"


SECRET_FIELD = "password: hunter22!"


def test_a_request_that_was_not_sent_has_no_record_and_a_refused_one_claims_only_refuse(monkeypatch):
    from app.services.content_security.handling import SURFACE_PLATFORM
    from app.services.content_security.model_call_outcome import CallOutcome

    entries = _plan(monkeypatch, {})
    staged = {"outcome": "remedied", "obligation": {"applied": True, "masked": 2}}
    outcome = CallOutcome("model_call", "m", plan_for({"email": "mask"}, SURFACE_PLATFORM))
    outcome.cedar, outcome.withheld_at = staged, {"messages": 1}
    assert outcome.write() is None and entries == []
    refused = CallOutcome("model_call", "m", plan_for({"email": "mask"}, SURFACE_PLATFORM))
    refused.cedar, refused.withheld_at = staged, {"messages": 1}
    refused.refuse((), "m", "content_route_unavailable", "reroute")
    refused.write()
    (entry,) = entries
    assert "cedar" not in entry["obligation"] and "withheld" not in entry["obligation"]
    assert entry["obligation"]["outcome"] == "refused" and entry["obligation"]["applied"] == {}
