"""Internal AWS Well-Architected-style assessment connector tool."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .aws_cost_topology import build_aws_cost_topology_report
from .aws_exposure_map import build_aws_exposure_map
from .aws_security_posture import build_aws_security_posture_summary
from .aws_topology import build_aws_topology_snapshot


def _status_from_counts(*, critical: int = 0, high: int = 0, warning: int = 0) -> str:
    if critical or high:
        return "risk"
    if warning:
        return "needs_review"
    return "ok"


def _score(status: str) -> int:
    return {"ok": 100, "needs_review": 70, "risk": 35}.get(status, 50)


def _check(check_id: str, pillar: str, title: str, status: str, evidence: Any = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "pillar": pillar,
        "title": title,
        "status": status,
        "score": _score(status),
        "evidence": evidence or {},
        "basis": "internal_derived_check_not_official_aws_review",
    }


def _security_checks(security: dict[str, Any] | None, exposure: dict[str, Any] | None) -> list[dict[str, Any]]:
    security_summary = (security or {}).get("summary") if isinstance((security or {}).get("summary"), dict) else {}
    exposure_summary = (exposure or {}).get("summary") if isinstance((exposure or {}).get("summary"), dict) else {}
    severity = security_summary.get("by_severity") if isinstance(security_summary.get("by_severity"), dict) else {}
    critical = int(severity.get("critical") or 0)
    high = int(severity.get("high") or 0) + int(exposure_summary.get("high_severity_count") or 0)
    return [
        _check(
            "security-public-exposure",
            "security",
            "Public exposure is understood and bounded",
            _status_from_counts(critical=critical, high=high),
            {"security_summary": security_summary, "exposure_summary": exposure_summary},
        )
    ]


def _cost_checks(cost: dict[str, Any] | None) -> list[dict[str, Any]]:
    summary = (cost or {}).get("summary") if isinstance((cost or {}).get("summary"), dict) else {}
    unmapped = int(summary.get("unmapped_cost_count") or 0)
    return [
        _check(
            "cost-attribution-coverage",
            "cost_optimization",
            "Cost is attributable to known services or tags",
            _status_from_counts(warning=unmapped),
            {"cost_summary": summary},
        )
    ]


def _reliability_checks(timeline: dict[str, Any] | None) -> list[dict[str, Any]]:
    events = (timeline or {}).get("events") if isinstance((timeline or {}).get("events"), list) else []
    failed = [event for event in events if str(event.get("status") or "").lower() in {"failed", "stopped"}]
    return [
        _check(
            "reliability-deployment-health",
            "reliability",
            "Recent deployment history has no failed or stopped executions",
            _status_from_counts(high=len(failed)),
            {"failed_event_count": len(failed)},
        )
    ]


def _operational_checks(topology: dict[str, Any] | None) -> list[dict[str, Any]]:
    scope = (topology or {}).get("scope") if isinstance((topology or {}).get("scope"), dict) else {}
    failed = len(scope.get("services_failed") or [])
    skipped = len(scope.get("services_skipped") or [])
    return [
        _check(
            "ops-evidence-coverage",
            "operational_excellence",
            "Operational evidence coverage is complete enough for review",
            _status_from_counts(high=failed, warning=skipped),
            {"scope": scope},
        )
    ]


def _performance_checks(topology: dict[str, Any] | None) -> list[dict[str, Any]]:
    nodes = (topology or {}).get("nodes") if isinstance((topology or {}).get("nodes"), list) else []
    has_runtime = any(node.get("type") in {"eks_cluster", "lambda_function"} for node in nodes if isinstance(node, dict))
    return [
        _check(
            "performance-runtime-inventory",
            "performance_efficiency",
            "Runtime compute inventory is visible",
            "ok" if has_runtime else "needs_review",
            {"runtime_node_present": has_runtime},
        )
    ]


def _pillar_summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    pillars: dict[str, list[int]] = {}
    for check in checks:
        pillars.setdefault(str(check.get("pillar")), []).append(int(check.get("score") or 0))
    return {
        pillar: {
            "score": round(sum(scores) / len(scores)),
            "check_count": len(scores),
            "status": "risk" if min(scores) < 50 else ("needs_review" if min(scores) < 100 else "ok"),
        }
        for pillar, scores in pillars.items()
    }


async def build_aws_well_architected_assessment(context: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    collect_missing = bool(params.get("collect_missing"))
    topology = params.get("topology_snapshot") if isinstance(params.get("topology_snapshot"), dict) else None
    if topology is None and collect_missing:
        topology = await build_aws_topology_snapshot(context, params.get("snapshot_params") or {})

    security = params.get("security_posture") if isinstance(params.get("security_posture"), dict) else None
    if security is None and collect_missing:
        security = await build_aws_security_posture_summary(context, {"topology_snapshot": topology} if topology else {})

    exposure = params.get("exposure_map") if isinstance(params.get("exposure_map"), dict) else None
    if exposure is None and collect_missing:
        exposure = await build_aws_exposure_map(context, {"topology_snapshot": topology} if topology else {})

    cost = params.get("cost_report") if isinstance(params.get("cost_report"), dict) else None
    if cost is None and collect_missing:
        cost = await build_aws_cost_topology_report(context, params.get("cost_params") or {})

    timeline = params.get("deployment_timeline") if isinstance(params.get("deployment_timeline"), dict) else None
    checks = [
        *_security_checks(security, exposure),
        *_cost_checks(cost),
        *_reliability_checks(timeline),
        *_operational_checks(topology),
        *_performance_checks(topology),
    ]
    pillars = _pillar_summary(checks)
    return {
        "status": "ok",
        "basis": "internal_derived_assessment_not_official_aws_well_architected_review",
        "summary": {
            "overall_score": round(sum(item["score"] for item in pillars.values()) / len(pillars)) if pillars else 0,
            "risk_pillar_count": sum(1 for item in pillars.values() if item["status"] == "risk"),
            "check_count": len(checks),
        },
        "pillars": pillars,
        "checks": checks,
        "warnings": [
            {
                "severity": "info",
                "message": "This is an internal derived assessment, not an official AWS Well-Architected Tool review.",
            }
        ],
    }


class AwsWellArchitectedAssessmentTool:
    name = "aws_well_architected_assessment"
    description = (
        "Evaluate AWS evidence against internal Well-Architected-style pillars without creating or modifying AWS "
        "Well-Architected workloads."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await build_aws_well_architected_assessment(context, params or {})
