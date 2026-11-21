"""A stub ServiceNow instance for the ServiceNow tests: its own OAuth (password and refresh-token grants) and two
Scripted REST resources that accept only the current Bearer token. Every name is neutral (``servicenow.test``).
"""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx

import app.services.servicenow_password_grant as grant_module

SN_URL = "https://servicenow.test"
TOKEN_URL = f"{SN_URL}/oauth_token.do"
INCIDENTS_PATH = "/api/x_test/integration/incidents"
CHANGES_PATH = "/api/x_test/integration/changes"
CLIENT_SECRET = "sn-client-secret-value"
PASSWORD = "sn-user-password-value"


def sys_id(index: int) -> str:
    return f"{index:032x}"


def record(index: int, prefix: str = "INC") -> dict:
    return {
        "sys_id": sys_id(index), "number": f"{prefix}{index:07d}", "short_description": f"Record {index}",
        "description": "Details", "state": {"display_value": "New", "value": "1"}, "priority": "3 - Moderate",
        "assigned_to": "Test User", "assignment_group": "Test Group", "opened_at": "2026-10-01 10:00:00",
        "u_custom": f"custom-{index}",
    }


class StubInstance:
    def __init__(self, *, incidents: int = 3, changes: int = 2):
        self.data = {INCIDENTS_PATH: [record(i) for i in range(1, incidents + 1)],
                     CHANGES_PATH: [record(1000 + i, "CHG") for i in range(1, changes + 1)]}
        self.list_keys = {INCIDENTS_PATH: "incidents", CHANGES_PATH: "changes"}
        self.token_forms: list[dict] = []
        self.api_requests: list[tuple[str, dict, str | None]] = []
        self.issued = 0
        self.refresh_refused = False
        self.token_answer: tuple[int, dict] | None = None
        self.api_answer: dict[str, tuple[int, object]] = {}
        self.expires_in = 1800

    @property
    def current(self) -> str:
        return f"tok-{self.issued}"

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        self.token_forms.append(form)
        if self.token_answer is not None:
            status, body = self.token_answer
            return httpx.Response(status, json=body, headers={"location": "https://elsewhere.test/t"})
        if (form.get("client_id"), form.get("client_secret")) != ("octryx-client", CLIENT_SECRET):
            return httpx.Response(401, json={"error": "invalid_client"})
        grant = form.get("grant_type")
        if grant == "refresh_token":
            if self.refresh_refused or form.get("refresh_token") != f"ref-{self.issued}":
                return httpx.Response(400, json={"error": "invalid_grant"})
        elif grant != "password" or (form.get("username"), form.get("password")) != ("integration.user", PASSWORD):
            return httpx.Response(400, json={"error": "invalid_grant"})
        self.issued += 1
        return httpx.Response(200, json={"access_token": self.current, "refresh_token": f"ref-{self.issued}",
                                         "expires_in": self.expires_in, "token_type": "Bearer"})

    def _api(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization")
        params = dict(request.url.params)
        self.api_requests.append((request.url.path, params, auth))
        if auth != f"Bearer {self.current}":
            return httpx.Response(401, json={"error": {"message": "User Not Authenticated"}})
        if request.url.path in self.api_answer:
            status, body = self.api_answer[request.url.path]
            return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
        rows = self.data.get(request.url.path)
        if rows is None:
            return httpx.Response(404, json={"error": {"message": "Not found"}})
        limit, offset = int(params.get("sysparm_limit", 100)), int(params.get("sysparm_offset", 0))
        page = rows[offset:offset + min(limit, 200)]
        return httpx.Response(200, json={"result": {
            self.list_keys[request.url.path]: page, "total": len(rows), "limit": limit, "offset": offset,
            "current_page": offset // max(limit, 1) + 1, "total_pages": -(-len(rows) // max(limit, 1)),
        }})

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            return self._token(request)
        return self._api(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


def stub_instance(monkeypatch, instance: StubInstance):
    """Every ServiceNow client's egress transport is the stub (the egress rule has its own suites)."""
    grant_module.clear_password_token_cache()

    def transport(*_args, inner=None, **_kwargs):
        return inner or instance.transport()

    import app.services.connector_test.servicenow as connection_test
    import app.services.knowledge.sources.sync.egress as sync_egress
    import app.tools.connectors.common as connector_common
    import app.tools.connectors.servicenow_scripted_tools as scripted_tools

    for module in (grant_module, connection_test, sync_egress, connector_common, scripted_tools):
        monkeypatch.setattr(module, "egress_transport", transport)
    yield instance
    grant_module.clear_password_token_cache()


def config(**extra) -> dict:
    return {
        "servicenow_url": SN_URL, "servicenow_auth_mode": "oauth_password", "servicenow_token_url": TOKEN_URL,
        "servicenow_client_id": "octryx-client", "servicenow_client_secret": CLIENT_SECRET,
        "servicenow_username": "integration.user", "servicenow_password": PASSWORD,
        "servicenow_api_style": "scripted", "servicenow_incidents_path": INCIDENTS_PATH,
        "servicenow_changes_path": CHANGES_PATH, **extra,
    }
