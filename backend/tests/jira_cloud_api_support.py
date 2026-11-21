"""Shared helpers for the Jira Cloud API tests (test_jira_cloud_api*)."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

import app.services.secure_work.jira.jira_connector as connector_module
import app.services.secure_work.jira.jira_state_sync as state_sync_module
import app.tools.jira_impl._jira_query_search as search_module
import app.tools.jira_impl._jira_query_ticket_actions as ticket_actions_module
import app.tools.jira_impl._jira_release_bundle as bundle_module
import app.tools.jira_impl._jira_ticket_tools as ticket_tools_module
from app.tools.registry import ToolContext
from tests import source_stub_support as stubs

cloud_stub = stubs.load("jira_stub_cloud")


CLOUD_URL = "https://your-site.atlassian.net"


MODULES = (search_module, ticket_actions_module, ticket_tools_module, bundle_module, connector_module, state_sync_module)


def _cloud_config(**extra) -> dict:
    return {"jira_url": CLOUD_URL, "jira_auth_mode": "cloud_api_token", "jira_email": cloud_stub.CLOUD_EMAIL,
            "jira_token": cloud_stub.CLOUD_TOKEN, "jira_allowed_projects": ["OPS"], **extra}


def _context(config: dict) -> ToolContext:
    return ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1", project_config=config,
                       capability_type="change", agent_mode_key="change", workspace_root="/tmp")


def _cloud_transport(seen: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        target = request.url.raw_path.decode()
        seen.append({"method": request.method, "path": request.url.path,
                     "query": parse_qs(urlsplit(target).query), "body": body})
        status, payload = cloud_stub.handle(request.method, target, request.headers.get("Authorization"), body)
        return httpx.Response(status) if status == 204 else httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


@pytest.fixture
def cloud(monkeypatch) -> list[dict]:
    seen: list[dict] = []
    transport = _cloud_transport(seen)
    for module in MODULES:
        monkeypatch.setattr(module, "egress_transport", lambda *_args, **_kwargs: transport)
    return seen


def _no_server_only_request(seen: list[dict]) -> None:
    for request in seen:
        assert request["path"] not in {"/rest/api/2/search", "/rest/api/3/search"}
        assert not request["path"].startswith("/rest/api/2/"), request["path"]
        assert "username" not in request["query"]
