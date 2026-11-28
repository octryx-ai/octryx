"""Property cases of the indirect disposition consumers: under every cause of an unfinished scan nothing unread is
allowed, forwarded or returned."""

from __future__ import annotations

import json
import types

from app.services.content_detection.masking import WITHHELD_TEXT

TEXT = "deploy notes for 10.11.0.1"


async def result_adapters_case(fx):
    from app.tools.context import ToolContext
    from app.tools.result_content import content_checked, mcp_result_checked

    context = ToolContext(user_id="u", project_ids=["ws-1"], roles=[], session_id="", project_config={})
    for result in (await content_checked("crm_lookup", {"text": TEXT}, context),
                   await mcp_result_checked("mcp__crm__lookup", {"text": TEXT}, "ws-1")):
        assert TEXT not in json.dumps(result)
        assert result["reason"] == "content_scan_unfinished" and result["error_category"] == "policy_denied"


async def gateway_service_case(fx):
    from app.services.model_gateway.inbound import service
    from tests.model_gateway.test_inbound_anthropic_gateway import ROUTE, _request_body

    plans = []
    original = service.enforce_inbound

    async def spy(db, request):
        plan = await original(db, request)
        plans.append(plan)
        return plan

    fx.monkeypatch.setattr(service, "enforce_inbound", spy)
    fake, build = fx.gateway
    response = await fx.client.post(ROUTE, json=_request_body(newest_text=TEXT), headers=await build())
    [plan] = plans
    assert plan.refusal is not None and plan.refusal.reason == "content_scan_unfinished"
    assert response.status_code == 400 and fake.requests == []


async def seat_planner_case(fx):
    from app.services.content_routing.gateway_outcome import GatewayOutcome
    from app.services.model_gateway.inbound.seat_content import seat_content_plan

    session = types.SimpleNamespace(id=None, metadata_={"client": "octryx-claude"})
    identity = types.SimpleNamespace(workspace_id="ws-1", user=types.SimpleNamespace(id="u"))
    body = {"model": "claude-sonnet-5", "max_tokens": 16, "messages": [{"role": "user", "content": TEXT}]}
    plan = await seat_content_plan(fx.db, identity=identity, session=session, body=body, model=body["model"],
                                   headers={"x-claude-code-session-id": "c"}, outcome=GatewayOutcome())
    assert plan.refusal is not None and plan.refusal.reason == "content_scan_unfinished"


async def provider_base_case(fx):
    from app.agent.providers.base import BaseLLMProvider

    class Inner(BaseLLMProvider):
        name = "inner_case_driver"

        def __init__(self) -> None:
            self.sent: list = []

        async def chat(self, messages, model, tools=None, temperature=0, max_tokens=4096, reasoning_effort=None):
            self.sent.append(messages)
            return {"content": TEXT}

        async def list_models(self):
            return []

        async def close(self):
            return None

    class Outer(Inner):
        name = "outer_case_driver"

        def __init__(self) -> None:
            super().__init__()
            self.inner = Inner()

        async def chat(self, messages, model, tools=None, temperature=0, max_tokens=4096, reasoning_effort=None):
            return await self.inner.chat(messages=messages, model=model)

    outer = Outer()
    result = await outer.chat(messages=[{"role": "user", "content": TEXT}], model="m")
    assert TEXT not in json.dumps(outer.inner.sent) and WITHHELD_TEXT in json.dumps(outer.inner.sent)
    assert result["content"] == WITHHELD_TEXT


BOUNDARY_CASES = {
    "app.tools.result_content": result_adapters_case,
    "app.services.model_gateway.inbound.service": gateway_service_case,
    "app.services.model_gateway.inbound.seat_content": seat_planner_case,
    "app.agent.providers.base": provider_base_case,
}
