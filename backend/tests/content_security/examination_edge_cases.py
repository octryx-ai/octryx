"""Property cases of result-consuming edges inside already listed consumer modules (Cut 11 S-04, Part B).

A module's own case (``test_examination_contract.CASES``) does not prove what a second consumer in the same module
does with a result. This case asserts the edges themselves, under every cause of an unfinished scan
(``test_examination_contract.unfinished``), by capturing what each edge receives and the route's answer:

- the gateway decisions that act on the scan's findings (``gateway_plan.plan_inbound`` →
  ``gateway.handling_refusal``, ``client_tool_results.client_tool_result_denial``) never receive an unfinished
  scan: partial findings choose no action, name no credential kind and reach no record; the one record states only
  the fixed disposition,
  and nothing reaches the upstream;
- the Cedar conversion of the findings (``decision.decide_model_content``, ``decision.builtin_secret_decision``) is
  never built from an unfinished scan;
- the per-tool results (``GatewayScan.tool_results``) never reach a policy when only a tool result is unfinished;
- the final refusals of findings (``gateway.content_refusal``, ``gateway.tool_result_refusal``) never see an
  unfinished scan: the one record is the fixed one.
"""

from __future__ import annotations

import inspect
from typing import Any

TEXT = "deploy notes for 10.11.0.1"


def _spy(monkeypatch, module: Any, name: str) -> list[Any]:
    """Every call of ``module.name`` (sync or async) while the case runs."""
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
    """``gateway_plan.plan_inbound``: no handling or tool-result policy decision, and no credential kinds for the
    run's note, from an unfinished scan."""
    from app.services.content_routing import gateway, gateway_outcome, gateway_plan
    from tests.model_gateway.test_inbound_anthropic_gateway import ROUTE, _request_body

    entries: list[dict] = []
    fx.monkeypatch.setattr(gateway_outcome, "record_decision", entries.append)
    handled = _spy(fx.monkeypatch, gateway_plan, "handling_refusal")
    tools = _spy(fx.monkeypatch, gateway_plan, "client_tool_result_denial")
    kinds = _spy(fx.monkeypatch, gateway.GatewayScan, "secret_kinds")
    fake, build = fx.gateway
    response = await fx.client.post(ROUTE, json=_request_body(newest_text=TEXT), headers=await build())
    assert response.status_code == 400 and "content_scan_unfinished" in response.text
    assert handled == tools == kinds == [], "no action is chosen from an unfinished scan"
    (entry,) = entries
    assert entry["obligation"]["fixed"] == "unfinished" and entry["obligation"]["applied"] == {}
    assert entry["content"] == {"scanned": True, "complete": False, "unfinished": True}, "no partial finding"
    assert fake.requests == []


async def _unfinished_gateway_request(fx, body: dict) -> list[dict]:
    """``body`` on the Anthropic route under an unfinished scan: the fixed refusal, its one record (returned), and
    nothing upstream."""
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
    """``gateway_plan.plan_inbound`` → the Cedar conversion: no policy query is built from an unfinished scan."""
    from app.services.content_routing import gateway_plan
    from tests.model_gateway.test_inbound_anthropic_gateway import _request_body

    queried = _spy(fx.monkeypatch, gateway_plan, "decide_model_content")
    secret = _spy(fx.monkeypatch, gateway_plan, "builtin_secret_decision")
    await _unfinished_gateway_request(fx, _request_body(newest_text=TEXT))
    assert queried == secret == [], "Cedar never sees partial findings"


async def gateway_tool_grouping_case(fx):
    """``GatewayScan.tool_results``: an unfinished tool result never reaches the client tool-result policy, also when
    only a tool result is unfinished."""
    from app.services.content_routing import gateway_plan
    from tests.model_gateway.test_inbound_anthropic_gateway import _request_body

    denials = _spy(fx.monkeypatch, gateway_plan, "client_tool_result_denial")
    body = _request_body()
    body["messages"][2]["content"][0]["content"] = TEXT  # only the tool result is unfinished
    await _unfinished_gateway_request(fx, body)
    assert denials == [], "no tool's results reach a policy from an unfinished scan"


async def gateway_final_refusal_record_case(fx):
    """The final refusals of findings: none is built from an unfinished scan."""
    from app.services.content_routing import gateway_plan
    from tests.model_gateway.test_inbound_anthropic_gateway import _request_body

    calls = [_spy(fx.monkeypatch, gateway_plan, name) for name in ("content_refusal", "tool_result_refusal")]
    entries = await _unfinished_gateway_request(fx, _request_body(newest_text=TEXT))
    assert all(call == [] for call in calls), "no refusal is built from partial findings"
    assert entries[0]["obligation"]["requested"] == {}, "the one record names no occurrence"


#: edge case name → case (the guard's :data:`~test_examination_guard.EDGES` names them).
EDGE_CASES = {
    "edge:gateway_plan_actions": gateway_plan_actions_case,
    "edge:gateway_cedar_conversion": gateway_cedar_conversion_case,
    "edge:gateway_tool_grouping": gateway_tool_grouping_case,
    "edge:gateway_final_refusal_record": gateway_final_refusal_record_case,
}
