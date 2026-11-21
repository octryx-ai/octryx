"""Property cases (``test_examination_contract``) of the final check, the one budget and the one record.

Each runs under an unfinished-scan cause and asserts its own boundary: an unfinished request is refused at the final
check (``final_check``, ``model_call_outbound``), a gateway request whose deadline passed is refused unfinished and
recorded once (``gateway_outcome``), and a call's one record states the incompletion (``model_call_outcome``).
"""

from __future__ import annotations

import time

import pytest

from app.services.content_detection.examination import RequestBudget, examine_text
from app.services.content_detection.final_check import FinalCheck, FinalCheckRefused, examine_request
from app.services.content_detection.scanner import DetectorSet
from app.services.content_security.handling import SURFACE_PLATFORM, plan_for

TEXT = "deploy notes for 10.11.0.1"
IP = frozenset({"internal_ip"})


def _payload() -> dict:
    return {"model": "m", "messages": [{"role": "user", "content": TEXT}]}


async def final_check_case(fx):
    with pytest.raises(FinalCheckRefused) as refused:
        examine_request(FinalCheck(IP, RequestBudget()), _payload())
    assert refused.value.reason == "content_scan_unfinished" and refused.value.kinds == frozenset()


async def model_call_outbound_case(fx):
    from app.services.content_security.model_call_outbound import bound_constant, final_body

    with pytest.raises(FinalCheckRefused) as refused, bound_constant():
        final_body(_payload())
    assert refused.value.reason == "content_scan_unfinished"


def _spent() -> RequestBudget:
    budget = RequestBudget(deadline_ms=0.001)
    time.sleep(0.002)
    return budget


async def gateway_outcome_case(fx):
    from app.services.content_routing import gateway, gateway_outcome

    entries: list[dict] = []
    fx.monkeypatch.setattr(gateway_outcome, "record_decision", entries.append)
    outcome = gateway_outcome.GatewayOutcome(budget=_spent())
    outcome.bind(route="governed", workspace_id="ws-1", session_id="s", user_id="u", alias="m")
    scan = gateway.scan_request(_payload(), "ws-1", outcome.budget)
    refused = gateway.fixed_refusal(scan, outcome, scan.finished and not outcome.budget.overrun)
    assert refused.reason == "content_scan_unfinished" and refused.http_status == 400
    outcome.write()
    outcome.write()  # idempotent: written once
    (entry,) = entries
    assert (entry["obligation"]["outcome"], entry["obligation"]["fixed"]) == ("refused", "unfinished")


async def model_call_outcome_case(fx):
    from app.services.content_security import model_call_outcome

    entries: list[dict] = []
    fx.monkeypatch.setattr(model_call_outcome, "record_decision", entries.append)
    from app.services.content_detection.request_examination import RequestExaminer
    from app.services.content_security.model_call_fields import RecordedRun

    outcome = model_call_outcome.CallOutcome("model_call", "m", plan_for({}, SURFACE_PLATFORM))
    run = RecordedRun(RequestExaminer(DetectorSet(builtin=IP), RequestBudget()), frozenset())
    run.text(TEXT)  # not fully examined: withheld, its partial findings choose nothing
    outcome.input = run
    outcome.withhold(run.withheld_at)
    outcome.dispatched(examine_text("ok", "prompt", DetectorSet(builtin=IP)))
    result = outcome.forwarded({"content": "ok"}, "m", {})
    outcome.write()
    (entry,) = entries
    assert entry["content"]["unfinished"] is True and entry["content"]["detected"] == []
    assert entry["obligation"]["withheld"] == {"messages": 1} and result["content_obligation"]["withheld"] == 1


FINAL_CASES = {
    "app.services.content_detection.final_check": final_check_case,
    "app.services.content_security.model_call_outbound": model_call_outbound_case,
    "app.services.content_routing.gateway_outcome": gateway_outcome_case,
    "app.services.content_security.model_call_outcome": model_call_outcome_case,
}
