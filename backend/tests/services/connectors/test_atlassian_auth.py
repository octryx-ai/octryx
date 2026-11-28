"""Contract: Confluence/Jira auth modes for Atlassian Cloud and Server/Data Center."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from app.services.connector_auth.atlassian import auth_headers, resolve_credential
from app.services.connector_auth.atlassian_modes import AtlassianAuthConfigError
from app.services.connector_auth.atlassian_validation import (
    auth_failure_hint,
    confluence_cloud_url_problem,
    validate_auth_config,
)
from app.services.knowledge.sources.sync.connections import SourceConnection
from app.services.secure_work.jira.jira_connector import _jira_auth_headers as work_item_jira_headers
from app.services.tool_config.connection_fields import credential_unit_keys, global_config_for_scope
from app.services.tool_config.validation import validate_tool_config
from app.tools._confluence_access import confluence_auth_headers
from app.tools.jira_impl._jira_helpers_context import _jira_auth_headers as tool_jira_headers

ALL_CONFLUENCE = {"confluence_username": "me@example.com", "confluence_password": "pw", "confluence_token": "tok"}
ALL_JIRA = {"jira_email": "me@example.com", "jira_username": "me", "jira_token": "tok", "jira_password": "pw"}


def _basic(principal: str, secret: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{principal}:{secret}".encode()).decode()}


@pytest.mark.parametrize(("connector", "config", "expected"), [
    ("confluence", {**ALL_CONFLUENCE, "confluence_auth_mode": "cloud_api_token"}, _basic("me@example.com", "tok")),
    ("confluence", {**ALL_CONFLUENCE, "confluence_auth_mode": "basic"}, _basic("me@example.com", "pw")),
    ("confluence", {**ALL_CONFLUENCE, "confluence_auth_mode": "bearer_pat"}, {"Authorization": "Bearer tok"}),
    ("jira", {**ALL_JIRA, "jira_auth_mode": "cloud_api_token"}, _basic("me@example.com", "tok")),
    ("jira", {**ALL_JIRA, "jira_auth_mode": "basic"}, _basic("me", "pw")),
    ("jira", {**ALL_JIRA, "jira_auth_mode": "bearer_pat"}, {"Authorization": "Bearer tok"}),
])
def test_each_mode_builds_exactly_its_header(connector, config, expected):
    assert auth_headers(connector, config) == expected


@pytest.mark.parametrize(("connector", "config"), [
    # The mode's own secret is missing: the other secret is never used instead.
    ("confluence", {"confluence_username": "u", "confluence_password": "pw", "confluence_auth_mode": "cloud_api_token"}),
    ("confluence", {"confluence_username": "u", "confluence_token": "tok", "confluence_auth_mode": "basic"}),
    ("confluence", {"confluence_username": "u", "confluence_password": "pw", "confluence_auth_mode": "bearer_pat"}),
    ("jira", {"jira_email": "e", "jira_password": "pw", "jira_auth_mode": "cloud_api_token"}),
    ("jira", {"jira_username": "u", "jira_token": "tok", "jira_auth_mode": "basic"}),
    ("jira", {"jira_email": "e", "jira_username": "u", "jira_password": "pw", "jira_auth_mode": "bearer_pat"}),
    # The mode's own principal is missing: the other principal is never used instead.
    ("jira", {"jira_username": "u", "jira_token": "tok", "jira_auth_mode": "cloud_api_token"}),
    ("jira", {"jira_email": "e", "jira_password": "pw", "jira_auth_mode": "basic"}),
    ("confluence", ALL_CONFLUENCE),
    ("jira", ALL_JIRA),
    ("confluence", {**ALL_CONFLUENCE, "confluence_auth_mode": "oauth"}),
    ("jira", {**ALL_JIRA, "jira_auth_mode": ["basic"]}),
])
def test_no_cross_fallback_and_unknown_modes_resolve_to_nothing(connector, config):
    assert resolve_credential(connector, config) is None and auth_headers(connector, config) == {}


def test_every_consumer_uses_the_same_helper():
    bearer_confluence = {**ALL_CONFLUENCE, "confluence_auth_mode": "bearer_pat"}
    bearer_jira = {**ALL_JIRA, "jira_auth_mode": "bearer_pat"}
    assert confluence_auth_headers(SimpleNamespace(project_config=bearer_confluence)) == {"Authorization": "Bearer tok"}
    assert tool_jira_headers(SimpleNamespace(project_config=bearer_jira)) == {"Authorization": "Bearer tok"}
    assert work_item_jira_headers(bearer_jira) == {"Authorization": "Bearer tok"}
    credential = resolve_credential("jira", bearer_jira)
    sync = SourceConnection(kind="jira", base_url="https://jira.example.test", principal=credential.principal,
                            secret=credential.secret, scheme=credential.scheme)
    assert sync.auth_headers() == {"Authorization": "Bearer tok", "Accept": "application/json"}
    basic = SourceConnection(kind="jira", base_url="https://jira.example.test", principal="bot", secret="pw")
    assert basic.auth_headers()["Authorization"] == _basic("bot", "pw")["Authorization"]
    assert "tok" not in repr(credential) and "tok" not in repr(sync)


@pytest.mark.parametrize(("connector", "config", "fragment"), [
    ("confluence", {"confluence_auth_mode": "oauth"}, "confluence_auth_mode must be one of"),
    ("jira", {"jira_auth_mode": "cloud_api_token", "jira_email": "e"}, "Jira API token"),
    ("jira", {"jira_auth_mode": "basic", "jira_password_secret_ref": "ref-1"}, "Jira username"),
    ("confluence", {"confluence_auth_mode": "bearer_pat", "confluence_password": "pw"}, "personal access token"),
    ("jira", {"jira_email": "e"}, "Jira credentials need jira_auth_mode"),
    ("confluence", {"confluence_token_secret_ref": "ref-1"}, "Confluence credentials need confluence_auth_mode"),
])
def test_writers_refuse_unknown_or_incomplete_modes_without_echoing_values(connector, config, fragment):
    with pytest.raises(AtlassianAuthConfigError) as refused:
        validate_auth_config(connector, config)
    assert fragment in str(refused.value) and "pw" not in str(refused.value).split(": ", 1)[-1].split()
    with pytest.raises(ValueError):
        validate_tool_config(connector, config)


def test_a_stored_secret_reference_satisfies_its_mode_and_a_connection_without_credentials_passes():
    validate_auth_config("jira", {"jira_auth_mode": "bearer_pat", "jira_token_secret_ref": "ref-1"})
    validate_auth_config("confluence", {"confluence_auth_mode": "cloud_api_token", "confluence_username": "me@x.test",
                                        "confluence_token_secret_ref": "ref-2"})
    validate_auth_config("jira", {"jira_url": "https://jira.example.test"})


def test_the_auth_mode_belongs_to_the_credential_unit():
    assert "confluence_auth_mode" in credential_unit_keys("confluence")
    assert "jira_auth_mode" in credential_unit_keys("jira")
    global_config = {**ALL_JIRA, "jira_auth_mode": "basic", "jira_url": "https://jira.example.test",
                     "jira_allowed_projects": ["OPS"]}
    # A Workspace override with its own mode never mixes with the global credential.
    inherited = global_config_for_scope("jira", global_config, {"jira_auth_mode": "bearer_pat", "jira_token": "ws"})
    assert not set(inherited) & set(credential_unit_keys("jira"))
    assert inherited["jira_allowed_projects"] == ["OPS"]
    effective = {**inherited, "jira_auth_mode": "bearer_pat", "jira_token": "ws"}
    assert auth_headers("jira", effective) == {"Authorization": "Bearer ws"}


def test_hints_are_fixed_per_mode_and_the_cloud_wiki_url_is_refused_not_rewritten():
    assert "id.atlassian.com" in auth_failure_hint("confluence", {"confluence_auth_mode": "cloud_api_token"})
    assert "Personal access token mode" in auth_failure_hint("jira", {"jira_auth_mode": "bearer_pat"})
    assert "basic authentication disabled" in auth_failure_hint("jira", {"jira_auth_mode": "basic"})
    assert "authentication mode" in auth_failure_hint("jira", {})
    assert "/wiki" in confluence_cloud_url_problem("https://your-site.atlassian.net")
    assert confluence_cloud_url_problem("https://your-site.atlassian.net/wiki") is None
    assert confluence_cloud_url_problem("https://your-site.atlassian.net/wiki/") is None
    assert confluence_cloud_url_problem("https://confluence.example.com") is None


async def test_the_panel_save_validates_the_mode_before_writing_and_exposes_it(admin_client):
    url = "/admin/chat/api/panel/connectors/confluence"
    base = {"confluence_url": "https://confluence.example.com", "confluence_username": "svc"}
    unknown = await admin_client.put(url, json={**base, "confluence_auth_mode": "oauth", "confluence_password": "pw"})
    assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "atlassian_auth_invalid"
    missing = await admin_client.put(url, json={**base, "confluence_auth_mode": "bearer_pat", "confluence_password": "pw"})
    assert missing.status_code == 422 and "pw" not in missing.text
    assert (await admin_client.get("/admin/chat/api/panel/connectors")).status_code == 200

    saved = await admin_client.put(url, json={**base, "confluence_auth_mode": "bearer_pat", "confluence_token": "pat-secret-77"})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["public_fields"]["confluence_auth_mode"] == "bearer_pat"
    assert "pat-secret-77" not in saved.text and body["secret_status"]["confluence_token"] is True
    # A later save without the mode or the token keeps both (the stored reference satisfies the mode).
    kept = await admin_client.put(url, json={"confluence_url": "https://confluence.example.com", "is_active": True})
    assert kept.status_code == 200, kept.text
    assert kept.json()["public_fields"]["confluence_auth_mode"] == "bearer_pat"
    without_mode = await admin_client.put("/admin/chat/api/panel/connectors/jira", json={
        "jira_url": "https://jira.example.com", "jira_username": "svc", "jira_password": "pw"})
    assert without_mode.status_code == 422 and "jira_auth_mode" in without_mode.text and "pw" not in without_mode.text
