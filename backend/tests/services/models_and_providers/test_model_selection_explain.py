"""Explain a turn: the resolver's decision for a Workspace, with its trace; nothing is dispatched."""

from __future__ import annotations

import uuid

import pytest

from app.models import LLMModel, LLMProvider, Project
from app.services.auth import create_access_token
from app.services.model_selection.explain import explain_resolution
from app.services.model_selection.gates import CatalogModel, WorkspaceScope
from app.services.model_selection.platform_order import save_order
from app.services.model_selection.resolver import ModelRequest
from app.services.model_selection.snapshot import SelectionSnapshot

ROUTE = "/api/v1/admin/model-selection/explain"


def _model(key: str, cleared: str) -> CatalogModel:
    return CatalogModel(
        key=key, provider_id="p", model_id=key, display_name=key.title(), provider_name="P", driver="bedrock_api",
        enabled=True, provider_active=True, cleared_up_to=cleared,
        capabilities={"tools": True, "vision": False, "coding": False, "long_context": False}, target_ids=(f"t-{key}",),
    )


def _snapshot(fallback: str = "next") -> SelectionSnapshot:
    models = [_model("fast", "internal"), _model("large", "confidential"), _model("strict", "restricted")]
    return SelectionSnapshot(
        models={model.key: model for model in models}, by_target={f"t-{m.key}": m.key for m in models},
        order=tuple(model.key for model in models), fallback=fallback,
    )


def _explain(scope, *, request=ModelRequest(), fail=False, fallback="next"):
    return explain_resolution(
        _snapshot(fallback), scope, workspace_name="Claims Desk", request=request, first_fails=fail,
    )


CONFIDENTIAL = WorkspaceScope(data_class="confidential")


def test_automatic_turn_answers_on_the_first_cleared_model_of_the_order():
    result = _explain(CONFIDENTIAL)
    assert (result.state, result.title) == ("answered", "Answered by Large")
    # The order's #1 (Fast, Internal only) is skipped with its reason before Large starts.
    assert [step["label"] for step in result.trace] == ["Allowed", "Data", "Skipped", "Start"]


def test_a_person_choice_not_cleared_is_refused_never_swapped():
    result = _explain(CONFIDENTIAL, request=ModelRequest(person_choice="fast"))
    assert (result.state, result.title) == ("refused", "Refused · Fast")


def test_fallback_follows_the_mode_and_never_leaves_the_candidates():
    assert _explain(CONFIDENTIAL, fail=True).title == "Answered by Strict"
    assert _explain(CONFIDENTIAL, fail=True, fallback="stop").state == "error"
    alone = _explain(WorkspaceScope(data_class="restricted"), fail=True)
    assert alone.title == "Error · no allowed model left"


def test_no_cleared_model_is_needs_configuration():
    result = _explain(WorkspaceScope(data_class="secret"))
    assert result.state == "needs_configuration"


@pytest.mark.asyncio
async def test_the_api_explains_a_real_workspace(client, db, auth_user):
    provider = LLMProvider(name=f"p-{uuid.uuid4().hex[:6]}", driver="bedrock_api", display_name="P", is_active=True)
    db.add(provider)
    await db.flush()
    model = LLMModel(provider_id=provider.id, model_id=f"m-{uuid.uuid4().hex[:4]}", display_name="Vega Pro",
                     is_active=True, cleared_up_to="confidential")
    workspace = Project(id=str(uuid.uuid4()), name="Explain Desk", is_active=True,
                        config={"data_policy": {"classification": "confidential"}})
    db.add_all([model, workspace])
    await db.commit()
    await save_order(db, model_keys=[model.catalog_key], fallback="next", actor_id=auth_user.id)
    await db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(auth_user.id)}"}

    answered = await client.post(ROUTE, json={"workspace_id": workspace.id}, headers=headers)
    ignored = await client.post(ROUTE, json={"workspace_id": workspace.id, "card_data": True}, headers=headers)
    options = await client.get(f"{ROUTE}/options", headers=headers)
    missing = await client.post(ROUTE, json={"workspace_id": "nope"}, headers=headers)

    assert answered.status_code == 200 and answered.json()["title"] == "Answered by Vega Pro"
    assert ignored.status_code == 200 and ignored.json() == answered.json(), "a card_data field is ignored"
    assert any(item["name"] == "Explain Desk" and item["data_class"] == "confidential"
               for item in options.json()["workspaces"])
    assert missing.status_code == 404
    assert (await client.post(ROUTE, json={"workspace_id": workspace.id})).status_code == 401
