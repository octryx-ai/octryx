"""Contract: successful connection tests and admin error paths keep only closed facts.

A passed connector test answers with a fixed summary, a version only when it passes the strict
version validator, closed counts and the closed runtime flags. Account names, URLs, paths, banner
lines and raw runtime metadata never come back, even when the provider answers with them. The
admin device-flow services, the project quality overview and the database connector test keep a
closed code and the exception class name, never the exception or provider text.
"""

from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace

import pytest

from app.services.connector_test import cloud, collab, devtools, incident, infra, platforms
from app.services.connector_test.failure import strict_version
from tests.connection_test_redaction_support import FAKE_HOST, FAKE_TOKEN, LEAK, LEAK_MARKERS, NARROW_TEXT

NARROW_DETAILS = re.compile(r"^[a-z0-9_=. ]+$")


RUNTIME_FLAGS = {"provider", "containerized", "host_fallback"}


# Every field a connector test could read from a provider answer carries the leak.
LEAKY_PAYLOAD = {
    "emailAddress": LEAK,
    "displayName": LEAK,
    "accountId": LEAK,
    "login": LEAK,
    "name": LEAK,
    "version": LEAK,
    "buildNumber": LEAK,
    "harbor_version": LEAK,
    "gitVersion": LEAK,
    "platform": LEAK,
    "size": LEAK,
    "count": LEAK,
    "status": LEAK,
    "username": LEAK,
    "loggedIn": True,
    "valid": True,
    "value": [{"id": LEAK}],
    "projects": [{"name": LEAK}],
    "user": {"summary": LEAK, "email": LEAK},
    "users": [{"email": LEAK}],
    "data": {"name": LEAK, "display_name": LEAK, "viewer": {"name": LEAK}},
    "entry": [{"content": {"serverName": LEAK, "version": LEAK}}],
}


class _OkResponse:
    status_code = 200
    text = LEAK

    def json(self):
        return LEAKY_PAYLOAD


class _OkClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, *args, **kwargs):
        return _OkResponse()

    post = get


OK_HTTPX = SimpleNamespace(AsyncClient=_OkClient, BasicAuth=lambda *args: None)


async def _ok_kubectl(*args, **kwargs):
    return 0, json.dumps({"clientVersion": {"gitVersion": LEAK}, "serverVersion": {"gitVersion": LEAK}}), LEAK


async def _docker_runtime(*args, **kwargs):
    return SimpleNamespace(provider="docker")


async def _ok_execute(**kwargs):
    stdout = json.dumps({"terraform_version": LEAK, LEAK: {"hosts": [LEAK]}, "_meta": {}})
    return SimpleNamespace(
        exit_code=0,
        stdout=stdout,
        stderr=LEAK,
        timed_out=False,
        metadata={"provider": "host", "containerized": False, "fallback_reason": LEAK, "image": LEAK},
    )


PROBE = {"resolve_runtime_config_fn": _docker_runtime, "execute_with_runtime_fn": _ok_execute, "which_fn": None}


URL = f"https://{FAKE_HOST}"


def _http(fn, config):
    return lambda monkeypatch: fn(config, httpx_module=OK_HTTPX)


def _kubectl(monkeypatch):
    monkeypatch.setattr(incident, "_run_kubectl", _ok_kubectl)
    return incident.test_kubernetes_connection({"k8s_use_kubectl": True}, httpx_module=OK_HTTPX)


def _cloud(fn, config):
    async def _leaky_json(*args, **kwargs):
        return LEAKY_PAYLOAD

    async def _leaky_token(*args, **kwargs):
        return FAKE_TOKEN

    def run(monkeypatch):
        monkeypatch.setattr(cloud.aws_core, "_aws_json", _leaky_json)
        monkeypatch.setattr(cloud.azure, "_http_json", _leaky_json)
        monkeypatch.setattr(cloud.gcp, "_http_json", _leaky_json)
        monkeypatch.setattr(cloud.azure, "_azure_token", _leaky_token)
        monkeypatch.setattr(cloud.gcp_core, "_gcp_access_token", _leaky_token)
        return fn(config)

    return run


