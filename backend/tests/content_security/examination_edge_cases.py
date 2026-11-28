"""Property cases of the result-consuming edges inside already listed consumer modules: under every cause of an
unfinished scan, no gateway decision, Cedar conversion or final refusal acts on partial findings."""

from __future__ import annotations

import inspect
from typing import Any

TEXT = "deploy notes for 10.11.0.1"


def _spy(monkeypatch, module: Any, name: str) -> list[Any]:
    calls: list[Any] = []
    original = getattr(module, name)

    async def spy_async(*args, **kwargs):
        calls.append(args)
        return await original(*args, **kwargs)

    def spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, spy_async if inspect.iscoroutinefunction(original) else spy)
    return calls


async def gateway_plan_actions_case(fx):
    from app.services.content_routing import gateway_outcome
    from app.services.content_security import enforcement_inbound, format_request_body
    from tests.model_gateway.test_inbound_anthropic_gateway import ROUTE, _request_body

    entries: list[dict] = []
    fx.monkeypatch.setattr(gateway_outcome, "record_decision", entries.append)
    handled = _spy(fx.monkeypatch, enforcement_inbound, "handling_refusal")
    tools = _spy(fx.monkeypatch, enforcement_inbound, "client_tool_result_denial")
    kinds = _spy(fx.monkeypatch, format_request_body.GatewayScan, "secret_kinds")
    fake, build = fx.gateway
    response = await fx.client.post(ROUTE, json=_request_body(newest_text=TEXT), headers=await build())
    assert response.status_code == 400 and "content_scan_unfinished" in response.text
    assert handled == tools == kinds == [], "no action is chosen from an unfinished scan"
    (entry,) = entries
    assert entry["obligation"]["fixed"] == "unfinished" and entry["obligation"]["applied"] == {}
    assert entry["content"] == {"scanned": True, "complete": False, "unfinished": True}, "no partial finding"
    assert fake.requests == []


async def _unfinished_gateway_request(fx, body: dict) -> list[dict]:
    from app.services.content_routing import gateway_outcome
    from tests.model_gateway.test_inbound_anthropic_gateway import ROUTE

    entries: list[dict] = []
    fx.monkeypatch.setattr(gateway_outcome, "record_decision", entries.append)
    fake, build = fx.gateway
    response = await fx.client.post(ROUTE, json=body, headers=await build())
    assert response.status_code == 400 and "content_scan_unfinished" in response.text
    (entry,) = entries
    assert entry["obligation"]["fixed"] == "unfinished" and entry["obligation"]["applied"] == {}
    assert entry["content"] == {"scanned": True, "complete": False, "unfinished": True}, "no partial finding"
    assert fake.requests == []
    return entries


async def gateway_cedar_conversion_case(fx):
    from app.services.content_security import enforcement_inbound
    from tests.model_gateway.test_inbound_anthropic_gateway import _request_body

    queried = _spy(fx.monkeypatch, enforcement_inbound, "decide_model_content")
    await _unfinished_gateway_request(fx, _request_body(newest_text=TEXT))
    assert queried == [], "Cedar never sees partial findings"


async def gateway_tool_grouping_case(fx):
    from app.services.content_security import enforcement_inbound
    from tests.model_gateway.test_inbound_anthropic_gateway import _request_body

    denials = _spy(fx.monkeypatch, enforcement_inbound, "client_tool_result_denial")
    body = _request_body()
    body["messages"][2]["content"][0]["content"] = TEXT
    await _unfinished_gateway_request(fx, body)
    assert denials == [], "no tool's results reach a policy from an unfinished scan"


async def gateway_final_refusal_record_case(fx):
    from app.services.content_security import enforcement_inbound
    from tests.model_gateway.test_inbound_anthropic_gateway import _request_body

    calls = [_spy(fx.monkeypatch, enforcement_inbound, name) for name in ("content_refusal", "tool_result_refusal")]
    entries = await _unfinished_gateway_request(fx, _request_body(newest_text=TEXT))
    assert all(call == [] for call in calls), "no refusal is built from partial findings"
    assert entries[0]["obligation"]["requested"] == {}, "the one record names no occurrence"


EDGE_CASES = {
    "edge:gateway_plan_actions": gateway_plan_actions_case,
    "edge:gateway_cedar_conversion": gateway_cedar_conversion_case,
    "edge:gateway_tool_grouping": gateway_tool_grouping_case,
    "edge:gateway_final_refusal_record": gateway_final_refusal_record_case,
}
