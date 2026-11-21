"""Shared helpers for the test_run_context_tooling_* modules."""

from __future__ import annotations

from typing import Any


def _tool(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name}}


def _db_routing_resolution(
    *,
    allowlist: list[str] | None = None,
    denylist: list[str] | None = None,
    allow_patterns: list[str] | None = None,
    deny_patterns: list[str] | None = None,
    allow_read_only: bool = False,
    workflow_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source": "db",
        "status": "matched",
        "policy_id": "policy-1",
        "policy_version_id": "version-1",
        "matched_group_id": "aws-topology-diagram-message",
        "workflow_id": "generic_diagram",
        "workflow_class": "aws_topology_diagram_request",
        "tool_policy": {
            "allowlist": allowlist or [],
            "denylist": denylist or [],
            "allow_patterns": allow_patterns or [],
            "deny_patterns": deny_patterns or [],
            "allow_read_only": allow_read_only,
        },
        "workflow_contract": workflow_contract or {},
    }
