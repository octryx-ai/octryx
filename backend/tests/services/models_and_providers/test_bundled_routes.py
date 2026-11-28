"""Model routes of the bundled LiteLLM from Admin › Models: the route and its credential go to LiteLLM only, the alias
to the bundled provider; the admin never gets a credential back and a test call shows no content."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.models import AuditLog, LLMModel, LLMProvider
from app.services.model_gateway import bundled_litellm, bundled_routes

URL = "http://127.0.0.1:4000"
KEY = "sk-upstream-secret-0001"


class FakeLiteLLM:
    def __init__(self) -> None:
        self.models: dict[str, dict] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        path = request.url.path
        if path == "/model/info":
            return httpx.Response(200, json={"data": list(self.models.values())})
        if path == "/model/new":
            model_id = f"id-{len(self.models) + 1}"
            self.models[model_id] = {"model_name": body["model_name"], "litellm_params": body["litellm_params"],
                                     "model_info": {**body["model_info"], "id": model_id}}
            return httpx.Response(200, json={"model_id": model_id})
        if path.endswith("/update"):
            model_id = path.split("/")[2]
            current = self.models[model_id]
            current["litellm_params"] = {**current["litellm_params"], **body["litellm_params"]}
            return httpx.Response(200, json={"model_id": model_id})
        if path == "/model/delete":
            self.models.pop(body["id"])
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.fixture
async def litellm(db, monkeypatch, tmp_path):
    key_file = tmp_path / "master"
    key_file.write_text("sk-master")
    monkeypatch.setenv(bundled_litellm.URL_ENV, URL)
    monkeypatch.setenv(bundled_litellm.MASTER_KEY_FILE_ENV, str(key_file))
    fake = FakeLiteLLM()
    original = httpx.AsyncClient
    monkeypatch.setattr(bundled_routes.httpx, "AsyncClient",
                        lambda *a, **k: original(*a, **{**k, "transport": httpx.MockTransport(fake)}))

    async def no_sync(_db, _provider):
        await _db.commit()

    monkeypatch.setattr(bundled_routes, "_sync", no_sync)
    db.add(LLMProvider(name=bundled_litellm.PROVIDER_NAME, display_name="Bundled LiteLLM", driver="litellm_gateway",
                       endpoint_url=f"{URL}/v1", config_json=bundled_litellm.provider_config(URL), is_global=True))
    await db.commit()
    return fake


def _route(**overrides) -> dict:
    return {"alias": "claude-work", "provider_type": "anthropic", "model": "claude-sonnet-4-5",
            "credentials": {"api_key": KEY}, "data_policy_class": "internal", "context_limit": 200000,
            "input_per_million_usd": 3, "output_per_million_usd": 15, "tools": True, **overrides}


async def _provider(db) -> LLMProvider:
    return (await db.execute(select(LLMProvider).where(LLMProvider.name == bundled_litellm.PROVIDER_NAME))).scalar_one()


@pytest.mark.asyncio
async def test_a_route_goes_to_litellm_with_its_key_and_the_alias_to_the_provider(db, litellm):
    view = await bundled_routes.save_route(db, _route())

    deployment = next(iter(litellm.models.values()))
    assert deployment["model_name"] == "claude-work"
    assert deployment["litellm_params"] == {"model": "anthropic/claude-sonnet-4-5", "api_key": KEY}
    assert deployment["model_info"]["supports_function_calling"] is True  # the capability the gateway admits
    alias = (await _provider(db)).config_json["litellm_gateway"]["aliases"]["claude-work"]
    assert (alias["model_group"], alias["data_policy_class"], alias["served_model_ids"]) == (
        "claude-work", "internal", ["claude-sonnet-4-5"])
    assert view["state"] == "ok" and view["model"] == "claude-sonnet-4-5" and KEY not in json.dumps(view)
    listed = await bundled_routes.list_routes(db)
    assert [route["alias"] for route in listed["routes"]] == ["claude-work"] and KEY not in json.dumps(listed)
    assert KEY not in json.dumps((await _provider(db)).config_json)


@pytest.mark.asyncio
async def test_a_bedrock_route_takes_temporary_aws_credentials_and_never_shows_them(db, litellm):
    view = await bundled_routes.save_route(db, _route(
        alias="bedrock-work", provider_type="bedrock", model="eu.anthropic.claude-sonnet-5",
        credentials={"aws_region_name": "eu-west-1", "aws_access_key_id": "ASIA-test",
                     "aws_secret_access_key": "aws-secret", "aws_session_token": "sso-session-token"}))

    params = next(iter(litellm.models.values()))["litellm_params"]
    assert params["aws_session_token"] == "sso-session-token"
    assert view["settings"] == {"aws_region_name": "eu-west-1"} and "sso-session-token" not in json.dumps(view)


@pytest.mark.asyncio
async def test_an_edit_keeps_the_key_unless_a_new_one_is_given_and_a_delete_removes_both_sides(db, litellm):
    await bundled_routes.save_route(db, _route())
    db.add(LLMModel(provider_id=(await _provider(db)).id, model_id="claude-work", display_name="claude-work"))
    await db.commit()

    await bundled_routes.save_route(db, _route(credentials={}, input_per_million_usd=4), alias="claude-work")
    deployment = next(iter(litellm.models.values()))
    assert deployment["litellm_params"]["api_key"] == KEY
    assert (await _provider(db)).config_json["litellm_gateway"]["aliases"]["claude-work"]["cost"][
        "input_per_million_usd"] == 4

    await bundled_routes.delete_route(db, "claude-work")
    assert litellm.models == {} and (await _provider(db)).config_json["litellm_gateway"]["aliases"] == {}
    model = (await db.execute(select(LLMModel).where(LLMModel.model_id == "claude-work"))).scalar_one()
    assert model.is_active is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("change", "status"), [
    ({"provider_type": "copilot"}, 422), ({"credentials": {}}, 422), ({"data_policy_class": "galactic"}, 422),
    ({"alias": "Has Spaces"}, 422), ({"context_limit": 0}, 422), ({"input_per_million_usd": 0}, 422),
])
async def test_an_incomplete_route_is_refused_before_litellm_changes(db, litellm, change, status):
    with pytest.raises(Exception) as refused:
        await bundled_routes.save_route(db, _route(**change))
    assert getattr(refused.value, "status_code", None) == status and litellm.models == {}


@pytest.mark.asyncio
async def test_a_route_and_an_alias_without_each_other_show_as_needs_configuration(db, litellm):
    await bundled_routes.save_route(db, _route())
    litellm.models.clear()
    litellm.models["id-9"] = {"model_name": "orphan", "litellm_params": {"model": "openai/x"},
                              "model_info": {"id": "id-9", bundled_routes.TYPE_KEY: "openai"}}
    states = {route["alias"]: route["problem"] for route in (await bundled_routes.list_routes(db))["routes"]}
    assert states == {"claude-work": "no route in LiteLLM", "orphan": "no alias in Octryx"}


@pytest.mark.asyncio
async def test_the_test_call_goes_to_litellm_with_the_platform_key_and_shows_no_content(db, litellm, monkeypatch):
    from app.services.secret import set_secret_value

    await bundled_routes.save_route(db, _route())
    provider = await _provider(db)
    secret = await set_secret_value(db, tool_name="provider", field_name="api_key", project_id=None, value="sk-virtual")
    provider.api_key_secret_ref = secret.id
    await db.commit()
    seen = []
    original = litellm.__call__

    def answer(request):
        if request.url.path == "/v1/chat/completions":
            seen.append((request.headers["authorization"], json.loads(request.content)["model"]))
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK, private reply"}}]})
        return original(request)

    monkeypatch.setattr(litellm, "__call__", answer)
    monkeypatch.setattr(FakeLiteLLM, "__call__", lambda self, request: answer(request))
    result = await bundled_routes.test_route(db, "claude-work")
    assert result["state"] == "ok" and "private reply" not in json.dumps(result)
    assert seen == [("Bearer sk-virtual", "claude-work")]


@pytest.mark.asyncio
async def test_the_panel_routes_need_an_admin_and_audit_without_the_key(client, db, litellm, auth_headers):
    response = await client.post("/admin/chat/api/panel/model-routes", json=_route(), headers=auth_headers)
    assert response.status_code == 200, response.text
    audit = (await db.execute(select(AuditLog).where(AuditLog.resource_type == "model_route"))).scalars().all()
    assert [row.action for row in audit] == ["admin.model_route.created"] and KEY not in str(audit[0].__dict__)
    anonymous = await client.get("/admin/chat/api/panel/model-routes")
    assert anonymous.status_code in (401, 403)
