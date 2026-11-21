"""Simple data classification configuration (Workspace level, effects, seat switch, Instance default).

Backend scope: authorization (member read, member cannot write, admin write, non-member 404), the effects of every
level, the cleared marker, the Instance default never overwriting, and the audit rows.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.model_gateway.data_policy.classification import DATA_CLASSIFICATION_ORDER
from tests.data_classification_settings_support import (  # noqa: F401
    _actions,
    _admin_id,
    _bearer,
    _config,
    _route,
    _workspace,
    env,
)
from tests.knowledge_evidence_seed_support import seed_member
from tests.model_gateway.conftest import gateway_config, gateway_provider


@pytest.mark.asyncio
async def test_members_read_admins_write_and_non_members_see_nothing(client, db, env):  # noqa: F811
    workspace_id = await _workspace(db)
    member = await seed_member(db, workspace_id=workspace_id, role="member")
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    outsider = await seed_member(db, workspace_id=await _workspace(db), role="owner")
    await db.commit()

    read = await client.get(_route(workspace_id), headers=await _bearer(member))
    member_write = await client.put(_route(workspace_id), json={"classification": "internal"},
                                    headers=await _bearer(member))
    outsider_read = await client.get(_route(workspace_id), headers=await _bearer(outsider))
    outsider_write = await client.put(_route(workspace_id), json={"classification": "internal"},
                                      headers=await _bearer(outsider))
    missing = await client.get(_route(str(uuid.uuid4())), headers=await _bearer(member))
    owner_write = await client.put(_route(workspace_id), json={"classification": "internal"},
                                   headers=await _bearer(owner))
    admin_write = await client.put(_route(workspace_id), json={"classification": "public"},
                                   headers=await _bearer(await _admin_id(db)))

    assert read.status_code == 200 and read.json()["can_edit"] is False
    assert (read.json()["effective"], read.json()["source"]) == (None, "unset")
    assert [level["value"] for level in read.json()["levels"]] == list(DATA_CLASSIFICATION_ORDER)
    assert member_write.status_code == 403
    assert outsider_read.status_code == outsider_write.status_code == missing.status_code == 404
    assert owner_write.status_code == 200 and owner_write.json()["can_edit"] is True
    assert admin_write.status_code == 200 and admin_write.json()["effective"] == "public"
    assert (await _config(db, workspace_id))["data_policy"] == {"classification": "public"}
    actions = await _actions(db, workspace_id)
    assert actions.count("admin.data_classification.workspace_updated") == 2
    assert actions.count("admin.project_config.updated") == 2


@pytest.mark.asyncio
async def test_every_level_reports_what_it_admits_here(client, db, env):  # noqa: F811
    db.add(gateway_provider(name=f"litellm-{uuid.uuid4().hex[:6]}", config_json=gateway_config()))
    workspace_id = await _workspace(db, {"agent_gateway_policy": {"seat_mode": "allowed"}})
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    body = (await client.get(_route(workspace_id), headers=await _bearer(owner))).json()

    effects = {level["value"]: level["effects"] for level in body["levels"]}
    for value in ("public", "internal"):
        assert effects[value]["reranker_allowed"] is effects[value]["remote_embeddings_allowed"] is True
        assert effects[value]["seat_mode_allowed"] is True and "octryx-general" in effects[value]["governed_models"]
        assert effects[value]["reasons"] == {} and effects[value]["reranker_state"] == "ok"
    for value in ("confidential", "restricted", "secret"):
        assert effects[value]["reranker_allowed"] is effects[value]["remote_embeddings_allowed"] is False
        assert effects[value]["seat_mode_allowed"] is False and "octryx-general" not in effects[value]["governed_models"]
        assert effects[value]["reasons"]["seat_mode_allowed"] == "seat_classification_too_sensitive"
        assert effects[value]["reasons"]["reranker_allowed"] == "data_policy_class_insufficient"
        assert effects[value]["reranker_state"] == "denied"
    assert body["effects"] is None and body["seat_mode"] == "allowed"


@pytest.mark.asyncio
async def test_effects_name_missing_configuration_and_a_forbidden_seat_switch(client, db, monkeypatch):
    monkeypatch.delenv("OCTRYX_KNOWLEDGE_RERANKER", raising=False)
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_EMBEDDING_SPACE", "local_mlminilm_384_v1")
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"}})
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    body = (await client.get(_route(workspace_id), headers=await _bearer(owner))).json()

    assert body["effects"]["reranker_allowed"] is False
    assert body["effects"]["reasons"]["reranker_allowed"] == "reranker_not_configured"
    assert body["effects"]["remote_embeddings_allowed"] is True  # local: nothing leaves the platform
    assert body["effects"]["reasons"]["remote_embeddings_allowed"] == "embedding_space_local"
    # An unset seat switch is open up to internal data.
    assert "seat_mode_allowed" not in body["effects"]["reasons"]
    assert (body["effective"], body["source"]) == ("internal", "workspace")


@pytest.mark.asyncio
@pytest.mark.parametrize(("change", "reason"), [
    ({"OCTRYX_KNOWLEDGE_EMBEDDING_REGION": None, "AWS_REGION": None}, "region_missing"),
    ({"OCTRYX_KNOWLEDGE_RERANKER": "no_such_reranker"}, "reranker_unknown"),
])
async def test_the_reranker_effect_is_the_runtime_admission(client, db, env, change, reason):  # noqa: F811
    """Where search would answer ``rerank: needs_configuration``, the card never says allowed."""
    from app.services.knowledge.rerank.admission_state import reranker_admission

    for name, value in change.items():
        if value is None:
            env.delenv(name, raising=False)
        else:
            env.setenv(name, value)
    workspace_id = await _workspace(db, {"data_policy": {"classification": "public"}})
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    body = (await client.get(_route(workspace_id), headers=await _bearer(owner))).json()
    runtime = await reranker_admission(db, project_id=workspace_id)

    assert (runtime["state"], runtime["hold_reason"]) == ("needs_configuration", reason)
    for level in body["levels"]:
        effects = level["effects"]
        assert effects["reranker_allowed"] is False, level["value"]
        assert (effects["reranker_state"], effects["reasons"]["reranker_allowed"]) == ("needs_configuration", reason)


@pytest.mark.asyncio
async def test_the_reranker_effect_of_the_effective_level_matches_the_runtime(client, db, env):  # noqa: F811
    from app.services.knowledge.rerank.admission_state import reranker_admission

    for level, allowed in (("internal", True), ("confidential", False)):
        workspace_id = await _workspace(db, {"data_policy": {"classification": level}})
        owner = await seed_member(db, workspace_id=workspace_id, role="owner")
        await db.commit()
        body = (await client.get(_route(workspace_id), headers=await _bearer(owner))).json()
        runtime = await reranker_admission(db, project_id=workspace_id)
        assert body["effects"]["reranker_allowed"] is allowed is (runtime["state"] == "ok"), level


@pytest.mark.asyncio
async def test_clearing_sets_the_marker_and_an_unknown_level_is_refused(client, db, env):  # noqa: F811
    workspace_id = await _workspace(db, {"data_policy": {"classification": "internal"}})
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()
    headers = await _bearer(owner)

    unknown = await client.put(_route(workspace_id), json={"classification": "top-secret"}, headers=headers)
    missing = await client.put(_route(workspace_id), json={}, headers=headers)
    cleared = await client.put(_route(workspace_id), json={"classification": None}, headers=headers)

    assert unknown.status_code == 422 and unknown.json()["detail"]["errors"][0]["code"] == "data_classification_unknown"
    assert missing.status_code == 422
    assert cleared.status_code == 200 and cleared.json()["cleared"] is True and cleared.json()["effective"] is None
    assert (await _config(db, workspace_id))["data_policy"] == {"classification_cleared": True}


def test_effects_cover_every_level_in_the_platform_order():
    assert list(DATA_CLASSIFICATION_ORDER) == ["public", "internal", "confidential", "restricted", "secret"]


@pytest.mark.asyncio
async def test_every_level_carries_its_plain_language_description(client, db, env):  # noqa: F811
    workspace_id = await _workspace(db)
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()

    levels = (await client.get(_route(workspace_id), headers=await _bearer(owner))).json()["levels"]

    descriptions = {level["value"]: level["description"] for level in levels}
    assert set(descriptions) == set(DATA_CLASSIFICATION_ORDER) and all(descriptions.values())
    assert descriptions["internal"] == "Company-internal data; may be processed by approved external models."
