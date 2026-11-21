"""The issues a Jira sync run reads: supplied with the request, or fetched from the connector."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    WorkItemSyncConfig,
)
from .jira_connector import fetch_jira_issues_for_sync


def _issues_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues = payload.get("issues")
    if issues is None:
        return []
    if not isinstance(issues, list):
        raise HTTPException(status_code=422, detail="issues must be a list when provided")
    return [issue for issue in issues if isinstance(issue, dict)]


async def _resolve_source_issues(
    db: AsyncSession,
    *,
    config: WorkItemSyncConfig,
    payload: dict[str, Any],
    limit: int | None,
    query_preview: str,
) -> dict[str, Any]:
    raw_payload_issues = payload.get("issues")
    if raw_payload_issues is not None:
        issues = _issues_from_payload(payload)
        return {
            "configured": True,
            "issues": issues,
            "source_count": len(issues),
            "source_complete": limit is None,
            "metadata": {"source": "request_payload"},
        }
    return await fetch_jira_issues_for_sync(
        db,
        config=config,
        jql=query_preview,
        limit=limit,
    )
