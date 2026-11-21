"""Named Bitbucket, GitHub and GitLab connections: instances and technical users per repository.

- GitHub binds owners and repositories, the most specific binding wins; a bound repository narrows the
  connection's allowlist, a bound owner leaves it to the token (real chat tool: URL and token per request);
- GitLab binds groups and project paths, nested paths included; a numeric project id names no key;
- Bitbucket binds repositories; its allowlist is narrowed to them (case-insensitive keys, the default's own
  rules kept), the default keeps the rest;
- a call without a key, a repository without its owner and a CI call without its provider are refused with
  the candidates; an explicit provider routes the shared CI tools;
- a named connection without its token is refused instead of calling the API anonymously;
- the admin API needs each connector's credential; GitLab has no connection test.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.admin.project.named_connection_service import save_named
from app.services.admin.project.named_connection_service import test_named as run_named_test
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.named_connections.tool_routing import routed_execute
from app.services.tool_config import upsert_tool_config
from app.tools.connectors import github_source_control
from app.tools.context import ToolContext
from tests.knowledge_evidence_seed_support import seed_workspace


def _named(ref: str, tool: str, keys: set[str], **config) -> ResolvedNamedConnection:
    return ResolvedNamedConnection(ref, tool, ref, "workspace", frozenset(keys), config)


def _context(base: dict, *named: ResolvedNamedConnection) -> ToolContext:
    config = {**base, NAMED_CONNECTIONS_KEY: NamedConnectionRoutes(tuple(named))}
    return ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s", project_config=config)


class Recorder:
    def __init__(self) -> None:
        self.configs: list[dict] = []

    async def __call__(self, params, context):
        self.configs.append(context.project_config)
        return {"ok": True}


GITHUB_DEFAULT = {"github_token": "fake-default", "github_allowed_repositories": ["other/x"]}
ACME = _named("gh-acme", "github", {"acme"}, github_token="fake-acme", github_url="https://ghe.example.test/api/v3")
PAYMENTS = _named("gh-payments", "github", {"acme/payments"}, github_token="fake-payments")


@pytest.mark.parametrize("params, token, allowed", [
    ({"repository": "acme/payments"}, "fake-payments", ["acme/payments"]),
    ({"repository": "ACME/Web"}, "fake-acme", []),
    ({"owner": "acme", "repository": "web"}, "fake-acme", []),
    ({"owner": "acme", "repository": "payments"}, "fake-payments", ["acme/payments"]),
    ({"repository": "other/x"}, "fake-default", ["other/x"]),
])
async def test_github_routes_owners_and_repositories_most_specific_first(params, token, allowed) -> None:
    execute = Recorder()
    await routed_execute("list_github_branches", params, _context(GITHUB_DEFAULT, ACME, PAYMENTS), execute)
    assert execute.configs[0]["github_token"] == token
    assert execute.configs[0]["github_allowed_repositories"] == allowed


async def test_a_real_github_tool_sends_the_connection_url_and_token(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    async def http_json(method, url, headers=None, params=None, **kwargs):
        seen.append((url, (headers or {}).get("Authorization", "")))
        return [{"name": "main", "commit": {"sha": "abc"}}]

    async def allowed(*args, **kwargs):
        return None

    monkeypatch.setattr(github_source_control, "_http_json", http_json)
    monkeypatch.setattr(github_source_control, "require_github_repository_operation", allowed)
    result = await routed_execute("list_github_branches", {"repository": "acme/web"},
                                  _context(GITHUB_DEFAULT, ACME, PAYMENTS),
                                  github_source_control.ListGitHubBranchesTool().execute)
    assert result["branches"][0]["name"] == "main"
    assert seen == [("https://ghe.example.test/api/v3/repos/acme/web/branches", "Bearer fake-acme")]


async def test_github_refusals_name_the_candidates_and_never_call_anonymously() -> None:
    execute = Recorder()
    context = _context(GITHUB_DEFAULT, ACME, PAYMENTS)
    no_owner = await routed_execute("list_github_branches", {"repository": "web"}, context, execute)
    assert no_owner["code"] == "connection_ambiguous"
    assert [c["id"] for c in no_owner["candidates"]] == ["gh-acme", "gh-payments", "default"]
    foreign = await routed_execute("list_github_branches", {"repository": "other/y"}, context, execute)
    assert foreign["code"] == "connection_not_configured_for_scope"
    tokenless = _named("gh-acme", "github", {"acme"})
    refused = await routed_execute("list_github_branches", {"repository": "acme/web"},
                                   _context(GITHUB_DEFAULT, tokenless), execute)
    assert refused["code"] == "named_connection_credential_unavailable" and execute.configs == []


async def test_the_shared_ci_tools_belong_to_the_connector_their_provider_names() -> None:
    execute = Recorder()
    context = _context(GITHUB_DEFAULT, ACME, PAYMENTS)
    await routed_execute("get_job_logs", {"provider": "github", "repository": "acme/payments", "job_id": "1"},
                         context, execute)
    assert execute.configs[0]["github_token"] == "fake-payments"
    unnamed = await routed_execute("get_job_logs", {"repository": "acme/payments", "job_id": "1"}, context, execute)
    assert unnamed["code"] == "connection_ambiguous" and "provider" in unnamed["error"]
    await routed_execute("get_job_logs", {"provider": "azure_devops", "job_id": "1"}, context, execute)
    assert len(execute.configs) == 2 and execute.configs[1] is context.project_config  # not a routed connector


GITLAB_DEFAULT = {"gitlab_url": "https://gitlab.example.test", "gitlab_token": "fake-default"}
RIVER = _named("gl-river", "gitlab", {"river"}, gitlab_url="https://gitlab.river.test", gitlab_token="fake-river")


@pytest.mark.parametrize("params, token", [
    ({"project": "river/payments/api"}, "fake-river"),
    ({"project_id": "River/web"}, "fake-river"),
    ({"project": "ops/infra"}, "fake-default"),
])
async def test_gitlab_routes_groups_and_nested_project_paths(params, token) -> None:
    execute = Recorder()
    gitlab_default = {**GITLAB_DEFAULT, "gitlab_allowed_projects": ["ops/infra"]}
    await routed_execute("list_gitlab_branches", params, _context(gitlab_default, RIVER), execute)
    assert execute.configs[0]["gitlab_token"] == token


async def test_a_numeric_gitlab_project_names_no_key_and_is_ambiguous() -> None:
    refused = await routed_execute("list_gitlab_branches", {"project": "4711"}, _context(GITLAB_DEFAULT, RIVER),
                                   Recorder())
    assert refused["code"] == "connection_ambiguous"


BITBUCKET_DEFAULT = {
    "bitbucket_url": "https://bitbucket.example.test", "bitbucket_auth_mode": "bearer_pat", "bitbucket_token": "fake-default",
    "bitbucket_allowed_repos": [{"project_key": "RIVER", "repo_slug": "payments", "enabled": True, "label": "pay"},
                                {"project_key": "OPS", "repo_slug": "infra", "enabled": True}],
}
PAY = _named("bb-pay", "bitbucket", {"river/payments", "river/ledger"}, bitbucket_url="https://bb.river.test",
             bitbucket_auth_mode="bearer_pat", bitbucket_token="fake-pay")


async def test_bitbucket_narrows_both_allowlists_to_their_repositories() -> None:
    execute = Recorder()
    context = _context(BITBUCKET_DEFAULT, PAY)
    await routed_execute("list_bitbucket_branches", {"project_key": "river", "repo_slug": "Payments"}, context, execute)
    named = execute.configs[0]
    assert named["bitbucket_token"] == "fake-pay" and named["bitbucket_url"] == "https://bb.river.test"
    assert named["bitbucket_allowed_repos"] == [
        {"project_key": "RIVER", "repo_slug": "ledger", "enabled": True},
        {"project_key": "RIVER", "repo_slug": "payments", "enabled": True, "label": "pay"},
    ]
    await routed_execute("list_bitbucket_branches", {"project_key": "OPS", "repo_slug": "infra"}, context, execute)
    assert execute.configs[1]["bitbucket_token"] == "fake-default"
    assert execute.configs[1]["bitbucket_allowed_repos"] == [{"project_key": "OPS", "repo_slug": "infra",
                                                               "enabled": True}]
    other = await routed_execute("list_bitbucket_branches", {"project_key": "X", "repo_slug": "y"}, context, execute)
    assert other["code"] == "connection_not_configured_for_scope"


async def test_the_admin_api_needs_each_connectors_credential(db) -> None:
    workspace_id = await seed_workspace(db)
    for tool, config in (("github", {"github_owner": "acme"}), ("gitlab", dict(GITLAB_DEFAULT)),
                         ("bitbucket", {"bitbucket_url": "https://bitbucket.example.test"})):
        await upsert_tool_config(db, tool_name=tool, project_id=workspace_id, config=config, is_active=True)

    async def save(tool, body):
        return await save_named(db, connector=tool, project_id=workspace_id, payload=body, actor_id=None)

    for tool, body in (("github", {"bound_scopes": ["acme"]}),
                       ("gitlab", {"bound_scopes": ["river"], "gitlab_url": "https://gitlab.river.test"}),
                       ("bitbucket", {"bound_scopes": ["RIVER/payments"], "bitbucket_url": "https://bb.test",
                                      "bitbucket_username": "svc"})):
        with pytest.raises(HTTPException) as refused:
            await save(tool, {"name": "x", **body})
        assert refused.value.status_code == 422, tool
    github = await save("github", {"name": "acme", "bound_scopes": ["acme", "acme/payments"], "github_token": "t1"})
    assert github["bound_scopes"] == ["acme", "acme/payments"]
    gitlab = await save("gitlab", {"name": "river", "bound_scopes": ["River/Sub"], "gitlab_url": "https://g.test",
                                   "gitlab_token": "t2"})
    assert gitlab["bound_scopes"] == ["river/sub"]
    bitbucket = await save("bitbucket", {"name": "pay", "bound_scopes": ["RIVER/payments"], "bitbucket_url":
                                         "https://bb.test", "bitbucket_auth_mode": "basic", "bitbucket_username": "svc",
                                         "bitbucket_password": "pw"})
    assert bitbucket["secret_status"] == {"bitbucket_token": False, "bitbucket_password": True,
                                          "bitbucket_oidc_client_secret": False}

    async def never(tool, config):
        raise AssertionError("no test runs")

    with pytest.raises(HTTPException) as untestable:
        await run_named_test(db, connector="gitlab", project_id=workspace_id, connection_id=gitlab["id"], payload={},
                         run_connection_test=never, actor_id=None)
    assert untestable.value.status_code == 409
    assert untestable.value.detail["code"] == "named_connection_test_unavailable"
