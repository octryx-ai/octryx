from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ...tools.connectors import aws_core, azure, gcp, gcp_core
from ..run_capability.worker_profiles import worker_tool_context_state
from .failure import connection_success, exception_failure


def _build_health_context(config: dict[str, Any], db: Any = None) -> ToolContext:
    """The test's tool context; ``db``: the caller's session, so tool helpers resolve as in a real call."""
    return ToolContext(
        user_id="connector-health",
        project_ids=[],
        roles=["admin"],
        session_id="connector-health",
        project_config=config,
        workspace_root=str(Path.cwd()),
        run_capability=worker_tool_context_state("connector_health_check"),
        db=db,
    )


async def test_aws_connection(
    config: dict[str, Any],
    *,
    which_fn: Callable[[str], str | None] | None = None,
    db: Any = None,
) -> dict[str, Any]:
    context = _build_health_context(config, db)
    try:
        await aws_core._aws_json(context, "sts", ["get-caller-identity"])
    except Exception as exc:
        return exception_failure("AWS", exc)
    return connection_success("Connected to AWS.")


async def test_azure_connection(config: dict[str, Any], *, db: Any = None) -> dict[str, Any]:
    raw_subscriptions = config.get("azure_subscription_ids")
    if isinstance(raw_subscriptions, list):
        subscriptions = [str(item).strip() for item in raw_subscriptions if str(item).strip()]
    else:
        subscriptions = [
            item.strip() for item in str(raw_subscriptions or "").replace(",", "\n").splitlines() if item.strip()
        ]
    if not subscriptions:
        return {"ok": False, "summary": "azure_subscription_ids is required."}
    context = _build_health_context(config, db)
    try:
        token = await azure._azure_token(context)
        base = str(config.get("azure_management_url") or "https://management.azure.com").strip().rstrip("/")
        response = await azure._http_json(
            "GET",
            f"{base}/subscriptions/{subscriptions[0]}/resourcegroups",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"api-version": "2021-04-01"},
        )
    except Exception as exc:
        return exception_failure("Azure", exc)
    return connection_success(
        "Connected to Azure.", counts={"visible_resource_groups": len(response.get("value") or [])}
    )


async def test_gcp_connection(config: dict[str, Any], *, db: Any = None) -> dict[str, Any]:
    context = _build_health_context(config, db)
    try:
        token = await gcp_core._gcp_access_token(context)
        base = (
            str(config.get("gcp_resourcemanager_url") or "https://cloudresourcemanager.googleapis.com")
            .strip()
            .rstrip("/")
        )
        response = await gcp._http_json(
            "GET",
            f"{base}/v1/projects",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"pageSize": 1},
        )
    except Exception as exc:
        return exception_failure("GCP", exc)
    projects = response.get("projects") or []
    return connection_success("Connected to GCP.", counts={"visible_projects": len(projects)})
