"""Stubbed connector API scenarios, one per sourced connector read tool, registered in ``SCENARIOS``."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import httpx

from tests.support.tools_github_source_control_support import _create_github_project, _github_context, _pr_payload
from tests.tools.connectors.connector_evidence_coverage_support import (
    ARGOCD,
    AZURE,
    BITBUCKET,
    CONFLUENCE,
    GRAFANA,
    JIRA,
    JIRA_ROUTES,
    SERVICENOW,
    SHAREPOINT,
    SONAR,
    SYS_ID,
    _client_factory,
    _context,
    _http_json,
    _jira_get,
    _route,
    _run,
)
from tests.tools.connectors.test_tools_gitlab_source_control import _create_gitlab_project, _gitlab_context, _mr_payload

Scenario = Callable[[Any, Any], Awaitable[tuple[dict, set[str]]]]
SCENARIOS: dict[str, Scenario] = {}


def scenario(*names: str):
    def register(function: Scenario) -> Scenario:
        for name in names:
            SCENARIOS[name] = function
        return function

    return register


JIRA_PARAMS = {
    "search_jira_tickets": {"jql": "project = OPS"},
    "get_jira_ticket": {"ticket_id": "OPS-2"},
    "get_sprint_issues": {"sprint_id": "3"},
    "list_jira_versions": {"project_key": "OPS"},
    "list_jira_projects": {},
    "list_jira_boards": {},
}


@scenario(*JIRA_PARAMS)
async def _jira(db, monkeypatch, name: str):
    _jira_get(monkeypatch, JIRA_ROUTES)
    return await _run(name, JIRA_PARAMS[name], _context(jira_url=JIRA)), {"jira.example.test"}


@scenario("jira_release_status")
async def _jira_release(db, monkeypatch, name: str):
    async def fake_status(db, **_kwargs):
        return {
            "state": "ok",
            "jira_project": "OPS",
            "jira_version": "2.4.20",
            "version_url": f"{JIRA}/projects/OPS/versions/10020",
            "open_blockers": [{"key": "OPS-2", "summary": "x", "url": f"{JIRA}/browse/OPS-2"}],
        }

    async def authorized(params, context):
        return SimpleNamespace(project_id="p1")

    monkeypatch.setattr("app.tools.jira_release_status.jira_release_status", fake_status)
    monkeypatch.setattr("app.tools.jira_release_status.authorized_workspace", authorized)
    return await _run(name, {"product": "ops", "version": "2.4.20"}, _context()), {"jira.example.test"}


# Confluence


@scenario("search_confluence", "get_confluence_page", "list_confluence_pages")
async def _confluence(db, monkeypatch, name: str):
    page = {"id": "123", "title": "Runbook", "space": {"key": "OPS"}, "version": {"number": 2}}
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory({"/content/search": {"results": [page]}}))

    async def fake_fetch(client, base, kwargs, **_kwargs):
        return {**page, "body": {"storage": {"value": "<p>x</p>"}}}

    async def fake_list(params, context):
        return {"pages": [page], "listing_complete": True}

    monkeypatch.setattr("app.tools.confluence.fetch_page_record", fake_fetch)
    monkeypatch.setattr("app.tools.confluence.page_allowed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("app.tools.confluence.list_confluence_pages", fake_list)
    params = {"search_confluence": {"query": "runbook"}, "get_confluence_page": {"page_id": "123"}}
    return await _run(name, params.get(name, {}), _context(confluence_url=CONFLUENCE)), {"wiki.example.test"}


# Bitbucket Server

BITBUCKET_ROUTES = {
    "/pull-requests/5": {"id": 5, "title": "Fix failover"},
    "/pull-requests": {"values": [{"id": 5, "title": "Fix failover"}]},
    "/commits/abc/changes": {"values": [{"path": {"components": ["src", "A.java"]}, "type": "MODIFY"}]},
    "/commits/abc/diff": {"diffs": []},
    "/commits": {"values": [{"id": "abc", "displayId": "abc", "authorTimestamp": 4_102_444_800_000}]},
    "/branches": {"values": [{"displayId": "main", "isDefault": True}]},
    "/browse": {"children": {"values": [{"path": {"components": ["README.md"]}, "type": "FILE"}]}},
    "/raw/": "file text",
}
BITBUCKET_PARAMS = {
    "list_bitbucket_repositories": {},
    "read_bitbucket_file": {"path": "README.md"},
    "list_bitbucket_directory": {},
    "list_bitbucket_branches": {},
    "list_bitbucket_pull_requests": {},
    "get_bitbucket_pull_request": {"pr_id": "5"},
    "list_bitbucket_commits": {},
    "list_recent_bitbucket_commits": {},
    "get_bitbucket_commit_changes": {"commit_id": "abc"},
    "get_bitbucket_diff": {"commit_id": "abc"},
}


@scenario(*BITBUCKET_PARAMS)
async def _bitbucket(db, monkeypatch, name: str):
    async def fake_get(context, path, params=None):
        return _route(BITBUCKET_ROUTES, path)

    async def branch_names(context, **_kwargs):
        return ["main"]

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_get)
    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_repository_commits._list_repo_branch_names", branch_names)
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(BITBUCKET_ROUTES))
    context = _context(bitbucket_url=BITBUCKET, bitbucket_allowed_repos=["OPS/api"])
    params = {"project_key": "OPS", "repo_slug": "api", **BITBUCKET_PARAMS[name]}
    return await _run(name, params, context), {"bitbucket.example.test"}


# GitHub / GitLab


@scenario(
    "list_github_repositories",
    "list_github_branches",
    "list_github_pull_requests",
    "get_github_pull_request",
    "list_github_issues",
    "get_github_issue",
    "read_github_file",
    "list_github_action_runs",
)
async def _github(db, monkeypatch, name: str):
    routes = {
        "/repos/example/octryx/pulls/7": _pr_payload(7),
        "/pulls": [_pr_payload(7)],
        "/issues/3": {"number": 3, "title": "Flaky"},
        "/issues": [{"number": 3, "title": "Flaky"}],
        "/branches": [{"name": "main", "commit": {"sha": "s"}}],
        "/contents/": {"content": "", "sha": "b", "html_url": "https://github.com/example/octryx/blob/main/README.md"},
        "/actions/runs": {"workflow_runs": [{"id": 9, "name": "ci", "html_url": "https://github.com/example/octryx/actions/runs/9"}]},
        "/repos/example/octryx": {"full_name": "example/octryx", "html_url": "x"},
    }
    for module in ("github", "github_issues", "github_pull_requests", "github_source_control"):
        monkeypatch.setattr(f"app.tools.connectors.{module}._http_json", _http_json(routes))
    context = _github_context(await _create_github_project(db), db=db)
    params = {"repository": "example/octryx", "pr_number": "7", "issue_number": "3", "path": "README.md"}
    return await _run(name, params, context), {"github.com"}


@scenario(
    "list_gitlab_projects",
    "list_gitlab_branches",
    "list_gitlab_merge_requests",
    "get_gitlab_merge_request",
    "list_gitlab_pipelines",
    "read_gitlab_file",
)
async def _gitlab(db, monkeypatch, name: str):
    routes = {
        "/merge_requests/9": _mr_payload(9),
        "/merge_requests": [_mr_payload(9)],
        "/repository/branches": [{"name": "main", "commit": {"id": "s"}}],
        "/repository/files/": {"content": base64.b64encode(b"x").decode(), "encoding": "base64"},
        "/pipelines": [{"id": 12, "web_url": "https://gitlab.example/group/octryx/-/pipelines/12"}],
        "/projects/": {"id": 1, "path_with_namespace": "group/octryx", "web_url": "https://gitlab.example/group/octryx"},
    }
    for module in ("gitlab", "gitlab_merge_requests", "gitlab_source_control"):
        monkeypatch.setattr(f"app.tools.connectors.{module}._http_json", _http_json(routes))
    context = _gitlab_context(await _create_gitlab_project(db), db=db)
    params = {"project": "group/octryx", "mr_iid": "9", "path": "README.md", "ref": "main"}
    return await _run(name, params, context), {"gitlab.example"}


# ServiceNow


@scenario("list_servicenow_records", "get_servicenow_record", "list_servicenow_incidents", "list_servicenow_changes")
async def _servicenow(db, monkeypatch, name: str):
    record = {"sys_id": SYS_ID, "number": "INC0010001", "short_description": "Failover drill"}
    routes = {f"/{SYS_ID}": {"result": record}, "/api/now/table/": {"result": [record]}}
    monkeypatch.setattr("app.tools.connectors.servicenow._http_json", _http_json(routes))
    params = {"table": "incident", "sys_id": SYS_ID}
    return await _run(name, params, _context(servicenow_url=SERVICENOW)), {"acme.service-now.com"}


# Notion, SharePoint, Linear / SonarQube, Azure DevOps


@scenario("search_notion_pages", "get_notion_page")
async def _notion(db, monkeypatch, name: str):
    page = {"id": "p1", "object": "page", "url": "https://www.notion.so/Runbook-p1", "properties": {}}
    routes = {"/search": {"results": [page]}, "/children": {"results": []}, "/pages/p1": page}
    monkeypatch.setattr("app.tools.connectors.notion._http_json", _http_json(routes))
    return await _run(name, {"query": "runbook", "page_id": "p1"}, _context()), {"www.notion.so"}


@scenario("search_sharepoint", "list_sharepoint_site_pages")
async def _sharepoint(db, monkeypatch, name: str):
    routes = {
        "/pages/": {"value": [{"id": "1", "title": "Runbook", "webUrl": f"{SHAREPOINT}/sites/ops/SitePages/Runbook.aspx"}]},
        "/sites/acme": {"id": "site-1"},
        "/v1.0/sites": {"value": [{"id": "s", "displayName": "Ops", "webUrl": f"{SHAREPOINT}/sites/ops"}]},
    }
    monkeypatch.setattr("app.tools.connectors.sharepoint._http_json", _http_json(routes))
    context = _context(sharepoint_url=SHAREPOINT, microsoft_graph_access_token="t", sharepoint_site_paths=["/sites/ops"])
    return await _run(name, {"query": "ops"}, context), {"acme.sharepoint.com"}


@scenario("list_issues", "get_project_metrics", "get_quality_gate")
async def _sonarqube(db, monkeypatch, name: str):
    routes = {
        "/api/issues/search": {"issues": [{"key": "AX1", "rule": "java:S1", "message": "Fix"}]},
        "/api/measures/component": {"component": {"measures": [{"metric": "bugs", "value": "1"}]}},
        "/api/qualitygates/project_status": {"projectStatus": {"status": "OK"}},
    }
    for module in ("issues", "sonarqube"):
        monkeypatch.setattr(f"app.tools.connectors.{module}._http_json", _http_json(routes))
    context = _context(sonarqube_url=SONAR, issues_provider="sonarqube", sonarqube_allowed_projects=["ops-api"])
    return await _run(name, {}, context), {"sonar.example.test"}


@scenario("list_work_items", "list_pipelines")
async def _azure_devops(db, monkeypatch, name: str):
    routes = {
        "/_apis/wit/wiql": {"workItems": [{"id": 42}]},
        "/_apis/wit/workitems": {"value": [{"id": 42, "fields": {"System.Title": "Failover"}}]},
        "/_apis/pipelines": {"value": [{"id": 3, "name": "ci"}]},
    }
    monkeypatch.setattr("app.tools.connectors.azure_devops._http_json", _http_json(routes))
    return await _run(name, {}, _context(azure_devops_url=AZURE, azure_devops_project="Ops")), {"dev.azure.com"}


# Grafana, ArgoCD


@scenario("list_grafana_alerts", "read_grafana_alert", "get_dashboard_json", "render_panel_as_image")
async def _grafana(db, monkeypatch, name: str):
    routes = {
        "/alert-rules/r1": {"uid": "r1", "title": "Failover alert"},
        "/alert-rules": [{"uid": "r1", "title": "Failover alert"}],
        "/api/v2/alerts": [],
        "/api/dashboards/uid/d1": {"dashboard": {"title": "Ops"}, "meta": {}},
        "/render/d-solo/d1": b"",
    }
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(routes))
    params = {"alert_id": "r1", "dashboard_uid": "d1", "panel_id": 2}
    return await _run(name, params, _context(grafana_url=GRAFANA)), {"grafana.example.test"}


@scenario("list_apps", "get_app_status", "get_rollout_status", "list_events")
async def _argocd(db, monkeypatch, name: str):
    application = {"metadata": {"name": "ops-api"}, "status": {"sync": {"status": "Synced"}}}
    routes = {"/events": {"items": [{"reason": "Synced"}]}, "/applications/ops-api": application, "/applications": {"items": [application]}}
    monkeypatch.setattr("app.tools.connectors.argocd._http_json", _http_json(routes))
    context = _context(argocd_url=ARGOCD, argocd_allowed_applications=["ops-api"])
    return await _run(name, {"app_name": "ops-api"}, context), {"argocd.example.test"}
