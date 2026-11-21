from __future__ import annotations

from typing import Any

from ...models import AnalyticsDaily, ReportExport


def serialize_analytics_daily(row: AnalyticsDaily) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "team_id": row.team_id,
        "date": row.date.isoformat() if row.date else None,
        "sessions_total": int(row.sessions_total or 0),
        "sessions_completed": int(row.sessions_completed or 0),
        "sessions_failed": int(row.sessions_failed or 0),
        "avg_session_duration_minutes": float(row.avg_session_duration_minutes or 0.0),
        "tool_calls_total": int(row.tool_calls_total or 0),
        "tool_calls_success": int(row.tool_calls_success or 0),
        "tool_calls_failed": int(row.tool_calls_failed or 0),
        "approvals_requested": int(row.approvals_requested or 0),
        "approvals_approved": int(row.approvals_approved or 0),
        "total_cost": float(row.total_cost or 0.0),
        "cost_by_provider": row.cost_by_provider,
        "total_tokens_in": int(row.total_tokens_in or 0),
        "total_tokens_out": int(row.total_tokens_out or 0),
        "knowledge_queries": int(row.knowledge_queries or 0),
        "knowledge_hits": int(row.knowledge_hits or 0),
        "memory_reads": int(row.memory_reads or 0),
        "memory_writes": int(row.memory_writes or 0),
        "positive_feedback": int(row.positive_feedback or 0),
        "negative_feedback": int(row.negative_feedback or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_report_export(row: ReportExport) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_by": row.created_by,
        "report_type": row.report_type,
        "parameters": row.parameters,
        "format": row.format,
        "status": row.status,
        "file_url": row.file_url,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }
