"""Contract: a failed connector connection test never echoes provider or tool text.

Every admin connection-test helper is made to fail with a response body, command output or
exception message that carries a fake token, an internal URL and an internal path. The result
(shown in the admin UI and stored in the connector health log) and the captured logs must
contain none of it: only a closed reason code, the exception class name and the HTTP status or
exit code.
"""

from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace

import pytest

from app.services import connector_test_service
from app.services.connector_test import cloud, collab, devtools, incident, infra, platforms
from app.services.connector_test.failure import CONNECTION_TEST_FAILURE_REASONS

FAKE_TOKEN = "octryx-fake-token-9f8e7d6c5b4a"
FAKE_HOST = "internal-host.example.test"
FAKE_PATH = "/srv/octryx-internal/kubeconfig"
LEAK = f"401 unauthorized: token={FAKE_TOKEN} at https://{FAKE_HOST}:8443/rest?auth={FAKE_TOKEN} from {FAKE_PATH}"
LEAK_MARKERS = (FAKE_TOKEN, FAKE_HOST, FAKE_PATH, "unauthorized")

NARROW_DETAILS = re.compile(r"^[A-Za-z0-9_=. ,-]+$")


class _LeakyResponse:
    status_code = 401
    text = LEAK

    def json(self):
        return {"message": LEAK}


class _LeakyClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, *args, **kwargs):
        return _LeakyResponse()

    post = get


LEAKY_HTTPX = SimpleNamespace(AsyncClient=_LeakyClient, BasicAuth=lambda *args: None)


async def _leaky_kubectl(*args, **kwargs):
    return 1, LEAK, LEAK


async def _raise_leak(*args, **kwargs):
    raise RuntimeError(LEAK)


async def _docker_runtime(*args, **kwargs):
    return SimpleNamespace(provider="docker")


async def _leaky_execute(**kwargs):
    return SimpleNamespace(
        exit_code=1,
        stdout=LEAK,
        stderr=LEAK,
        timed_out=False,
        metadata={"provider": "host", "containerized": False, "fallback_reason": LEAK},
    )


PROBE = {"resolve_runtime_config_fn": _docker_runtime, "execute_with_runtime_fn": _leaky_execute, "which_fn": None}

K8S_API = {"k8s_api_url": f"https://{FAKE_HOST}", "k8s_token": FAKE_TOKEN}
K8S_KUBECTL = {"k8s_use_kubectl": True}
JIRA = {"jira_url": f"https://{FAKE_HOST}", "jira_auth_mode": "cloud_api_token", "jira_email": "a@example.test",
        "jira_token": FAKE_TOKEN}
BITBUCKET = {"bitbucket_url": f"https://{FAKE_HOST}", "bitbucket_auth_mode": "bearer_pat", "bitbucket_token": FAKE_TOKEN}
CONFLUENCE = {"confluence_url": f"https://{FAKE_HOST}", "confluence_auth_mode": "cloud_api_token",
              "confluence_username": "a", "confluence_token": FAKE_TOKEN}


def _http(fn, config):
    return lambda monkeypatch: fn(config, httpx_module=LEAKY_HTTPX)


def _kubectl(module, call):
    def run(monkeypatch):
        monkeypatch.setattr(module, "_run_kubectl", _leaky_kubectl)
        return call()

    return run


def _cloud(attribute, fn, config):
    def run(monkeypatch):
        module, name = attribute
        monkeypatch.setattr(module, name, _raise_leak)
        return fn(config)

    return run


def _raising_dispatch(run_test):
    def run(monkeypatch):
        monkeypatch.setitem(connector_test_service.CONNECTOR_TESTS, "jira", _raise_leak)
        return run_test("jira", JIRA)

    return run


