from __future__ import annotations

from typing import get_args

import pytest

from app.services import servicenow_scripted
from app.services.connector_auth import atlassian_modes, servicenow
from app.services.connector_auth.atlassian import resolve_credential
from app.services.connector_auth.servicenow import resolve_servicenow_auth
from app.services.connector_auth.types import (
    AtlassianAuthMode,
    AtlassianProduct,
    AtlassianScheme,
    ServiceNowAuthMode,
    ServiceNowScheme,
)
from app.services.servicenow_connector_types import (
    ApiStyle,
    FilterMode,
    RecordLimitView,
    ScriptedListing,
    WorknoteMode,
)
from app.services.servicenow_record_limit import MODES, describe, record_limit
from app.tools.context import ToolContext
from tests.servicenow_stub_support import config
from tests.support.servicenow_scripted_api_support import sn  # noqa: F401
from tests.typed_dict_support import shape_problems

TOKEN_URL = "https://idp.example.test/token"


def test_the_auth_literals_are_the_modes_and_schemes_the_code_uses():
    assert set(get_args(AtlassianAuthMode)) == set(atlassian_modes.AUTH_MODES)
    assert set(get_args(AtlassianProduct)) == set(atlassian_modes.MODE_FIELDS)
    assert set(get_args(AtlassianScheme)) == {atlassian_modes.SCHEME_BASIC, atlassian_modes.SCHEME_BEARER,
                                              atlassian_modes.SCHEME_OIDC}
    assert set(get_args(ServiceNowAuthMode)) == set(servicenow.AUTH_MODES)
    assert set(get_args(ServiceNowScheme)) == {servicenow.SCHEME_OIDC, servicenow.SCHEME_OAUTH_PASSWORD,
                                               servicenow.SCHEME_BEARER, servicenow.SCHEME_BASIC}
    assert get_args(ApiStyle) == servicenow_scripted.API_STYLES
    assert get_args(WorknoteMode) == servicenow_scripted.WORKNOTE_MODES
    assert get_args(FilterMode) == MODES


@pytest.mark.parametrize(("connector", "settings"), [
    ("jira", {"jira_auth_mode": "cloud_api_token", "jira_email": "a@example.test", "jira_token": "t"}),
    ("jira", {"jira_auth_mode": "basic", "jira_username": "u", "jira_password": "p"}),
    ("confluence", {"confluence_auth_mode": "bearer_pat", "confluence_token": "t"}),
    ("bitbucket", {"bitbucket_auth_mode": "oidc_client_credentials", "bitbucket_oidc_token_url": TOKEN_URL,
                   "bitbucket_oidc_client_id": "c", "bitbucket_oidc_client_secret": "s"}),
])
def test_a_resolved_atlassian_credential_names_a_closed_mode_and_scheme(connector, settings):
    credential = resolve_credential(connector, settings)
    assert credential is not None
    assert credential.connector in get_args(AtlassianProduct)
    assert credential.mode in get_args(AtlassianAuthMode) and credential.scheme in get_args(AtlassianScheme)


@pytest.mark.parametrize("settings", [
    {"servicenow_auth_mode": "bearer_token", "servicenow_token": "t"},
    {"servicenow_auth_mode": "basic", "servicenow_username": "u", "servicenow_password": "p"},
    {"servicenow_auth_mode": "oidc_client_credentials", "servicenow_token_url": TOKEN_URL,
     "servicenow_client_id": "c", "servicenow_client_secret": "s"},
    config(),
])
def test_a_resolved_servicenow_auth_names_a_closed_mode_and_scheme(settings):
    auth = resolve_servicenow_auth(settings)
    assert auth is not None
    assert auth.mode in get_args(ServiceNowAuthMode) and auth.scheme in get_args(ServiceNowScheme)


@pytest.mark.parametrize("settings", [
    {}, {"servicenow_assignment_groups": ["Network Ops"]},
    {"servicenow_assignment_groups": ["Network Ops"], "servicenow_services": ["Mail"], "servicenow_filter_mode": "any"},
    {"servicenow_assignment_groups": "not a list"},
])
def test_every_described_record_limit_is_a_record_limit_view(settings):
    assert shape_problems(describe(record_limit(settings)), RecordLimitView, "limit") == []


@pytest.mark.parametrize(("name", "params", "settings"), [
    ("incidents", {"limit": 3}, {}),
    ("changes", {"limit": 2}, {}),
    ("incidents", {"query": "active=true"}, {}),
    ("changes", {}, {"servicenow_changes_path": ""}),
    ("incidents", {"limit": 2}, {"servicenow_assignment_groups": ["Network Ops"]}),
])
async def test_every_scripted_listing_answer_is_a_scripted_listing(sn, name, params, settings):  # noqa: F811
    from app.tools.connectors import servicenow as tools

    tool = {"incidents": tools.ListServiceNowIncidentsTool, "changes": tools.ListServiceNowChangesTool}[name]()
    context = ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1",
                          project_config=config(**settings), workspace_root="/tmp")
    assert shape_problems(await tool.execute(params, context), ScriptedListing, "answer") == []
