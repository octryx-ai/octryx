"""The chat driver and its units: alias switching within the catalog, resolution, masking across the request and the sticky conversation state."""

from __future__ import annotations

import json
import logging
import uuid

import pytest
from sqlalchemy import select

from app.models import ContentConversationState
from tests.content_detection.content_obligations_support import DATA_TEXT, EMAIL, ROUTE_GOVERNED, ROUTED, ROUTED_ID
from tests.model_gateway.conftest import ALIAS, gateway_config
from tests.model_gateway.test_inbound_anthropic_gateway import _request_body
from tests.policy_engine_support import use_custom_policies


@pytest.mark.asyncio
async def test_chat_masks_and_switches_alias_within_the_catalog(client):
    from app.services.content_routing.chat import apply_chat_content
    from app.services.model_gateway.litellm.alias_catalog import resolve_alias_admission
    from app.services.prompt_catalog import prompt_set_scope
    from tests.model_gateway.conftest import verified_admission

    config = gateway_config()
    approved = dict(config["litellm_gateway"]["aliases"][ALIAS], approved_data_categories=["pii"])
    config["litellm_gateway"]["aliases"]["approved-model"] = approved
    current = resolve_alias_admission(ALIAS, config).entry
    target = resolve_alias_admission("approved-model", config).entry
    admits = {ALIAS: current, "approved-model": target}
    policy = ROUTED.replace(f'@reroute_to("{ALIAS}")', '@reroute_to("approved-model")')
    use_custom_policies(policy, mode="enforce")
    admission = verified_admission(ALIAS, "approved-model")
    messages = [{"role": "user", "content": DATA_TEXT}]
    from app.db import core as db_core
    from app.services.prompt_catalog import resolve_prompt_set

    async with db_core.async_session_factory() as db:
        prompt_set = await resolve_prompt_set(db, workspace_id=None)
    with prompt_set_scope(prompt_set):
        result = await apply_chat_content(admission, current, messages, admit=lambda alias: (admits[alias], None),
                                          tools=True)
    assert result.entry.alias == "approved-model"
    assert EMAIL not in json.dumps(result.messages) and result.messages[-1]["role"] == "system"
    assert result.notice["model_to"] == "approved-model" and result.notice["found"] == {"email": 1, "phone": 1}


def test_resolve_never_repairs_a_baseline_denial_or_routes_a_tool_result():
    from app.services.content_routing.obligations import Obligation, Unresolved, resolve

    text = ROUTED
    assert isinstance(resolve([ROUTED_ID], frozenset({ROUTED_ID}), text), Obligation)
    baseline = resolve(["platform:secrets-never-leave", ROUTED_ID], frozenset({ROUTED_ID}), text)
    assert isinstance(baseline, Unresolved) and baseline.reason == "content_policy_denied"
    assert baseline.policies == ("platform:secrets-never-leave", ROUTED_ID)
    routed_tool_result = resolve([ROUTED_ID], frozenset({ROUTED_ID}), text, tool_result=True)
    assert isinstance(routed_tool_result, Unresolved)


def test_a_stored_mask_of_a_removed_detector_masks_only_the_known_ones(caplog):
    from app.services.content_routing.obligations import Obligation, resolve

    text = ('@id("legacy-mask")\n@obligation("mask")\n@mask("retired_one,retired_two,email")\n@mask_style("last4")\n'
            'forbid (principal, action == Action::"call_model", resource)\n'
            'when { context.content.detected.contains("email") };')
    caplog.set_level(logging.INFO, logger="app.services.content_routing.obligations")
    resolved = resolve(["legacy-mask"], frozenset({"legacy-mask"}), text)
    assert isinstance(resolved, Obligation)
    assert resolved.kind == "mask" and resolved.mask == frozenset({"email"}) and resolved.mask_style == "last4"
    [record] = [item for item in caplog.records if "content_obligation_unknown_detector" in item.getMessage()]
    assert "retired_one" in record.getMessage() and "retired_two" in record.getMessage()
    assert "legacy-mask" in record.getMessage()


@pytest.mark.asyncio
async def test_conversation_state_accumulates_and_keeps_the_route(client, db):
    from app.models import Session
    from app.services.content_detection.scanner import scan_text
    from app.services.content_routing.conversation_state import load_state, remember
    from tests.knowledge_evidence_seed_support import seed_workspace

    workspace = await seed_workspace(db)
    user_id = None
    from app.models import User

    user_id = user_id or (await db.execute(select(User.id).limit(1))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user_id, project_id=workspace)
    db.add(session)
    await db.commit()
    await remember(session.id, "c1", scan_text(f"mail {EMAIL}", "prompt"), route_to=ALIAS)
    await remember(session.id, "c1", scan_text("key AKIA" + "ABCDEFGHIJKLMNOP", "prompt"))
    state = await load_state(session.id, "c1")
    assert state.categories == {"pii", "secrets"} and state.route_to == ALIAS
    assert (await load_state(session.id, "c2")).categories == frozenset()


@pytest.mark.asyncio
async def test_an_allowed_request_adds_its_categories_to_the_conversation(client, db, gateway_setup):
    _fake, build = gateway_setup
    headers = await build()
    response = await client.post(ROUTE_GOVERNED, json=_request_body(newest_text="login password=Hunter2024x"),
                                 headers=headers)
    assert response.status_code == 200
    [state] = (await db.execute(select(ContentConversationState))).scalars().all()
    # The gateway's badge counts its own kinds only: an email is not examined there.
    assert state.categories == ["secrets"] and state.detectors == {"credential_assignment": 1}