CASES = {
    # services/connector_test: the one implementation behind the connector panel, the /admin/tools
    # form, the health worker and worker readiness
    "jira": _http(collab.test_jira_connection, JIRA),
    "bitbucket": _http(collab.test_bitbucket_connection, BITBUCKET),
    "github": _http(
        collab.test_github_connection, {"github_url": "https://api.github.com", "github_token": FAKE_TOKEN}
    ),
    "confluence": _http(collab.test_confluence_connection, CONFLUENCE),
    "kubernetes_api": _http(incident.test_kubernetes_connection, K8S_API),
    "kubernetes_kubectl": _kubectl(
        incident, lambda: incident.test_kubernetes_connection(K8S_KUBECTL, httpx_module=LEAKY_HTTPX)
    ),
    "pagerduty": _http(incident.test_pagerduty_connection, {"pagerduty_token": FAKE_TOKEN}),
    "opsgenie": _http(incident.test_pagerduty_connection, {"opsgenie_token": FAKE_TOKEN}),
    "argocd": _http(
        incident.test_argocd_connection, {"argocd_url": f"https://{FAKE_HOST}", "argocd_token": FAKE_TOKEN}
    ),
    "statuspage": _http(
        incident.test_statuspage_connection, {"statuspage_api_key": FAKE_TOKEN, "statuspage_page_id": "p1"}
    ),
    "outlook_events": _http(
        platforms.test_outlook_calendar_connection,
        {"outlook_default_mailbox": "m@example.test", "outlook_access_token": FAKE_TOKEN},
    ),
    "outlook_token_exchange": _http(
        platforms.test_outlook_calendar_connection,
        {
            "outlook_default_mailbox": "m@example.test",
            "outlook_tenant_id": "t",
            "outlook_client_id": "c",
            "outlook_client_secret": FAKE_TOKEN,
        },
    ),
    "vault": _http(platforms.test_vault_connection, {"vault_url": f"https://{FAKE_HOST}", "vault_token": FAKE_TOKEN}),
    "sonarqube": _http(
        platforms.test_sonarqube_connection, {"sonarqube_url": f"https://{FAKE_HOST}", "sonarqube_token": FAKE_TOKEN}
    ),
    "snyk": _http(platforms.test_snyk_connection, {"snyk_token": FAKE_TOKEN, "snyk_org_id": "o1"}),
    "datadog": _http(platforms.test_datadog_connection, {"datadog_api_key": FAKE_TOKEN, "datadog_app_key": "k"}),
    "newrelic": _http(platforms.test_newrelic_connection, {"newrelic_api_key": FAKE_TOKEN}),
    "splunk": _http(
        platforms.test_splunk_connection, {"splunk_url": f"https://{FAKE_HOST}", "splunk_token": FAKE_TOKEN}
    ),
    "harbor": _http(
        devtools.test_docker_registry_connection,
        {"docker_registry_url": f"https://{FAKE_HOST}", "docker_registry_provider": "harbor"},
    ),
    "docker_registry": _http(devtools.test_docker_registry_connection, {"docker_registry_url": f"https://{FAKE_HOST}"}),
    "linear": _http(devtools.test_linear_connection, {"linear_api_key": FAKE_TOKEN}),
    "azure_devops": _http(
        devtools.test_azure_devops_connection,
        {"azure_devops_url": f"https://{FAKE_HOST}", "azure_devops_pat": FAKE_TOKEN},
    ),
    "aws": _cloud((cloud.aws_core, "_aws_json"), cloud.test_aws_connection, {}),
    "azure": _cloud((cloud.azure, "_azure_token"), cloud.test_azure_connection, {"azure_subscription_ids": "s1"}),
    "gcp": _cloud((cloud.gcp_core, "_gcp_access_token"), cloud.test_gcp_connection, {}),
    "terraform": lambda monkeypatch: infra.test_terraform_connection({}, **PROBE),
    "ldap": lambda monkeypatch: infra.test_ldap_connection(
        {"ldap_server_url": "ldap://directory", "ldap_base_dn": "dc=example"}, **PROBE
    ),
    "ansible": lambda monkeypatch: infra.test_ansible_connection({"ansible_inventory_path": "pyproject.toml"}, **PROBE),
    "helm": lambda monkeypatch: infra.test_helm_connection({}, **PROBE),
    "service_dispatch_raises": _raising_dispatch(connector_test_service.run_connector_connection_test),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(CASES))
async def test_failed_connection_test_keeps_only_narrow_facts(case, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    result = await CASES[case](monkeypatch)

    assert result["ok"] is False
    assert result["reason"] in CONNECTION_TEST_FAILURE_REASONS
    assert result["error_type"] is None or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", result["error_type"])
    assert result["http_status"] is None or isinstance(result["http_status"], int)
    assert NARROW_DETAILS.fullmatch(result["details"]), result["details"]
    serialized = json.dumps(result)
    captured_logs = caplog.text
    for marker in LEAK_MARKERS:
        assert marker not in serialized, f"{case} result echoes provider or tool text"
        assert marker not in captured_logs, f"{case} logs provider or tool text"
