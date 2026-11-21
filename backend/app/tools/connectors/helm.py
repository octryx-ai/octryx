"""Helm connector tools."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .common import _limit, _normalize_string_list, _string
from .helm_runtime import (
    _helm_binary,
    _helm_chart_ref,
    _helm_json,
    _helm_namespace,
    _helm_release_name,
    _helm_text,
    _maybe_block_helm_action_with_approval,
)


class ListHelmReleasesTool:
    name = "list_releases"
    description = "List Helm releases in an allowed namespace."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        args = ["list", "-o", "json"]
        try:
            namespace = _helm_namespace(context, params)
        except Exception as exc:
            return {"error": str(exc)}
        if namespace:
            args.extend(["-n", namespace])
        else:
            args.append("-A")
        try:
            data = await _helm_json(context, args)
        except Exception as exc:
            return {"error": str(exc)}
        releases = data if isinstance(data, list) else []
        allowed = _normalize_string_list(context.project_config.get("helm_allowed_releases"))
        if allowed:
            releases = [item for item in releases if _string(item.get("name")) in allowed]
        limit = _limit(context, params, default=20, maximum=100)
        return {
            "count": len(releases[:limit]),
            "releases": [
                {
                    "name": item.get("name"),
                    "namespace": item.get("namespace"),
                    "revision": item.get("revision"),
                    "status": item.get("status"),
                    "chart": item.get("chart"),
                    "app_version": item.get("app_version"),
                    "updated": item.get("updated"),
                }
                for item in releases[:limit]
            ],
        }


class GetHelmStatusTool:
    name = "get_status"
    description = "Get status details for a Helm release."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            release_name = _helm_release_name(context, params)
            namespace = _helm_namespace(context, params)
        except Exception as exc:
            return {"error": str(exc)}
        args = ["status", release_name, "-o", "json"]
        if namespace:
            args.extend(["-n", namespace])
        try:
            data = await _helm_json(context, args)
        except Exception as exc:
            return {"error": str(exc)}
        return {
            "release": {
                "name": data.get("name"),
                "namespace": data.get("namespace"),
                "revision": data.get("version"),
                "status": ((data.get("info") or {}).get("status")),
                "description": ((data.get("info") or {}).get("description")),
                "chart": ((data.get("chart") or {}).get("metadata") or {}).get("name"),
                "app_version": ((data.get("chart") or {}).get("metadata") or {}).get("appVersion"),
            },
            "raw": data,
        }


class GetHelmHistoryTool:
    name = "get_history"
    description = "Get revision history for a Helm release."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            release_name = _helm_release_name(context, params)
            namespace = _helm_namespace(context, params)
        except Exception as exc:
            return {"error": str(exc)}
        args = ["history", release_name, "-o", "json"]
        if namespace:
            args.extend(["-n", namespace])
        try:
            data = await _helm_json(context, args)
        except Exception as exc:
            return {"error": str(exc)}
        rows = data if isinstance(data, list) else []
        return {
            "count": len(rows),
            "history": [
                {
                    "revision": item.get("revision"),
                    "status": item.get("status"),
                    "chart": item.get("chart"),
                    "app_version": item.get("app_version"),
                    "description": item.get("description"),
                    "updated": item.get("updated"),
                }
                for item in rows
            ],
        }


class UpgradeHelmReleaseTool:
    name = "upgrade"
    description = "Run helm upgrade --install with dry-run support and approval gating for real changes."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            release_name = _helm_release_name(context, params)
            namespace = _helm_namespace(context, params)
            chart = _helm_chart_ref(context, params)
        except Exception as exc:
            return {"error": str(exc)}
        args = ["upgrade", "--install", release_name, chart]
        if namespace:
            args.extend(["-n", namespace, "--create-namespace"])
        values_file = _string(params.get("values_file"))
        if values_file:
            args.extend(["-f", values_file])
        for item in _normalize_string_list(params.get("set_values")):
            args.extend(["--set", item])
        if bool(params.get("wait")):
            args.append("--wait")
        timeout_value = _string(params.get("timeout"))
        if timeout_value:
            args.extend(["--timeout", timeout_value])
        if bool(params.get("dry_run", False)):
            result = await _helm_text(context, [*args, "--dry-run"])
            if result.get("error"):
                return result
            return {
                "status": "dry_run_completed",
                "release_name": release_name,
                "namespace": namespace or None,
                "chart": chart,
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "command": result["command"],
            }
        command = [_helm_binary(context), *args]
        blocked = await _maybe_block_helm_action_with_approval(self.name, params, context, command=command)
        if blocked:
            return blocked
        result = await _helm_text(context, args)
        if result.get("error"):
            return result
        return {
            "status": "completed",
            "release_name": release_name,
            "namespace": namespace or None,
            "chart": chart,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "command": result["command"],
        }


class RollbackHelmReleaseTool:
    name = "rollback"
    description = "Rollback a Helm release revision with approval gating."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            release_name = _helm_release_name(context, params)
            namespace = _helm_namespace(context, params)
        except Exception as exc:
            return {"error": str(exc)}
        revision = _string(params.get("revision"))
        if not revision:
            return {"error": "revision is required"}
        args = ["rollback", release_name, revision]
        if namespace:
            args.extend(["-n", namespace])
        if bool(params.get("wait")):
            args.append("--wait")
        command = [_helm_binary(context), *args]
        blocked = await _maybe_block_helm_action_with_approval(self.name, params, context, command=command)
        if blocked:
            return blocked
        result = await _helm_text(context, args)
        if result.get("error"):
            return result
        return {
            "status": "completed",
            "release_name": release_name,
            "namespace": namespace or None,
            "revision": revision,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "command": result["command"],
        }
