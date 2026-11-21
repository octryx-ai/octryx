import re
from pathlib import Path
from typing import Any

_SHAPE_LIBRARY_DIR = Path(__file__).with_name("shape_libraries")
_GLOBAL_SHAPE_ALIASES = {
    "load_balancer": "load_balancer",
    "load_balancing": "load_balancer",
    "router": "router",
    "switch": "switch",
    "firewall": "firewall",
    "server": "server",
    "database": "database",
    "gateway": "gateway",
}
_SHAPE_ALIASES_BY_LIBRARY: dict[str, dict[str, str]] = {
    "aws4": {
        "api_gateway": "api_gateway",
        "application_load_balancer": "application_load_balancer",
        "auth": "cognito",
        "cognito": "cognito",
        "cloudfront": "cloudfront",
        "cloudformation": "cloudformation",
        "codebuild": "codebuild",
        "codecommit": "codecommit",
        "codepipeline": "codepipeline",
        "dynamo_db": "dynamodb",
        "dynamodb": "dynamodb",
        "ecr": "container_registry",
        "ecs": "ecs",
        "eks": "eks",
        "eventbridge": "eventbridge",
        "fargate": "fargate",
        "iam": "identity_and_access_management_iam",
        "lambda": "lambda",
        "rds": "rds",
        "s3": "s3",
        "sns": "sns",
        "sqs": "sqs",
        "step_functions": "step_functions",
        "vpc": "vpc",
        "waf": "waf",
    },
    "azure2": {
        "acr": "Container_Registries",
        "aks": "Kubernetes_Services",
        "api_management": "API_Management_Services",
        "app_gateway": "Application_Gateways",
        "app_service": "App_Services",
        "application_gateway": "Application_Gateways",
        "azure_functions": "Function_Apps",
        "azure_sql": "SQL_Database",
        "container_registry": "Container_Registries",
        "cosmos": "Azure_Cosmos_DB",
        "cosmos_db": "Azure_Cosmos_DB",
        "firewall": "Firewalls",
        "front_door": "Front_Doors",
        "function_app": "Function_Apps",
        "functions": "Function_Apps",
        "key_vault": "Key_Vaults",
        "load_balancer": "Load_Balancers",
        "postgres": "Azure_Database_PostgreSQL_Server",
        "postgresql": "Azure_Database_PostgreSQL_Server",
        "private_link": "Private_Link",
        "public_ip": "Public_IP_Addresses",
        "service_bus": "Service_Bus",
        "sql": "SQL_Database",
        "sql_database": "SQL_Database",
        "virtual_machine": "Virtual_Machine",
        "vm": "Virtual_Machine",
        "virtual_network": "Virtual_Networks",
        "vnet": "Virtual_Networks",
        "waf": "Web_Application_Firewall_Policies_WAF",
    },
    "gcp2": {
        "bigquery": "bigquery",
        "cloud_dns": "cloud_dns",
        "cloud_firestore": "cloud_firestore",
        "cloud_functions": "cloud_functions",
        "cloud_load_balancing": "cloud_load_balancing",
        "cloud_router": "cloud_router",
        "cloud_run": "cloud_run",
        "cloud_spanner": "cloud_spanner",
        "cloud_sql": "cloud_sql",
        "cloud_storage": "cloud_storage",
        "compute_engine": "compute_engine",
        "firestore": "cloud_firestore",
        "functions": "cloud_functions",
        "gke": "gke_on_prem",
        "load_balancer": "cloud_load_balancing",
        "load_balancing": "cloud_load_balancing",
        "pub_sub": "cloud_pubsub",
        "pubsub": "cloud_pubsub",
        "router": "cloud_router",
        "spanner": "cloud_spanner",
        "storage": "cloud_storage",
        "vpn_gateway": "vpn_gateway",
    },
    "kubernetes": {
        "configmap": "cm",
        "config_map": "cm",
        "daemonset": "ds",
        "deployment": "deploy",
        "endpoint": "ep",
        "endpoints": "ep",
        "ingress": "ing",
        "namespace": "ns",
        "persistent_volume": "pv",
        "persistent_volume_claim": "pvc",
        "service": "svc",
        "services": "svc",
        "statefulset": "sts",
    },
    "network": {
        "load_balancer": "load_balancer",
        "proxy": "proxy_server",
        "web_server": "web_server",
    },
    "cisco19": {
        "database": "database_relational",
        "load_balancer": "load_balancer",
        "router": "router",
        "secure_router": "secure_router",
        "switch": "l3_switch",
        "firewall": "firewall",
        "server": "server",
        "vpn_gateway": "ip_ip_gateway",
        "web_application_firewall": "web_application_firewall",
        "wireless_router": "wireless_router",
    },
    "bpmn": {
        "and_gateway": "gateway_and",
        "business_rule_task": "business_rule_task",
        "end_event": "general_end",
        "manual_task": "manual_task",
        "message_end": "message_end",
        "message_start": "message_start",
        "script_task": "script_task",
        "service_task": "service_task",
        "start_event": "general_start",
        "timer_start": "timer_start",
        "user_task": "user_task",
        "xor_gateway": "gateway_xor_(data)",
    },
    "openstack": {
        "cinder": "cinder_volume",
        "glance": "glance_image",
        "heat": "heat_autoscalinggroup",
        "keystone": "keystone",
        "neutron_router": "neutron_router",
        "nova": "nova_server",
        "server": "nova_server",
        "swift": "swift_container",
    },
    "salesforce": {
        "analytics": "analytics",
        "commerce": "commerce",
        "field_service": "field_service",
        "marketing": "marketing",
        "platform": "platform",
        "sales": "sales",
        "service": "service",
    },
    "atlassian": {
        "bitbucket": "Bitbucket_Logo",
        "confluence": "Confluence_Logo",
        "jira": "Jira_Logo",
        "trello": "Trello_Logo",
    },
    "sap": {
        "abap": "SAP_BTP,_ABAP_environment",
        "analytics_cloud": "SAP_Analytics_Cloud",
        "ariba": "SAP_Ariba",
        "cloud_connector": "Cloud_Connector",
        "hana": "SAP_HANA_Cloud",
        "s4hana": "SAP_S4HANA_for_MS_Teams",
        "successfactors": "SAP_SuccessFactors",
    },
    "rack": {
        "rack": "rackCabinet3",
    },
    "webicons": {
        "bitbucket": "bitbucket",
        "confluence": "confluence",
        "github": "github",
        "gitlab": "gitlab",
        "jira": "jira",
        "slack": "slack",
    },
}


