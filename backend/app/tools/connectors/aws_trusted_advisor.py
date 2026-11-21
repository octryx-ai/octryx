"""AWS Trusted Advisor summary connector tool."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .aws_core import _aws_json
from .aws_topology_common import bounded_int
from .common import _normalize_string_list

MAX_CHECK_RESULTS = 20


def _checks_by_category(checks: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for check in checks:
        category = str(check.get("category") or "unknown")
        result[category] = result.get(category, 0) + 1
    return result


def _check_summary(check: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": check.get("id"),
        "name": check.get("name"),
        "category": check.get("category"),
        "description": check.get("description"),
        "metadata": check.get("metadata") or [],
        "evidence": [{"service": "support", "operation": "describe-trusted-advisor-checks", "direct": True}],
    }


def _result_summary(check_id: str, data: dict[str, Any]) -> dict[str, Any]:
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    flagged = result.get("flaggedResources") or []
    return {
        "check_id": check_id,
        "status": result.get("status"),
        "timestamp": result.get("timestamp"),
        "resources_summary": result.get("resourcesSummary") or {},
        "category_specific_summary": result.get("categorySpecificSummary") or {},
        "flagged_resource_count": len(flagged),
        "flagged_resources_sample": flagged[:10],
        "evidence": [
            {
                "service": "support",
                "operation": "describe-trusted-advisor-check-result",
                "check_id": check_id,
                "direct": True,
            }
        ],
    }


async def build_aws_trusted_advisor_summary(context: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    language = str(params.get("language") or "en")
    warnings = []
    try:
        checks_data = await _aws_json(context, "support", ["describe-trusted-advisor-checks", "--language", language])
    except Exception as exc:
        return {
            "status": "unavailable",
            "checks": [],
            "check_results": [],
            "summary": {"check_count": 0, "result_count": 0},
            "warnings": [
                {
                    "severity": "warning",
                    "message": f"Trusted Advisor is unavailable or unauthorized: {exc}",
                }
            ],
        }

    checks = [_check_summary(check) for check in checks_data.get("checks", []) if isinstance(check, dict)]
    requested_ids = _normalize_string_list(params.get("check_ids"))
    include_results = bool(params.get("include_results") or requested_ids)
    if not requested_ids and include_results:
        requested_ids = [str(check.get("id")) for check in checks if check.get("id")]
    requested_ids = requested_ids[: bounded_int(params.get("max_results"), default=10, maximum=MAX_CHECK_RESULTS)]

    check_results = []
    if include_results:
        for check_id in requested_ids:
            try:
                result = await _aws_json(
                    context,
                    "support",
                    ["describe-trusted-advisor-check-result", "--check-id", check_id, "--language", language],
                )
                check_results.append(_result_summary(check_id, result))
            except Exception as exc:
                warnings.append({"severity": "warning", "message": f"Trusted Advisor result failed for {check_id}: {exc}"})

    return {
        "status": "ok",
        "summary": {
            "check_count": len(checks),
            "result_count": len(check_results),
            "checks_by_category": _checks_by_category(checks),
            "warning_count": len(warnings),
        },
        "checks": checks,
        "check_results": check_results,
        "warnings": warnings,
    }


class AwsTrustedAdvisorSummaryTool:
    name = "aws_trusted_advisor_summary"
    description = (
        "Summarize AWS Trusted Advisor checks and optional check results when AWS Support API access is available."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await build_aws_trusted_advisor_summary(context, params or {})
