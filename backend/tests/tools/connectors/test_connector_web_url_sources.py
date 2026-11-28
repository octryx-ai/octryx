"""Connectors whose web host differs from their API host link items only with a configured, https-validated
``<connector>_web_url``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import pytest

from app.services.tool_config.presets import TOOL_CONFIG_PRESETS
from app.services.tool_config.validation import validate_tool_config
from app.services.tool_config.web_url import OPSGENIE_WEB_URL_FIELD, WEB_URL_FIELDS, normalize_web_url
from app.tools.registry import _dispatch_registered_tool
from tests.tools.connectors.connector_evidence_coverage_catalog import WEB_URL_LINKED_CONNECTOR_READS

WEB_URLS = {
    "datadog_web_url": "https://app.datadoghq.eu",
    "newrelic_web_url": "https://alerts.newrelic.com",
    "snyk_web_url": "https://app.snyk.io/org/acme",
    "pagerduty_web_url": "https://acme.pagerduty.com",
    "opsgenie_web_url": "https://acme.app.opsgenie.com",
    "statuspage_web_url": "https://status.acme.example",
    "aws_web_url": "https://eu-central-1.console.aws.amazon.com",
    "azure_web_url": "https://portal.azure.com/#@acme.onmicrosoft.com",
    "gcp_web_url": "https://console.cloud.google.com",
}


def test_every_web_url_field_is_an_admin_configurable_preset_field() -> None:
    fields = {*WEB_URL_FIELDS.values(), OPSGENIE_WEB_URL_FIELD}
    preset_fields = {field for preset in TOOL_CONFIG_PRESETS.values() for field in preset.get("fields") or []}
    assert fields <= preset_fields
    for connector, field in WEB_URL_FIELDS.items():
        assert field in TOOL_CONFIG_PRESETS[connector]["fields"]
        assert normalize_web_url(TOOL_CONFIG_PRESETS[connector]["example"][field]), field


@pytest.mark.parametrize(
    "value",
    ["http://app.datadoghq.eu", "https://user:pw@app.datadoghq.eu", "https://app.datadoghq.eu/?x=1", "app.datadoghq.eu",
     "https://", "https://app datadoghq.eu", 42],
)
def test_a_web_url_that_is_not_an_https_base_is_refused_at_save(value) -> None:
    with pytest.raises(ValueError):
        validate_tool_config("datadog", {"datadog_url": "https://api.datadoghq.com", "datadog_web_url": value})


def test_a_valid_web_url_is_kept_and_an_empty_one_means_not_configured() -> None:
    kept = validate_tool_config("datadog", {"datadog_web_url": "https://app.datadoghq.eu/"})
    assert kept["datadog_web_url"] == "https://app.datadoghq.eu/"
    assert normalize_web_url(kept["datadog_web_url"]) == "https://app.datadoghq.eu"
    assert validate_tool_config("azure", {"azure_web_url": WEB_URLS["azure_web_url"]})["azure_web_url"]
    assert validate_tool_config("datadog", {"datadog_web_url": ""}) == {"datadog_web_url": ""}


def _route(routes: dict[str, Any], url: str) -> Any:
    for fragment, payload in routes.items():
        if fragment in url:
            return payload
    raise AssertionError(f"unexpected request: {url}")


def _http_json(routes: dict[str, Any]):
    async def fake(method, url, **_kwargs):
        return _route(routes, str(url))

    return fake


Scenario = Callable[[Any], Awaitable[tuple[str, dict, dict, str]]]
SCENARIOS: dict[str, Scenario] = {}


def scenario(*names: str):
    def register(function):
        for name in names:
            SCENARIOS[name] = function
        return function

    return register


async def _token(*_args, **_kwargs) -> str:
    return "token"


@scenario("list_monitors", "get_events")
async def _datadog(monkeypatch):
    routes = {"/api/v1/monitor": [{"id": 7, "name": "API latency"}], "/api/v1/events": {"events": [{"id": 9, "title": "Deploy"}]}}
    monkeypatch.setattr("app.tools.connectors.datadog._http_json", _http_json(routes))
    return {}, {"datadog_url": "https://api.datadoghq.com"}, "datadog_web_url"


@scenario("get_alerts")
async def _newrelic(monkeypatch):
    violations = {"violations": [{"id": 3, "label": "CPU", "links": {"incident_id": 44}}]}
    monkeypatch.setattr("app.tools.connectors.newrelic._http_json", _http_json({"/v2/alerts_violations.json": violations}))
    return {}, {"newrelic_account_id": 1234567}, "newrelic_web_url"


@scenario("list_vulnerabilities", "get_severity", "get_fix_advice")
async def _snyk(monkeypatch):
    issue = {"id": "SNYK-JAVA-1", "title": "RCE", "severity": "high"}
    routes = {"/issue/SNYK-JAVA-1": {"issue": issue}, "/issues": {"issues": {"vulnerabilities": [issue]}}}
    monkeypatch.setattr("app.tools.connectors.snyk._http_json", _http_json(routes))
    return {"project_id": "p-1", "issue_id": "SNYK-JAVA-1"}, {"snyk_org_id": "org-1", "snyk_allowed_projects": ["p-1"]}, "snyk_web_url"


@scenario("get_schedule", "get_escalation_policy", "list_oncall")
async def _pagerduty(monkeypatch):
    routes = {
        "/oncalls": {"oncalls": [{"id": "o1", "schedule": {"id": "S1", "summary": "Primary"}}]},
        "/schedules/S1": {"schedule": {"id": "S1", "name": "Primary"}},
        "/escalation_policies/EP1": {"escalation_policy": {"id": "EP1", "name": "Ops"}},
    }
    monkeypatch.setattr("app.tools.connectors.pagerduty._http_json", _http_json(routes))
    config = {"incident_provider": "pagerduty", "pagerduty_schedule_ids": ["S1"], "pagerduty_escalation_policy_ids": ["EP1"]}
    return {"schedule_id": "S1", "escalation_policy_id": "EP1"}, config, "pagerduty_web_url"


@scenario("list_components")
async def _statuspage(monkeypatch):
    routes = {"/components": [{"id": "c1", "name": "API", "status": "operational"}]}
    monkeypatch.setattr("app.tools.connectors.statuspage._http_json", _http_json(routes))
    return {}, {"statuspage_page_id": "page-1"}, "statuspage_web_url"


AWS_JSON = {
    "ec2": {"Reservations": [{"Instances": [{"InstanceId": "i-0abc", "State": {"Name": "running"}}]}]},
    "lambda": {"Functions": [{"FunctionName": "billing"}]},
    "rds": {"DBInstances": [{"DBInstanceIdentifier": "orders-db"}]},
    "cloudwatch": {"MetricAlarms": [{"AlarmName": "high cpu"}]},
    "codepipeline": {"pipelines": [{"name": "deploy"}]},
    "eks": {"clusters": ["prod"]},
}


class _BotoClient:
    def get_pipeline_state(self, **_kwargs):
        return {"pipelineName": "deploy", "stageStates": []}

    def list_pipeline_executions(self, **_kwargs):
        return {"pipelineExecutionSummaries": [{"pipelineExecutionId": "e-1", "status": "Succeeded"}]}

    def list_web_acls(self, **_kwargs):
        return {"WebACLs": [{"Name": "edge", "Id": "a1"}]}

    def get_web_acl(self, **_kwargs):
        return {"WebACL": {"Name": "edge", "Id": "a1", "Rules": []}}


@scenario(
    "list_aws_ec2_instances", "list_aws_lambda_functions", "list_aws_rds_instances", "list_aws_cloudwatch_alarms",
    "list_aws_codepipelines", "get_aws_codepipeline_state", "list_aws_codepipeline_executions",
    "list_aws_waf_web_acls", "get_aws_waf_web_acl", "list_aws_eks_clusters",
)
async def _aws(monkeypatch):
    async def fake_aws_json(context, service, args):
        return AWS_JSON[service]

    async def same_session(context, session):
        return session

    session = SimpleNamespace(client=lambda _name: _BotoClient())
    for module in ("aws_compute", "aws_data", "aws_lambda", "aws_pipeline"):
        monkeypatch.setattr(f"app.tools.connectors.{module}._aws_json", fake_aws_json)
    monkeypatch.setattr("app.tools.connectors.aws_pipeline._get_boto_session", lambda context: session)
    monkeypatch.setattr("app.tools.connectors.aws_pipeline._assume_role_if_needed", same_session)
    return {"pipeline_name": "deploy", "name": "edge", "id": "a1"}, {"aws_region": "eu-central-1"}, "aws_web_url"


@scenario("list_azure_resource_groups", "list_azure_vms", "list_azure_aks_clusters")
async def _azure(monkeypatch):
    rg = "/subscriptions/sub-1/resourceGroups/ops"
    routes = {
        "/resourcegroups": {"value": [{"name": "ops", "id": rg}]},
        "/virtualMachines": {"value": [{"name": "vm1", "id": f"{rg}/providers/Microsoft.Compute/virtualMachines/vm1"}]},
        "/managedClusters": {"value": [{"name": "aks1", "id": f"{rg}/providers/Microsoft.ContainerService/managedClusters/aks1"}]},
    }
    monkeypatch.setattr("app.tools.connectors.azure._http_json", _http_json(routes))
    monkeypatch.setattr("app.tools.connectors.azure._azure_token", _token)
    return {}, {"azure_subscription_ids": ["sub-1"]}, "azure_web_url"


@scenario(
    "list_gcp_projects", "list_gcp_compute_instances", "list_gcp_cloud_sql_instances", "list_gcp_gke_clusters",
    "list_gcp_cloud_run_services",
)
async def _gcp(monkeypatch):
    routes = {
        "/v1/projects?": None,
        "/aggregated/instances": {"items": {"zones/europe-west3-a": {"instances": [{"name": "vm1", "zone": "https://x/zones/europe-west3-a"}]}}},
        "/sql/v1beta4/": {"items": [{"name": "orders"}]},
        "/clusters": {"clusters": [{"name": "gke1", "location": "europe-west3"}]},
        "/services": {"services": [{"name": "projects/acme/locations/europe-west3/services/api"}]},
        "/v1/projects": {"projects": [{"projectId": "acme"}]},
    }
    routes.pop("/v1/projects?")
    monkeypatch.setattr("app.tools.connectors.gcp._http_json", _http_json(routes))
    monkeypatch.setattr("app.tools.connectors.gcp._gcp_access_token", _token)
    return {}, {"gcp_project_id": "acme"}, "gcp_web_url"


def _context(config: dict) -> SimpleNamespace:
    return SimpleNamespace(
        project_config=config, turn_context_snapshot=None, current_user_message="", project_ids=[], user_id="u1", db=None
    )


def _source_items(value: Any) -> list[dict]:
    if isinstance(value, dict):
        own = [value] if "source_url" in value else []
        return own + [item for child in value.values() for item in _source_items(child)]
    if isinstance(value, list):
        return [item for child in value for item in _source_items(child)]
    return []


def test_every_web_url_linked_tool_has_a_scenario() -> None:
    assert set(SCENARIOS) == set(WEB_URL_LINKED_CONNECTOR_READS)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(WEB_URL_LINKED_CONNECTOR_READS))
async def test_a_web_url_linked_read_links_only_with_its_configured_web_url(name, monkeypatch) -> None:
    params, config, field = await SCENARIOS[name](monkeypatch)
    assert field in WEB_URL_LINKED_CONNECTOR_READS[name].split("|")

    unconfigured = await _dispatch_registered_tool(name, dict(params), _context(dict(config)))
    assert "error" not in unconfigured, unconfigured
    assert _source_items(unconfigured) == [], "without a web URL the read stays unsourced"

    configured = await _dispatch_registered_tool(name, dict(params), _context({**config, field: WEB_URLS[field]}))
    items = _source_items(configured)
    assert items, f"{name} emitted no source fields with {field} set: {configured}"
    host = urlsplit(WEB_URLS[field]).hostname
    for item in items:
        assert urlsplit(item["source_url"]).hostname == host, item
        assert item["source_url"].startswith(WEB_URLS[field].rstrip("/")), item
        assert item["cite_as"].endswith(f"]({item['source_url']})")


@pytest.mark.asyncio
async def test_the_item_pages_are_the_vendor_forms(monkeypatch) -> None:
    async def run(name: str, field: str, scenario_name: str | None = None) -> list[dict]:
        params, config, _ = await SCENARIOS[scenario_name or name](monkeypatch)
        result = await _dispatch_registered_tool(name, params, _context({**config, field: WEB_URLS[field]}))
        return [item["source_url"] for item in _source_items(result)]

    assert await run("list_monitors", "datadog_web_url") == ["https://app.datadoghq.eu/monitors/7"]
    assert await run("get_alerts", "newrelic_web_url") == ["https://alerts.newrelic.com/accounts/1234567/incidents/44"]
    assert await run("get_severity", "snyk_web_url") == ["https://app.snyk.io/org/acme/project/p-1#issue-SNYK-JAVA-1"]
    assert await run("get_schedule", "pagerduty_web_url") == ["https://acme.pagerduty.com/schedules/S1"]
    assert await run("list_aws_ec2_instances", "aws_web_url") == [
        "https://eu-central-1.console.aws.amazon.com/ec2/home?region=eu-central-1#InstanceDetails:instanceId=i-0abc"
    ]
    assert await run("list_azure_vms", "azure_web_url") == [
        "https://portal.azure.com/#@acme.onmicrosoft.com/resource/subscriptions/sub-1/resourceGroups/ops"
        "/providers/Microsoft.Compute/virtualMachines/vm1"
    ]
    assert await run("list_gcp_compute_instances", "gcp_web_url") == [
        "https://console.cloud.google.com/compute/instancesDetail/zones/europe-west3-a/instances/vm1?project=acme"
    ]


@pytest.mark.asyncio
async def test_opsgenie_links_its_schedules_on_its_own_web_url(monkeypatch) -> None:
    routes = {"/v2/schedules/sched-1": {"data": {"id": "sched-1", "name": "Primary"}}}
    monkeypatch.setattr("app.tools.connectors.opsgenie._http_json", _http_json(routes))
    config = {"incident_provider": "opsgenie", "opsgenie_schedule_ids": ["sched-1"]}
    without = await _dispatch_registered_tool("get_schedule", {"schedule_id": "sched-1"}, _context(config))
    assert _source_items(without) == []
    with_url = await _dispatch_registered_tool(
        "get_schedule", {"schedule_id": "sched-1"}, _context({**config, OPSGENIE_WEB_URL_FIELD: WEB_URLS["opsgenie_web_url"]})
    )
    assert [item["source_url"] for item in _source_items(with_url)] == [
        "https://acme.app.opsgenie.com/settings/schedule/detail/sched-1"
    ]


@pytest.mark.asyncio
async def test_an_invalid_stored_web_url_links_nothing(monkeypatch) -> None:
    params, config, field = await SCENARIOS["list_monitors"](monkeypatch)
    result = await _dispatch_registered_tool("list_monitors", params, _context({**config, field: "http://app.datadoghq.eu"}))
    assert _source_items(result) == []
