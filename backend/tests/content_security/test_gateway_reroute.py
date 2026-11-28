"""``reroute`` / ``mask_reroute`` on the coding-agent gateway: the governance alias, a Claude seat to the company route,
a ChatGPT seat refused (``content_route_unavailable``)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from sqlalchemy import select

from app.models import PolicyDecisionLog
from app.services.model_gateway.inbound import service
from app.services.policy_engine.decision_log import flush_decision_log
from tests.agent_gateway.seat_upstream_support import anthropic  # noqa: F401 - fixture
from tests.content_detection.content_obligations_support import _governed_alias
from tests.content_detection.test_content_obligations import litellm  # noqa: F401 - fixture
from tests.content_security.gateway_route_support import (
    configure,
    open_anthropic,
    open_claude_seat,
    open_codex_seat,
    open_responses,
)
from tests.model_gateway.codex_seat_support import chatgpt  # noqa: F401 - fixture
from tests.model_gateway.conftest import ALIAS
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture
from tests.model_gateway.model_gateway_openai_responses_support import responses_setup  # noqa: F401 - fixture

SECRET = "AKIA" + "ABCDEFGHIJKLMNOP"
GOVERNANCE = "governance-model"


# The governance alias is listed by the test gateway under ALIAS's provider entry. Its project admission grants and
# lists it too, as a real installation's would: the Cedar shadow reads that admission for the rerouted call (strict
# module in ``policy_engine_shadow_plugin``).
@pytest.fixture
def governance(monkeypatch) -> list[str]:
    asked: list[str] = []
    real = service.admit_inbound_call

    async def admit(db, *, workspace_id, alias, declares_tools):
        asked.append(alias)
        admitted = await real(db, workspace_id=workspace_id, alias=ALIAS if alias == GOVERNANCE else alias,
                              declares_tools=declares_tools)
        if alias != GOVERNANCE or not hasattr(admitted, "entry"):
            return admitted
        project = admitted.project_admission
        granted = {**project.policy, "allowed_aliases": [*project.policy.get("allowed_aliases", []), GOVERNANCE]}
        levels = {level: aliases | {GOVERNANCE} for level, aliases in project.level_model_aliases.items()}
        project = replace(project, policy=granted, level_model_aliases=levels)
        assert project.decide(GOVERNANCE).allowed
        return replace(admitted, entry=replace(admitted.entry, alias=GOVERNANCE), project_admission=project)

    monkeypatch.setattr(service, "admit_inbound_call", admit)
    return asked


async def _record(db) -> PolicyDecisionLog:
    await flush_decision_log(db)
    await db.commit()
    [row] = [row for row in (await db.execute(select(PolicyDecisionLog))).scalars()
             if row.resource.startswith("gateway ")]
    return row


@pytest.mark.parametrize("action", ["reroute", "mask_reroute"])
async def test_the_governed_anthropic_route_goes_to_the_governance_alias(client, db, gateway_setup,  # noqa: F811
                                                                         governance, action):
    route = await open_anthropic(gateway_setup)
    await configure(db, route.workspace_id, "secrets", action, GOVERNANCE)
    response = await client.post(route.path, json=route.body(newest=f"deploy with {SECRET}"), headers=route.headers)
    assert response.status_code == 200, response.text
    assert governance[-1] == GOVERNANCE
    [sent] = route.sent()
    assert (SECRET in json.dumps(sent)) is (action == "reroute"), "mask_reroute masks too"
    record = await _record(db)
    assert record.obligation["target"] == GOVERNANCE and record.obligation["requested"] == {"secrets": action}


async def test_the_governed_responses_route_goes_to_the_governance_alias(client, db, responses_setup,  # noqa: F811
                                                                         governance):
    route = await open_responses(responses_setup)
    await configure(db, route.workspace_id, "secrets", "mask_reroute", GOVERNANCE)
    response = await client.post(route.path, json=route.body(newest=f"deploy with {SECRET}"), headers=route.headers)
    assert response.status_code == 200, response.text
    assert governance[-1] == GOVERNANCE
    [sent] = route.sent()
    assert SECRET not in json.dumps(sent)
    assert (await _record(db)).obligation["target"] == GOVERNANCE


async def test_a_governance_alias_that_cannot_be_admitted_refuses(client, db, gateway_setup):  # noqa: F811
    route = await open_anthropic(gateway_setup)
    await configure(db, route.workspace_id, "secrets", "reroute", "not-listed")
    response = await client.post(route.path, json=route.body(newest=f"deploy with {SECRET}"), headers=route.headers)
    assert route.reason(response) == "content_route_unavailable" and route.upstream == []
    assert SECRET not in response.text


@pytest.mark.committed_db  # the seat call records in its own session (see test_seat_presence)
async def test_a_claude_code_seat_request_leaves_the_subscription(client, db, anthropic, litellm):  # noqa: F811
    route = await open_claude_seat(client, db, anthropic)
    await _governed_alias(db, route.workspace_id, approved=["secrets"])
    await configure(db, route.workspace_id, "secrets", "mask_reroute", ALIAS)
    response = await client.post(route.path, json=route.body(newest=f"deploy with {SECRET}"), headers=route.headers)
    assert response.status_code == 200, response.text
    assert anthropic.requests == [], "never the person's subscription"
    (sent,) = litellm.bodies()
    assert SECRET not in json.dumps(sent)
    clean = await client.post(route.path, json=route.body(), headers=route.headers)
    assert clean.status_code == 200 and len(anthropic.requests) == 1, "a request without the kind stays on the seat"


async def test_a_chatgpt_seat_request_cannot_be_rerouted(client, db, chatgpt):  # noqa: F811
    route = await open_codex_seat(client, db, chatgpt)
    await configure(db, route.workspace_id, "secrets", "reroute", ALIAS)
    response = await client.post(route.path, json=route.body(newest=f"deploy with {SECRET}"), headers=route.headers)
    assert route.reason(response) == "content_route_unavailable" and route.upstream == []
