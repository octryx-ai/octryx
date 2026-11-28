"""Stubs for the OIDC tests: a local identity provider and systems that accept only its current Bearer token."""

from __future__ import annotations

import asyncio
import base64
from urllib.parse import parse_qs

import httpx

import app.services.connector_auth.oidc_token_cache as oidc_tokens
from app.services.knowledge.sources.sync import egress as sync_egress
from app.tools.context import ToolContext

IDP = "https://idp.test/realms/r/protocol/openid-connect/token"
SECRET = "s3cr3t-client-value"
JIRA_URL, WIKI_URL, SN_URL = "https://jira.test", "https://wiki.test", "https://sn.test"


class StubIdp:
    def __init__(self, *, expires_in: object = 300, answer: tuple[int, dict] | None = None, delay: float = 0.0):
        self.expires_in, self.answer, self.delay = expires_in, answer, delay
        self.requests: list[httpx.Request] = []
        self.issued = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.answer is not None:
            status, body = self.answer
            return httpx.Response(status, json=body, headers={"location": "https://elsewhere.test/t"})
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        basic = request.headers.get("Authorization", "")
        if basic.startswith("Basic "):
            client_id, _, secret = base64.b64decode(basic[6:]).decode().partition(":")
        else:
            client_id, secret = form.get("client_id"), form.get("client_secret")
        if form.get("grant_type") != "client_credentials" or (client_id, secret) != ("octryx-client", SECRET):
            return httpx.Response(401, json={"error": "invalid_client"})
        self.issued += 1
        body = {"access_token": f"tok-{self.issued}", "token_type": "Bearer"}
        if self.expires_in is not None:
            body["expires_in"] = self.expires_in
        return httpx.Response(200, json=body)

    @property
    def current(self) -> str:
        return f"tok-{self.issued}"


class World:
    def __init__(self, idp: StubIdp, *, refuse_all: bool = False):
        self.idp, self.refuse_all = idp, refuse_all
        self.system_requests: list[httpx.Request] = []
        self.system_auth: list[str | None] = []  # the header as received (a retry reuses the request object)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "idp.test":
            return await self.idp(request)
        self.system_requests.append(request)
        self.system_auth.append(request.headers.get("Authorization"))
        if self.refuse_all or request.headers.get("Authorization") != f"Bearer {self.idp.current}":
            return httpx.Response(401, json={"message": "unauthorized"})
        if request.url.path.endswith("/priority"):
            return httpx.Response(200, json=[{"id": "1", "name": "High"}])
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"issues": [], "total": 0, "startAt": 0, "maxResults": 50})
        if request.url.path.endswith("/transitions"):
            return httpx.Response(200, json={"transitions": [{"id": "1", "name": "Done", "to": {"name": "Done"}}]})
        if request.url.path.startswith("/api/now/table/"):
            return httpx.Response(200, json={"result": [{"sys_id": "abc123", "number": "INC1"}]})
        return httpx.Response(200, json={"ok": True, "size": 1, "results": []})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


def stub_world(monkeypatch):
    oidc_tokens.clear_token_cache()
    state = World(StubIdp())

    def transport(*_args, inner=None, **_kwargs):
        return inner or state.transport()

    import app.services.connector_test.collab as collab
    import app.services.secure_work.jira.jira_connector as intake
    import app.services.secure_work.jira.jira_state_sync as state_sync
    import app.tools._confluence_access as confluence_access
    import app.tools.connectors.common as connector_common
    import app.tools.jira_impl._jira_query_metadata as jira_metadata

    modules = (oidc_tokens, collab, confluence_access, connector_common, jira_metadata, sync_egress, intake, state_sync)
    for module in modules:
        monkeypatch.setattr(module, "egress_transport", transport)
    yield state
    oidc_tokens.clear_token_cache()


def _jira(**extra) -> dict:
    return {"jira_url": JIRA_URL, "jira_auth_mode": "oidc_client_credentials", "jira_oidc_token_url": IDP,
            "jira_oidc_client_id": "octryx-client", "jira_oidc_client_secret": SECRET, **extra}


def _wiki(**extra) -> dict:
    return {"confluence_url": WIKI_URL, "confluence_auth_mode": "oidc_client_credentials",
            "confluence_oidc_token_url": IDP, "confluence_oidc_client_id": "octryx-client",
            "confluence_oidc_client_secret": SECRET, "confluence_allowed_spaces": [{"space_key": "ENG"}], **extra}


def _sn(**extra) -> dict:
    return {"servicenow_url": SN_URL, "servicenow_auth_mode": "oidc_client_credentials",
            "servicenow_token_url": IDP, "servicenow_client_id": "octryx-client", "servicenow_client_secret": SECRET,
            "servicenow_allowed_tables": ["incident"], **extra}


def _context(config: dict) -> ToolContext:
    return ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1", project_config=config,
                       workspace_root="/tmp")


def _form(request: httpx.Request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(request.content.decode()).items()}


async def _priorities(config: dict) -> dict:
    from app.tools.jira_impl._jira_query_metadata import ListJiraPriorities

    return await ListJiraPriorities().execute({}, _context(config))