def available_shape_libraries() -> list[str]:
    return sorted(path.stem for path in _SHAPE_LIBRARY_DIR.glob("*.md") if path.stem.lower() != "readme")


def load_shape_library(
    library: str,
    requested_shape_names: list[str],
) -> dict[str, Any]:
    library_path = _SHAPE_LIBRARY_DIR / f"{library}.md"
    content = library_path.read_text(encoding="utf-8")
    prefix, usage_xml, available_shapes = _extract_shape_library_metadata(content)
    matched_shapes, missing_shape_names = _match_shape_names(
        available_shapes,
        requested_shape_names,
        library=library,
    )
    return {
        "content": content,
        "prefix": prefix,
        "usage_xml": usage_xml,
        "shape_count": len(available_shapes),
        "requested_shape_names": requested_shape_names,
        "matched_shapes": matched_shapes,
        "missing_shape_names": missing_shape_names,
    }


def shape_library_exists(library: str) -> bool:
    return (_SHAPE_LIBRARY_DIR / f"{library}.md").is_file()


def _extract_shape_library_metadata(content: str) -> tuple[str | None, str | None, list[str]]:
    prefix_match = re.search(r"^\*\*Prefix:\*\*\s*`([^`]+)`", content, re.MULTILINE)
    usage_match = re.search(r"## Usage\s+```xml\s*(.*?)\s*```", content, re.DOTALL)
    shapes = re.findall(r"^- `([^`]+)`\s*$", content, re.MULTILINE)
    return (
        prefix_match.group(1) if prefix_match else None,
        usage_match.group(1).strip() if usage_match else None,
        shapes,
    )


def _normalize_shape_name(value: str) -> str:
    lowered = value.strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def _match_shape_names(
    available_shapes: list[str],
    requested_shape_names: list[str],
    *,
    library: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized_available = {_normalize_shape_name(shape): shape for shape in available_shapes}
    aliases = dict(_GLOBAL_SHAPE_ALIASES)
    aliases.update(_SHAPE_ALIASES_BY_LIBRARY.get(library, {}))
    matches: list[dict[str, Any]] = []
    missing: list[str] = []

    for requested in requested_shape_names:
        normalized_requested = _normalize_shape_name(requested)
        if not normalized_requested:
            continue
        candidates = [normalized_requested]
        alias = aliases.get(normalized_requested)
        if alias and alias not in candidates:
            candidates.append(_normalize_shape_name(alias))
        for candidate in candidates:
            exact = normalized_available.get(candidate)
            if exact:
                match_type = "alias" if candidate != normalized_requested else "exact"
                matches.append({"requested": requested, "shape": exact, "match_type": match_type})
                break
        else:
            contains_matches = [
                shape for shape in available_shapes if normalized_requested in _normalize_shape_name(shape)
            ][:10]
            if contains_matches:
                matches.append(
                    {
                        "requested": requested,
                        "shape": contains_matches[0],
                        "match_type": "contains",
                        "alternatives": contains_matches,
                    }
                )
                continue
            missing.append(requested)

    return matches, missing
