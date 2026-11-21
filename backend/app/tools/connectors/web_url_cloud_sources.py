"""Configured-web-URL source linkers for AWS, Azure and GCP console pages (``web_url_sources``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from ...services.tool_config.web_url import WEB_URL_FIELDS
from ..evidence_fields import http_url, item_url, with_source
from .web_url_linking import Linker, _items, _query, _web


def _aws(config: dict[str, Any], service_path: tuple[str, ...], fragment: str = "", **query: object) -> str | None:
    base = _web(config, WEB_URL_FIELDS["aws"])
    region = str(config.get("aws_region") or "").strip()
    return item_url(base, *service_path, query=_query(region=region, **query), fragment=fragment) if base else None


def _aws_items(key: str, title: str, page: Callable[[dict[str, Any], dict[str, Any]], str | None]) -> Linker:
    def link(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        return _items(result, key, lambda item: with_source(
            item, title=f"AWS {title} {item.get('name') or item.get('instance_id') or item.get('identifier')}",
            url=page(item, config),
        ))

    return link


def _aws_pipeline(name: object, config: dict[str, Any], *tail: object) -> str | None:
    return _aws(config, ("codesuite", "codepipeline", "pipelines", name, *tail)) if name else None


def _aws_pipeline_state(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    name = result.get("pipeline_name")
    return with_source(result, title=f"AWS CodePipeline {name}", url=_aws_pipeline(name, config, "view"))


def _aws_pipeline_executions(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    name = result.get("pipeline_name")
    return _items(result, "executions", lambda item: with_source(
        item, title=f"AWS CodePipeline {name} execution {item.get('execution_id')}",
        url=_aws_pipeline(name, config, "executions", item.get("execution_id"), "timeline")
        if item.get("execution_id")
        else None,
    ))


def _aws_waf_acl(item: dict[str, Any], config: dict[str, Any]) -> str | None:
    if not item.get("name") or not item.get("id"):
        return None
    return _aws(config, ("wafv2", "homev2", "web-acl", item.get("name"), item.get("id"), "overview"))


def _aws_eks(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    # The API answers cluster names only: their pages are listed next to them.
    names = [name for name in result.get("clusters") or [] if isinstance(name, str) and name]
    pages = [
        with_source({"name": name}, title=f"AWS EKS cluster {name}",
                    url=_aws(config, ("eks", "home"), fragment=f"/clusters/{quote(name, safe='')}"))
        for name in names
    ]
    if any("source_url" in page for page in pages):
        result["cluster_pages"] = pages
    return result


def _azure_resource(config: dict[str, Any], resource_id: object) -> str | None:
    base = _web(config, WEB_URL_FIELDS["azure"])
    resource = str(resource_id or "").strip()
    if not base or not resource.startswith("/subscriptions/"):
        return None
    return http_url(f"{base}/resource{resource}" if "#" in base else f"{base}/#resource{resource}")


def _azure_items(key: str, title: str, resource_id: Callable[[dict[str, Any]], object]) -> Linker:
    def link(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        return _items(result, key, lambda item: with_source(
            item, title=f"Azure {title} {item.get('name')}", url=_azure_resource(config, resource_id(item))
        ))

    return link


def _aks_resource_id(item: dict[str, Any]) -> str | None:
    if not (item.get("subscription_id") and item.get("resource_group") and item.get("name")):
        return None
    return (
        f"/subscriptions/{item['subscription_id']}/resourceGroups/{item['resource_group']}"
        f"/providers/Microsoft.ContainerService/managedClusters/{item['name']}"
    )


def _last_segment(value: object) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def _gcp(config: dict[str, Any], project: object, *path: object) -> str | None:
    base = _web(config, WEB_URL_FIELDS["gcp"])
    return item_url(base, *path, query=_query(project=project)) if base and project else None


def _gcp_items(key: str, title: str, path: Callable[[dict[str, Any]], tuple[object, ...] | None]) -> Linker:
    def link(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        project = result.get("project_id")

        def source(item: dict[str, Any]) -> dict[str, Any]:
            page = path(item)
            title_text = f"GCP {title} {_last_segment(item.get('name'))}"
            return with_source(item, title=title_text, url=_gcp(config, project, *page) if page else None)

        return _items(result, key, source)

    return link


def _gcp_projects(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return _items(result, "projects", lambda item: with_source(
        item, title=f"GCP project {item.get('project_id')}",
        url=_gcp(config, item.get("project_id"), "home", "dashboard"),
    ))


def _cloud_run_path(item: dict[str, Any]) -> tuple[object, ...] | None:
    # "projects/{p}/locations/{region}/services/{name}"
    parts = str(item.get("name") or "").split("/")
    return ("run", "detail", parts[3], parts[5]) if len(parts) == 6 and parts[2] == "locations" else None


CLOUD_WEB_URL_LINKERS: dict[str, Linker] = {
    "list_aws_ec2_instances": _aws_items(
        "instances", "EC2 instance",
        lambda item, config: _aws(
            config, ("ec2", "home"), fragment=f"InstanceDetails:instanceId={item.get('instance_id')}"
        )
        if item.get("instance_id") else None,
    ),
    "list_aws_lambda_functions": _aws_items(
        "functions", "Lambda function",
        lambda item, config: _aws(
            config, ("lambda", "home"), fragment=f"/functions/{quote(str(item.get('name')), safe='')}"
        )
        if item.get("name") else None,
    ),
    "list_aws_rds_instances": _aws_items(
        "instances", "RDS instance",
        lambda item, config: _aws(config, ("rds", "home"), fragment=f"database:id={item.get('identifier')}")
        if item.get("identifier") else None,
    ),
    "list_aws_cloudwatch_alarms": _aws_items(
        "alarms", "CloudWatch alarm",
        lambda item, config: _aws(
            config, ("cloudwatch", "home"), fragment=f"alarmsV2:alarm/{quote(str(item.get('name')), safe='')}"
        )
        if item.get("name") else None,
    ),
    "list_aws_codepipelines": _aws_items(
        "pipelines", "CodePipeline", lambda item, config: _aws_pipeline(item.get("name"), config, "view")
    ),
    "get_aws_codepipeline_state": _aws_pipeline_state,
    "list_aws_codepipeline_executions": _aws_pipeline_executions,
    "list_aws_waf_web_acls": _aws_items("web_acls", "WAF web ACL", _aws_waf_acl),
    "get_aws_waf_web_acl": lambda result, config: with_source(
        result, title=f"AWS WAF web ACL {result.get('name')}", url=_aws_waf_acl(result, config)
    ),
    "list_aws_eks_clusters": _aws_eks,
    "list_azure_resource_groups": _azure_items("resource_groups", "resource group", lambda item: item.get("id")),
    "list_azure_vms": _azure_items("virtual_machines", "VM", lambda item: item.get("id")),
    "list_azure_aks_clusters": _azure_items("clusters", "AKS cluster", _aks_resource_id),
    "list_gcp_projects": _gcp_projects,
    "list_gcp_compute_instances": _gcp_items(
        "instances", "VM",
        lambda item: (
            "compute", "instancesDetail", "zones", _last_segment(item.get("zone")), "instances", item.get("name")
        )
        if item.get("zone") and item.get("name") else None,
    ),
    "list_gcp_cloud_sql_instances": _gcp_items(
        "instances", "Cloud SQL instance",
        lambda item: ("sql", "instances", item.get("name"), "overview") if item.get("name") else None,
    ),
    "list_gcp_gke_clusters": _gcp_items(
        "clusters", "GKE cluster",
        lambda item: ("kubernetes", "clusters", "details", item.get("location"), item.get("name"))
        if item.get("location") and item.get("name") else None,
    ),
    "list_gcp_cloud_run_services": _gcp_items("services", "Cloud Run service", _cloud_run_path),
}