SUCCESS_CASES = {
    "jira": _http(
        collab.test_jira_connection,
        {"jira_url": URL, "jira_auth_mode": "cloud_api_token", "jira_email": "a@x.test", "jira_token": FAKE_TOKEN},
    ),
    "bitbucket": _http(
        collab.test_bitbucket_connection,
        {"bitbucket_url": URL, "bitbucket_auth_mode": "bearer_pat", "bitbucket_token": FAKE_TOKEN},
    ),
    "github": _http(collab.test_github_connection, {"github_url": URL, "github_token": FAKE_TOKEN}),
    "confluence": _http(
        collab.test_confluence_connection,
        {"confluence_url": URL, "confluence_auth_mode": "cloud_api_token", "confluence_username": "a",
         "confluence_token": FAKE_TOKEN},
    ),
    "kubernetes_api": _http(incident.test_kubernetes_connection, {"k8s_api_url": URL, "k8s_token": FAKE_TOKEN}),
    "kubernetes_kubectl": _kubectl,
    "pagerduty": _http(incident.test_pagerduty_connection, {"pagerduty_url": URL, "pagerduty_token": FAKE_TOKEN}),
    "opsgenie": _http(incident.test_pagerduty_connection, {"opsgenie_url": URL, "opsgenie_token": FAKE_TOKEN}),
    "argocd": _http(incident.test_argocd_connection, {"argocd_url": URL, "argocd_token": FAKE_TOKEN}),
    "statuspage": _http(
        incident.test_statuspage_connection,
        {"statuspage_url": URL, "statuspage_api_key": FAKE_TOKEN, "statuspage_page_id": FAKE_HOST},
    ),
    "outlook": _http(
        platforms.test_outlook_calendar_connection,
        {"outlook_graph_url": URL, "outlook_default_mailbox": FAKE_HOST, "outlook_access_token": FAKE_TOKEN},
    ),
    "vault": _http(platforms.test_vault_connection, {"vault_url": URL, "vault_token": FAKE_TOKEN}),
    "sonarqube": _http(platforms.test_sonarqube_connection, {"sonarqube_url": URL, "sonarqube_token": FAKE_TOKEN}),
    "snyk": _http(platforms.test_snyk_connection, {"snyk_url": URL, "snyk_token": FAKE_TOKEN, "snyk_org_id": "o1"}),
    "datadog": _http(
        platforms.test_datadog_connection, {"datadog_url": URL, "datadog_api_key": FAKE_TOKEN, "datadog_app_key": "k"}
    ),
    "newrelic": _http(platforms.test_newrelic_connection, {"newrelic_url": URL, "newrelic_api_key": FAKE_TOKEN}),
    "splunk": _http(platforms.test_splunk_connection, {"splunk_url": URL, "splunk_token": FAKE_TOKEN}),
    "harbor": _http(
        devtools.test_docker_registry_connection, {"docker_registry_url": URL, "docker_registry_provider": "harbor"}
    ),
    "docker_registry": _http(devtools.test_docker_registry_connection, {"docker_registry_url": URL}),
    "linear": _http(devtools.test_linear_connection, {"linear_url": URL, "linear_api_key": FAKE_TOKEN}),
    "azure_devops": _http(
        devtools.test_azure_devops_connection, {"azure_devops_url": URL, "azure_devops_pat": FAKE_TOKEN}
    ),
    "aws": _cloud(cloud.test_aws_connection, {}),
    "azure": _cloud(cloud.test_azure_connection, {"azure_subscription_ids": "s1", "azure_management_url": URL}),
    "gcp": _cloud(cloud.test_gcp_connection, {"gcp_resourcemanager_url": URL}),
    "terraform": lambda monkeypatch: infra.test_terraform_connection({}, **PROBE),
    "ldap": lambda monkeypatch: infra.test_ldap_connection(
        {"ldap_server_url": URL, "ldap_base_dn": f"dc={FAKE_HOST}"}, **PROBE
    ),
    "ansible": lambda monkeypatch: infra.test_ansible_connection({"ansible_inventory_path": "pyproject.toml"}, **PROBE),
    "helm": lambda monkeypatch: infra.test_helm_connection({}, **PROBE),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(SUCCESS_CASES))
async def test_successful_connection_test_keeps_only_closed_facts(case, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    result = await SUCCESS_CASES[case](monkeypatch)

    assert result["ok"] is True, result
    assert NARROW_TEXT.fullmatch(result["summary"]), result["summary"]
    assert result["version"] is None or re.fullmatch(r"\d+(\.\d+)*", result["version"])
    assert all(isinstance(value, int) for value in result["counts"].values())
    assert result["details"] is None or NARROW_DETAILS.fullmatch(result["details"]), result["details"]
    if "execution_runtime" in result:
        assert set(result["execution_runtime"]) == RUNTIME_FLAGS
    serialized = json.dumps(result)
    for marker in LEAK_MARKERS:
        assert marker not in serialized, f"{case} result echoes provider or tool text"
        assert marker not in caplog.text, f"{case} logs provider or tool text"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("9.1.0", "9.1.0"),
        ("v1.29.3", "1.29.3"),
        ("10.4.1.88267", "10.4.1.88267"),
        (7, "7"),
        ("v3.14.0+g3fc9f4b", None),
        ("1.2.3-beta", None),
        ("ldapsearch: @(#) $OpenLDAP: ldapsearch 2.6.7 $", None),
        ("", None),
        (True, None),
        (None, None),
        (LEAK, None),
    ],
)
def test_strict_version_is_a_validator_not_a_parser(value, expected):
    assert strict_version(value) == expected


@pytest.mark.asyncio
async def test_valid_versions_and_counts_are_kept():
    class _VersionResponse(_OkResponse):
        def json(self):
            return {"gitVersion": "v1.29.3", "version": "9.1.0", "size": 3}

    class _VersionClient(_OkClient):
        async def get(self, *args, **kwargs):
            return _VersionResponse()

    versioned = SimpleNamespace(AsyncClient=_VersionClient)
    kubernetes = await incident.test_kubernetes_connection({"k8s_api_url": URL}, httpx_module=versioned)
    bitbucket = await collab.test_bitbucket_connection(
        {"bitbucket_url": URL, "bitbucket_auth_mode": "bearer_pat", "bitbucket_token": FAKE_TOKEN},
        httpx_module=versioned,
    )
    confluence = await collab.test_confluence_connection(
        {"confluence_url": URL, "confluence_auth_mode": "cloud_api_token", "confluence_username": "a",
         "confluence_token": FAKE_TOKEN},
        httpx_module=versioned,
    )

    assert (kubernetes["version"], kubernetes["details"]) == ("1.29.3", "version=1.29.3.")
    assert bitbucket["version"] == "9.1.0"
    assert confluence["counts"] == {"visible_spaces_in_sample": 3}
