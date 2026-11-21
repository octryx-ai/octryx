"""AWS incident evidence bundle connector tool."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .aws_deployment_timeline import build_aws_deployment_timeline
from .aws_exposure_map import build_aws_exposure_map
from .aws_security_posture import build_aws_security_posture_summary
from .aws_topology import build_aws_topology_snapshot
from .common import _string

SENSITIVE_KEY_PARTS = ("secret", "token", "password", "authorization", "credential", "access_key")
MAX_SECTION_ITEMS = 100


def _redact(value: Any, redactions: list[str], *, path: str = "$") -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if any(part in key_text.lower() for part in SENSITIVE_KEY_PARTS):
                redactions.append(child_path)
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = _redact(item, redactions, path=child_path)
        return result
    if isinstance(value, list):
        return [_redact(item, redactions, path=f"{path}[{index}]") for index, item in enumerate(value[:MAX_SECTION_ITEMS])]
    return value


def _section(name: str, payload: Any, redactions: list[str]) -> dict[str, Any]:
    sanitized = _redact(payload, redactions, path=f"$.sections.{name}")
    item_count = len(sanitized) if isinstance(sanitized, list) else 1
    return {"name": name, "item_count": item_count, "payload": sanitized}


def _count_evidence(value: Any) -> int:
    if isinstance(value, dict):
        count = 1 if "evidence" in value else 0
        return count + sum(_count_evidence(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_evidence(item) for item in value)
    return 0


async def build_aws_incident_evidence_bundle(context: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    collect_missing = bool(params.get("collect_missing"))
    snapshot_params = params.get("snapshot_params") if isinstance(params.get("snapshot_params"), dict) else {}
    redactions: list[str] = []

    topology = params.get("topology_snapshot") if isinstance(params.get("topology_snapshot"), dict) else None
    if topology is None and collect_missing:
        topology = await build_aws_topology_snapshot(context, snapshot_params)

    security = params.get("security_posture") if isinstance(params.get("security_posture"), dict) else None
    if security is None and collect_missing:
        security = await build_aws_security_posture_summary(context, {"topology_snapshot": topology} if topology else {})

    exposure = params.get("exposure_map") if isinstance(params.get("exposure_map"), dict) else None
    if exposure is None and collect_missing:
        exposure = await build_aws_exposure_map(context, {"topology_snapshot": topology} if topology else {})

    timeline = params.get("deployment_timeline") if isinstance(params.get("deployment_timeline"), dict) else None
    if timeline is None and collect_missing:
        timeline = await build_aws_deployment_timeline(context, params.get("timeline_params") or {})

    sections = []
    for name, payload in (
        ("topology", topology),
        ("security_posture", security),
        ("exposure_map", exposure),
        ("deployment_timeline", timeline),
        ("cost_report", params.get("cost_report")),
        ("additional_evidence", params.get("additional_evidence") or []),
    ):
        if payload:
            sections.append(_section(name, payload, redactions))

    bundle = {
        "status": "ok",
        "incident": {
            "id": _string(params.get("incident_id")) or None,
            "title": _string(params.get("title")) or "AWS incident evidence bundle",
            "severity": _string(params.get("severity")) or "unknown",
        },
        "summary": {
            "section_count": len(sections),
            "evidence_reference_count": sum(_count_evidence(section) for section in sections),
            "redaction_count": len(redactions),
            "collect_missing": collect_missing,
        },
        "sections": sections,
        "redactions": redactions,
        "warnings": [
            {
                "severity": "warning",
                "message": "Bundle is an evidence package, not a remediation action or full trace export.",
            }
        ],
    }
    return bundle


class AwsIncidentEvidenceBundleTool:
    name = "aws_incident_evidence_bundle"
    description = (
        "Package selected AWS investigation evidence into an audit-ready structured bundle with basic secret redaction."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await build_aws_incident_evidence_bundle(context, params or {})
