"""Controlled AWS Config advanced-query connector tool."""

from __future__ import annotations

import json
import re
from typing import Any

from ..context import ToolContext
from .aws_core import _aws_json
from .cloud_common import _aws_allowed
from .common import _string

AWS_CONFIG_SERVICE = "configservice"
AWS_CONFIG_SERVICE_ALIAS = "config"
DEFAULT_LIMIT = 50
MAX_LIMIT = 500
MAX_QUERY_CHARS = 4000

QUERY_TEMPLATES: dict[str, str] = {
    "resource_inventory": "SELECT resourceType, resourceId, resourceName, awsRegion, accountId",
    "ec2_network_inventory": (
        "SELECT resourceType, resourceId, resourceName, awsRegion, accountId, configuration.vpcId "
        "WHERE resourceType = 'AWS::EC2::VPC' OR resourceType = 'AWS::EC2::Subnet' "
        "OR resourceType = 'AWS::EC2::SecurityGroup'"
    ),
    "rds_inventory": (
        "SELECT resourceType, resourceId, resourceName, awsRegion, accountId, configuration.engine, "
        "configuration.dBInstanceStatus WHERE resourceType = 'AWS::RDS::DBInstance'"
    ),
    "s3_inventory": (
        "SELECT resourceType, resourceId, resourceName, awsRegion, accountId "
        "WHERE resourceType = 'AWS::S3::Bucket'"
    ),
    "tag_coverage": "SELECT resourceType, resourceId, resourceName, tags",
}

FORBIDDEN_QUERY_TOKENS = {
    "alter",
    "create",
    "delete",
    "describe",
    "drop",
    "execute",
    "grant",
    "insert",
    "revoke",
    "show",
    "update",
}


def _bounded_limit(raw: Any) -> int:
    try:
        parsed = int(raw)
    except Exception:
        parsed = DEFAULT_LIMIT
    return max(1, min(parsed, MAX_LIMIT))


def _query_for_params(params: dict[str, Any]) -> tuple[str, str | None]:
    custom_query = _string(params.get("query"))
    template = _string(params.get("template")) or "resource_inventory"
    if custom_query:
        return _validate_query(custom_query), None
    if template not in QUERY_TEMPLATES:
        known = ", ".join(sorted(QUERY_TEMPLATES))
        raise ValueError(f"Unknown AWS Config query template '{template}'. Supported templates: {known}")
    return QUERY_TEMPLATES[template], template


def _validate_query(query: str) -> str:
    normalized = " ".join(query.split())
    if not normalized:
        raise ValueError("AWS Config query must not be empty")
    if len(normalized) > MAX_QUERY_CHARS:
        raise ValueError(f"AWS Config query is too long; max {MAX_QUERY_CHARS} characters")
    if not normalized.lower().startswith("select "):
        raise ValueError("AWS Config query must be a SELECT statement")
    if any(token in normalized for token in (";", "--", "/*", "*/")):
        raise ValueError("AWS Config query must not contain statement separators or comments")

    words = {word.lower() for word in re.findall(r"[A-Za-z_]+", normalized)}
    blocked = sorted(words & FORBIDDEN_QUERY_TOKENS)
    if blocked:
        raise ValueError(f"AWS Config query contains forbidden token(s): {', '.join(blocked)}")
    return normalized


def _parse_config_result(item: Any) -> Any:
    if not isinstance(item, str):
        return item
    try:
        return json.loads(item)
    except json.JSONDecodeError:
        return {"raw": item}


def _allowed_config_service(context: ToolContext) -> str | None:
    if _aws_allowed(context, AWS_CONFIG_SERVICE):
        return AWS_CONFIG_SERVICE
    if _aws_allowed(context, AWS_CONFIG_SERVICE_ALIAS):
        return AWS_CONFIG_SERVICE_ALIAS
    return None


async def run_aws_config_query(context: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    service = _allowed_config_service(context)
    if service is None:
        return {
            "status": "blocked",
            "service": AWS_CONFIG_SERVICE,
            "error": f"AWS service '{AWS_CONFIG_SERVICE}' is not allowed by project policy",
            "items": [],
            "warnings": [
                {
                    "service": AWS_CONFIG_SERVICE,
                    "operation": "select-resource-config",
                    "severity": "warning",
                    "message": f"AWS service '{AWS_CONFIG_SERVICE}' is not allowed by project policy.",
                }
            ],
        }

    try:
        expression, template = _query_for_params(params)
    except ValueError as exc:
        return {
            "status": "invalid_query",
            "service": AWS_CONFIG_SERVICE,
            "error": str(exc),
            "items": [],
            "warnings": [],
        }

    limit = _bounded_limit(params.get("limit"))
    command = ["select-resource-config", "--expression", expression, "--limit", str(limit)]
    next_token = _string(params.get("next_token"))
    if next_token:
        command.extend(["--next-token", next_token])

    warnings: list[dict[str, Any]] = []
    try:
        raw = await _aws_json(context, service, command)
    except Exception as exc:
        warnings.append(
            {
                "service": AWS_CONFIG_SERVICE,
                "operation": "select-resource-config",
                "severity": "warning",
                "message": str(exc),
            }
        )
        return {
            "status": "error",
            "service": AWS_CONFIG_SERVICE,
            "operation": "select-resource-config",
            "template": template,
            "query": expression,
            "limit": limit,
            "items": [],
            "warnings": warnings,
        }

    results = [_parse_config_result(item) for item in raw.get("Results", [])] if isinstance(raw, dict) else []
    return {
        "status": "ok",
        "service": AWS_CONFIG_SERVICE,
        "operation": "select-resource-config",
        "template": template,
        "query": expression,
        "limit": limit,
        "next_token": raw.get("NextToken") if isinstance(raw, dict) else None,
        "result_count": len(results),
        "items": results,
        "evidence": [
            {
                "service": AWS_CONFIG_SERVICE,
                "operation": "select-resource-config",
                "template": template,
                "query": expression,
                "direct": True,
            }
        ],
        "warnings": warnings,
    }


class AwsConfigQueryTool:
    name = "aws_config_query"
    description = (
        "Run a bounded, read-only AWS Config advanced query through approved runtime credentials. "
        "Use this for normalized AWS resource inventory and governance evidence."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await run_aws_config_query(context, params or {})
