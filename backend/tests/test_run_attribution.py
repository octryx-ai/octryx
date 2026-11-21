"""Metrics are complete and never come from the database: a run-bound gateway session carries its
run context, kept on binding and on each phase change, and the gateway's session resolution puts it into the
request's attribution, from which the token metrics take their labels."""

from __future__ import annotations

import pytest

from app.services.agent_gateway.identity import GatewayIdentity
from app.services.agent_gateway.sessions import find_gateway_session
from app.services.observability import attribution
from app.services.workflow_runs.octryx.attribution import moved_to
from tests.workflow_run_octryx_support import _bound_run, _fix_definition


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


@pytest.mark.asyncio
async def test_a_bound_session_carries_its_run_context_into_each_request(db):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    labels = gateway.metadata_["attribution"]
    assert labels == {"run": run.id, "workflow": run.workflow_key, "workspace": workspace_id, "role": "work",
                      "phase": run.current_node_id}

    run.current_node_id = "green"
    await moved_to(db, run)
    assert gateway.metadata_["attribution"]["phase"] == "green"

    attribution.use()
    assert attribution.current() is None
    identity = GatewayIdentity(user=await db.get(type(gateway).user.property.mapper.class_, gateway.user_id),
                               grant_id="gw", oauth_client_id="octryx", workspace_id=workspace_id, session_key=key,
                               work_item_key="")
    assert (await find_gateway_session(db, identity)).id == gateway.id
    assert attribution.current() == {**labels, "phase": "green"}

    with attribution.scope(run="r", ticket="", role="review"):
        assert attribution.current() == {"run": "r", "role": "review"}  # empty values left out
    assert attribution.current()["phase"] == "green"
